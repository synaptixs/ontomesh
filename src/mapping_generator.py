"""
mapping_generator.py — Phase 4
────────────────────────────────
Generates the logical/physical mapping workbook (CSV) and runs
the semantic loss detection heuristics.

Produces:
  output/mapping/logical_physical_map.csv
  output/mapping/semantic_loss_report.csv
  output/mapping/orphan_candidates.csv

Semantic loss detection rules
──────────────────────────────
1. STATUS_AS_EVENT   — tables with a 'status' column but no event table FK
2. IMPLICIT_ACTOR    — event tables with no agent/actor FK column
3. OVERLOADED_TYPE   — columns named 'type' or 'kind' with no OWL subclass hint
4. MISSING_TIMESTAMP — event tables with no timestamp column
5. FLOATING_VALUE    — observation-like tables with no confidence or source column
6. ORPHAN_TABLE      — tables with no FK in or out (no relations to other tables)
7. MISSING_PROV      — tables flagged as event/observation with no agent FK
"""

import os
import csv
from typing import List, Dict, Tuple
from db_introspector import (
    DBIntrospector, TableModel, ColumnModel,
    snake_to_camel, BASE_IRI
)


# ── Mapping CSV ──────────────────────────────────────────────────────────

MAPPING_HEADERS = [
    "ontology_class",
    "ontology_property",
    "property_type",
    "logical_element",
    "physical_table",
    "physical_column",
    "xsd_type",
    "required",
    "sensitivity_tier",
    "semantic_notes",
    "cq_coverage",
]


def _get_physical_type(conn, table: str, col: str) -> str:
    try:
        from db_connector import Connector
        if isinstance(conn, Connector):
            cols = conn.get_columns(table)
            for c in cols:
                if c.name == col:
                    return c.data_type
        return "TEXT"
    except Exception:
        return "TEXT"


def generate_mapping(intro: DBIntrospector, output_dir: str):
    tables = intro.introspect_all()
    os.makedirs(output_dir, exist_ok=True)

    mapping_rows = []

    for t in tables:
        # Class-level row
        mapping_rows.append({
            "ontology_class": t.class_name,
            "ontology_property": "(class)",
            "property_type": "OWL Class",
            "logical_element": t.name,
            "physical_table": t.name,
            "physical_column": "(table)",
            "xsd_type": "",
            "required": "Y",
            "sensitivity_tier": t.sensitivity_tier,
            "semantic_notes": t.description or "",
            "cq_coverage": ", ".join(t.cq_coverage),
        })

        # Data properties
        for col in t.data_properties:
            prop_name = f"has{snake_to_camel(col.name)}"
            mapping_rows.append({
                "ontology_class": t.class_name,
                "ontology_property": prop_name,
                "property_type": "Data Property",
                "logical_element": f"{t.name}.{col.name}",
                "physical_table": t.name,
                "physical_column": col.name,
                "xsd_type": col.effective_xsd_type,
                "required": "Y" if col.not_null else "N",
                "sensitivity_tier": col.sensitivity_tier,
                "semantic_notes": col.description or "",
                "cq_coverage": ", ".join(col.cq_coverage),
            })

        # Object properties
        for col in t.object_properties:
            ref = col.fk_references or "unknown"
            ref_table = ref.split(".")[0] if ref != "unknown" else "?"
            from db_introspector import snake_to_lower_camel
            col_stripped = col.name.replace("_id", "").replace("_org", "").replace("_type", "")
            prop_name = snake_to_lower_camel(col_stripped)

            # Find range class
            range_class = "?"
            for rt in tables:
                if rt.name == ref_table:
                    range_class = rt.class_name
                    break

            mapping_rows.append({
                "ontology_class": t.class_name,
                "ontology_property": prop_name,
                "property_type": "Object Property",
                "logical_element": f"{t.name}.{col.name} → {ref_table}",
                "physical_table": t.name,
                "physical_column": col.name,
                "xsd_type": f"→ {range_class}",
                "required": "Y" if col.not_null else "N",
                "sensitivity_tier": col.sensitivity_tier,
                "semantic_notes": f"FK to {ref_table}; range class: {range_class}",
                "cq_coverage": ", ".join(col.cq_coverage),
            })

    map_path = os.path.join(output_dir, "logical_physical_map.csv")
    with open(map_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAPPING_HEADERS)
        w.writeheader()
        w.writerows(mapping_rows)
    print(f"  ✓ Mapping workbook      → {map_path}")
    print(f"    Rows: {len(mapping_rows)}")

    # ── Semantic loss detection ───────────────────────────────────────
    loss_rows = _detect_semantic_loss(tables, intro)
    loss_path = os.path.join(output_dir, "semantic_loss_report.csv")
    with open(loss_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "severity", "table", "column", "loss_type", "description", "remediation"
        ])
        w.writeheader()
        w.writerows(loss_rows)
    print(f"  ✓ Semantic loss report  → {loss_path}")
    print(f"    Issues found: {len(loss_rows)}  "
          f"({sum(1 for r in loss_rows if r['severity']=='CRITICAL')} CRITICAL, "
          f"{sum(1 for r in loss_rows if r['severity']=='HIGH')} HIGH, "
          f"{sum(1 for r in loss_rows if r['severity']=='MEDIUM')} MEDIUM, "
          f"{sum(1 for r in loss_rows if r['severity']=='LOW')} LOW)")

    # Write loss to DB
    _write_loss_to_db(intro, loss_rows)

    # ── Orphan candidates ─────────────────────────────────────────────
    orphans = _detect_orphans(tables)
    orphan_path = os.path.join(output_dir, "orphan_candidates.csv")
    with open(orphan_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["class_name", "table_name", "inbound_fks", "outbound_fks", "status"])
        w.writeheader()
        w.writerows(orphans)
    print(f"  ✓ Orphan analysis       → {orphan_path}")
    print(f"    Orphan candidates: {sum(1 for o in orphans if o['status']=='ORPHAN')}")


