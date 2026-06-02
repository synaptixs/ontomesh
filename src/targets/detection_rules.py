"""
src/targets/detection_rules.py — T1.5
─────────────────────────────────────
Datadog / Splunk detection-rule target.

Reads APPROVED ``LOG_CAUSAL_EDGE`` proposals from the context and
emits one YAML alert per causal claim. The pitch: an SRE team's
existing alerting pipeline gets *automatically* extended with rules
the toolkit's PC algorithm has already statistically vindicated.

Output structure
----------------
- ``detection_rules/datadog/<edge_id>.yaml`` — Datadog monitor spec.
- ``detection_rules/splunk/<edge_id>.yml`` — Splunk savedsearch.
- ``detection_rules/index.json`` — manifest mapping proposal_id → files.

Severity mapping
----------------
``confidence_score`` controls Datadog's ``priority`` (1 = highest):

   ≥ 0.90  →  priority 1
   ≥ 0.75  →  priority 2
   ≥ 0.60  →  priority 3
   else    →  priority 4

The rule fires when the *cause* event spikes and the *effect* event
follows within a window. ``query`` strings are SDL-style placeholders
the SRE customises with their own tag taxonomy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import GenerationContext, Target, TargetResult


def _safe_id(s: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]+", "_", (s or "").strip().lower())
    return out.strip("_") or "edge"


def _priority(confidence: Optional[float]) -> int:
    try:
        c = float(confidence or 0.0)
    except (TypeError, ValueError):
        c = 0.0
    if c >= 0.90:
        return 1
    if c >= 0.75:
        return 2
    if c >= 0.60:
        return 3
    return 4


# Pure YAML emitter — avoids a hard dependency on PyYAML in targets.
# Only handles the shape we actually emit (dict of scalars + lists of
# scalars). For richer YAML, the test suite still validates via PyYAML.

def _yaml_emit(obj: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}\n"
        out = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.append(_yaml_emit(v, indent + 1).rstrip("\n"))
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(v)}")
        return "\n".join(out) + "\n"
    if isinstance(obj, list):
        if not obj:
            return pad + "[]\n"
        out = []
        for item in obj:
            if isinstance(item, (dict, list)):
                out.append(f"{pad}-")
                out.append(_yaml_emit(item, indent + 1).rstrip("\n"))
            else:
                out.append(f"{pad}- {_yaml_scalar(item)}")
        return "\n".join(out) + "\n"
    return pad + _yaml_scalar(obj) + "\n"


def _yaml_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if re.search(r'[\n:#"\'{}\[\],&*?|<>!%@`]', s) or s != s.strip():
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _extract_endpoints(proposal: Dict[str, Any]) -> tuple:
    """Pull (cause, effect) labels from a LOG_CAUSAL_EDGE row. The
    title's shape is ``Causal candidate: <src> → <dst> (PMI X.X, …)``
    (set by ``wizard.log_review.seed_from_mining``). Falls back to
    evidence_sample if the title is empty."""
    text = proposal.get("title") or ""
    m = re.search(r":\s*(.+?)\s*→\s*(.+?)(?:\s*\(|$)", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    fallback = proposal.get("evidence_sample") or ""
    m = re.search(r"^\s*(.+?)\s*→\s*(.+?)\s*$", fallback)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "cause", "effect"


@dataclass
class DetectionRulesTarget:
    name: str = "detection_rules"

    def generate(self, ctx: GenerationContext) -> TargetResult:
        result = TargetResult(target=self.name)
        edges = ctx.causal_edges()
        index_entries: List[Dict[str, Any]] = []
        n_dd = 0
        n_splunk = 0

        if not edges:
            result.warnings.append(
                "no LOG_CAUSAL_EDGE proposals in context — no detection "
                "rules generated"
            )
            result.stats = {"datadog": 0, "splunk": 0}
            return result

        for edge in edges:
            cause, effect = _extract_endpoints(edge)
            edge_id = _safe_id(
                edge.get("proposal_id") or f"{cause}_to_{effect}"
            )
            confidence = edge.get("confidence_score")
            shared_causes = edge.get("shared_causes") or []
            severity = _priority(confidence)

            # ── Datadog ─────────────────────────────────────────────
            dd = {
                "name": f"[Toolkit] {cause} → {effect}",
                "type": "log alert",
                "tags": [
                    "source:ontology-toolkit",
                    f"edge:{edge_id}",
                    f"cause:{_safe_id(cause)}",
                    f"effect:{_safe_id(effect)}",
                    f"confidence:{round(float(confidence or 0), 2)}",
                ],
                "priority": severity,
                "message": _datadog_message(cause, effect, edge, shared_causes),
                # query is a placeholder — Datadog's actual log-alert
                # syntax depends on the customer's tag taxonomy.
                "query": (
                    f"logs(\"@event.cause:{_safe_id(cause)} OR "
                    f"@event.effect:{_safe_id(effect)}\").index(\"*\")"
                    f".rollup(\"count\").last(\"15m\") > 5"
                ),
                "options": {
                    "thresholds": {"critical": 5},
                    "notify_no_data": False,
                    "renotify_interval": 0,
                },
            }
            result.files[f"detection_rules/datadog/{edge_id}.yaml"] = \
                _yaml_emit(dd)
            n_dd += 1

            # ── Splunk ──────────────────────────────────────────────
            splunk = {
                "name": f"toolkit_{edge_id}",
                "search": (
                    f"index=* sourcetype=app_logs "
                    f"({_safe_id(cause)} OR {_safe_id(effect)}) "
                    f"| stats count by event_type | where count > 5"
                ),
                "cron_schedule": "*/15 * * * *",
                "dispatch.earliest_time": "-15m",
                "dispatch.latest_time": "now",
                "alert.severity": severity,
                "description": _splunk_description(cause, effect, edge,
                                                    shared_causes),
            }
            result.files[f"detection_rules/splunk/{edge_id}.yml"] = \
                _yaml_emit(splunk)
            n_splunk += 1

            index_entries.append({
                "edge_id":   edge_id,
                "cause":     cause,
                "effect":    effect,
                "confidence": confidence,
                "priority":  severity,
                "datadog":   f"detection_rules/datadog/{edge_id}.yaml",
                "splunk":    f"detection_rules/splunk/{edge_id}.yml",
                "shared_causes": shared_causes,
            })

        result.files["detection_rules/index.json"] = \
            json.dumps({"edges": index_entries, "generator": "T1.5"},
                       indent=2)
        result.stats = {"datadog": n_dd, "splunk": n_splunk}
        return result


def _datadog_message(cause: str, effect: str,
                     edge: Dict[str, Any],
                     shared: List[Any]) -> str:
    bits = [
        f"@here Causal pattern fired: **{cause} → {effect}**.",
        "",
        f"This rule was generated by the ontology toolkit's PC "
        f"algorithm pass (L11). Confidence "
        f"{round(float(edge.get('confidence_score') or 0), 2)}.",
    ]
    if shared:
        bits.append(
            f"Shared upstream causes flagged: "
            + ", ".join(str(s) for s in shared) + "."
        )
    bits.append(
        "Triage: review whether the cause event preceded the effect "
        "in the last window and whether shared upstream causes are "
        "currently active."
    )
    return "\n".join(bits)


def _splunk_description(cause: str, effect: str,
                        edge: Dict[str, Any],
                        shared: List[Any]) -> str:
    out = (
        f"Causal pattern from ontology toolkit. "
        f"Cause: {cause}; Effect: {effect}. "
        f"Confidence: {round(float(edge.get('confidence_score') or 0), 2)}."
    )
    if shared:
        out += " Shared upstream: " + ", ".join(str(s) for s in shared)
    return out


__all__ = ["DetectionRulesTarget"]
