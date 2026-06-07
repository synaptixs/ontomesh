"""Ontology-grounded reasoning search — engine entry point.

Turns a natural-language question into a **cited, reasoned** answer grounded in
the generated ontology and executed **safely** (read-only) against the connected
database. Runs against local (Ollama) or cloud (OpenAI) providers.

Pipeline — see REASONING_SEARCH_DESIGN.local.md §3/§11:

    understand → plan → execute → (reason) → synthesize → (verify)

Phase 0 implemented the single-hop slice. Phase 1 (§11 #10–#13) adds the safety
layer (read-only, allow-list, **sensitivity-tier gating**, de-identification),
plus graceful **blocked / can't-ground / empty** states. The `reason`
(OWL-RL/Datalog), `verify` (SHACL), multi-hop, and agentic loop land in Phase 2.
Feature-flagged via ``ONTOMESH_SEARCH``; ships dark.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ._loaders import controlled_vocab, load_flavor, load_mapping
from .planner import PlanValidationError
from .planner import plan as _plan
from .query_compiler import CompileError, compile_sql
from .reasoner import parse_rule, reason
from .safety import SafetyError, deidentify, enforce_limit, safe_execute, tier_ok
from .structured_output import Adapter

__all__ = ["Citation", "ReasonedAnswer", "search"]

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
_DEFAULT_FLAVORS = os.path.join(_ROOT, "runtime", "flavors")
_DEFAULT_MAPPING = os.path.join(_ROOT, "output", "mapping", "logical_physical_map.csv")


@dataclass
class Citation:
    """A traceable source backing a claim in the answer."""

    iri: str
    label: str = ""
    source_table: str = ""
    inferred: bool = False


@dataclass
class ReasonedAnswer:
    """The single response contract shared by SDK / CLI / API / app console."""

    answer: str
    plan: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    inferred: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    executed_query: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    status: str = "ok"          # "ok" | "blocked" | "ungrounded" | "empty"


# ── helpers ──────────────────────────────────────────────────────────────────
def _resolve_adapter(providers: str | dict | None):
    """Build an adapter from a provider name (lazy import). Tests inject instead."""
    name = providers if isinstance(providers, str) else (providers or {}).get("planner", "ollama")
    name = (name or "ollama").lower()
    try:
        if name == "ollama":
            from ollama_adapter import OllamaAdapter  # type: ignore

            return OllamaAdapter(os.environ.get("OLLAMA_MODEL", "llama3.1"))
        if name == "openai":
            from openai_adapter import OpenAIAdapter  # type: ignore

            return OpenAIAdapter(os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    except Exception as exc:  # pragma: no cover - depends on optional SDKs
        raise RuntimeError(f"could not initialise provider {name!r}: {exc}") from exc
    raise ValueError(f"unknown provider {name!r} (use 'ollama' or 'openai', or inject adapter=)")


_SYNTH_SYSTEM = (
    "You are a careful analyst. Answer ONLY from the provided records — never "
    "invent facts. Be concise and specific. If the records are empty, say so."
)


def _synthesize(adapter: Adapter, question: str, rows: list[dict],
                inferred: list[dict] | None = None) -> str:
    inferred_txt = (
        f"\n\nDerived facts (inferred via rules — cite as derived): "
        f"{json.dumps(inferred, default=str)[:2000]}" if inferred else ""
    )
    payload = {
        "system": _SYNTH_SYSTEM,
        "messages": [{"role": "user", "content": (
            f"Question: {question}\n\n"
            f"Records (JSON): {json.dumps(rows, default=str)[:6000]}"
            f"{inferred_txt}\n\n"
            "Write a short, direct answer grounded in these records and any "
            "derived facts. Make clear which conclusions are derived."
        )}],
        "token_budget": 600,
        "payload_id": "reasoning-search-synth",
    }
    return adapter.complete(payload).strip()


def _terminal(answer: str, status: str, provider: str, trace: list, **kw) -> ReasonedAnswer:
    return ReasonedAnswer(answer=answer, status=status, confidence=0.0,
                          provider=str(provider), trace=trace, **kw)


def _load_fk_facts(db_path: str, table: str | None, rows: list[dict]) -> list:
    """Auto-load 1-hop neighbour facts via the table's foreign keys (Phase 4 #1).

    For each FK (from_col → ref_table.to_col), fetch the referenced rows for the
    result set and emit their facts keyed by the FK value — so reasoner rules can
    chain across the relationship without manually supplied edges. Read-only;
    schema identifiers come from SQLite PRAGMA (not user input).
    """
    import sqlite3

    if not table or not table.isidentifier():
        return []
    facts: list = []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        try:
            fks = con.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        except sqlite3.Error:
            return []
        for fk in fks:
            ref_table, from_col, to_col = fk["table"], fk["from"], (fk["to"] or "id")
            if not (str(ref_table).isidentifier() and str(from_col).isidentifier()
                    and str(to_col).isidentifier()):
                continue
            seen: set = set()
            for row in rows:
                fv = row.get(from_col)
                if fv is None or fv in seen:
                    continue
                seen.add(fv)
                try:
                    nbrs = con.execute(
                        f"SELECT * FROM {ref_table} WHERE {to_col} = ? LIMIT 5", (fv,)
                    ).fetchall()
                except sqlite3.Error:
                    continue
                for nb in nbrs:
                    key = str(fv)
                    facts.append((ref_table, key))
                    for c, v in dict(nb).items():
                        facts.append((c, key, str(v)))
    finally:
        con.close()
    return facts


# ── public API ────────────────────────────────────────────────────────────────
def search(
    question: str,
    *,
    flavor: str,
    db_path: str | None = None,
    providers: str | dict[str, str] | None = "ollama",
    depth: str = "single_hop",
    k: int = 5,
    max_tier: str = "Internal",
    deid_columns: set[str] | None = None,
    adapter: Adapter | None = None,
    flavors_dir: str | None = None,
    mapping_path: str | None = None,
    limit: int = 200,
    timeout_ms: int = 5000,
    rules: list[str] | None = None,
    extra_facts: list | None = None,
    max_replans: int = 1,
    on_event=None,
    memory=None,
    auto_relations: bool = False,
) -> ReasonedAnswer:
    """Run ontology-grounded reasoning search and return a `ReasonedAnswer`.

    Never raises for *expected* failure modes — returns a `ReasonedAnswer` with a
    ``status`` of ``"blocked"`` (tier), ``"ungrounded"`` (can't map to ontology),
    or ``"empty"`` (no rows). ``max_tier`` is the caller's access ceiling.
    """
    flavors_dir = flavors_dir or _DEFAULT_FLAVORS
    mapping_path = mapping_path or _DEFAULT_MAPPING
    llm = adapter or _resolve_adapter(providers)
    provider_label = providers if isinstance(providers, str) else getattr(llm, "model_id", "")
    trace: list[dict[str, Any]] = []

    def emit(entry: dict) -> None:
        """Append to the trace and stream it (for SSE) via on_event."""
        trace.append(entry)
        if on_event:
            try:
                on_event(dict(entry))
            except Exception:  # noqa: BLE001 - streaming must never break search
                pass

    # 0. Memory recall — surface prior related questions (AgentMemory or any
    #    object exposing recall(question, flavor=...)).
    if memory is not None:
        try:
            recalled = list(memory.recall(question, flavor=flavor) or [])
        except Exception:  # noqa: BLE001
            recalled = []
        if recalled:
            emit({"stage": "recall", "count": len(recalled)})

    # 1–3. Understand + Plan + Compile — graceful on can't-ground / tier block.
    try:
        flavor_cfg = load_flavor(flavor, flavors_dir)
        vocab = controlled_vocab(flavor_cfg)
        allowed_tables = set(flavor_cfg.get("db_tables", []) or [])
        mapping = load_mapping(mapping_path)

        the_plan = _plan(question, vocab=vocab, adapter=llm)
        emit({"stage": "plan", "classes": the_plan.classes,
                      "intent": the_plan.intent,
                      "filters": [vars(f) for f in the_plan.filters]})

        ctier = mapping.tier.get(the_plan.primary_class)
        if ctier and not tier_ok(ctier, max_tier):
            return _terminal(
                f"That question targets {the_plan.primary_class} data classified "
                f"'{ctier}', above your access ceiling ('{max_tier}'). Request denied.",
                "blocked", provider_label, trace,
                plan={"classes": the_plan.classes, "intent": the_plan.intent})

        sql, params = compile_sql(the_plan, mapping=mapping,
                                  allowed_tables=allowed_tables, limit=limit, max_tier=max_tier)
        sql = enforce_limit(sql, limit)
    except (PlanValidationError, CompileError, SafetyError) as exc:
        emit({"stage": "error", "detail": str(exc)})
        return _terminal(
            f"I couldn't ground that question in the ontology: {exc}",
            "ungrounded", provider_label, trace)

    # 4. Execute (read-only, guarded) — with a light agentic re-plan on empty.
    rows = safe_execute(db_path, sql, params, timeout_ms=timeout_ms) if db_path else []
    replans = 0
    while not rows and db_path and replans < max_replans:
        replans += 1
        emit({"stage": "replan", "n": replans, "reason": "no rows; broadening"})
        try:
            the_plan = _plan(
                question + " (the previous query returned no rows — relax or drop "
                "non-essential filters)", vocab=vocab, adapter=llm)
            sql, params = compile_sql(the_plan, mapping=mapping,
                                      allowed_tables=allowed_tables, limit=limit, max_tier=max_tier)
            sql = enforce_limit(sql, limit)
        except (PlanValidationError, CompileError, SafetyError):
            break
        rows = safe_execute(db_path, sql, params, timeout_ms=timeout_ms)
    if deid_columns:
        rows = deidentify(rows, deid_columns)
    emit({"stage": "execute", "sql": sql, "params": params,
          "rows": len(rows), "replans": replans})

    # 4b. Reason — derive facts over the result subgraph (+ any relationship facts).
    inferred: list[dict] = []
    inferred_cites: list[Citation] = []
    if rules:
        facts: list = list(extra_facts or [])
        for i, row in enumerate(rows):
            key = str(row.get("id", i))
            facts.append((the_plan.primary_class, key))
            for col, val in row.items():
                facts.append((col, key, str(val)))
        if auto_relations and db_path:
            fk_facts = _load_fk_facts(db_path, mapping.table_for(the_plan.primary_class), rows)
            facts += fk_facts
            emit({"stage": "relations", "neighbor_facts": len(fk_facts)})
        try:
            res = reason(facts, [parse_rule(r) for r in rules])
            for f in res.derived:
                rule_name, support = res.provenance[f]
                inferred.append({"fact": list(f), "rule": rule_name,
                                 "derived_from": [list(s) for s in support]})
                inferred_cites.append(Citation(
                    iri="prov:Derived/" + "/".join(map(str, f)),
                    label=f"{f[0]}(" + ", ".join(map(str, f[1:])) + ")",
                    inferred=True))
            emit({"stage": "reason", "derived": len(res.derived)})
        except ValueError as exc:
            emit({"stage": "reason", "error": str(exc)})

    # 5. Synthesize.
    answer = _synthesize(llm, question, rows, inferred)
    emit({"stage": "synthesize", "chars": len(answer)})

    # 6. Remember — persist this turn for future recall.
    if memory is not None:
        try:
            memory.remember({"question": question, "flavor": flavor,
                             "answer": answer, "status": "ok" if rows else "empty"})
        except Exception:  # noqa: BLE001
            pass

    table = mapping.table_for(the_plan.primary_class) or ""
    citations = [
        Citation(iri=f"{the_plan.primary_class}/{row.get('id', i)}",
                 label=str(next(iter(row.values()), "")), source_table=table)
        for i, row in enumerate(rows[:k])
    ] + inferred_cites

    return ReasonedAnswer(
        answer=answer,
        plan={"intent": the_plan.intent, "classes": the_plan.classes,
              "filters": [vars(f) for f in the_plan.filters]},
        results=rows,
        citations=citations,
        inferred=inferred,
        confidence=0.85 if rows else (0.5 if inferred else 0.3),
        executed_query=sql,
        trace=trace,
        provider=str(provider_label),
        status="ok" if rows else "empty",
    )
