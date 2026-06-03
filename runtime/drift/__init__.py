"""Production-drift integration for the ontology-toolkit.

Wraps the `drift_monitor` package (formerly known as *infodrift*) with the
toolkit's OWL class hierarchy, SHACL shapes, and JSON-LD context.

Five phases:

  P1 — pip dependency declared in requirements.txt
  P2 — :class:`OntologyDriftMonitor` registers OWL individuals as monitored
        entities in :class:`drift_monitor.DriftOrchestrator`.
  P3 — :class:`SHACLGate` validates production DataFrames against the
        toolkit's NodeShapes before they reach any monitor.
  P4 — :class:`DriftEnricher` wraps a drift report in JSON-LD + PROV-O and
        appends it to the toolkit's ObservationRecord store.
  P5 — :class:`OWLPropagator` traverses the class graph to surface
        dependent or sibling entities that should also be watched after an
        alert. :class:`runtime.client.RuntimeClient` reads the monitor's
        recent-alerts buffer and injects it into every payload.

Each component is independently importable; they wire together in
``runtime/client.py``.
"""

from .monitor import OntologyDriftMonitor, iri_to_entity_key
from .gate import SHACLGate
from .enricher import DriftEnricher
from .propagator import OWLPropagator

__all__ = [
    "OntologyDriftMonitor",
    "iri_to_entity_key",
    "SHACLGate",
    "DriftEnricher",
    "OWLPropagator",
]
