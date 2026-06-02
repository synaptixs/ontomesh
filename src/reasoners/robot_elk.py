"""
src/reasoners/robot_elk.py — T2.1
─────────────────────────────────
ROBOT (Java) + ELK reasoner adapter.

ELK is the fastest known OWL 2 EL reasoner — perfect for the
classification call site on large ontologies that stay inside
the EL profile (no inverse properties, no functional restrictions
on object properties, etc.).

Wraps the existing :func:`reasoner.run_reasoner` codepath but
exposes it via the new plug-in Protocol so callers can swap
reasoners without touching call sites.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

from .base import Inconsistency, ReasonerResult, RedundancyFinding


@dataclass
class RobotElkReasoner:
    name: str = "robot-elk"

    def available(self) -> bool:
        return _robot_binary() is not None

    def classify(self, ontology_path: str,
                 *, output_path: Optional[str] = None,
                 ) -> ReasonerResult:
        robot = _robot_binary()
        if not robot:
            return ReasonerResult(
                reasoner=self.name, status="SKIPPED",
                message="ROBOT binary not found; place in bin/robot or install.",
            )
        out = output_path or os.path.join(
            os.path.dirname(ontology_path) or ".",
            "enterprise-elk-classified.ttl",
        )
        t0 = time.perf_counter()
        cmd = [robot, "reason",
               "--reasoner", "elk",
               "--input", ontology_path,
               "--output", out]
        result = _run(cmd)
        if result.returncode != 0:
            return ReasonerResult(
                reasoner=self.name, status="ERROR",
                message=(result.stderr or result.stdout)[:500],
                duration_s=time.perf_counter() - t0,
            )
        # ROBOT writes only the inferred axioms by default. We surface
        # the path; downstream code can diff against the input.
        return ReasonerResult(
            reasoner=self.name, status="OK",
            message="ELK closure written",
            duration_s=time.perf_counter() - t0,
            derived_axioms_path=out,
        )

    def check_consistency(self, ontology_path: str) -> Inconsistency:
        robot = _robot_binary()
        if not robot:
            return Inconsistency(message="ROBOT binary not found")
        cmd = [robot, "reason",
               "--reasoner", "elk",
               "--input", ontology_path,
               "--output", "/dev/null"]
        result = _run(cmd)
        unsat: List[str] = []
        for line in (result.stderr + result.stdout).splitlines():
            if "unsatisfiable" in line.lower():
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
        # ROBOT doesn't expose entailment-vs-SHACL natively. We leave
        # the redundancy detector to the rdflib-based adapter; an
        # advanced ROBOT-only deployment can run owlrl alongside.
        return []


# ── helpers ──────────────────────────────────────────────────────────────


def _robot_binary() -> Optional[str]:
    """Locate the ROBOT binary (bundled at ``bin/robot`` or on PATH)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [os.path.join(here, "..", "bin", "robot"),
                  shutil.which("robot")]
    for path in candidates:
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        try:
            r = subprocess.run([path, "--version"], capture_output=True,
                               timeout=15)
            if r.returncode == 0:
                return path
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _run(cmd, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


__all__ = ["RobotElkReasoner"]
