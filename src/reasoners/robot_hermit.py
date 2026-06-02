"""
src/reasoners/robot_hermit.py — T2.1
────────────────────────────────────
ROBOT (Java) + HermiT — full OWL 2 DL reasoner.

Use this when your ontology needs:
- Inverse object properties
- Functional / inverse-functional object properties
- ``owl:hasKey`` declarations
- Property chains beyond what ELK handles

The trade-off vs ELK: HermiT is materially slower (10–100×) on
ontologies that *could* have stayed in EL. We default to ELK in
:func:`registry.default_reasoner_for_profile` and only return
HermiT when the profile is DL.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from .base import Inconsistency, ReasonerResult, RedundancyFinding
from .robot_elk import _robot_binary, _run


@dataclass
class RobotHermitReasoner:
    name: str = "robot-hermit"

    def available(self) -> bool:
        return _robot_binary() is not None

    def classify(self, ontology_path: str,
                 *, output_path: Optional[str] = None,
                 ) -> ReasonerResult:
        robot = _robot_binary()
        if not robot:
            return ReasonerResult(
                reasoner=self.name, status="SKIPPED",
                message="ROBOT binary not found.",
            )
        out = output_path or os.path.join(
            os.path.dirname(ontology_path) or ".",
            "enterprise-hermit-classified.ttl",
        )
        t0 = time.perf_counter()
        cmd = [robot, "reason",
               "--reasoner", "hermit",
               "--input", ontology_path,
               "--output", out]
        result = _run(cmd)
        if result.returncode != 0:
            return ReasonerResult(
                reasoner=self.name, status="ERROR",
                message=(result.stderr or result.stdout)[:500],
                duration_s=time.perf_counter() - t0,
            )
        return ReasonerResult(
            reasoner=self.name, status="OK",
            message="HermiT closure written",
            duration_s=time.perf_counter() - t0,
            derived_axioms_path=out,
        )

    def check_consistency(self, ontology_path: str) -> Inconsistency:
        robot = _robot_binary()
        if not robot:
            return Inconsistency(message="ROBOT binary not found")
        cmd = [robot, "reason",
               "--reasoner", "hermit",
               "--input", ontology_path,
               "--output", "/dev/null"]
        result = _run(cmd)
        unsat: List[str] = []
        for line in (result.stderr + result.stdout).splitlines():
            if "unsatisfiable" in line.lower() or "inconsistent" in line.lower():
                m = re.search(r"<[^>]+>|:\w+", line)
                if m:
                    unsat.append(m.group(0))
        msg = ""
        if result.returncode != 0:
            msg = (result.stderr or result.stdout)[:500]
        return Inconsistency(
            unsat_classes=sorted(set(unsat)),
            message=msg or ("consistent" if not unsat else
                            f"{len(unsat)} unsatisfiable class(es)"),
        )

    def detect_redundant_shacl(self, ontology_path: str,
                               shapes_path: str,
                               ) -> List[RedundancyFinding]:
        return []          # see RobotElkReasoner.detect_redundant_shacl


__all__ = ["RobotHermitReasoner"]