def _col_names(t: TableModel) -> List[str]:
    return [c.name for c in t.columns]


def _has_col_pattern(t: TableModel, *patterns: str) -> bool:
    names = _col_names(t)
    return any(any(p in n.lower() for p in patterns) for n in names)


def _detect_semantic_loss(tables: List[TableModel], intro: DBIntrospector) -> List[Dict]:
    rows = []

    # Build a set of table names that have inbound FKs (i.e. are referenced)
    referenced = set()
    for t in tables:
        for ref in t.fk_map.values():
            referenced.add(ref)

    for t in tables:
        col_names = _col_names(t)

        # Rule 1: Status-as-event
        # SID design uses operational_state/admin_state/usage_state on resources — these
        # are governed by the eTOM state machine and are intentional status fields.
        # TMF alarm and order tables are themselves event tables — skip.
        _sid_lifecycle_tables = {
            "tmf_resource", "tmf_service", "tmf_product", "tmf_party",
            "tmf_agreement", "tmf_customer_account", "tmf_party_role",
            "tmf_policy", "tmf_resource_spec", "tmf_service_spec",
            "tmf_product_spec", "tmf_product_offering",
        }
        if "status" in col_names and not t.is_event_class:
            has_event_link = any(
                "event" in ref.lower() or "alarm" in ref.lower() or "order" in ref.lower()
                for ref in t.fk_map.values()
            )
            # SID lifecycle tables carry eTOM state machine values — flag LOW not HIGH
            severity = "LOW" if t.name in _sid_lifecycle_tables else "HIGH"
            remediation = (
                "SID/eTOM lifecycle table. Ensure state transitions are recorded via "
                "the corresponding TMF event/order table (e.g. ServiceOrder for Service state changes). "
                "Add prov:wasInvalidatedBy annotations when state changes."
                if t.name in _sid_lifecycle_tables
                else
                "Create or link to a domain_events entry when status changes. "
                "Model the transition as a DomainEvent subclass in the ontology."
            )
            if not has_event_link:
                rows.append({
                    "severity": severity,
                    "table": t.name,
                    "column": "status",
                    "loss_type": "STATUS_AS_EVENT",
                    "description": (
                        f"Table '{t.name}' has a 'status' lifecycle column but no direct FK to an event table. "
                        "State transitions are implicit — the history of state changes is not tracked in the ontology."
                    ),
                    "remediation": remediation,
                })

        # Rule 2: Implicit actor on event-like tables
        if t.is_event_class:
            # Recognise both generic agent tables and TMF party tables
            _actor_keywords = ("agent", "user", "operator", "party", "person", "individual")
            has_agent_fk = any(
                any(kw in ref.lower() for kw in _actor_keywords)
                for ref in t.fk_map.values()
            )
            if not has_agent_fk:
                rows.append({
                    "severity": "CRITICAL",
                    "table": t.name,
                    "column": "(any)",
                    "loss_type": "IMPLICIT_ACTOR",
                    "description": (
                        f"Event table '{t.name}' has no FK to an agent, party, or operator table. "
                        "Who initiated this event is not recorded — provenance is broken."
                    ),
                    "remediation": (
                        "Add an initiated_by or raised_by FK to an agents/party table. "
                        "Map to prov:wasAssociatedWith in the ontology."
                    ),
                })

        # Rule 3: Overloaded type field
        type_cols = [c for c in t.data_properties
                     if c.name in ("type", "kind", "category", "event_type", "asset_type")]
        for tc in type_cols:
            if tc.semantic_type is None:
                rows.append({
                    "severity": "MEDIUM",
                    "table": t.name,
                    "column": tc.name,
                    "loss_type": "OVERLOADED_TYPE",
                    "description": (
                        f"Column '{t.name}.{tc.name}' is a type discriminator with no OWL subclass hint "
                        "in ontology_metadata. Subclass distinctions are buried in application code."
                    ),
                    "remediation": (
                        f"Add ontology_metadata entry for '{t.name}.{tc.name}' with "
                        "semantic_type pointing to the discriminated OWL class. "
                        "Generate OWL subclasses for each distinct value."
                    ),
                })

        # Rule 4: Missing timestamp on event tables
        if t.is_event_class:
            has_timestamp = any("_at" in c.name or "time" in c.name or "date" in c.name
                                for c in t.columns)
            if not has_timestamp:
                rows.append({
                    "severity": "HIGH",
                    "table": t.name,
                    "column": "(none)",
                    "loss_type": "MISSING_TIMESTAMP",
                    "description": (
                        f"Event table '{t.name}' has no timestamp column. "
                        "Temporal ordering and PROV-O prov:startedAtTime cannot be recorded."
                    ),
                    "remediation": "Add started_at and completed_at columns. Map to prov:startedAtTime.",
                })

        # Rule 5: Floating observation value
        # SID Characteristic is a generic key-value ABE — confidence not applicable by design
        _float_exclusions = {"tmf_characteristic", "tmf_note", "tmf_attachment"}
        has_value_col = any(c.name in ("value", "numeric_value", "text_value", "reading")
                            for c in t.columns) and t.name not in _float_exclusions
        has_confidence  = _has_col_pattern(t, "confidence", "score", "certainty")
        has_source      = _has_col_pattern(t, "source", "ref", "citation")
        if has_value_col and not has_confidence:
            rows.append({
                "severity": "HIGH",
                "table": t.name,
                "column": "value",
                "loss_type": "FLOATING_VALUE",
                "description": (
                    f"Table '{t.name}' stores a measured/computed value but has no "
                    "confidence score column. Trust level of assertions is unquantifiable."
                ),
                "remediation": (
                    "Add confidence_score REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0). "
                    "Map to :hasConfidenceScore in the ontology."
                ),
            })
        if has_value_col and not has_source:
            rows.append({
                "severity": "MEDIUM",
                "table": t.name,
                "column": "value",
                "loss_type": "MISSING_SOURCE_REF",
                "description": (
                    f"Table '{t.name}' stores a value with no source reference column. "
                    "The origin of imported or synthesized values cannot be traced."
                ),
                "remediation": (
                    "Add source_ref TEXT to record the IRI or document reference of the source. "
                    "Map to :sourceRef (xsd:anyURI) in the ontology."
                ),
            })

        # Rule 6: Table with no label in ontology_metadata
        if not t.label and t.name not in ("agent_roles", "event_participants", "policy_applications"):
            rows.append({
                "severity": "LOW",
                "table": t.name,
                "column": "(none)",
                "loss_type": "MISSING_METADATA",
                "description": (
                    f"Table '{t.name}' has no entry in ontology_metadata. "
                    "OWL class label and description will be auto-generated from column name only."
                ),
                "remediation": (
                    "Add TABLE-level row to ontology_metadata with label, description, "
                    "sensitivity_tier, and cq_coverage."
                ),
            })

    return rows


