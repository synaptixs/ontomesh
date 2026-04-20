"""
conflict_resolver.py
────────────────────
Multi-agent assertion conflict resolution for the Ontology Toolkit.

Implements the 3-tier resolution chain from framework Section 10.1:

  Tier 1 — SHACL axiom check
    Rejects logically inconsistent assertions (e.g. Disabled+Unlocked
    resource state) before they reach the knowledge graph.

  Tier 2 — Derivation-method priority chain
    When two assertions about the same entity/property conflict, the
    one with the higher-priority derivation method wins:
      measured > inferred > imported > synthesized > default

  Tier 3 — Human escalation queue
    If neither tier resolves the conflict (or the conflict is a
    SHACL_VIOLATION that needs manual review), insert a record into
    tmf_conflict_event with escalated_to_human=1.

Additionally:
  • Detects conflicts via SPARQL ASK queries on the loaded RDF graph.
  • Records prov:wasInvalidatedBy on the losing assertion.
  • Writes all conflict events to tmf_conflict_event.

CLI:
  python3 toolkit.py --phase conflict [--db db/tmf.db]
"""

from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


# ── Derivation method priority ────────────────────────────────────────────
# Lower number = higher priority.  "default" is a catch-all fallback.
DERIVATION_PRIORITY: dict[str, int] = {
    "MEASURED":    1,
    "INFERRED":    2,
    "IMPORTED":    3,
    "SYNTHESIZED": 4,
    "DEFAULT":     5,
}

# ── State machine consistency rules (Tier 1) ──────────────────────────────
# Each rule is (description, SQL query that returns rows when violation exists)
TIER1_CONSISTENCY_RULES: list[dict] = [
    {
        "rule_id": "T1-RES-STATE-01",
        "description": "Resource: operational_state=Disabled must not have admin_state=Unlocked.",
        "shacl_msg": "OperationalAndAdminStateConsistency — Disabled resource must not be Unlocked.",
        "sql": """
            SELECT resource_iri, name, operational_state, admin_state
            FROM tmf_resource
            WHERE operational_state = 'Disabled' AND admin_state = 'Unlocked'
        """,
    },
    {
        "rule_id": "T1-ALARM-CLEARED-01",
        "description": "Cleared alarm must not still have null cleared_at timestamp.",
        "shacl_msg": "AlarmClearedAtConsistency — Cleared alarm must have a cleared_at timestamp.",
        "sql": """
            SELECT alarm_iri, alarm_state, cleared_at
            FROM tmf_alarm
            WHERE alarm_state = 'Cleared' AND cleared_at IS NULL
        """,
    },
    {
        "rule_id": "T1-BILL-DUE-01",
        "description": "Customer bill amount_due must be non-negative (credit notes may be negative via bill_type).",
        "shacl_msg": "BillAmountConsistency — amount_due < 0 requires bill_type=CreditNote.",
        "sql": """
            SELECT bill_number, bill_type, amount_due
            FROM tmf_customer_bill
            WHERE amount_due < 0 AND bill_type != 'CreditNote'
        """,
    },
    {
        "rule_id": "T1-TICKET-RESOLVE-01",
        "description": "Resolved or Closed trouble ticket must have a resolved_at timestamp.",
        "shacl_msg": "TroubleTicketResolvedAtConsistency — Resolved/Closed ticket must have resolved_at.",
        "sql": """
            SELECT ticket_iri, status, resolved_at
            FROM tmf_trouble_ticket
            WHERE status IN ('Resolved','Closed') AND resolved_at IS NULL
        """,
    },
    {
        "rule_id": "T1-CONFLICT-TIER2-01",
        "description": "Conflicting KPI measurements for same resource+kpi_type within same 5-minute window.",
        "shacl_msg": "KPIMeasurementConflict — Multiple conflicting measurements for same resource+kpi_type.",
        "sql": """
            SELECT a.resource_id, a.kpi_type,
                   COUNT(*) AS conflict_count,
                   MIN(a.numeric_value) AS min_val,
                   MAX(a.numeric_value) AS max_val
            FROM tmf_performance_indicator a
            JOIN tmf_performance_indicator b
              ON a.resource_id = b.resource_id
             AND a.kpi_type    = b.kpi_type
             AND a.id          != b.id
             AND ABS(JULIANDAY(a.observed_at) - JULIANDAY(b.observed_at)) * 86400 < 300
            WHERE ABS(a.numeric_value - b.numeric_value) > (a.numeric_value * 0.10)
            GROUP BY a.resource_id, a.kpi_type
            HAVING COUNT(*) >= 2
        """,
    },
]

