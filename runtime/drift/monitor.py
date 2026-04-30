"""Phase 2 — OWL individuals drive ``drift_monitor`` entity registration.

Reads the toolkit-generated OWL ontology, walks every individual under a
configured namespace, and registers each as an entity inside
:class:`drift_monitor.DriftOrchestrator`. The toolkit DB / ontology is the
single source of truth for *which* entities to monitor; baselines (training
DataFrames and log corpora) are passed in by the caller.

Differences vs. the original integration plan
---------------------------------------------
* Import is ``drift_monitor``, not ``infodrift`` — the published package
  uses dist name ``drift-monitor`` and module name ``drift_monitor``.
* The orchestrator has no ``recent_alerts(n=)`` API, so this wrapper keeps
  its own bounded ring buffer of alerts produced by every ``run()`` call.
  :meth:`OntologyDriftMonitor.recent_alerts` is what the toolkit's
  :class:`runtime.client.RuntimeClient` reads at prompt-assembly time.
* The ``FIVEG`` namespace from the plan is generalised — pass any IRI
  prefix that matches your generated ontology (e.g. the retail flavor
  uses ``https://ontology.example.com/retail#``). The default points at
  the toolkit's canonical retail/5G IRI roots, but is configurable.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Iterable

# Defer the heavy import so this module can be loaded for type-hint and
# docstring inspection even when drift_monitor is not installed.
try:
    from drift_monitor import Alert, DriftOrchestrator
    _DRIFT_MONITOR_OK = True
except ImportError as _exc:  # pragma: no cover — dependency missing
    Alert = None  # type: ignore[assignment]
    DriftOrchestrator = None  # type: ignore[assignment]
    _DRIFT_MONITOR_OK = False
    _IMPORT_ERROR = _exc

from rdflib import Graph, Namespace, RDF, URIRef
from rdflib.namespace import OWL


DEFAULT_ONTOLOGY_PATH = Path("output/ontology/enterprise.ttl")
DEFAULT_NAMESPACE = "https://ontology.example.com/retail#"
ALERT_BUFFER_DEFAULT = 64

DEFAULT_SLO_CONFIG = {
    "psi":         {"warning": 0.10, "critical": 0.20},
    "ttd_seconds": {"warning": 120,  "critical": 300},
    "fpr":         {"warning": 0.08, "critical": 0.15},
}


def iri_to_entity_key(iri: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    """Convert an OWL IRI under *namespace* to a ``::`` entity key.

    Examples
    --------
    >>> iri_to_entity_key("https://ontology.example.com/retail#Customer/1",
    ...                   "https://ontology.example.com/retail#")
    'Customer::1'

    >>> iri_to_entity_key("https://example.org/5g#AMF_RegionA_N11",
    ...                   "https://example.org/5g#")
    'AMF::RegionA::N11'

    Toolkit-style IRIs (``Class/instance-id``) are split on ``/`` so
    they yield ``Class::instance-id`` directly. Underscore-separated
    IRIs are split on the first two underscores, which fits common 5G
    NF naming. Domain-specific schemes can bypass this helper entirely
    by passing pre-built entity keys to
    :meth:`OntologyDriftMonitor.register_all`.
    """
    local = str(iri)
    if local.startswith(namespace):
        local = local[len(namespace):]
    if "/" in local:
        # Toolkit-style — Class/instance-id, e.g. Customer/1.
        return local.replace("/", "::")
    if "_" in local:
        # 5G-NF-style — Class_version_region_iface, e.g. AMF_v2_RegionA_N11.
        parts = local.split("_", maxsplit=2)
        return "::".join(parts) if len(parts) > 1 else local
    return local


class OntologyDriftMonitor:
    """OWL-driven wrapper around :class:`drift_monitor.DriftOrchestrator`.

    Parameters
    ----------
    ontology_path:
        Path to the toolkit-generated OWL Turtle (default
        ``output/ontology/enterprise.ttl``).
    namespace:
        IRI prefix under which to discover individuals. Anything else
        in the graph is ignored. Defaults to the toolkit retail prefix;
        override for telecom / 5G / etc.
    slo_config:
        Override drift_monitor SLO thresholds. ``None`` uses
        :data:`DEFAULT_SLO_CONFIG`.
    alert_buffer:
        Maximum number of alerts retained in the local ring buffer
        :meth:`recent_alerts` reads from.
    """

    def __init__(
        self,
        ontology_path: str | Path = DEFAULT_ONTOLOGY_PATH,
        namespace: str = DEFAULT_NAMESPACE,
        slo_config: dict | None = None,
        alert_buffer: int = ALERT_BUFFER_DEFAULT,
        **orchestrator_kwargs,
    ) -> None:
        if not _DRIFT_MONITOR_OK:  # pragma: no cover
            raise RuntimeError(
                "drift_monitor (a.k.a. infodrift) is not installed. "
                "`pip install -r requirements.txt` will pull it in."
            ) from _IMPORT_ERROR
        self._ontology_path = Path(ontology_path)
        self._ns = Namespace(namespace)
        self._g = Graph()
        if self._ontology_path.exists():
            self._g.parse(self._ontology_path, format="turtle")
        self._orch = DriftOrchestrator(
            slo_config=slo_config or DEFAULT_SLO_CONFIG,
            **orchestrator_kwargs,
        )
        self._registered: list[str] = []
        self._recent: deque[Alert] = deque(maxlen=alert_buffer)

    # ── Discovery ────────────────────────────────────────────────────────
    def discover_individuals(self) -> list[str]:
        """Return the entity keys discovered under :attr:`namespace`.

        Pulls anything that is either a NamedIndividual or has any
        rdf:type pointing inside the configured namespace. Result keys
        are deterministic (sorted).
        """
        keys: set[str] = set()
        ns_str = str(self._ns)
        for subj, _, obj in self._g.triples((None, RDF.type, None)):
            s = str(subj)
            if not s.startswith(ns_str):
                continue
            if isinstance(obj, URIRef) and (
                obj == OWL.NamedIndividual or str(obj).startswith(ns_str)
            ):
                keys.add(iri_to_entity_key(s, ns_str))
        return sorted(keys)

    # ── Registration ─────────────────────────────────────────────────────
    def register_all(
        self,
        baseline_features: dict[str, Any],
        baseline_logs: dict[str, list[str]] | None = None,
        numeric_features: list[str] | None = None,
        categorical_features: list[str] | None = None,
        *,
        skip_unknown: bool = True,
    ) -> list[str]:
        """Register every discovered individual that has a baseline.

        Returns the list of entity keys actually registered. Entities
        with no baseline DataFrame are silently skipped (with
        ``skip_unknown=True``) or raise :class:`KeyError`.
        """
        baseline_logs = baseline_logs or {}
        registered: list[str] = []
        for key in self.discover_individuals():
            if key not in baseline_features:
                if skip_unknown:
                    continue
                raise KeyError(f"baseline_features missing entity {key!r}")
            self._orch.register_entity(
                entity_key=key,
                train_features_df=baseline_features[key],
                numeric_features=numeric_features,
                categorical_features=categorical_features,
                train_logs=baseline_logs.get(key, []),
            )
            registered.append(key)
        self._registered = registered
        return registered

    # ── Run ──────────────────────────────────────────────────────────────
    def run(
        self,
        entity_key: str,
        prod_df=None,
        prod_logs: list[str] | None = None,
        *,
        window_id: str = "latest",
        **kwargs,
    ) -> list[Alert]:
        """Invoke a single drift_monitor pass and append alerts to the
        local ring buffer."""
        alerts = self._orch.run(
            entity_key=entity_key,
            prod_features_df=prod_df,
            prod_logs=prod_logs or [],
            window_id=window_id,
            **kwargs,
        )
        self._recent.extend(alerts)
        return alerts

    # ── Read-side API ────────────────────────────────────────────────────
    def recent_alerts(self, n: int = 5) -> list[Alert]:
        """Return the *n* most recent alerts (newest last)."""
        if n <= 0:
            return []
        items = list(self._recent)
        return items[-n:]

    def latest_report(self, entity_key: str):
        """Pass-through to :meth:`DriftOrchestrator.latest_report`."""
        return self._orch.latest_report(entity_key)

    def orchestrator(self) -> "DriftOrchestrator":
        """Escape hatch for callers that need the underlying orchestrator
        (e.g. :class:`drift_monitor.HealthReporter`)."""
        return self._orch

    @property
    def registered_entities(self) -> list[str]:
        return list(self._registered)

    @property
    def namespace(self) -> str:
        return str(self._ns)

    @property
    def ontology(self) -> Graph:
        return self._g

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"OntologyDriftMonitor(ontology={self._ontology_path}, "
            f"ns={self._ns}, registered={len(self._registered)})"
        )


def _public_api() -> Iterable[str]:
    return ("OntologyDriftMonitor", "iri_to_entity_key", "DEFAULT_SLO_CONFIG")
