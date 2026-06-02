"""
src/reasoners/mock.py — T2.1
────────────────────────────
Deterministic mock reasoner for unit tests + cold-start envs.

Returns canned ReasonerResult / Inconsistency values without
touching disk or invoking subprocesses. Tests inject this when
they want to exercise the plug-in framework itself rather than
any real reasoning engine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from .base import Inconsistency, ReasonerResult, RedundancyFinding


@dataclass
class MockReasoner:
    name: str = "mock"
    # Knobs the test sets up so it can control returned results.
    canned_derived: List[tuple] = field(default_factory=list)
    canned_inconsistency: Optional[Inconsistency] = None
    canned_redundancies: List[RedundancyFinding] = field(default_factory=list)
    _is_available: bool = True

    def available(self) -> bool:
        return self._is_available

    def classify(self, ontology_path: str,
                 *, output_path: Optional[str] = None,
                 ) -> ReasonerResult:
        return ReasonerResult(
            reasoner=self.name, status="OK",
            derived_subclass=list(self.canned_derived),
            duration_s=0.001,
            derived_axioms_path=output_path,
        )

    def check_consistency(self, ontology_path: str) -> Inconsistency:
        if self.canned_inconsistency is not None:
            return self.canned_inconsistency
        return Inconsistency(message="consistent")

    def detect_redundant_shacl(self, ontology_path: str,
                               shapes_path: str,
                               ) -> List[RedundancyFinding]:
        return list(self.canned_redundancies)


__all__ = ["MockReasoner"]
