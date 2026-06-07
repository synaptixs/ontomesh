"""Ontology-grounded reasoning search (Phase 0 scaffold).

Public API:
    from runtime.reasoning_search import search, ReasonedAnswer, Citation

See REASONING_SEARCH_DESIGN.local.md for the design and §11 task plan.
"""

from .engine import Citation, ReasonedAnswer, search

__all__ = ["Citation", "ReasonedAnswer", "search"]
