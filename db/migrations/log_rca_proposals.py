"""
db/migrations/log_rca_proposals.py
──────────────────────────────────
Idempotent migration that extends ``ontology_evolution_proposals`` with
the columns and proposal types used by the log-driven RCA pipeline
(see docs/log-rca-roadmap.md, docs/log-rca-dev-plan.md §0.3).

Two-step migration:

  1. ``ALTER TABLE … ADD COLUMN`` for ``source_log_path``,
     ``evidence_template_id``, ``evidence_sample``. SQLite's
     ``ALTER ADD COLUMN`` is idempotent only via PRAGMA detection —
     ``IF NOT EXISTS`` is not supported on columns.

  2. **CHECK-constraint relaxation.** SQLite cannot ``ALTER`` a CHECK
     in place. We detect whether the existing table accepts the new
     ``LOG_*`` proposal types and, if not, rebuild the table via the
     standard rename-create-copy-drop dance. The rebuild preserves
     every existing row.

Safe to call on a freshly-created DB (the schema.sql shipped at
db/schema.sql already declares the new columns and CHECK list, so
both steps are no-ops).

Usage::

    from db.migrations.log_rca_proposals import migrate
    migrate(sqlite_conn)
"""

from __future__ import annotations

import sqlite3
from typing import Sequence


# New columns we add. (name, type-decl).
_NEW_COLUMNS: Sequence[tuple[str, str]] = (
    ("source_log_path",      "TEXT"),
    ("evidence_template_id", "INTEGER"),
    ("evidence_sample",      "TEXT"),
)


# Probe rows we attempt to insert during a transaction we always roll
# back. If any one fails, the CHECK constraint hasn't been relaxed yet
# and we need a table rebuild.
_PROBE_TYPES = ("LOG_ENTITY", "LOG_RELATIONSHIP", "LOG_EVENT", "LOG_CAUSAL_EDGE")
_PROBE_STRATEGIES = (
    "LOG_TEMPLATE_CLUSTERING",
    "PMI_TEMPORAL_ORDERING",
    "HMM_SEQUENCE_ANOMALY",
    "GRANGER_CAUSALITY",
    "DRIFT_ON_NEW_TEMPLATE",
)


def migrate(conn: sqlite3.Connection) -> dict:
    """Run the migration on `conn`. Returns a small dict describing
    what was applied so callers can log it. Never raises on an
    already-migrated DB.
    """
    applied = {"columns_added": [], "table_rebuilt": False}

    _add_missing_columns(conn, applied)
    if not _check_accepts_new_types(conn):
        _rebuild_with_new_check(conn)
        applied["table_rebuilt"] = True
    conn.commit()
    return applied


# ── Step 1: column additions ─────────────────────────────────────────────


def _add_missing_columns(conn: sqlite3.Connection, applied: dict) -> None:
    existing = {row[1] for row in
                conn.execute("PRAGMA table_info(ontology_evolution_proposals)")}
    for name, type_ in _NEW_COLUMNS:
        if name in existing:
            continue
        conn.execute(
            f"ALTER TABLE ontology_evolution_proposals "
            f"ADD COLUMN {name} {type_}"
        )
        applied["columns_added"].append(name)


# ── Step 2: CHECK-constraint probe + rebuild ────────────────────────────


def _check_accepts_new_types(conn: sqlite3.Connection) -> bool:
    """Try inserting one row per new proposal_type + strategy combo in
    a SAVEPOINT we always roll back. If every insert succeeds, the
    constraint is already permissive enough.
    """
    savepoint = "log_rca_probe"
    try:
        conn.execute(f"SAVEPOINT {savepoint}")
        for ptype, strategy in zip(_PROBE_TYPES, _PROBE_STRATEGIES):
            conn.execute(
                "INSERT INTO ontology_evolution_proposals "
                "(proposal_id, proposal_type, title, candidate_turtle, "
                " evidence_sparql, detection_strategy) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"__probe_{ptype}", ptype, "probe", ":x a owl:Class .",
                 "ASK { ?s ?p ?o }", strategy),
            )
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except sqlite3.Error:
            pass


def _rebuild_with_new_check(conn: sqlite3.Connection) -> None:
    """Standard SQLite migration dance: rename, create new, copy, drop.

    Uses ``PRAGMA legacy_alter_table=ON`` so existing foreign-key
    references continue to point at the table rather than its rename
    while we copy rows over.
    """
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        # 1. Move the old table aside.
        conn.execute("ALTER TABLE ontology_evolution_proposals "
                     "RENAME TO _ontology_evolution_proposals_old")
        # 2. Create the new shape (matches db/schema.sql).
        conn.execute(_NEW_TABLE_DDL)
        # 3. Copy every row, including the columns we may have just added.
        old_cols = [row[1] for row in
                    conn.execute("PRAGMA table_info(_ontology_evolution_proposals_old)")]
        new_cols = [row[1] for row in
                    conn.execute("PRAGMA table_info(ontology_evolution_proposals)")]
        shared = [c for c in old_cols if c in new_cols]
        col_list = ", ".join(shared)
        conn.execute(
            f"INSERT INTO ontology_evolution_proposals ({col_list}) "
            f"SELECT {col_list} FROM _ontology_evolution_proposals_old"
        )
        # 4. Drop the old table.
        conn.execute("DROP TABLE _ontology_evolution_proposals_old")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


# Kept in sync with db/schema.sql. If you edit the table over there,
# update this string too — there's a test that diffs them.
_NEW_TABLE_DDL = """
CREATE TABLE ontology_evolution_proposals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id        TEXT NOT NULL UNIQUE,
    proposal_type      TEXT NOT NULL
                       CHECK(proposal_type IN (
                         'NEW_CLASS','NEW_PROPERTY','NEW_CONSTRAINT','DEPRECATE',
                         'LOG_ENTITY','LOG_RELATIONSHIP','LOG_EVENT','LOG_CAUSAL_EDGE')),
    title              TEXT NOT NULL,
    candidate_turtle   TEXT NOT NULL,
    evidence_sparql    TEXT NOT NULL,
    detection_strategy TEXT NOT NULL
                       CHECK(detection_strategy IN (
                         'SHACL_VIOLATION_ACCUMULATION',
                         'CARDINALITY_BREACH',
                         'CLASS_COOCCURRENCE',
                         'NLP_CANDIDATE_PROMOTION',
                         'LOG_TEMPLATE_CLUSTERING',
                         'PMI_TEMPORAL_ORDERING',
                         'HMM_SEQUENCE_ANOMALY',
                         'GRANGER_CAUSALITY',
                         'DRIFT_ON_NEW_TEMPLATE')),
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
    source_log_path    TEXT,
    evidence_template_id INTEGER,
    evidence_sample    TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);
"""


__all__ = ["migrate"]