def _detect_orphans(tables: List[TableModel]) -> List[Dict]:
    """Tables with no inbound FK references and no outbound FKs."""
    # Build inbound FK map
    inbound: Dict[str, int] = {t.name: 0 for t in tables}
    for t in tables:
        for ref_table in t.fk_map.values():
            if ref_table in inbound:
                inbound[ref_table] += 1

    results = []
    for t in tables:
        outbound = len(t.fk_map)
        inb = inbound.get(t.name, 0)
        status = "ORPHAN" if (inb == 0 and outbound == 0) else (
            "ISOLATED_SOURCE" if inb == 0 else (
                "ISOLATED_SINK" if outbound == 0 else "CONNECTED"
            )
        )
        results.append({
            "class_name": t.class_name,
            "table_name": t.name,
            "inbound_fks": inb,
            "outbound_fks": outbound,
            "status": status,
        })
    return sorted(results, key=lambda r: r["status"])


def _write_loss_to_db(intro: DBIntrospector, rows: List[Dict]):
    try:
        intro._connector.execute("DELETE FROM semantic_loss_log WHERE resolved = 0")
        for r in rows:
            intro._connector.execute(
                "INSERT INTO semantic_loss_log "
                "(table_name, column_name, loss_type, description, severity, remediation) "
                "VALUES (?,?,?,?,?,?)",
                (r["table"], r["column"], r["loss_type"],
                 r["description"], r["severity"], r["remediation"])
            )
        if hasattr(intro._connector, 'conn'):
            intro._connector.conn.commit()
    except Exception as e:
        print(f"    (Could not write to semantic_loss_log: {e})")
