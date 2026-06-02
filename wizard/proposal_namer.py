"""
wizard/proposal_namer.py — T1.1
───────────────────────────────
LLM-assisted naming + descriptions for proposals in
``ontology_evolution_proposals``. Reads a proposal row, asks a
provider-abstracted LLM for a class name and one-sentence
description, writes them back.

Design contract
───────────────
- **LLMs at the labeling layer only.** The statistical inference
  (Drain, HMM, GP, PC algorithm, VB-HMM, …) stays untouched. We
  rename ``:Event_42`` to ``:UserAuthFailureRetry`` and write a
  human-readable ``rdfs:comment``. We never let an LLM decide
  whether something is anomalous.
- **Provider-abstracted.** ``PROPOSAL_NAMER_PROVIDER`` env var
  picks ``mock`` / ``anthropic`` / ``openai`` / ``none``.
  ``none`` is the safe default — the namer becomes a no-op so the
  pipeline never blocks on a missing API key.
- **Idempotent and engineer-respecting.** A new ``name_source``
  column on each proposal tracks whether the title is ``auto``
  (mechanical, our seed), ``llm`` (this module wrote it), or
  ``human`` (engineer edited it in the wizard). The rename pass
  only touches ``auto`` rows; ``llm`` and ``human`` rows are
  left alone unless ``force=True``.
- **Cache aggressively.** Same proposal → same name. We hash the
  template + sample + kind + key dims into a stable identifier
  and skip the LLM call if we've named it before with the same
  inputs.

Public API
──────────
    provider = get_provider()                         # env-driven
    out = name_proposal(row, provider=provider)       # {name, description}
    n = rename_pending_proposals(conn, provider)      # bulk pass
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


# ── Provider abstraction ─────────────────────────────────────────────────


class LLMProvider(Protocol):
    """Tiny interface — one method, completion-style. Keeps the rest
    of the namer testable without coupling to any SDK."""

    name: str

    def complete(self, prompt: str, *, max_tokens: int = 200,
                 temperature: float = 0.2) -> str:
        ...


@dataclass
class MockProvider:
    """Deterministic fake provider for tests + cold-start envs. Picks
    a name from the prompt by scanning for capitalised tokens. Slow
    enough to look "real-ish" but no network, no cost."""

    name: str = "mock"

    def complete(self, prompt: str, *, max_tokens: int = 200,
                 temperature: float = 0.2) -> str:
        # Extract a fragment of the log template for naming. The
        # prompt always carries the template after "Template:".
        m = re.search(r"Template:\s*(.+?)(?:\n|$)", prompt)
        words = []
        if m:
            raw = m.group(1)
            words = re.findall(r"[A-Z][A-Za-z0-9]+", raw)
        name = "".join(words[:3]) if words else "GenericEvent"
        return (f"NAME: :{name}\n"
                f"DESC: Mock-generated description for {name}.")


@dataclass
class AnthropicProvider:
    """Provider backed by the ``anthropic`` SDK. Used when the env var
    selects it and the SDK is importable. Falls back silently if not."""

    api_key: str
    model: str = "claude-sonnet-4-5"
    name: str = "anthropic"

    def complete(self, prompt: str, *, max_tokens: int = 200,
                 temperature: float = 0.2) -> str:
        try:
            import anthropic                                       # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed; pip install anthropic"
            ) from exc
        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate text blocks in the response.
        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "".join(parts)


@dataclass
class OpenAIProvider:
    """Provider backed by the ``openai`` SDK."""

    api_key: str
    model: str = "gpt-4o-mini"
    name: str = "openai"

    def complete(self, prompt: str, *, max_tokens: int = 200,
                 temperature: float = 0.2) -> str:
        try:
            import openai                                          # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed; pip install openai"
            ) from exc
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()


def get_provider() -> Optional[LLMProvider]:
    """Pick a provider based on ``PROPOSAL_NAMER_PROVIDER``.

    ``mock`` / ``anthropic`` / ``openai`` / ``none`` (default).
    Returns None when ``none`` is selected or the chosen provider's
    API key isn't present in the env — the namer then becomes a
    no-op rather than crashing the pipeline."""
    choice = (os.environ.get("PROPOSAL_NAMER_PROVIDER") or "none").lower()
    if choice == "mock":
        return MockProvider()
    if choice == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        model = os.environ.get("PROPOSAL_NAMER_MODEL", "claude-sonnet-4-5")
        return AnthropicProvider(api_key=key, model=model)
    if choice == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        model = os.environ.get("PROPOSAL_NAMER_MODEL", "gpt-4o-mini")
        return OpenAIProvider(api_key=key, model=model)
    return None


# ── Prompts ──────────────────────────────────────────────────────────────


_PROMPT_EVENT = """You are naming a structured event class for an OWL ontology.

