"""
src/reasoning.py — T2.1
───────────────────────
High-level v3 API for ontology reasoning. Wraps the plug-in
:mod:`reasoners` subpackage with the three call sites the roadmap
names:

    classify(ontology_path)
        — derived class hierarchy + accidentally-entailed subclass
          relationships the engineer didn't write.

    check_consistency(ontology_path)
        — fail-fast pass used as a build gate inside ``--phase 2``.
          Returns an :class:`Inconsistency` whose ``has_findings()``
          flips True when the ontology is internally contradictory.

    detect_redundant_shacl(ontology_path, shapes_path)
        — SHACL shapes whose body is already implied by OWL.

The legacy :mod:`reasoner` (no ``s``) module remains untouched —
toolkit.py's existing call sites keep working with the v2 behaviour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from reasoners import (
    Inconsistency, Reasoner, ReasonerResult, get_reasoner,
)


@dataclass
class ClassificationReport:
    """Result of :func:`classify`. Same shape an engineer reads in
    the wizard's reasoning panel."""
    reasoner:           str
    status:             str
    derived_subclass:   List[tuple] = field(default_factory=list)
    accidental_subclass: List[tuple] = field(default_factory=list)
    derived_class_count: int = 0
    duration_s:         float = 0.0
    message:            str = ""
    raw:                Optional[ReasonerResult] = None

    def as_dict(self) -> dict:
        return {
            "reasoner":            self.reasoner,
            "status":              self.status,
            "derived_subclass":    list(self.derived_subclass),
            "accidental_subclass": list(self.accidental_subclass),
            "derived_class_count": self.derived_class_count,
            "duration_s":          self.duration_s,
            "message":             self.message,
        }


def classify(ontology_path: str,
             *, reasoner: Optional[str] = None,
             profile: Optional[str] = None,
             expected_subclass: Optional[List[tuple]] = None,
             output_path: Optional[str] = None,
             ) -> ClassificationReport:
    """Run the reasoner and return a classification report.

    Parameters
    ----------
    ontology_path : str
        Path to the input Turtle / OWL file.
    reasoner : str, optional
        Explicit reasoner name. When None, picked by ``profile`` via
        :func:`reasoners.default_reasoner_for_profile`.
    profile : str, optional
        Free-text profile hint ("OWL 2 EL" / "OWL 2 DL" / "OWL 2 RL").
    expected_subclass : list of (sub_iri, super_iri), optional
        The set of asserted-or-intended subclass pairs. Any
        ``rdfs:subClassOf`` triple in the closure that is *not* in
        this set is surfaced as an "accidental" subclass — a
        derived axiom the engineer didn't intend to write.
    output_path : str, optional
        When given, the adapter writes the full closure here.
    """
    r = get_reasoner(reasoner, profile=profile)
    result = r.classify(ontology_path, output_path=output_path)
    expected_set = set(expected_subclass or [])
    accidental = [pair for pair in result.derived_subclass
                  if pair not in expected_set]
    return ClassificationReport(
        reasoner=result.reasoner, status=result.status,
        derived_subclass=list(result.derived_subclass),
        accidental_subclass=accidental,
        derived_class_count=result.derived_class_count,
        duration_s=result.duration_s,
        message=result.message,
        raw=result,
    )


def check_consistency(ontology_path: str,
                      *, reasoner: Optional[str] = None,
                      profile: Optional[str] = None,
                      ) -> Inconsistency:
    """Fail-fast consistency check for the build gate.

    Returns an :class:`Inconsistency` whose ``has_findings()`` is
    True when the ontology is internally contradictory. Caller can:

        report = check_consistency(path)
        if report.has_findings():
            raise BuildError(report.message)
    """
    r = get_reasoner(reasoner, profile=profile)
    return r.check_consistency(ontology_path)


def detect_redundant_shacl(ontology_path: str,
                           shapes_path: str,
                           *, reasoner: Optional[str] = None,
                           profile: Optional[str] = None,
                           ) -> list:
    """Surface SHACL constraints already entailed by the OWL axioms.

    Each finding carries the shape IRI, target class, the
    constraint's human-readable form, and a one-sentence
    explanation of which entailment makes it redundant.
    """
    r = get_reasoner(reasoner, profile=profile)
    return r.detect_redundant_shacl(ontology_path, shapes_path)


__all__ = [
    "ClassificationReport", "Inconsistency",
    "classify", "check_consistency", "detect_redundant_shacl",
]
