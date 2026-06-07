"""Ontology-grounded reasoning search — engine entry point.

Turns a natural-language question into a **cited, reasoned** answer grounded in
the generated ontology and executed **safely** (read-only) against the connected
database. Runs against local (Ollama) or cloud (OpenAI) providers.

Pipeline — see REASONING_SEARCH_DESIGN.local.md §3/§11:

    understand → plan → execute → (reason) → synthesize → (verify)

Phase 0 implements the single-hop slice: understand+plan (`planner`) → compile to
read-only SQL (`query_compiler`) → execute → synthesize. The `reason` (OWL-RL/
Datalog) and `verify` (SHACL) stages, multi-hop, and the agentic loop land in
Phase 2 (§11 #19–#25). Feature-flagged via ``ONTOMESH_SEARCH``; ships dark.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ._loaders import controlled_vocab, load_flavor, load_mapping
from .planner import plan as _plan
from .query_compiler import compile_sql
from .structured_output import Adapter

__all__ = ["Citation", "ReasonedAnswer", "search"]

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))            # repo root
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


# ── internal helpers ────────────────────────────────────────────────────────
def _execute_readonly(db_path: str, sql: str, params: list) -> list[dict]:
    """Execute a SELECT against a SQLite DB opened read-only (Phase 0).

    Phase 1 (§11 #10) routes all backends through ``src/db_connector`` with the
    full safety layer; for now SQLite ``mode=ro`` gives a hard read-only guard.
    """
    import sqlite3

    if not sql.lstrip().upper().startswith("SELECT"):
        raise RuntimeError("refusing to run a non-SELECT statement")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]
    finally:
        con.close()


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


def _synthesize(adapter: Adapter, question: str, rows: list[dict]) -> str:
    import json

    payload = {
        "system": _SYNTH_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Records (JSON): {json.dumps(rows, default=str)[:6000]}\n\n"
                    "Write a short, direct answer grounded in these records."
                ),
            }
        ],
        "token_budget": 600,
        "payload_id": "reasoning-search-synth",
    }
    return adapter.complete(payload).strip()


# ── public API ──────────────────────────────────────────────────────────────
def search(
    question: str,
    *,
    flavor: str,
    db_path: str | None = None,
    providers: str | dict[str, str] | None = "ollama",
    depth: str = "single_hop",
    k: int = 5,
    adapter: Adapter | None = None,
    flavors_dir: str | None = None,
    mapping_path: str | None = None,
    limit: int = 200,
) -> ReasonedAnswer:
    """Run ontology-grounded reasoning search and return a `ReasonedAnswer`.

    Phase 0: single-hop. ``adapter`` may be injected (tests / custom providers);
    otherwise it is resolved from ``providers``. ``flavors_dir`` / ``mapping_path``
    default to the repo's generated artifacts but can be pointed at fixtures.
    """
    flavors_dir = flavors_dir or _DEFAULT_FLAVORS
    mapping_path = mapping_path or _DEFAULT_MAPPING
    llm = adapter or _resolve_adapter(providers)
    provider_label = providers if isinstance(providers, str) else getattr(llm, "model_id", "")

    trace: list[dict[str, Any]] = []

    # 1–2. Understand + Plan (ontology-validated)
    flavor_cfg = load_flavor(flavor, flavors_dir)
    vocab = controlled_vocab(flavor_cfg)
    allowed_tables = set(flavor_cfg.get("db_tables", []) or [])
    the_plan = _plan(question, vocab=vocab, adapter=llm)
    trace.append({"stage": "plan", "classes": the_plan.classes, "intent": the_plan.intent,
                  "filters": [vars(f) for f in the_plan.filters]})

    # 3. Execute (read-only, allow-listed)
    mapping = load_mapping(mapping_path)
    sql, params = compile_sql(the_plan, mapping=mapping, allowed_tables=allowed_tables, limit=limit)
    rows = _execute_readonly(db_path, sql, params) if db_path else []
    trace.append({"stage": "execute", "sql": sql, "params": params, "rows": len(rows)})

    # 5. Synthesize (Phase 0 — reason/verify stages added in Phase 2)
    answer = _synthesize(llm, question, rows)
    trace.append({"stage": "synthesize", "chars": len(answer)})

    table = mapping.table_for(the_plan.primary_class) or ""
    citations = [
        Citation(
            iri=f"{the_plan.primary_class}/{row.get('id', i)}",
            label=str(next(iter(row.values()), "")),
            source_table=table,
        )
        for i, row in enumerate(rows[:k])
    ]

    return ReasonedAnswer(
        answer=answer,
        plan={"intent": the_plan.intent, "classes": the_plan.classes,
              "filters": [vars(f) for f in the_plan.filters]},
        results=rows,
        citations=citations,
        confidence=0.85 if rows else 0.3,
        executed_query=sql,
        trace=trace,
        provider=str(provider_label),
    )