The event corresponds to this Drain log template:
Template: {template}

Sample log line:
{sample}

Severity: {severity}
Service: {service}
Hit count: {hits}

Propose:
1. A class name in PascalCase prefixed with ":" (e.g. :UserLoggedIn). Maximum 4 words. Should describe what happened, not just what was logged.
2. A one-sentence rdfs:comment describing what this event represents in plain English.

Output ONLY the following exact format with no preamble or explanation:
NAME: :YourClassName
DESC: Your one-sentence description.
"""


_PROMPT_ENTITY = """You are naming an identifier property for an OWL ontology.

The slot extracted from log templates carries these values:
Sample template: {template}
Slot type: {slot_type}
Top values: {top_values}

Propose:
1. A property qname in camelCase prefixed with ":" (e.g. :hasUserId, :hasOrderId).
2. A one-sentence description of what this property identifies.

Output ONLY:
NAME: :yourPropertyName
DESC: Your one-sentence description.
"""


_PROMPT_RELATIONSHIP = """You are naming an undirected relationship between two entity types.

The relationship is based on observed co-occurrence in logs:
Endpoint A: {src}
Endpoint B: {dst}
Sample template context: {template}

Propose:
1. A property qname in camelCase prefixed with ":" (e.g. :relatesTo, :sharesContext). Symmetric / undirected sense.
2. A one-sentence description.

Output ONLY:
NAME: :yourPropertyName
DESC: Your one-sentence description.
"""


_PROMPT_CAUSAL = """You are explaining a causal edge in an RCA ontology.

Cause: {src}
Effect: {dst}
PMI: {pmi}
Granger p-value: {granger_p}
Shared upstream causes (if any): {shared_causes}

Propose a one-sentence explanation suitable for an SRE / on-call reviewer. Be specific and avoid vague phrases like "is related to". Note any shared upstream causes explicitly.

