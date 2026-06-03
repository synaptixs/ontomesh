"""
evolution_monitor.py — Workstream 2: Autonomous Ontology Evolution
===================================================================
Production anomaly monitor that surfaces candidate ontology changes as
scored proposals.  No axiom ever enters the ontology without human
review — the autonomy lies in *detection* and *scoring*.

Four detection strategies:

  1. SHACL_VIOLATION_ACCUMULATION
     Repeated `sh:in` violations on the same property signal a missing
     enumeration term.  Accumulated rejected values become NEW_CONSTRAINT
     proposals (extend the enumeration).

  2. CARDINALITY_BREACH
     FK-like reference patterns in JSON-LD payloads that have no OWL
     ObjectProperty counterpart.  Recurrence promotes them to
     NEW_PROPERTY proposals.

  3. CLASS_COOCCURRENCE
     Entity pairs consistently appearing together in ObservationRecords
     but with no defined relationship.  Repeated co-occurrence produces
     NEW_PROPERTY proposals (link the two classes).

  4. NLP_CANDIDATE_PROMOTION
     Candidate entities from the NLP log entity discoverer that have
     appeared in ≥N confirmed observations get promoted to NEW_CLASS
     proposals.

Every detection writes to the ``ontology_evolution_proposals`` table.
Scoring is handled by :mod:`evolution_scorer`.

Usage:
    from evolution_monitor import EvolutionMonitor
    mon = EvolutionMonitor(db_path="db/enterprise.db",
                           out_path="output")
    summary = mon.run_all()                # runs the 4 strategies
    summary = mon.run_strategy("CLASS_COOCCURRENCE")
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

_BASE_IRI  = "https://ontology.example.com/tmf/"
_EVO_IRI   = "https://ontology.example.com/evolution/"


# ── DDL for the proposal store (lazy create, mirrors schema.sql) ─────

_DDL_PROPOSALS = """
CREATE TABLE IF NOT EXISTS ontology_evolution_proposals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id        TEXT NOT NULL UNIQUE,
    proposal_type      TEXT NOT NULL
                       CHECK(proposal_type IN (
                         'NEW_CLASS','NEW_PROPERTY','NEW_CONSTRAINT','DEPRECATE')),
    title              TEXT NOT NULL,
    candidate_turtle   TEXT NOT NULL,
    evidence_sparql    TEXT NOT NULL,
    detection_strategy TEXT NOT NULL
                       CHECK(detection_strategy IN (
                         'SHACL_VIOLATION_ACCUMULATION',
                         'CARDINALITY_BREACH',
                         'CLASS_COOCCURRENCE',
                         'NLP_CANDIDATE_PROMOTION')),
    confidence_score   REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),
    dim_evidence_volume    REAL,
    dim_evidence_recency   REAL,
    dim_cross_domain       REAL,
    dim_consistency_risk   REAL,
    dim_schema_alignment   REAL,
    status             TEXT DEFAULT 'PENDING'
                       CHECK(status IN ('PENDING','APPROVED','REJECTED','DEFERRED')),
    reviewer_id        TEXT,
    review_note        TEXT,
    reviewed_at        TEXT,
    defer_until        TEXT,
    version_target     TEXT,
    primary_cq         TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);
"""

_DDL_VERSION_LEDGER = """
CREATE TABLE IF NOT EXISTS ontology_version_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    version            TEXT NOT NULL UNIQUE,
    parent_version     TEXT,
    proposal_id        TEXT,
    reasoner_status    TEXT,
    shacl_status       TEXT,
    sparql_status      TEXT,
    pr_url             TEXT,
    scorecard_delta    TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_PROPOSALS)
    conn.execute(_DDL_VERSION_LEDGER)
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────────────────────
# Evolution Monitor
# ─────────────────────────────────────────────────────────────────────