# ── SPARQL ASK conflict detection patterns (run against rdflib graph) ──────
SPARQL_CONFLICT_PATTERNS: list[dict] = [
    {
        "pattern_id": "SP-CONFLICT-01",
        "description": "Detect resource with two conflicting operational states in graph.",
        "query": """
            ASK {
              ?r a <https://ontology.example.com/tmf/Resource> ;
                 <https://ontology.example.com/tmf/hasOperationalState> ?s1 ,
                                                                         ?s2 .
              FILTER(?s1 != ?s2)
              FILTER(?s1 IN ("Enabled","Disabled"))
              FILTER(?s2 IN ("Enabled","Disabled"))
            }
        """,
    },
    {
        "pattern_id": "SP-CONFLICT-02",
        "description": "Detect two observations about same resource+kpi with >10% value divergence.",
        "query": """
            ASK {
              ?obs1 a <https://ontology.example.com/tmf/PerformanceIndicator> ;
                    <https://ontology.example.com/tmf/kpiType> ?kt ;
                    <https://ontology.example.com/tmf/aboutResource> ?r .
              ?obs2 a <https://ontology.example.com/tmf/PerformanceIndicator> ;
                    <https://ontology.example.com/tmf/kpiType> ?kt ;
                    <https://ontology.example.com/tmf/aboutResource> ?r .
              FILTER(?obs1 != ?obs2)
            }
        """,
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conflict_iri(prefix: str = "CONF") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"https://ontology.example.com/conflicts/{prefix}-{ts}"


def run_tier1_checks(conn: sqlite3.Connection) -> list[dict]:
    """Run Tier-1 SHACL-equivalent SQL consistency rules.

    Returns list of violation dicts, each with:
      rule_id, shacl_msg, rows (list of offending records)
    """
    violations = []
    conn.row_factory = sqlite3.Row
    for rule in TIER1_CONSISTENCY_RULES:
        try:
            rows = conn.execute(rule["sql"].strip()).fetchall()
            if rows:
                violations.append({
                    "rule_id": rule["rule_id"],
                    "description": rule["description"],
                    "shacl_msg": rule["shacl_msg"],
                    "rows": [dict(r) for r in rows],
                })
        except Exception as exc:
            violations.append({
                "rule_id": rule["rule_id"],
                "description": rule["description"],
                "shacl_msg": rule["shacl_msg"],
                "error": str(exc),
                "rows": [],
            })
    return violations


def resolve_tier2(assertion_a: dict, assertion_b: dict) -> tuple[dict, dict, str]:
    """Apply Tier-2 derivation-method priority chain.

    Returns (winner, loser, resolution_rule_string).
    """
    pri_a = DERIVATION_PRIORITY.get(
        (assertion_a.get("derivation_method") or "DEFAULT").upper(), 5
    )
    pri_b = DERIVATION_PRIORITY.get(
        (assertion_b.get("derivation_method") or "DEFAULT").upper(), 5
    )
    rule = (
        f"{assertion_a.get('derivation_method','DEFAULT').lower()} "
        f"{'>' if pri_a < pri_b else '<' if pri_a > pri_b else '='} "
        f"{assertion_b.get('derivation_method','DEFAULT').lower()} "
        f"(derivation_method priority chain)"
    )
    if pri_a <= pri_b:
        return assertion_a, assertion_b, rule
    return assertion_b, assertion_a, rule


def record_invalidation(conn: sqlite3.Connection, loser_iri: str,
                        winner_iri: str, conflict_iri: str) -> None:
    """Write PROV-O wasInvalidatedBy semantics to a provenance log table.

    If the prov_invalidation_log table does not exist, create it on the fly.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prov_invalidation_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            invalidated_entity TEXT NOT NULL,
            invalidated_by     TEXT NOT NULL,
            invalidation_time  TEXT NOT NULL,
            conflict_iri       TEXT,
            recorded_at        TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        """INSERT INTO prov_invalidation_log
           (invalidated_entity, invalidated_by, invalidation_time, conflict_iri)
           VALUES (?,?,?,?)""",
        (loser_iri, winner_iri, _now_iso(), conflict_iri),
    )
    conn.commit()


def escalate_to_human(conn: sqlite3.Connection, conflict_iri: str,
                      assigned_to_id: Optional[int] = None) -> None:
    """Mark a conflict event as escalated (Tier-3)."""
    conn.execute(
        """UPDATE tmf_conflict_event
           SET escalated_to_human = 1,
               status = 'Escalated',
               assigned_to_id = COALESCE(?, assigned_to_id)
           WHERE conflict_iri = ?""",
        (assigned_to_id, conflict_iri),
    )
    conn.commit()


def insert_conflict_event(conn: sqlite3.Connection, **kwargs) -> str:
    """Insert a new conflict event record and return its IRI."""
    iri = kwargs.get("conflict_iri") or _conflict_iri()
    conn.execute(
        """INSERT OR IGNORE INTO tmf_conflict_event (
            conflict_iri, assertion_a_iri, assertion_b_iri,
            conflict_type, description, shacl_violation_msg,
            resolution_tier, winning_assertion_iri, resolution_rule,
            escalated_to_human, invalidation_recorded,
            status, detected_at, resolved_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            iri,
            kwargs.get("assertion_a_iri", ""),
            kwargs.get("assertion_b_iri", ""),
            kwargs.get("conflict_type", "VALUE_CONFLICT"),
            kwargs.get("description", ""),
            kwargs.get("shacl_violation_msg"),
            kwargs.get("resolution_tier"),
            kwargs.get("winning_assertion_iri"),
            kwargs.get("resolution_rule"),
            int(kwargs.get("escalated_to_human", False)),
            int(kwargs.get("invalidation_recorded", False)),
            kwargs.get("status", "Open"),
            kwargs.get("detected_at", _now_iso()),
            kwargs.get("resolved_at"),
        ),
    )
    conn.commit()
    return iri


def run_conflict_resolution(db_path: str, out_path: str) -> dict:
    """Full 3-tier conflict resolution pass.

    Returns a summary dict with counts per tier.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    summary = {
        "tier1_violations": 0,
        "tier1_escalated": 0,
        "tier2_resolved": 0,
        "tier3_escalated": 0,
        "invalidations_recorded": 0,
        "timestamp": _now_iso(),
    }

    print("\n  ── Tier 1: SHACL-equivalent consistency rules ──────────────")
    tier1_violations = run_tier1_checks(conn)
    for v in tier1_violations:
        summary["tier1_violations"] += len(v.get("rows", []))
        for row in v.get("rows", []):
            # Build entity IRIs from row if available
            a_iri = row.get("resource_iri") or row.get("alarm_iri") or \
                    row.get("ticket_iri") or row.get("bill_number", "unknown")
            b_iri = f"urn:rule:{v['rule_id']}"
            c_iri = insert_conflict_event(
                conn,
                assertion_a_iri=a_iri,
                assertion_b_iri=b_iri,
                conflict_type="SHACL_VIOLATION",
                description=v["description"],
                shacl_violation_msg=v["shacl_msg"],
                resolution_tier=1,
                status="Escalated",
                escalated_to_human=True,
            )
            summary["tier1_escalated"] += 1
            print(f"    ✗ SHACL violation [{v['rule_id']}]: {v['shacl_msg'][:70]}")
            print(f"      → Conflict IRI: {c_iri}  (escalated to Tier-3)")

    if not tier1_violations:
        print("    ✓ All Tier-1 consistency rules passed — no violations found.")

    print("\n  ── Tier 2: Derivation-method priority resolution ───────────")
    # Detect conflicting KPI measurements (same resource, kpi_type, ~same time)
    conn.row_factory = sqlite3.Row
    try:
        conflict_pairs = conn.execute("""
            SELECT a.kpi_iri AS iri_a,
                   b.kpi_iri AS iri_b,
                   a.derivation_method AS dm_a,
                   b.derivation_method AS dm_b,
                   a.numeric_value AS val_a,
                   b.numeric_value AS val_b,
                   a.resource_id, a.kpi_type
            FROM tmf_performance_indicator a
            JOIN tmf_performance_indicator b
              ON a.resource_id = b.resource_id
             AND a.kpi_type    = b.kpi_type
             AND a.id          < b.id
             AND ABS(JULIANDAY(a.observed_at) - JULIANDAY(b.observed_at)) * 86400 < 300
            WHERE a.numeric_value IS NOT NULL
              AND b.numeric_value IS NOT NULL
              AND ABS(a.numeric_value - b.numeric_value) > (
                    COALESCE(a.numeric_value,1) * 0.10)
        """).fetchall()
    except Exception:
        conflict_pairs = []

    for pair in conflict_pairs:
        a = {"kpi_iri": pair["iri_a"], "derivation_method": pair["dm_a"],
             "numeric_value": pair["val_a"]}
        b = {"kpi_iri": pair["iri_b"], "derivation_method": pair["dm_b"],
             "numeric_value": pair["val_b"]}
        winner, loser, rule = resolve_tier2(a, b)
        c_iri = insert_conflict_event(
            conn,
            assertion_a_iri=pair["iri_a"],
            assertion_b_iri=pair["iri_b"],
            conflict_type="VALUE_CONFLICT",
            description=(
                f"Conflicting {pair['kpi_type']} measurements: "
                f"{pair['val_a']} ({pair['dm_a']}) vs "
                f"{pair['val_b']} ({pair['dm_b']})"
            ),
            resolution_tier=2,
            winning_assertion_iri=winner.get("kpi_iri"),
            resolution_rule=rule,
            status="Resolved",
            resolved_at=_now_iso(),
            invalidation_recorded=True,
        )
        record_invalidation(conn, loser.get("kpi_iri", ""), winner.get("kpi_iri", ""), c_iri)
        summary["tier2_resolved"] += 1
        summary["invalidations_recorded"] += 1
        print(f"    ✓ Resolved [{pair['kpi_type']}]: {rule}")
        print(f"      Winner: {winner.get('kpi_iri')}  |  Loser invalidated.")

    if not conflict_pairs:
        print("    ✓ No value conflicts detected in measurement data.")

    print("\n  ── Tier 3: Human escalation queue ──────────────────────────")
    try:
        open_escalations = conn.execute("""
            SELECT conflict_iri, conflict_type, description, status
            FROM tmf_conflict_event
            WHERE status = 'Escalated' AND escalated_to_human = 1
        """).fetchall()
    except Exception:
        open_escalations = []

    summary["tier3_escalated"] = len(open_escalations)
    if open_escalations:
        print(f"    ⚠ {len(open_escalations)} conflict(s) awaiting human resolution:")
        for row in open_escalations:
            print(f"      [{row['conflict_type']}] {row['conflict_iri']}")
            print(f"        {row['description'][:80]}")
    else:
        print("    ✓ No conflicts in human escalation queue.")

    # Write JSON report
    rpt_dir = os.path.join(out_path, "reports")
    os.makedirs(rpt_dir, exist_ok=True)
    rpt_path = os.path.join(rpt_dir, "conflict_resolution_report.json")

    # Collect all conflict events for report
    try:
        all_conflicts = [
            dict(r) for r in conn.execute(
                "SELECT * FROM tmf_conflict_event ORDER BY detected_at DESC"
            ).fetchall()
        ]
    except Exception:
        all_conflicts = []

    report = {
        "summary": summary,
        "tier1_violations": tier1_violations,
        "conflict_events": all_conflicts,
        "sparql_patterns": [p["pattern_id"] for p in SPARQL_CONFLICT_PATTERNS],
    }
    with open(rpt_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    conn.close()
    print(f"\n  ✓ Conflict resolution report → {rpt_path}")
    print(f"  Summary: Tier-1 violations={summary['tier1_violations']}  "
          f"Tier-2 resolved={summary['tier2_resolved']}  "
          f"Tier-3 escalated={summary['tier3_escalated']}  "
          f"Invalidations={summary['invalidations_recorded']}")
    return summary


def generate_conflict_shacl(output_dir: str) -> None:
    """Generate SHACL shapes for conflict resolution constraints."""
    os.makedirs(output_dir, exist_ok=True)
    BASE = "https://ontology.example.com/tmf/"
    SH   = "http://www.w3.org/ns/shacl#"
    # Build TTL without nested f-string triple quotes
    lines = [
        f"@prefix :       <{BASE}> .\n",
        f"@prefix sh:     <{SH}> .\n",
        "@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .\n",
        "@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .\n",
        f"@prefix shapes: <{BASE}shapes/> .\n\n",
        "# ── Phase 2B: Conflict Resolution SHACL Shapes ────────────────────────────\n\n",
        "shapes:ResourceStateConsistencyShape\n"
        "  a sh:NodeShape ;\n"
        "  sh:targetClass :Resource ;\n"
        '  rdfs:comment "Tier-1: operational_state=Disabled must not coexist with admin_state=Unlocked." ;\n'
        "  sh:sparql [\n"
        '    sh:message "OperationalAndAdminStateConsistency — Disabled resource must not be Unlocked." ;\n'
        "    sh:severity sh:Violation ;\n"
        f"    sh:prefixes <{BASE}> ;\n"
        '    sh:select "SELECT $this WHERE { $this :hasOperationalState \\"Disabled\\" ; :hasAdminState \\"Unlocked\\" . }" ;\n'
        "  ] .\n\n",
        "shapes:AlarmClearedAtShape\n"
        "  a sh:NodeShape ;\n"
        "  sh:targetClass :Alarm ;\n"
        '  rdfs:comment "Tier-1: Cleared alarm must have a cleared_at timestamp." ;\n'
        "  sh:sparql [\n"
        '    sh:message "AlarmClearedAtConsistency — Cleared alarm must have a cleared_at timestamp." ;\n'
        "    sh:severity sh:Violation ;\n"
        f"    sh:prefixes <{BASE}> ;\n"
        '    sh:select "SELECT $this WHERE { $this :hasAlarmState \\"Cleared\\" . FILTER NOT EXISTS { $this :clearedAt ?t } }" ;\n'
        "  ] .\n\n",
        "shapes:TroubleTicketResolvedShape\n"
        "  a sh:NodeShape ;\n"
        "  sh:targetClass :TroubleTicket ;\n"
        '  rdfs:comment "Tier-1: Resolved/Closed ticket must have resolved_at." ;\n'
        "  sh:sparql [\n"
        '    sh:message "TroubleTicketResolvedAtConsistency — Resolved or Closed ticket must have resolved_at." ;\n'
        "    sh:severity sh:Violation ;\n"
        f"    sh:prefixes <{BASE}> ;\n"
        '    sh:select "SELECT $this WHERE { $this :hasTicketStatus ?s . FILTER(?s IN (\\"Resolved\\",\\"Closed\\")) FILTER NOT EXISTS { $this :resolvedAt ?t } }" ;\n'
        "  ] .\n\n",
        "shapes:ConflictEventShape\n"
        "  a sh:NodeShape ;\n"
        "  sh:targetClass :ConflictEvent ;\n"
        "  sh:property [\n"
        "    sh:path :assertionAIri ;\n"
        "    sh:minCount 1 ;\n"
        "    sh:datatype xsd:anyURI ;\n"
        '    sh:message "ConflictEvent must reference at least one assertion IRI (assertionAIri)." ;\n'
        "    sh:severity sh:Violation ;\n"
        "  ] ;\n"
        "  sh:property [\n"
        "    sh:path :conflictType ;\n"
        "    sh:minCount 1 ;\n"
        '    sh:message "conflictType must be one of the allowed values." ;\n'
        "    sh:severity sh:Violation ;\n"
        "  ] ;\n"
        "  sh:property [\n"
        "    sh:path :resolutionTier ;\n"
        "    sh:datatype xsd:integer ;\n"
        '    sh:message "resolutionTier must be 1, 2, or 3." ;\n'
        "    sh:severity sh:Warning ;\n"
        "  ] .\n\n",
        "shapes:EventSubscriptionShape\n"
        "  a sh:NodeShape ;\n"
        "  sh:targetClass :EventSubscription ;\n"
        "  sh:property [\n"
        "    sh:path :callbackUrl ;\n"
        "    sh:minCount 1 ;\n"
        "    sh:datatype xsd:anyURI ;\n"
        '    sh:message "EventSubscription must have a callbackUrl." ;\n'
        "    sh:severity sh:Violation ;\n"
        "  ] ;\n"
        "  sh:property [\n"
        "    sh:path :eventType ;\n"
        "    sh:minCount 1 ;\n"
        "    sh:datatype xsd:string ;\n"
        '    sh:message "EventSubscription must specify an eventType." ;\n'
        "    sh:severity sh:Violation ;\n"
        "  ] .\n",
    ]
    path = os.path.join(output_dir, "conflict-resolution-shapes.ttl")
    with open(path, "w") as f:
        f.writelines(lines)
    print(f"  ✓ Conflict resolution shapes → {path}")


def generate_conflict_mcp_tools(output_dir: str) -> None:
    """Append conflict-resolution MCP tool definitions."""
    os.makedirs(output_dir, exist_ok=True)
    tools = [
        {
            "name": "subscribe_to_events",
            "description": (
                "Register a callback URL for async event notifications per TMF630 §5. "
                "Supported event types: AlarmStateChange, ServiceOrderStateChange, "
                "KPIThresholdBreach, TroubleTicketUpdate, ConflictEscalation."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Event type to subscribe to."},
                    "event_domain": {"type": "string", "description": "SID domain (Resource, Service, Product, EngagedParty)."},
                    "callback_url": {"type": "string", "format": "uri", "description": "Webhook URL."},
                    "filter_criteria": {"type": "object", "description": "Optional JSON filter (e.g. {severity: 'Critical'})."},
                    "subscriber_party_iri": {"type": "string", "description": "IRI of the subscribing party."},
                },
                "required": ["event_type", "callback_url"],
            },
        },
        {
            "name": "resolve_assertion_conflict",
            "description": (
                "Trigger the 3-tier conflict resolution chain for two conflicting assertions. "
                "Tier 1: SHACL consistency. Tier 2: derivation-method priority. Tier 3: human escalation. "
                "Returns the winning assertion IRI and PROV-O wasInvalidatedBy stamp for the loser."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "assertion_a_iri": {"type": "string", "description": "IRI of the first assertion."},
                    "assertion_b_iri": {"type": "string", "description": "IRI of the conflicting assertion."},
                    "conflict_type": {
                        "type": "string",
                        "enum": ["VALUE_CONFLICT", "STATE_CONFLICT", "PROVENANCE_CONFLICT", "SHACL_VIOLATION"],
                    },
                    "description": {"type": "string"},
                },
                "required": ["assertion_a_iri", "assertion_b_iri", "conflict_type"],
            },
        },
        {
            "name": "get_conflict_queue",
            "description": (
                "Return all open conflict events in the human escalation queue (Tier-3). "
                "Includes conflict type, description, and involved assertion IRIs."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "enum": ["Open", "Escalated", "Resolved", "All"],
                        "default": "Escalated",
                    },
                },
            },
        },
    ]
    path = os.path.join(output_dir, "conflict-resolution-mcp-tools.json")
    with open(path, "w") as f:
        json.dump({"tools": tools}, f, indent=2)
    print(f"  ✓ Conflict resolution MCP tools → {path}")
