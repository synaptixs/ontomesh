"""
src/reasoners/base.py — T2.1
────────────────────────────
Reasoner Protocol + result dataclasses.

The contract is intentionally narrow — three methods. Every
adapter (ROBOT-backed, owlrl-backed, mock) implements the same
shape, so swapping is free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple


@dataclass
class ReasonerResult:
    """Output of :meth:`Reasoner.classify`.

    - ``status`` is one of ``"OK"`` / ``"INCONSISTENT"`` / ``"SKIPPED"`` /
      ``"ERROR"``. ``"OK"`` means the reasoner ran cleanly; the derived
      hierarchy and axioms are populated.
    - ``derived_subclass`` lists the inferred ``(subclass, superclass)``
      pairs *not present* as asserted axioms — pure new knowledge.
    - ``derived_axioms_path`` (optional) holds a path to a Turtle file
      with the full closure if the adapter materialised it to disk.
    """
    reasoner:           str
    status:             str
    message:            str = ""
    derived_subclass:   List[Tuple[str, str]] = field(default_factory=list)
    derived_equivalent: List[Tuple[str, str]] = field(default_factory=list)
    asserted_class_count:  int = 0
    derived_class_count:   int = 0
    duration_s:         float = 0.0
    derived_axioms_path: Optional[str] = None

    def ok(self) -> bool:
        return self.status == "OK"


@dataclass
class Inconsistency:
    """One inconsistency the reasoner found. ``unsat_classes`` lists
    classes the closure proved equivalent to ``owl:Nothing`` (no
    possible instance). ``conflicting_axioms`` is the minimal axiom
    set the adapter could surface — empty when the adapter cannot
    produce one (ELK / owlrl)."""
    unsat_classes:       List[str] = field(default_factory=list)
    conflicting_axioms:  List[str] = field(default_factory=list)
    individuals:         List[str] = field(default_factory=list)
    message:             str = ""

    def has_findings(self) -> bool:
        return bool(self.unsat_classes
                    or self.conflicting_axioms
                    or self.individuals)


@dataclass
class RedundancyFinding:
    """A SHACL constraint whose body is already entailed by OWL.

    The reviewer can delete the SHACL shape without weakening the
    contract — the entailment will still hold.
    """
    shape_iri:    str
    target_class: str
    constraint:   str      # short human-readable rendering
    reason:       str      # how the OWL closure satisfies it


class Reasoner(Protocol):
    """Adapter contract — every reasoner implementation provides
    these three methods. Implementations must be safe to call in
    sequence on the same ontology file."""

    name: str
    """Lower-case identifier ('robot-hermit' / 'robot-elk' / 'owlrl' / 'mock')."""

    def available(self) -> bool:
        """Return ``True`` iff the underlying runtime (Java + ROBOT,
        owlrl, …) is present. Selection in :func:`registry.get_reasoner`
        uses this to skip unavailable adapters silently."""
        ...

    def classify(self, ontology_path: str,
                 *, output_path: Optional[str] = None,
                 ) -> ReasonerResult:
        """Compute the derived class hierarchy. If ``output_path`` is
        given the adapter writes the full closure as Turtle there."""
        ...

    def check_consistency(self, ontology_path: str) -> Inconsistency:
        """Run a fast pass that only checks for inconsistency. Used as
        the build-gate call site — fail fast on contradictions before
        we spend time materialising the full closure."""
        ...

    def detect_redundant_shacl(
            self, ontology_path: str, shapes_path: str,
    ) -> List[RedundancyFinding]:
        """Surface SHACL shapes whose body is already entailed by the
        OWL axioms. May return an empty list for adapters that don't
        support this (it's an opt-in capability)."""
        ...


__all__ = ["Reasoner", "ReasonerResult", "Inconsistency", "RedundancyFinding"]
