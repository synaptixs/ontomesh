"""Phase 5 — OWL-graph alert propagation.

Given an alert on an entity, walk the OWL class graph to surface
*dependent* and *sibling* entities whose monitoring should also be
elevated.

Differences vs. the original integration plan
---------------------------------------------
The plan called ``orchestrator.increase_monitoring_frequency(key)`` —
that method does not exist on :class:`drift_monitor.DriftOrchestrator`.
We instead record the escalations in a local ledger
(``OWLPropagator.escalations``) which the LLM-facing
``runtime/client.py`` injects into the prompt. The actual cadence
change is the orchestrator's responsibility (driven by ``slo_config``);
this module's job is purely *who else to look at*.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS


DEFAULT_ONTOLOGY_PATH = Path("output/ontology/enterprise.ttl")
DEFAULT_NAMESPACE = "https://ontology.example.com/retail#"


class OWLPropagator:
    """Find entities that should be watched after another entity alerts.

    The default policy:
      1. Find the OWL class of the alerting entity (from its IRI prefix).
      2. Collect every other class linked to it by an
         :class:`rdflib.namespace.RDFS.subClassOf` parent (siblings).
      3. Collect every individual whose IRI shares the alerting
         entity's instance suffix and whose class falls into the
         sibling set (dependents/peers).

    Override :meth:`related_classes` and :meth:`related_individuals` for
    domain-specific traversal (e.g. property-graph dependencies).
    """

    def __init__(
        self,
        ontology_path: str | Path = DEFAULT_ONTOLOGY_PATH,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> None:
        self._ontology_path = Path(ontology_path)
        self._ns = Namespace(namespace)
        self._g = Graph()
        if self._ontology_path.exists():
            self._g.parse(self._ontology_path, format="turtle")
        # entity_key → list of escalation events
        self._escalations: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # ── Traversal primitives ─────────────────────────────────────────────
    def related_classes(self, owl_class: URIRef) -> set[URIRef]:
        """Siblings: classes sharing any rdfs:subClassOf parent."""
        siblings: set[URIRef] = set()
        for parent in self._g.objects(owl_class, RDFS.subClassOf):
            for sibling in self._g.subjects(RDFS.subClassOf, parent):
                if isinstance(sibling, URIRef) and sibling != owl_class:
                    siblings.add(sibling)
        return siblings

    def related_individuals(
        self,
        owl_class: URIRef,
        suffix: str,
    ) -> set[str]:
        """Individuals of *owl_class* whose IRI ends with *suffix*."""
        out: set[str] = set()
        for indiv in self._g.subjects(RDF.type, owl_class):
            local = str(indiv)
            if not local.startswith(str(self._ns)):
                continue
            local = local[len(str(self._ns)):]
            if suffix and not local.endswith(suffix):
                continue
            out.add(local.replace("/", "::"))
        return out

    # ── Alert handling ───────────────────────────────────────────────────
    def dependents(self, entity_key: str) -> list[str]:
        """Return a deduplicated list of entity keys related to *entity_key*."""
        if "::" in entity_key:
            class_part, _, suffix_part = entity_key.partition("::")
            suffix = suffix_part.replace("::", "/")
        else:
            # 5G-NF-style: AMF_v2_RegionA_N11
            parts = entity_key.split("_")
            class_part = parts[0]
            suffix = "_".join(parts[1:])

        owl_class = self._ns[class_part]
        related: set[str] = set()
        for sibling_class in self.related_classes(owl_class):
            local_class = str(sibling_class).replace(str(self._ns), "")
            if suffix:
                related.add(f"{local_class}::{suffix}")
            else:
                related.add(local_class)
        return sorted(related)

    def propagate(
        self,
        alert: Any,
        monitor=None,
    ) -> list[str]:
        """Record escalations for entities related to *alert.entity_key*.

        ``alert`` may be a :class:`drift_monitor.Alert` dataclass or any
        object/dict with an ``entity_key`` attribute/key. ``monitor`` is
        accepted for API parity with the integration plan but is
        unused — the underlying orchestrator does not expose a
        per-entity frequency knob, so escalation is recorded locally
        and surfaced via :meth:`escalations_for`.
        """
        key = self._alert_field(alert, "entity_key", "")
        if not key:
            return []
        deps = self.dependents(key)
        for dep in deps:
            self._escalations[dep].append({
                "from_entity":   key,
                "severity":      self._alert_field(alert, "severity"),
                "metric_type":   self._alert_field(alert, "metric_type"),
                "message":       self._alert_field(alert, "message"),
                "timestamp":     self._alert_field(alert, "timestamp"),
            })
        return deps

    # ── Read API ─────────────────────────────────────────────────────────
    def escalations_for(self, entity_key: str) -> list[dict[str, Any]]:
        return list(self._escalations.get(entity_key, []))

    @property
    def escalations(self) -> dict[str, list[dict[str, Any]]]:
        return dict(self._escalations)

    def clear(self) -> None:
        self._escalations.clear()

    # ── Helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _alert_field(alert: Any, name: str, default: Any = None) -> Any:
        if alert is None:
            return default
        if hasattr(alert, name):
            return getattr(alert, name)
        if isinstance(alert, dict):
            return alert.get(name, default)
        return default
