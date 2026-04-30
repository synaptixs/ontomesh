"""Phase 4 — wrap a drift report as a JSON-LD ObservationRecord.

Consumes :meth:`drift_monitor.HealthReporter.full_report` (or any
JSON-serialisable dict shaped like one) and produces a JSON-LD object
that:

  * carries the toolkit's ``@context`` (so every key resolves to a
    stable IRI for downstream agents);
  * is stamped with PROV-O attribution (``wasGeneratedBy``,
    ``wasAttributedTo``, ``hadPrimarySource``, ``atTime``);
  * is appended to the toolkit's ObservationRecord JSONL store.

The toolkit elsewhere uses sqlite for ObservationRecord storage; for
this initial integration we land drift records in a JSONL sidecar
(``output/obs_records.jsonl`` by default) so they are auditable without
schema migration. A future commit can fold them into the main
ObservationRecord table.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CONTEXT_PATH = Path("output/jsonld/enterprise-context.json")
DEFAULT_OBS_DB = Path("output/obs_records.jsonl")
DEFAULT_NAMESPACE = "https://ontology.example.com/retail#"
DRIFT_NAMESPACE = "https://ontology.example.com/drift#"


# Friendly names → drift IRI predicates. Anything not listed is passed
# through unchanged (so callers can extend the schema without code
# changes here).
_KEY_MAP: dict[str, str] = {
    "psi_score":       "drift:psiScore",
    "drift_level":     "drift:driftLevel",
    "js_score":        "drift:jsScore",
    "kl_score":        "drift:klScore",
    "brier_score":     "drift:brierScore",
    "ece":             "drift:ece",
    "tpr":             "drift:tpr",
    "fpr":             "drift:fpr",
    "median_ttd_s":    "drift:medianTTDSeconds",
    "p95_ttd_s":       "drift:p95TTDSeconds",
    "log_template_alarms": "drift:logTemplateAlarms",
    "alerts":          "drift:alerts",
    "window_id":       "drift:windowId",
    "model_version":   "drift:modelVersion",
    "baseline_id":     "drift:baselineId",
}


class DriftEnricher:
    """Wraps a drift report in JSON-LD + PROV-O and persists it.

    Parameters
    ----------
    context_path:
        Path to the toolkit-generated JSON-LD context. If absent, an
        inline minimal context is synthesised so the enricher works
        even before the full pipeline has been run.
    obs_db_path:
        Append-only JSONL output. Parent directory is created on demand.
    entity_namespace:
        IRI prefix for entity ``@id``s.
    drift_namespace:
        IRI prefix for ``drift:*`` predicates.
    """

    def __init__(
        self,
        context_path: str | Path = DEFAULT_CONTEXT_PATH,
        obs_db_path: str | Path = DEFAULT_OBS_DB,
        entity_namespace: str = DEFAULT_NAMESPACE,
        drift_namespace: str = DRIFT_NAMESPACE,
    ) -> None:
        self._context_path = Path(context_path)
        self._obs_db = Path(obs_db_path)
        self._obs_db.parent.mkdir(parents=True, exist_ok=True)
        self._ns = entity_namespace
        self._drift_ns = drift_namespace
        self._ctx = self._load_context(self._context_path)

    # ── Loaders ──────────────────────────────────────────────────────────
    def _load_context(self, path: Path) -> dict:
        if path.exists():
            with path.open() as f:
                doc = json.load(f)
            if isinstance(doc, dict) and "@context" in doc:
                return doc["@context"]
            if isinstance(doc, dict):
                return doc
        # Fallback minimal context.
        return {
            "drift": self._drift_ns,
            "prov":  "http://www.w3.org/ns/prov#",
            "rdfs":  "http://www.w3.org/2000/01/rdf-schema#",
        }

    # ── Public API ───────────────────────────────────────────────────────
    def enrich(
        self,
        raw_report: dict | str,
        *,
        baseline_id: str,
        window_id: str,
        run_iri: str | None = None,
    ) -> dict:
        """Build a JSON-LD ObservationRecord (does NOT persist).

        ``raw_report`` may be a dict or a JSON string (the latter is
        what :meth:`HealthReporter.full_report(as_json=True)` returns).
        """
        report = self._coerce(raw_report)
        entity_key = report.get("entity_key", "")
        component = entity_key.split("::")[0] if "::" in entity_key else entity_key.split("_")[0]
        run_iri = run_iri or f"{self._drift_ns}MonitoringRun_{window_id}"

        out: dict[str, Any] = {
            "@context": self._ctx,
            "@id":      f"{self._ns}{entity_key.replace('::', '_')}",
            "@type":    f"{self._ns}{component}" if component else f"{self._drift_ns}Entity",
            "drift:windowId":         window_id,
            "drift:baselineId":       baseline_id,
            "prov:wasGeneratedBy":    run_iri,
            "prov:wasAttributedTo":   f"{self._ns}{entity_key.replace('::', '_')}",
            "prov:hadPrimarySource":  f"{self._drift_ns}Baseline_{baseline_id}",
            "prov:atTime":            datetime.now(timezone.utc).isoformat(),
        }
        for key, val in report.items():
            if key in ("entity_key",):
                continue
            out[_KEY_MAP.get(key, key)] = self._jsonable(val)
        return out

    def store(self, enriched: dict) -> Path:
        """Append one JSON-LD record to the JSONL store. Returns path."""
        with self._obs_db.open("a") as f:
            f.write(json.dumps(enriched, default=str) + "\n")
        return self._obs_db

    def enrich_and_store(
        self,
        raw_report: dict | str,
        *,
        baseline_id: str,
        window_id: str,
        run_iri: str | None = None,
    ) -> dict:
        """Convenience: build + persist in one call."""
        rec = self.enrich(
            raw_report, baseline_id=baseline_id, window_id=window_id, run_iri=run_iri,
        )
        self.store(rec)
        return rec

    # ── Internals ────────────────────────────────────────────────────────
    @staticmethod
    def _coerce(raw: dict | str) -> dict:
        if isinstance(raw, str):
            return json.loads(raw)
        return dict(raw)

    @classmethod
    def _jsonable(cls, val: Any) -> Any:
        """Recursively convert dataclasses + non-JSON types."""
        if is_dataclass(val) and not isinstance(val, type):
            return cls._jsonable(asdict(val))
        if isinstance(val, dict):
            return {k: cls._jsonable(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [cls._jsonable(v) for v in val]
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return val

    @property
    def obs_db_path(self) -> Path:
        return self._obs_db
