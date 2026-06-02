"""
wizard/policy_engine.py — T2.3
──────────────────────────────
YAML-defined auto-approval policies for the proposal review queue.

Why this exists
───────────────
Tier 1 closed the inference-quality and review-UX gaps. The next
blocker for SaaS-style adoption is that *every* proposal still
requires human eyes. On a corpus where the L9 ranker has watched
≥ 100 decisions and the T1.1 LLM names accurate, the high-
confidence non-PII proposals are wasting reviewer time.

T2.3 introduces a tight YAML policy layer that auto-approves
proposals when they clear *all* of:

  - The policy's structural predicates (kind / confidence / PII
    flag / consequence / age in queue / regime / shared-cause
    presence)
  - A guard set keyed off T2.6 drift state — auto-approval is
    disabled while any critical drift alert is firing.

Engineer can revoke an auto-approval; the policy that fired is
recorded in the proposal row's audit trail and tightened so the
same rule cannot fire that proposal again without explicit
reactivation.

Policy schema (single YAML file: ``policies/*.yml``)::

    - name: high_confidence_safe_events
      enabled: true
      if:
        kind:        LOG_EVENT
        confidence:  ">= 0.95"
        pii_risk:    "== 0"
        age_hours:   ">= 24"        # ranker had time to learn
      require:
        - ranker_decisions: ">= 100"
        - no_drift_alerts: true
      then: approve
      note: "Auto-approved by policy {policy}."

Predicate operators we support: ``==``, ``!=``, ``>=``, ``<=``,
``>``, ``<``, ``in``, ``not in``, ``startswith``, ``contains``.
The right-hand side is a Python literal (number, string, bool,
list).

Design contract
───────────────
- **Default disabled.** Policies ship in ``policies/*.yml`` but
  every one needs ``enabled: true``. Set to ``false`` to study a
  policy's hit rate without writing decisions.
- **Audit trail.** Every auto-approval writes the policy name to
  ``review_note`` and bumps ``reviewer_id`` to ``policy:<name>``.
  The proposal row carries an explicit trace of *why* it was
  auto-approved.
- **Override-aware.** A proposal whose ``review_note`` starts with
  ``REVOKED:`` is never auto-approved again by the same policy.
- **Drift-gated.** When a critical (sev 1 or 2) drift alert is
  firing, auto-approval is paused globally. The build-gate from
  T2.6 already surfaces those alerts.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ── Policy schema ────────────────────────────────────────────────────────


@dataclass
class Policy:
    name:     str
    enabled:  bool = False
    if_:      Dict[str, str] = field(default_factory=dict)
    require:  List[Dict[str, str]] = field(default_factory=list)
    then:     str = "approve"
    note:     str = "Auto-approved by policy {policy}."

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Policy":
        return cls(
            name=str(raw.get("name") or "unnamed"),
            enabled=bool(raw.get("enabled", False)),
            if_=dict(raw.get("if") or {}),
            require=list(raw.get("require") or []),
            then=str(raw.get("then") or "approve"),
            note=str(raw.get("note") or "Auto-approved by policy {policy}."),
        )


@dataclass
class PolicyMatch:
    policy:      str
    proposal_id: str
    action:      str             # "approve" / "reject" / "defer"
    note:        str
    proposal_kind: str
    confidence:  float


@dataclass
class PolicyRunReport:
    matches:    List[PolicyMatch] = field(default_factory=list)
    skipped:    int = 0
    drift_paused: bool = False
    n_policies: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "matches": [m.__dict__ for m in self.matches],
            "skipped": self.skipped,
            "drift_paused": self.drift_paused,
            "n_policies": self.n_policies,
            "duration_s": self.duration_s,
        }


# ── Predicate evaluation ─────────────────────────────────────────────────


_OP_RE = re.compile(
    r"\s*(==|!=|>=|<=|>|<|in|not in|startswith|contains)?\s*(.*)$"
)


def _eval_predicate(value: Any, expr: Any) -> bool:
    """Evaluate one predicate. ``expr`` is either a literal (then we
    test ``value == expr``) or a string ``"<op> <literal>"`` we parse."""
    if not isinstance(expr, str):
        return value == expr
    m = _OP_RE.match(expr.strip())
    if not m:
        return False
    op = (m.group(1) or "==").strip()
    rhs_raw = (m.group(2) or "").strip()
    try:
        rhs = _parse_literal(rhs_raw)
    except Exception:                                       # noqa: BLE001
        rhs = rhs_raw
    return _apply_op(op, value, rhs)


def _parse_literal(s: str) -> Any:
    """Tolerant: bool / int / float / list / quoted string / bare ident."""
    s = s.strip()
    if not s:
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if (s.startswith("[") and s.endswith("]")) \
            or (s.startswith("{") and s.endswith("}")):
        return json.loads(s)
    if (s.startswith("'") and s.endswith("'")) \
            or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _apply_op(op: str, lhs: Any, rhs: Any) -> bool:
    try:
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        if op == ">=":
            return float(lhs) >= float(rhs)
        if op == "<=":
            return float(lhs) <= float(rhs)
        if op == ">":
            return float(lhs) > float(rhs)
        if op == "<":
            return float(lhs) < float(rhs)
        if op == "in":
            return lhs in rhs
        if op == "not in":
            return lhs not in rhs
        if op == "startswith":
            return str(lhs).startswith(str(rhs))
        if op == "contains":
            return str(rhs) in str(lhs)
    except (TypeError, ValueError):
        return False
    return False


# ── Loading policies from YAML or list-of-dicts ─────────────────────────


def load_policies(source) -> List[Policy]:
    """``source`` is either a file/dir path or a list of dicts. Returns
    only ``enabled`` policies."""
    if isinstance(source, (list, tuple)):
        return [Policy.from_dict(d) for d in source if d.get("enabled")]
    p = Path(source)
    if p.is_dir():
        files = sorted(p.glob("*.yml")) + sorted(p.glob("*.yaml"))
    elif p.is_file():
        files = [p]
    else:
        return []
    try:
        import yaml
    except ImportError:                                     # pragma: no cover
        return []
    out: List[Policy] = []
    for f in files:
        try:
            data = yaml.safe_load(f.read_text()) or []
        except Exception:                                   # noqa: BLE001
            continue
        if isinstance(data, dict):
            data = [data]
        for d in data:
            if isinstance(d, dict) and d.get("enabled"):
                out.append(Policy.from_dict(d))
    return out


# ── Policy engine ────────────────────────────────────────────────────────


class PolicyEngine:
    """Runs a set of loaded policies against PENDING proposals.

    Parameters
    ----------
    conn : sqlite3.Connection
        Proposal store with ``ontology_evolution_proposals`` table.
    policies : list of Policy
        Enabled policies in evaluation order.
    drift_alerts : optional list of DriftAlert
        Auto-approval is paused while any critical alert (severity
        ≤ 2) is present.
    ranker_decisions : int
        Number of historical (APPROVED + REJECTED) decisions the
        L9 ranker has seen. Some policies require a floor.
    """

    def __init__(self, conn: sqlite3.Connection,
                 policies: Sequence[Policy],
                 *, drift_alerts: Optional[Sequence] = None,
                 ranker_decisions: int = 0) -> None:
        self.conn = conn
        self.policies = list(policies)
        self.drift_alerts = list(drift_alerts or [])
        self.ranker_decisions = int(ranker_decisions)

    # ── Public entry ────────────────────────────────────────────────────

    def run(self, *, limit: int = 200) -> PolicyRunReport:
        import time
        report = PolicyRunReport(n_policies=len(self.policies))
        started = time.perf_counter()
        if self._critical_drift_active():
            report.drift_paused = True
            report.duration_s = time.perf_counter() - started
            return report
        rows = self._pending_proposals(limit=limit)
        for row in rows:
            policy = self._first_matching_policy(row)
            if policy is None:
                report.skipped += 1
                continue
            note = policy.note.format(policy=policy.name)
            self._apply_action(row, policy, note)
            report.matches.append(PolicyMatch(
                policy=policy.name,
                proposal_id=row["proposal_id"],
                action=policy.then,
                note=note,
                proposal_kind=row.get("kind") or "",
                confidence=float(row.get("confidence_score") or 0.0),
            ))
        report.duration_s = time.perf_counter() - started
        return report

    # ── Helpers ─────────────────────────────────────────────────────────

    def _critical_drift_active(self) -> bool:
        for a in self.drift_alerts:
            sev = getattr(a, "severity", None)
            if isinstance(sev, int) and sev <= 2:
                return True
        return False

    def _pending_proposals(self, *, limit: int) -> List[Dict[str, Any]]:
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(ontology_evolution_proposals)"
        )}
        extras = []
        for c in ("regime_tag", "regime_posterior", "rate_sparkline",
                  "name_source"):
            if c in cols:
                extras.append(c)
        sel = (
            "SELECT proposal_id, proposal_type, title, "
            "       confidence_score, dim_consistency_risk, "
            "       dim_evidence_volume, dim_evidence_recency, "
            "       status, review_note, created_at"
            + (", " + ", ".join(extras) if extras else "")
            + " FROM ontology_evolution_proposals "
              "WHERE status = 'PENDING' "
              "ORDER BY id ASC LIMIT ?"
        )
        rows = self.conn.execute(sel, (int(limit),)).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = {
                "proposal_id": r[0], "kind": r[1], "title": r[2],
                "confidence_score": r[3] or 0.0,
                "pii_risk": float(r[4] or 0.0),
                "evidence_volume": r[5] or 0.0,
                "consequence": r[6] or 0.0,
                "status": r[7], "review_note": r[8] or "",
                "created_at": r[9],
            }
            for i, name in enumerate(extras):
                d[name] = r[10 + i]
            d["age_hours"] = _age_hours(d["created_at"])
            out.append(d)
        return out

    def _first_matching_policy(self, row: Dict[str, Any]) -> Optional[Policy]:
        # Skip rows the engineer revoked from prior auto-approvals.
        if (row.get("review_note") or "").startswith("REVOKED:"):
            return None
        for policy in self.policies:
            if not policy.enabled:
                continue
            if not self._row_matches(row, policy):
                continue
            if not self._requirements_met(policy):
                continue
            return policy
        return None

    def _row_matches(self, row: Dict[str, Any], policy: Policy) -> bool:
        for key, expr in policy.if_.items():
            value = row.get(key)
            if not _eval_predicate(value, expr):
                return False
        return True

    def _requirements_met(self, policy: Policy) -> bool:
        for req in policy.require:
            if not isinstance(req, dict):
                continue
            for key, expr in req.items():
                if key == "ranker_decisions":
                    if not _eval_predicate(self.ranker_decisions, expr):
                        return False
                elif key == "no_drift_alerts":
                    want = bool(expr) if isinstance(expr, bool) else \
                        _parse_literal(str(expr)) is True
                    has = bool(self.drift_alerts)
                    if want and has:
                        return False
                # other keys silently pass — extension point
        return True

    def _apply_action(self, row: Dict[str, Any], policy: Policy,
                      note: str) -> None:
        new_status = {
            "approve": "APPROVED",
            "reject":  "REJECTED",
            "defer":   "DEFERRED",
        }.get(policy.then, "APPROVED")
        self.conn.execute(
            "UPDATE ontology_evolution_proposals "
            "SET status = ?, review_note = ?, "
            "    reviewer_id = ?, reviewed_at = datetime('now'), "
            "    updated_at = datetime('now') "
            "WHERE proposal_id = ?",
            (new_status, note, f"policy:{policy.name}",
             row["proposal_id"]),
        )
        self.conn.commit()


# ── Engineer-facing helpers ──────────────────────────────────────────────


def revoke_auto_approval(conn: sqlite3.Connection,
                         proposal_id: str,
                         *, reviewer_id: str = "manual",
                         note: str = "Reviewer disagreed with policy") -> bool:
    """Roll an auto-approval back to PENDING with a REVOKED: marker.

    The marker is a literal prefix on ``review_note``; the policy
    engine refuses to re-fire on rows with that prefix until a
    human explicitly clears it. Returns True iff the row was
    eligible (status APPROVED and a ``policy:`` reviewer).
    """
    row = conn.execute(
        "SELECT status, reviewer_id FROM ontology_evolution_proposals "
        "WHERE proposal_id = ?", (proposal_id,),
    ).fetchone()
    if not row:
        return False
    status, prior_reviewer = row
    if status != "APPROVED" or not (prior_reviewer or "").startswith("policy:"):
        return False
    conn.execute(
        "UPDATE ontology_evolution_proposals "
        "SET status = 'PENDING', "
        "    review_note = 'REVOKED: ' || ?, "
        "    reviewer_id = ?, "
        "    reviewed_at = datetime('now'), "
        "    updated_at = datetime('now') "
        "WHERE proposal_id = ?",
        (note, reviewer_id, proposal_id),
    )
    conn.commit()
    return True


# ── Helpers ──────────────────────────────────────────────────────────────


def _age_hours(created_at: Any) -> float:
    if not created_at:
        return 0.0
    try:
        s = str(created_at).replace("T", " ").split(".")[0]
        ts = _dt.datetime.fromisoformat(s)
    except Exception:                                       # noqa: BLE001
        return 0.0
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    return max(0.0, (now - ts).total_seconds() / 3600.0)


__all__ = [
    "Policy", "PolicyMatch", "PolicyRunReport",
    "PolicyEngine", "load_policies", "revoke_auto_approval",
]