class EvolutionMonitor:
    """Detects ontology-evolution candidates from production observations.

    Args:
        db_path: SQLite enterprise DB path.
        out_path: Output directory root (used to locate log-discovery
                  candidate CSVs and SHACL validation reports).
        min_evidence: Minimum occurrence count for a candidate to be
                      promoted to a proposal (default 3).
    """

    def __init__(
        self,
        db_path: str,
        out_path: str,
        min_evidence: int = 3,
    ) -> None:
        self._db_path = db_path
        self._out_path = out_path
        self._min_evidence = min_evidence

    # ── Public API ─────────────────────────────────────────────────

    def run_all(self) -> Dict[str, Any]:
        """Run all four detection strategies sequentially."""
        summary = {
            "@context":   {"@vocab": _EVO_IRI},
            "@type":      "EvolutionMonitorSummary",
            "@id":        f"{_EVO_IRI}run/{uuid.uuid4()}",
            "generatedAt": _utcnow(),
            "min_evidence": self._min_evidence,
            "strategies": {},
        }
        for strat in (
            "SHACL_VIOLATION_ACCUMULATION",
            "CARDINALITY_BREACH",
            "CLASS_COOCCURRENCE",
            "NLP_CANDIDATE_PROMOTION",
        ):
            summary["strategies"][strat] = self.run_strategy(strat)
        summary["total_proposals"] = sum(
            s["proposals_created"] for s in summary["strategies"].values()
        )
        return summary

    def run_strategy(self, strategy: str) -> Dict[str, Any]:
        """Run a single named strategy and return its result summary."""
        fn = {
            "SHACL_VIOLATION_ACCUMULATION": self._detect_shacl_violations,
            "CARDINALITY_BREACH":           self._detect_cardinality_breach,
            "CLASS_COOCCURRENCE":           self._detect_class_cooccurrence,
            "NLP_CANDIDATE_PROMOTION":      self._detect_nlp_candidates,
        }.get(strategy)
        if fn is None:
            return {"strategy": strategy, "error": "unknown strategy",
                    "proposals_created": 0}
        started = _utcnow()
        created: List[Dict[str, Any]] = fn()
        return {
            "strategy":           strategy,
            "started_at":         started,
            "completed_at":       _utcnow(),
            "proposals_created":  len(created),
            "proposals":          created[:10],  # sample for display
        }

    # ── Strategy 1: SHACL violation accumulation ────────────────────

    def _detect_shacl_violations(self) -> List[Dict[str, Any]]:
        """Find recurring sh:in violations in the semantic_loss_log.

        When the same column carries ``loss_type=REJECTED_AT_RUNTIME_GATE``
        or ``SHACL_IN_VIOLATION`` ≥ min_evidence times, we propose
        extending the enumeration.
        """
        proposals: List[Dict[str, Any]] = []
        try:
            conn = _connect(self._db_path)
            rows = conn.execute("""
                SELECT table_name, column_name, COUNT(*) AS n,
                       GROUP_CONCAT(DISTINCT description) AS samples
                FROM   semantic_loss_log
                WHERE  loss_type IN ('SHACL_IN_VIOLATION',
                                     'REJECTED_AT_RUNTIME_GATE',
                                     'ENUMERATION_MISS')
                GROUP BY table_name, column_name
                HAVING COUNT(*) >= ?
            """, (self._min_evidence,)).fetchall()

            for r in rows:
                table = r["table_name"] or "unknown"
                col   = r["column_name"] or "unknown"
                samples = (r["samples"] or "")[:300]
                turtle = (
                    f":{_camel(col)}\n"
                    f"  a owl:DatatypeProperty ;\n"
                    f"  rdfs:domain :{_camel(table)} ;\n"
                    f"  rdfs:comment \"Extension candidate from "
                    f"accumulated SHACL violations.\" .\n"
                    f"# Evidence samples: {samples}"
                )
                sparql = (
                    "PREFIX : <https://ontology.example.com/enterprise/>\n"
                    "SELECT (COUNT(*) AS ?n) WHERE {\n"
                    f"  [] :table_name \"{table}\" ;\n"
                    f"     :column_name \"{col}\" ;\n"
                    f"     :loss_type \"SHACL_IN_VIOLATION\" .\n"
                    "}"
                )
                p = self._insert_proposal(
                    conn=conn,
                    proposal_type="NEW_CONSTRAINT",
                    title=f"Extend enumeration for {table}.{col}",
                    turtle=turtle,
                    sparql=sparql,
                    strategy="SHACL_VIOLATION_ACCUMULATION",
                    evidence_count=r["n"],
                )
                if p:
                    proposals.append(p)
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"  WARN evolution_monitor SHACL: {exc}")
        return proposals

    # ── Strategy 2: Cardinality breach ──────────────────────────────

    def _detect_cardinality_breach(self) -> List[Dict[str, Any]]:
        """Detect FK-like columns in observations whose target class
        has no declared ObjectProperty link to the source table."""
        proposals: List[Dict[str, Any]] = []
        try:
            conn = _connect(self._db_path)

            # Look for high-frequency source_ref patterns that carry
            # an IRI reference but lack a corresponding ObjectProperty.
            rows = conn.execute("""
                SELECT derivation_method,
                       entity_type,
                       COUNT(*) AS n
                FROM   observation_record
                WHERE  source_ref LIKE '%iri=%'
                  AND  (invalidated_by IS NULL OR invalidated_by = '')
                GROUP BY derivation_method, entity_type
                HAVING COUNT(*) >= ?
            """, (self._min_evidence,)).fetchall() if _has_table(conn, "observation_record") else []

            for r in rows:
                et   = r["entity_type"] or "Entity"
                turtle = (
                    f":refersTo{_camel(et)}\n"
                    f"  a owl:ObjectProperty ;\n"
                    f"  rdfs:domain :ObservationRecord ;\n"
                    f"  rdfs:range  :{_camel(et)} ;\n"
                    f"  rdfs:comment \"FK-style reference surfaced from "
                    f"{r['n']} untyped payloads.\" .\n"
                )
                sparql = (
                    "PREFIX tmf: <https://ontology.example.com/tmf/>\n"
                    "SELECT (COUNT(*) AS ?n) WHERE {\n"
                    "  ?rec a tmf:ObservationRecord ;\n"
                    f"       tmf:entity_type \"{et}\" ;\n"
                    "       tmf:source_ref ?src .\n"
                    "  FILTER (CONTAINS(?src,\"iri=\"))\n"
                    "}"
                )
                p = self._insert_proposal(
                    conn=conn,
                    proposal_type="NEW_PROPERTY",
                    title=f"Untyped IRI reference on {et} observations",
                    turtle=turtle,
                    sparql=sparql,
                    strategy="CARDINALITY_BREACH",
                    evidence_count=r["n"],
                )
                if p:
                    proposals.append(p)
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"  WARN evolution_monitor CARD: {exc}")
        return proposals

    # ── Strategy 3: Class co-occurrence ─────────────────────────────

    def _detect_class_cooccurrence(self) -> List[Dict[str, Any]]:
        """Find entity-type pairs that co-occur in ObservationRecords
        against the same entity_iri without a declared relationship."""
        proposals: List[Dict[str, Any]] = []
        try:
            conn = _connect(self._db_path)
            if not _has_table(conn, "observation_record"):
                conn.close()
                return proposals

            rows = conn.execute("""
                SELECT a.entity_type AS ta, b.entity_type AS tb,
                       COUNT(*) AS n
                FROM   observation_record AS a
                JOIN   observation_record AS b
                       ON a.entity_iri = b.entity_iri
                      AND a.entity_type < b.entity_type
                WHERE  (a.invalidated_by IS NULL OR a.invalidated_by='')
                  AND  (b.invalidated_by IS NULL OR b.invalidated_by='')
                GROUP BY a.entity_type, b.entity_type
                HAVING COUNT(*) >= ?
            """, (self._min_evidence,)).fetchall()

            for r in rows:
                ta, tb = r["ta"] or "EntityA", r["tb"] or "EntityB"
                prop = f"relatedTo{_camel(tb)}"
                turtle = (
                    f":{prop}\n"
                    f"  a owl:ObjectProperty ;\n"
                    f"  rdfs:domain :{_camel(ta)} ;\n"
                    f"  rdfs:range  :{_camel(tb)} ;\n"
                    f"  rdfs:comment \"Co-occurrence observed in {r['n']} "
                    "records — no explicit relationship declared.\" .\n"
                )
                sparql = (
                    "PREFIX tmf: <https://ontology.example.com/tmf/>\n"
                    "SELECT (COUNT(*) AS ?n) WHERE {\n"
                    "  ?a tmf:entity_iri ?e ; tmf:entity_type \""
                    f"{ta}\" .\n"
                    "  ?b tmf:entity_iri ?e ; tmf:entity_type \""
                    f"{tb}\" .\n"
                    "}"
                )
                p = self._insert_proposal(
                    conn=conn,
                    proposal_type="NEW_PROPERTY",
                    title=f"Relationship {ta} ↔ {tb}",
                    turtle=turtle,
                    sparql=sparql,
                    strategy="CLASS_COOCCURRENCE",
                    evidence_count=r["n"],
                )
                if p:
                    proposals.append(p)
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"  WARN evolution_monitor COOCC: {exc}")
        return proposals

    # ── Strategy 4: NLP candidate promotion ─────────────────────────

    def _detect_nlp_candidates(self) -> List[Dict[str, Any]]:
        """Promote log-discovery NLP candidates that appear in ≥N
        confirmed observations to NEW_CLASS proposals."""
        proposals: List[Dict[str, Any]] = []
        try:
            conn = _connect(self._db_path)

            candidates_path = os.path.join(
                self._out_path, "reports", "entity_discovery_candidates.csv"
            )
            if not os.path.isfile(candidates_path):
                conn.close()
                return proposals

            import csv as _csv
            with open(candidates_path) as f:
                reader = _csv.DictReader(f)
                rows = list(reader)

            for r in rows:
                try:
                    freq = int(r.get("frequency") or 0)
                except ValueError:
                    freq = 0
                if freq < self._min_evidence:
                    continue
                cand = (r.get("candidate_entity") or "").strip()
                suggested = (r.get("suggested_class_name") or cand).strip()
                if not cand:
                    continue
                class_name = _camel(suggested or cand)
                turtle = (
                    f":{class_name}\n"
                    f"  a owl:Class ;\n"
                    f"  rdfs:subClassOf :DomainEntity ;\n"
                    f"  rdfs:label \"{class_name}\" ;\n"
                    f"  rdfs:comment \"NLP log-discovery candidate, "
                    f"freq={freq}.\" .\n"
                )
                sparql = (
                    "PREFIX tmf: <https://ontology.example.com/tmf/>\n"
                    "SELECT (COUNT(*) AS ?n) WHERE {\n"
                    "  ?rec a tmf:ObservationRecord ;\n"
                    "       tmf:value_text ?v .\n"
                    f"  FILTER (CONTAINS(LCASE(STR(?v)), \"{cand.lower()}\"))\n"
                    "}"
                )
                p = self._insert_proposal(
                    conn=conn,
                    proposal_type="NEW_CLASS",
                    title=f"Promote NLP candidate → class :{class_name}",
                    turtle=turtle,
                    sparql=sparql,
                    strategy="NLP_CANDIDATE_PROMOTION",
                    evidence_count=freq,
                )
                if p:
                    proposals.append(p)
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"  WARN evolution_monitor NLP: {exc}")
        return proposals

    # ── Insert helper ───────────────────────────────────────────────

    def _insert_proposal(
        self,
        *,
        conn: sqlite3.Connection,
        proposal_type: str,
        title: str,
        turtle: str,
        sparql: str,
        strategy: str,
        evidence_count: int,
    ) -> Optional[Dict[str, Any]]:
        """Insert a proposal if no identical one already exists."""
        existing = conn.execute(
            "SELECT proposal_id FROM ontology_evolution_proposals "
            "WHERE title = ? AND detection_strategy = ? AND status = 'PENDING'",
            (title, strategy),
        ).fetchone()
        if existing:
            return None

        pid = str(uuid.uuid4())
        # Seed evidence-volume dim; scorer will overwrite the composite.
        dim_vol = min(1.0, evidence_count / (self._min_evidence * 10))
        conn.execute("""
            INSERT INTO ontology_evolution_proposals (
                proposal_id, proposal_type, title, candidate_turtle,
                evidence_sparql, detection_strategy,
                confidence_score, dim_evidence_volume,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """, (
            pid, proposal_type, title, turtle, sparql, strategy,
            dim_vol, dim_vol, _utcnow(), _utcnow(),
        ))
        return {
            "proposal_id":      pid,
            "proposal_type":    proposal_type,
            "title":            title,
            "strategy":         strategy,
            "evidence_count":   evidence_count,
            "confidence_seed":  dim_vol,
        }


# ── Helpers ─────────────────────────────────────────────────────────

def _camel(s: str) -> str:
    """Convert ``snake_or-kebab`` to ``CamelCase``."""
    parts = [p for p in s.replace("-", "_").split("_") if p]
    return "".join(p.capitalize() for p in parts) or "X"


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    try:
        r = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return r is not None
    except sqlite3.DatabaseError:
        return False


# ── Entry point used by toolkit.py ──────────────────────────────────

def run_evolution_monitor(
    db_path: str,
    out_path: str,
    min_evidence: int = 3,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper used by `toolkit.py --phase evolve`."""
    mon = EvolutionMonitor(db_path=db_path, out_path=out_path,
                           min_evidence=min_evidence)
    summary = (
        {"strategies": {strategy: mon.run_strategy(strategy)}}
        if strategy else mon.run_all()
    )

    # Write summary artifact
    reports_dir = os.path.join(out_path, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    out_file = os.path.join(reports_dir, "evolution_monitor_summary.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  ✓ Evolution monitor summary → {out_file}")
    return summary
