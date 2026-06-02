"""
src/reasoners — T2.1 pluggable reasoner adapters.

The toolkit emits OWL 2; this subpackage closes the loop by *reasoning*
over what's emitted. Three call sites use these adapters:

  - **Classification.** Compute the derived ``rdfs:subClassOf``
    closure so the engineer can spot accidental subsumptions.
  - **Consistency.** Fail the build when the ontology is internally
    contradictory; surface the minimal unsatisfiable axiom set.
  - **Entailment-redundant SHACL.** Flag SHACL constraints whose
    body is already entailed by the OWL axioms — the redundancy is
    a sign the constraint isn't pulling its weight.

Three adapters ship in this release:

  - ``robot_hermit``  — ROBOT (Java) + HermiT — full OWL 2 DL.
  - ``robot_elk``     — ROBOT (Java) + ELK — fast, OWL 2 EL only.
  - ``owlrl``         — pure-Python owlrl forward-chain — OWL 2 RL.
                        Always available; default fallback.

A ``mock`` adapter is registered for tests.
"""

from .base import Reasoner, ReasonerResult, Inconsistency
from .registry import (
    AVAILABLE_REASONERS, get_reasoner, default_reasoner_for_profile,
)
from .mock import MockReasoner
from .owlrl_adapter import OwlrlReasoner
from .robot_elk import RobotElkReasoner
from .robot_hermit import RobotHermitReasoner

__all__ = [
    "Reasoner", "ReasonerResult", "Inconsistency",
    "AVAILABLE_REASONERS", "get_reasoner", "default_reasoner_for_profile",
    "MockReasoner", "OwlrlReasoner",
    "RobotElkReasoner", "RobotHermitReasoner",
]
