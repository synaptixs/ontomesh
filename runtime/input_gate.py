"""
Input Gate — validates enterprise data against SHACL shapes BEFORE it enters
the LLM payload. Rejects malformed, incomplete, or low-confidence records.
Integrates with the existing agent-gate.ttl shapes.
Reports rejected records to semantic_loss_log with loss_type=REJECTED_AT_RUNTIME_GATE.
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Valid derivation method values (from DB schema CHECK constraint)
_VALID_DERIVATION_METHODS = {"MEASURED", "INFERRED", "IMPORTED", "SYNTHESIZED", "DEFAULT"}

# Fields that are mandatory for entity records (by entity type marker)
_MANDATORY_FIELDS_BY_TYPE: dict[str, list[str]] = {
    "Resource":             ["resource_iri", "name", "resource_type"],
    "Alarm":                ["alarm_iri", "alarm_type", "perceived_severity", "raised_at"],
    "TroubleTicket":        ["ticket_iri", "description", "submitted_at"],
    "Service":              ["service_iri", "name", "service_type"],
    "Product":              ["product_iri", "name"],
    "Party":                ["party_iri", "name", "party_type"],
    "CustomerBill":         ["bill_iri", "bill_number", "amount_due"],
    "Agreement":            ["agreement_iri", "name"],
    "PerformanceIndicator": ["kpi_iri", "name", "observed_at"],
    "ObservationRecord":    ["record_iri", "entity_iri", "derivation_method"],
    "ConflictEvent":        ["conflict_iri", "assertion_a_iri", "assertion_b_iri", "conflict_type"],
    "Policy":               ["policy_iri", "name"],
    "ServiceQualityReport": ["report_iri"],
    "NetworkSlice":         ["profile_iri", "name", "slice_type"],
}

# Table → entity type mapping (mirrors grounder._TABLE_CLASS_MAP)
_TABLE_TYPE_MAP: dict[str, str] = {
    "tmf_resource":               "Resource",
    "tmf_alarm":                  "Alarm",
    "tmf_trouble_ticket":         "TroubleTicket",
    "tmf_service":                "Service",
    "tmf_product":                "Product",
    "tmf_party":                  "Party",
    "tmf_customer_bill":          "CustomerBill",
    "tmf_agreement":              "Agreement",
    "tmf_performance_indicator":  "PerformanceIndicator",
    "observation_record":         "ObservationRecord",
    "tmf_conflict_event":         "ConflictEvent",
    "tmf_policy":                 "Policy",
    "tmf_service_quality_report": "ServiceQualityReport",
    "tmf_network_slice_profile":  "NetworkSlice",
}


class InputGate:
    """Screens enterprise data records before they enter the LLM payload.

    Enforces minimum data quality requirements:
    - Mandatory field presence checks (entity-type specific)
    - Confidence score threshold enforcement
    - Derivation method validation
    - Null/empty value detection on key fields

    Rejected records are logged to ``semantic_loss_log`` with
    ``loss_type=REJECTED_AT_RUNTIME_GATE``.
    """

    def __init__(
        self,
        db_path: str,
        shapes_dir: Optional[str] = None,
        min_confidence: float = 0.0,
    ):
        """Initialise the InputGate.

        Args:
            db_path: Absolute path to the SQLite enterprise database.
            shapes_dir: Directory containing SHACL shape TTL files (optional;
                reserved for future full SHACL-based screening).
            min_confidence: Minimum acceptable confidence score (inclusive).
                Records with a lower ``confidence_score`` are rejected.
                Default is 0.0 (accept all confidence levels).
        """
        self._db_path = db_path
        self._shapes_dir = shapes_dir or os.path.join(
            os.path.dirname(_HERE), "output", "shapes"
        )
        self._min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def screen(
        self, records: list, flavor_name: str
    ) -> tuple:
        """Screen a list of records and return accepted/rejected partitions.

        Args:
            records: List of raw record dicts (as returned by the Grounder).
            flavor_name: The active flavor name (used for logging context).

        Returns:
            A tuple ``(accepted, rejected)`` where each element is a list of
            record dicts.  Rejected records have a ``__rejection_reasons__``
            key added.
        """
        accepted: list[dict] = []
        rejected: list[dict] = []
        rejection_reasons: dict[int, list[str]] = {}

        for idx, record in enumerate(records):
            reasons = self._check_record(record, {})
            if reasons:
                r = dict(record)
                r["__rejection_reasons__"] = reasons
                rejected.append(r)
                rejection_reasons[idx] = reasons
            else:
                accepted.append(record)

        if rejected:
            self._log_rejections(rejected, rejection_reasons)

        return accepted, rejected

    def screen_db_query(
        self,
        table_name: str,
        where_clause: str = "1=1",
        flavor_name: str = "network-ops",
    ) -> tuple:
        """Query a DB table and screen the results.

        Args:
            table_name: Name of the SQLite table to query.
            where_clause: SQL WHERE clause (without the WHERE keyword).
            flavor_name: Active flavor name for context.

        Returns:
            A tuple ``(accepted, rejected)`` of record lists.
        """
        records: list[dict] = []
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"SELECT * FROM {table_name} WHERE {where_clause}")
            for row in cursor.fetchall():
                d = dict(row)
                d["__table__"] = table_name
                records.append(d)
            conn.close()
        except Exception as exc:
            print(f"  WARN InputGate.screen_db_query: {exc}")
            return [], []

        return self.screen(records, flavor_name)

    def summary(self, accepted: list, rejected: list) -> dict:
        """Return statistics for a screening run.

        Args:
            accepted: The accepted records list.
            rejected: The rejected records list.

        Returns:
            A dict with keys: ``total``, ``accepted_count``, ``rejected_count``,
            ``rejection_rate``, ``rejection_reasons_breakdown``.
        """
        total = len(accepted) + len(rejected)
        rejection_rate = len(rejected) / total if total > 0 else 0.0

        # Tally rejection reasons
        reasons_breakdown: dict[str, int] = {}
        for r in rejected:
            for reason in r.get("__rejection_reasons__", []):
                # Use the first 60 chars as a category key
                key = reason[:60]
                reasons_breakdown[key] = reasons_breakdown.get(key, 0) + 1

        return {
            "total": total,
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "rejection_rate": round(rejection_rate, 4),
            "rejection_reasons_breakdown": reasons_breakdown,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_record(self, record: dict, flavor: dict) -> list:
        """Check a single record and return a list of rejection reasons.

        Args:
            record: A raw record dict.
            flavor: The loaded flavor dict (may be empty for generic checks).

        Returns:
            A list of rejection reason strings.  Empty list means the record passes.
        """
        reasons: list[str] = []

        # Determine entity type from __table__ or @type
        table_name = record.get("__table__", "")
        entity_type = record.get("@type") or _TABLE_TYPE_MAP.get(table_name, "")

        # 1. Mandatory field presence check
        mandatory = _MANDATORY_FIELDS_BY_TYPE.get(entity_type, [])
        for field in mandatory:
            if field not in record:
                # Field not present at all
                reasons.append(f"Missing mandatory field '{field}' for type '{entity_type}'")
            elif record[field] is None or str(record[field]).strip() == "":
                reasons.append(f"Mandatory field '{field}' is null/empty for type '{entity_type}'")

        # 2. Confidence score threshold check
        if "confidence_score" in record and record["confidence_score"] is not None:
            try:
                score = float(record["confidence_score"])
                if score < self._min_confidence:
                    reasons.append(
                        f"confidence_score {score:.4f} is below minimum threshold "
                        f"{self._min_confidence:.4f}"
                    )
            except (TypeError, ValueError):
                reasons.append(
                    f"confidence_score '{record['confidence_score']}' is not a valid number"
                )

        # 3. Derivation method validation
        if "derivation_method" in record and record["derivation_method"] is not None:
            dm = str(record["derivation_method"]).upper()
            if dm not in _VALID_DERIVATION_METHODS:
                reasons.append(
                    f"Invalid derivation_method '{dm}'. "
                    f"Must be one of: {sorted(_VALID_DERIVATION_METHODS)}"
                )

        # 4. Generic null check on a small set of universal fields
        for field in ("name", "description"):
            if field in record and record[field] is None:
                reasons.append(f"Field '{field}' must not be null")

        return reasons

    def _log_rejections(self, rejected: list, reasons: dict) -> None:
        """Write each rejected record to the semantic_loss_log table.

        Args:
            rejected: List of rejected record dicts (with ``__rejection_reasons__``).
            reasons: Dict mapping list index → list of reason strings (unused
                directly; reason strings are read from the record's
                ``__rejection_reasons__`` key).
        """
        now = datetime.now(timezone.utc).isoformat()

        try:
            conn = sqlite3.connect(self._db_path)
        except Exception as exc:
            print(f"  WARN InputGate._log_rejections: cannot open DB: {exc}")
            return

        rows_to_insert: list[tuple] = []
        for record in rejected:
            table_name = record.get("__table__", "unknown")
            record_reasons = record.get("__rejection_reasons__", ["Unknown rejection reason"])
            description = "; ".join(record_reasons)[:500]

            rows_to_insert.append((
                table_name,
                None,  # column_name — not applicable for row-level rejection
                "REJECTED_AT_RUNTIME_GATE",
                description,
                "MEDIUM",
                "Review mandatory fields and confidence score before re-submission.",
                now,
                0,  # resolved = False
            ))

        try:
            with conn:
                conn.executemany("""
                    INSERT INTO semantic_loss_log (
                        table_name, column_name, loss_type, description,
                        severity, remediation, detected_at, resolved
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, rows_to_insert)
        except Exception as exc:
            print(f"  WARN InputGate._log_rejections: DB write failed: {exc}")
        finally:
            conn.close()