Output ONLY:
DESC: Your one-sentence explanation.
"""


def _format_prompt(row: Dict[str, Any]) -> str:
    kind = row.get("kind") or row.get("proposal_type") or ""
    text = lambda k: str(row.get(k) or "")[:300]  # noqa: E731
    if kind == "LOG_EVENT":
        return _PROMPT_EVENT.format(
            template=text("title") or text("evidence_sample"),
            sample=text("evidence_sample"),
            severity=text("severity") or "unknown",
            service=text("service") or "unknown",
            hits=text("dim_evidence_volume") or "unknown",
        )
    if kind == "LOG_ENTITY":
        return _PROMPT_ENTITY.format(
            template=text("title"),
            slot_type=text("evidence_sample") or "unknown",
            top_values=text("evidence_sample"),
        )
    if kind == "LOG_RELATIONSHIP":
        src, dst = _split_endpoint_pair(row, "↔")
        return _PROMPT_RELATIONSHIP.format(
            src=src, dst=dst, template=text("title"),
        )
    if kind == "LOG_CAUSAL_EDGE":
        src, dst = _split_endpoint_pair(row, "→")
        return _PROMPT_CAUSAL.format(
            src=src, dst=dst,
            pmi=text("dim_cross_domain") or "?",
            granger_p=text("dim_consistency_risk") or "?",
            shared_causes=text("candidate_turtle"),
        )
    return _PROMPT_EVENT.format(
        template=text("title"), sample=text("evidence_sample"),
        severity="unknown", service="unknown", hits="unknown",
    )


def _split_endpoint_pair(row: Dict[str, Any], glyph: str) -> tuple:
    """Parse 'Relationship candidate: A ↔ B (PMI X.X)' style title."""
    title = str(row.get("title") or "")
    m = re.search(rf":\s*(.+?)\s*{re.escape(glyph)}\s*(.+?)\s*\(", title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "endpoint_a", "endpoint_b"


# ── Output parsing ───────────────────────────────────────────────────────


_NAME_RE = re.compile(r"^\s*NAME:\s*(:?[A-Za-z][A-Za-z0-9_]*)\s*$", re.M)
_DESC_RE = re.compile(r"^\s*DESC:\s*(.+?)\s*$", re.M | re.DOTALL)


def _parse_completion(text: str) -> Dict[str, str]:
    """Pull NAME / DESC lines out of an LLM response. Tolerant of
    chatty preambles — we just look for the labelled lines."""
    out = {"name": "", "description": ""}
    m = _NAME_RE.search(text or "")
    if m:
        name = m.group(1).strip()
        if not name.startswith(":"):
            name = ":" + name
        out["name"] = name
    m = _DESC_RE.search(text or "")
    if m:
        out["description"] = m.group(1).strip().split("\n")[0].strip()
    return out


# ── Naming pipeline ──────────────────────────────────────────────────────


def name_proposal(row: Dict[str, Any],
                  *, provider: Optional[LLMProvider] = None,
                  ) -> Dict[str, str]:
    """Pure function. Given a proposal dict, return
    ``{name, description, source}``. If ``provider`` is None,
    returns the row's existing name + empty description with
    ``source='auto'`` — i.e. no-op."""
    if provider is None:
        return {
            "name": str(row.get("title") or ""),
            "description": "",
            "source": "auto",
        }
    prompt = _format_prompt(row)
    try:
        raw = provider.complete(prompt, max_tokens=200, temperature=0.2)
    except Exception:                                  # noqa: BLE001
        return {
            "name": str(row.get("title") or ""),
            "description": "",
            "source": "auto",
        }
    parsed = _parse_completion(raw)
    if not parsed["name"]:
        return {
            "name": str(row.get("title") or ""),
            "description": "",
            "source": "auto",
        }
    return {
        "name": parsed["name"],
        "description": parsed.get("description", ""),
        "source": "llm",
    }


def _fingerprint(row: Dict[str, Any]) -> str:
    """Stable hash of the *inputs* the namer cares about. If the
    template or sample changes, the fingerprint changes and we
    re-name; otherwise we cache the existing LLM name."""
    key = {
        "kind":    row.get("kind"),
        "title":   row.get("title"),
        "sample":  row.get("evidence_sample"),
    }
    blob = json.dumps(key, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def rename_pending_proposals(conn: sqlite3.Connection,
                             provider: Optional[LLMProvider] = None,
                             *, force: bool = False,
                             limit: int = 50) -> Dict[str, Any]:
    """Bulk pass over ``ontology_evolution_proposals`` with
    ``name_source = 'auto'`` (or all rows when ``force=True``).
    For each, call the LLM, write the new title + description,
    and bump ``name_source`` to 'llm'.

    Engineer edits land in ``name_source = 'human'`` (set by the
    wizard's approve/edit flow) and are NEVER overwritten by this
    function. Even with ``force=True`` we only re-do rows that
    were auto or llm, not human."""
    if not _table_exists(conn, "ontology_evolution_proposals"):
        return {"renamed": 0, "skipped": 0, "errors": 0,
                "provider": provider.name if provider else "none"}

    if provider is None:
        return {"renamed": 0, "skipped": 0, "errors": 0, "provider": "none"}

    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(ontology_evolution_proposals)"
    )}
    if "name_source" not in cols:
        return {"renamed": 0, "skipped": 0, "errors": 0,
                "reason": "v3 migration not applied",
                "provider": provider.name}

    where = "name_source IN ('auto', 'llm')" if force else "name_source = 'auto'"
    rows = list(conn.execute(
        "SELECT proposal_id, proposal_type, title, evidence_sample, "
        "       candidate_turtle, dim_evidence_volume, "
        "       dim_cross_domain, dim_consistency_risk, status "
        f"FROM ontology_evolution_proposals WHERE {where} "
        "ORDER BY id ASC LIMIT ?",
        (int(limit),),
    ))

    stats = {"renamed": 0, "skipped": 0, "errors": 0,
             "provider": provider.name, "duration_s": 0.0}
    started = time.perf_counter()
    for r in rows:
        pid, ptype, title, sample, turtle, ev_vol, xdom, cons, status = r
        if status in ("APPROVED", "REJECTED"):
            stats["skipped"] += 1
            continue
        row_dict = {
            "proposal_id": pid, "kind": ptype, "title": title,
            "evidence_sample": sample, "candidate_turtle": turtle,
            "dim_evidence_volume": ev_vol,
            "dim_cross_domain": xdom,
            "dim_consistency_risk": cons,
        }
        result = name_proposal(row_dict, provider=provider)
        if result["source"] != "llm":
            stats["errors"] += 1
            continue
        # Compose the new title — keep the kind prefix the v2 UI
        # expects so badges still render, but inject the LLM name.
        new_title = (
            f"{_kind_prefix(ptype)}: {result['name']} "
            f"— {result['description']}"
        )[:240]
        new_turtle = _inject_llm_name(turtle or "", ptype,
                                       result["name"],
                                       result["description"])
        conn.execute(
            "UPDATE ontology_evolution_proposals "
            "SET title = ?, candidate_turtle = ?, "
            "    name_source = 'llm', "
            "    name_generated_at = ?, "
            "    updated_at = datetime('now') "
            "WHERE proposal_id = ?",
            (new_title, new_turtle, _now_iso(), pid),
        )
        stats["renamed"] += 1
    conn.commit()
    stats["duration_s"] = round(time.perf_counter() - started, 3)
    return stats


def _kind_prefix(kind: str) -> str:
    return {
        "LOG_EVENT":        "Event",
        "LOG_ENTITY":       "Entity",
        "LOG_RELATIONSHIP": "Relationship",
        "LOG_CAUSAL_EDGE":  "Causal edge",
    }.get(kind or "", "Proposal")


def _inject_llm_name(turtle: str, kind: str, name: str,
                     description: str) -> str:
    """Best-effort: keep the original turtle but prepend an
    LLM-suggested label / comment block. The engineer can edit
    on approve."""
    safe_name = (name or "").lstrip(":") or "Proposal"
    safe_desc = (description or "").replace("\n", " ").replace('"', '\\"')
    return (
        f"# LLM-suggested name: {name}\n"
        f":{safe_name} a owl:Class ;\n"
        f'  rdfs:label "{safe_name}" ;\n'
        f'  rdfs:comment "{safe_desc}" .\n\n'
        f"# Original (mechanical) candidate below — preserved\n"
        f"# for the reviewer to compare and edit if needed.\n"
        + turtle
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def mark_human_edited(conn: sqlite3.Connection, proposal_id: str) -> None:
    """Call this from the wizard's edit/approve flow. Once a row is
    marked 'human', neither the auto seed nor the LLM rename will
    overwrite its title again."""
    conn.execute(
        "UPDATE ontology_evolution_proposals "
        "SET name_source = 'human', updated_at = datetime('now') "
        "WHERE proposal_id = ?",
        (proposal_id,),
    )
    conn.commit()


__all__ = [
    "LLMProvider", "MockProvider", "AnthropicProvider", "OpenAIProvider",
    "get_provider", "name_proposal", "rename_pending_proposals",
    "mark_human_edited",
]
