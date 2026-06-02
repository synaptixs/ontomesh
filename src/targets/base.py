"""
src/targets/base.py — T1.5
──────────────────────────
GenerationContext + Target abstract base class.

The contract: the ontology in memory is captured once as a
``GenerationContext`` (tables + session + log-discovery proposals).
Each ``Target`` adapter consumes that context and returns a dict
mapping ``relative/output/path -> content``. The caller writes the
files; targets remain pure functions of the context.

Why pure?
  - Testable without disk.
  - Idempotent — same context → same output.
  - Caller controls atomicity (write to tmp, rename) and overwrite policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence


@dataclass
class GenerationContext:
    """Single source of truth handed to every target.

    Fields mirror what the existing generators already build up
    internally:

    - ``tables`` — output of ``DBIntrospector.introspect_all()``;
      list of ``TableModel`` (kept as ``Any`` here to avoid a hard
      dependency cycle when targets are imported in isolation).
    - ``session`` — the wizard session dict (entities, events,
      relationships, competency_questions, causal_rules).
    - ``proposals`` — rows from ``ontology_evolution_proposals``,
      already filtered to ``status='APPROVED'`` (the rule of thumb:
      generate from approved truth, not pending guesses).
    - ``base_iri`` and ``domain_name`` — the standard ontology
      identity fields from session.domain.
    """
    tables:      List[Any] = field(default_factory=list)
    session:     Dict[str, Any] = field(default_factory=dict)
    proposals:   List[Dict[str, Any]] = field(default_factory=list)
    base_iri:    str = "https://ontology.example.com/enterprise/"
    domain_name: str = "Enterprise"

    @classmethod
    def from_introspector(cls,
                          intro: Any,
                          *, session: Optional[Dict[str, Any]] = None,
                          proposals: Optional[Sequence[Dict[str, Any]]] = None,
                          ) -> "GenerationContext":
        """Build the context from a ``DBIntrospector`` instance plus
        optional wizard session + approved proposals."""
        tables = list(intro.introspect_all()) if intro is not None else []
        s = dict(session or {})
        domain = (s.get("domain") or {})
        return cls(
            tables=tables,
            session=s,
            proposals=list(proposals or []),
            base_iri=domain.get("base_iri")
                     or "https://ontology.example.com/enterprise/",
            domain_name=domain.get("name") or "Enterprise",
        )

    # ── Convenience accessors ────────────────────────────────────────────

    def causal_edges(self) -> List[Dict[str, Any]]:
        return [p for p in self.proposals
                if p.get("kind") == "LOG_CAUSAL_EDGE"
                or p.get("proposal_type") == "LOG_CAUSAL_EDGE"]

    def event_proposals(self) -> List[Dict[str, Any]]:
        return [p for p in self.proposals
                if p.get("kind") == "LOG_EVENT"
                or p.get("proposal_type") == "LOG_EVENT"]

    def entity_proposals(self) -> List[Dict[str, Any]]:
        return [p for p in self.proposals
                if p.get("kind") == "LOG_ENTITY"
                or p.get("proposal_type") == "LOG_ENTITY"]


@dataclass
class TargetResult:
    """Wraps a single target's run: the file map + summary stats.

    Stats are simple ints — every target reports how many rules,
    classes, types it emitted, for the wizard / CLI to display.
    """
    target:    str
    files:     Dict[str, str] = field(default_factory=dict)
    stats:     Dict[str, int] = field(default_factory=dict)
    warnings:  List[str] = field(default_factory=list)


class Target(Protocol):
    """Adapter contract.

    Implementations are pure functions of ``GenerationContext``.
    A target with no relevant input (e.g. detection_rules with no
    causal edges in the context) returns an empty ``files`` dict —
    the dispatcher decides whether to skip writing entirely.
    """

    name: str
    """Lower-case identifier used in CLI flags and file paths."""

    def generate(self, ctx: GenerationContext) -> TargetResult:
        ...


__all__ = ["GenerationContext", "TargetResult", "Target"]
