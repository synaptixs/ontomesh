"""
Data Grounding Module — bridges enterprise DB records to JSON-LD.

Given a natural-language question and a flavor, queries the SQLite
database for relevant records and serialises them as JSON-LD using
the flavor's scoped context — binding each field value to its ontology IRI.

CLI: python3 runtime/grounder.py --flavor network-ops --question "..." --db path/to/db
"""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

# Allow running as standalone script (adds runtime/ to path so flavor_registry imports)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flavor_registry import FlavorRegistry

# Mapping from DB table name → OWL class name
_TABLE_CLASS_MAP: dict[str, str] = {
    "tmf_resource":                   "Resource",
    "tmf_resource_spec":              "ResourceSpecification",
    "tmf_resource_relationship":      "ResourceRelationship",
    "tmf_service":                    "Service",
    "tmf_service_spec":               "ServiceSpecification",
    "tmf_service_order":              "ServiceOrder",
    "tmf_service_problem":            "ServiceProblem",
    "tmf_service_quality_report":     "ServiceQualityReport",
    "tmf_product":                    "Product",
    "tmf_product_spec":               "ProductSpecification",
    "tmf_product_offering":           "ProductOffering",
    "tmf_product_order":              "ProductOrder",
    "tmf_product_offering_qualification": "ProductOfferingQualification",
    "tmf_party":                      "Party",
    "tmf_party_role":                 "PartyRole",
    "tmf_customer_account":           "BillingAccount",
    "tmf_customer_bill":              "CustomerBill",
    "tmf_agreement":                  "Agreement",
    "tmf_alarm":                      "Alarm",
    "tmf_trouble_ticket":             "TroubleTicket",
    "tmf_performance_indicator":      "PerformanceIndicator",
    "tmf_network_slice_profile":      "NetworkSlice",
    "tmf_geographic_site":            "GeographicSite",
    "tmf_place":                      "GeographicLocation",
    "tmf_policy":                     "Policy",
    "tmf_characteristic":             "Characteristic",
    "tmf_event_subscription":         "EventSubscription",
    "tmf_conflict_event":             "ConflictEvent",
    "observation_record":             "ObservationRecord",
    "semantic_loss_log":              "SemanticLossRecord",
}

# IRI column names that identify a row as an ontology entity
_IRI_COLUMNS = (
    "resource_iri", "service_iri", "product_iri", "party_iri", "alarm_iri",
    "ticket_iri", "kpi_iri", "report_iri", "bill_iri", "order_iri",
    "agreement_iri", "account_iri", "conflict_iri", "record_iri",
    "profile_iri", "site_iri", "spec_iri", "offering_iri", "poq_iri",
    "subscription_iri", "problem_iri", "policy_iri", "place_iri",
)

# Columns that hold text useful for keyword matching
_TEXT_COLUMNS = (
    "name", "description", "resource_type", "nf_type", "alarm_type",
    "perceived_severity", "specific_problem", "probable_cause",
    "kpi_type", "status", "state", "alarm_state", "ticket_type",
    "report_type", "bill_type", "agreement_type", "party_type",
    "conflict_type", "record_type", "loss_type", "label",
    "operational_state", "admin_state", "usage_state", "severity",
    "category", "sub_category", "service_type", "order_type",
    "slice_type", "site_type", "policy_type", "org_type",
)


