"""Ontology-grounded reasoning search — engine entry point.

Turns a natural-language question into a **cited, reasoned** answer that is
grounded in the generated ontology and executed **safely** against the connected
database. Runs against local (Ollama) or cloud (OpenAI) providers.

Pipeline (filled in across Phase 0–2 — see REASONING_SEARCH_DESIGN.local.md §3/§11):

    understand → plan → execute → reason → synthesize → verify

This module defines the **public response contract** (`ReasonedAnswer`,
`Citation`) shared by the SDK, CLI, API, and the wizard "Ask" console, plus a
`search()` stub. The feature is flagged via the ``ONTOMESH_SEARCH`` env var and
ships dark until Phase 1 GA.

Status: **Phase 0 scaffold** — `search()` is not implemented yet; the
north-star acceptance test (`tests/test_reasoning_search_e2e.py`) is `xfail`
until the engine lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Citation", "ReasonedAnswer", "search"]


@dataclass
class Citation:
    """A traceable source backing a claim in the answer.

    Every factual claim in a `ReasonedAnswer` must map to at least one Citation.
    Inferred (rule-derived) facts set ``inferred=True`` and carry their
    ``prov:wasDerivedFrom`` lineage instead of a physical source table.
    """

    iri: str                      # e.g. "tmf:Customer/acme" or "prov:Derived/impacts-acme"
    label: str = ""               # human-readable description
    source_table: str = ""        # physical provenance ("" when inferred)
    inferred: bool = False        # True if derived via OWL-RL/Datalog


@dataclass
class ReasonedAnswer:
    """The single response contract shared by every surface (SDK/CLI/API/app).

    Keeping one typed shape means the wizard console, the `/api/search` route,
    the CLI, and the SDK all render the same fields — and the JSON form is stable
    from day one (pinned here intentionally before any surface is built).
    """

    answer: str                                   # synthesized natural-language answer
    plan: dict[str, Any] = field(default_factory=dict)        # the validated query plan
    results: list[dict[str, Any]] = field(default_factory=list)   # retrieved records (JSON-LD)
    citations: list[Citation] = field(default_factory=list)       # sources per claim
    inferred: list[dict[str, Any]] = field(default_factory=list)  # derived facts + prov lineage
    confidence: float = 0.0                        # 0.0–1.0
    executed_query: str = ""                       # the read-only SQL actually run (transparency)
    trace: list[dict[str, Any]] = field(default_factory=list)     # stage-by-stage reasoning trace
    provider: str = ""                             # which LLM produced the answer


def search(
    question: str,
    *,
    flavor: str,
    db_path: str | None = None,
    providers: str | dict[str, str] | None = None,
    depth: str = "single_hop",      # "single_hop" (MVP-1) | "multi_hop" (MVP-2)
    k: int = 5,
) -> ReasonedAnswer:
    """Run ontology-grounded reasoning search and return a `ReasonedAnswer`.

    NOT YET IMPLEMENTED — Phase 0 stub. The implementation wires:
    planner → query_compiler (safe SQL) → retriever/grounder → reasoner →
    synthesis, per REASONING_SEARCH_DESIGN.local.md §11.

    Args:
        question: the natural-language question.
        flavor:   ontology flavor / scope (e.g. "network-ops", "clinical-research").
        db_path:  path/connection to the database to query (live, read-only).
        providers: provider name (e.g. "ollama", "openai") or a per-role mapping
                   ``{"planner": "openai", "synthesizer": "ollama", ...}``.
        depth:    "single_hop" or "multi_hop".
        k:        retrieval breadth.
    """
    raise NotImplementedError(
        "reasoning_search.search() is a Phase-0 scaffold — "
        "see REASONING_SEARCH_DESIGN.local.md §11 for the task plan."
    )