class Grounder:
    """Bridges enterprise database records to JSON-LD payloads.

    Given a natural-language question and an ontology flavor, the Grounder
    queries the SQLite database for records relevant to the question,
    serialises them as JSON-LD nodes using the flavor's scoped context,
    and returns a grounding result dict ready for inclusion in an LLM payload.
    """

    def __init__(self, db_path: str, flavor_registry: Optional[FlavorRegistry] = None):
        """Initialise the Grounder.

        Args:
            db_path: Absolute path to the SQLite enterprise database.
            flavor_registry: An existing :class:`FlavorRegistry` instance.
                If ``None``, a new one is created with default settings.
        """
        self._db_path = db_path
        self._registry = flavor_registry or FlavorRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ground(self, question: str, flavor_name: str, max_records: int = 50) -> dict:
        """Ground a question by querying the DB and returning a JSON-LD payload.

        Args:
            question: The natural-language question driving the data retrieval.
            flavor_name: Name of the flavor to use for scoping (e.g. ``"network-ops"``).
            max_records: Maximum total number of records to return across all
                queried tables.

        Returns:
            A dict with keys:
            - ``"@context"``: scoped JSON-LD context dict
            - ``"@graph"``: list of JSON-LD node dicts
            - ``"meta"``: grounding metadata (flavor, question, record_count, etc.)
        """
        flavor = self._registry.load(flavor_name)
        ctx_wrapper = self._registry.get_context(flavor_name)
        context = ctx_wrapper["@context"]

        raw_rows, tables_queried = self._query_tables(flavor, question, max_records)

        graph = [
            self._to_jsonld_node(row, row.pop("__table__", "unknown"), context)
            for row in raw_rows
        ]

        meta = {
            "flavor": flavor_name,
            "question": question,
            "record_count": len(graph),
            "tables_queried": tables_queried,
            "grounded_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "@context": context,
            "@graph": graph,
            "meta": meta,
        }

    def record_grounding(self, grounding_result: dict) -> str:
        """Insert an ObservationRecord for the grounding event.

        Args:
            grounding_result: The dict returned by :meth:`ground`.

        Returns:
            The IRI of the newly created observation record.
        """
        meta = grounding_result.get("meta", {})
        record_iri = f"https://ontology.example.com/tmf/grounding/{uuid.uuid4()}"
        entity_iri = f"https://ontology.example.com/tmf/flavor/{meta.get('flavor', 'unknown')}"
        now = datetime.now(timezone.utc).isoformat()

        try:
            conn = sqlite3.connect(self._db_path)
            with conn:
                conn.execute("""
                    INSERT OR IGNORE INTO observation_record (
                        record_iri, entity_iri, entity_type, record_type, kpi_type,
                        value_numeric, value_text, unit, derivation_method,
                        confidence_score, source_ref, prov_agent_iri,
                        generated_at, valid_from, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record_iri,
                    entity_iri,
                    "Flavor",
                    "GROUNDING",
                    None,
                    float(meta.get("record_count", 0)),
                    json.dumps(meta.get("tables_queried", [])),
                    "records",
                    "SYNTHESIZED",
                    1.0,
                    meta.get("question", "")[:500],
                    "https://ontology.example.com/tmf/agent/Grounder",
                    now,
                    now,
                    now,
                ))
            conn.close()
        except Exception as exc:
            print(f"  WARN record_grounding: could not write observation record: {exc}")

        return record_iri

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _query_tables(self, flavor: dict, question: str, max_records: int) -> tuple:
        """Query each table in the flavor's db_tables for relevant records.

        Performs simple keyword matching against common text columns.

        Args:
            flavor: The loaded flavor dict.
            question: The natural-language question.
            max_records: Maximum records to return in total.

        Returns:
            A tuple of ``(rows, tables_queried)`` where ``rows`` is a list of
            raw row dicts (each with a ``__table__`` key) and ``tables_queried``
            is a list of table names that were successfully queried.
        """
        tokens = [t.lower().strip("?.,!") for t in question.split() if len(t) > 2]
        db_tables: list[str] = flavor.get("db_tables", [])
        per_table_limit = max(1, max_records // max(len(db_tables), 1))

        all_rows: list[dict] = []
        tables_queried: list[str] = []

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
        except Exception as exc:
            print(f"  WARN Grounder: cannot open DB at {self._db_path}: {exc}")
            return [], []

        for table in db_tables:
            rows = self._query_single_table(conn, table, tokens, per_table_limit)
            if rows is not None:
                for row in rows:
                    row["__table__"] = table
                all_rows.extend(rows)
                tables_queried.append(table)

        conn.close()
        return all_rows[:max_records], tables_queried

    def _query_single_table(
        self, conn: sqlite3.Connection, table: str, tokens: list[str], limit: int
    ) -> Optional[list]:
        """Query a single table, returning rows as dicts or None on error."""
        # Check table exists
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                return None
        except Exception:
            return None

        # Get column names
        try:
            col_rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            columns = [r[1] for r in col_rows]
        except Exception:
            return None

        # Build WHERE clause using available text columns
        text_cols = [c for c in columns if c in _TEXT_COLUMNS]

        if tokens and text_cols:
            # Match any token against any text column (broad retrieval)
            conditions = []
            params: list[str] = []
            for col in text_cols:
                for tok in tokens:
                    conditions.append(f'LOWER("{col}") LIKE ?')
                    params.append(f"%{tok}%")
            where_clause = " OR ".join(conditions)
            sql = f'SELECT * FROM {table} WHERE ({where_clause}) LIMIT ?'
            params.append(limit)
        else:
            # No useful tokens — return most recent records
            sql = f'SELECT * FROM {table} ORDER BY id DESC LIMIT ?'
            params = [limit]

        try:
            cursor = conn.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]
            return rows
        except Exception as exc:
            print(f"  WARN Grounder: query failed on {table}: {exc}")
            return None

    def _to_jsonld_node(self, row: dict, table_name: str, context: dict) -> dict:
        """Convert a DB row dict to a JSON-LD node dict.

        Args:
            row: A raw DB row dict.
            table_name: The source DB table name.
            context: The active JSON-LD context dict (used to map column→IRI).

        Returns:
            A JSON-LD node dict with ``@type``, ``@id``, and mapped properties.
        """
        node: dict = {}

        # Determine @type
        owl_class = self._table_to_class(table_name)
        node["@type"] = owl_class

        # Determine @id from known IRI columns
        for iri_col in _IRI_COLUMNS:
            if iri_col in row and row[iri_col]:
                node["@id"] = row[iri_col]
                break

        if "@id" not in node:
            # Mint a blank-node-style IRI
            table_short = table_name.replace("tmf_", "")
            row_id = row.get("id", uuid.uuid4().hex[:8])
            node["@id"] = f"https://ontology.example.com/tmf/{table_short}/{row_id}"

        # Map columns to context terms or plain camelCase
        skip = {"id", "__table__"}
        for col, val in row.items():
            if col in skip or val is None:
                continue
            if col in _IRI_COLUMNS:
                # Already used as @id or is a referenced IRI
                term = _col_to_camel(col)
                if term not in node:
                    node[term] = val
                continue
            term = _col_to_camel(col)
            node[term] = val

        # PROV-O annotations
        if "created_at" in row and row["created_at"]:
            node["prov:generatedAtTime"] = {
                "@type": "xsd:dateTime",
                "@value": row["created_at"],
            }

        if "derivation_method" in row and row["derivation_method"]:
            node["derivationMethod"] = row["derivation_method"]

        return node

    def _table_to_class(self, table_name: str) -> str:
        """Map a DB table name to an OWL class name.

        Args:
            table_name: The SQLite table name.

        Returns:
            The corresponding OWL class name string.
        """
        return _TABLE_CLASS_MAP.get(table_name, _default_class_name(table_name))


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _col_to_camel(col: str) -> str:
    """Convert snake_case column name to lowerCamelCase ontology term."""
    parts = col.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _default_class_name(table_name: str) -> str:
    """Derive a default OWL class name from a table name."""
    name = table_name.replace("tmf_", "")
    return "".join(p.capitalize() for p in name.split("_"))


# ------------------------------------------------------------------
# CLI entry-point
# ------------------------------------------------------------------

def main():
    """CLI entry-point for the Grounder."""
    parser = argparse.ArgumentParser(
        description="Ground a natural-language question against the enterprise DB."
    )
    parser.add_argument("--flavor", required=True, help="Flavor name (e.g. network-ops)")
    parser.add_argument("--question", required=True, help="Natural-language question")
    parser.add_argument(
        "--db",
        default=os.path.join(os.path.dirname(_HERE), "db", "enterprise.db"),
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--max-records", type=int, default=50, help="Maximum records to retrieve"
    )
    parser.add_argument("--out", default=None, help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    grounder = Grounder(db_path=args.db)
    result = grounder.ground(
        question=args.question,
        flavor_name=args.flavor,
        max_records=args.max_records,
    )

    output = json.dumps(result, indent=2, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output)
        print(f"  ✓ Grounding result → {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
