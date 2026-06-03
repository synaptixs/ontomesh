"""
db/migrations/log_discovery_v2.py
─────────────────────────────────
Idempotent migration that extends the schema for the Log Discovery v2
roadmap (docs/log-discovery-enhancements-roadmap.md).

What this migration adds — scoped to what's needed by L8 + L9:

  L9 — Active-learning ranker:
      log_ranker_meta(id, model_path, n_decisions, n_approved,
                      n_rejected, auc, fit_at)

  L8 — Switching state-space regimes (reserved; L8 itself adds the
       actual model blobs once it ships):
      log_regime_models(service, n_regimes, model_blob, fit_at)
      log_trajectory_regimes(trajectory_id, regime_id, posterior)

The tables are created with ``CREATE TABLE IF NOT EXISTS`` so the
migration is safe to call on a fresh DB and safe to call repeatedly.
No data migration is required — these tables hold derived/audit state
that any prior schema simply did not record.

Usage::

    from db.migrations.log_discovery_v2 import migrate
    migrate(sqlite_conn)
"""

from __future__ import annotations

import sqlite3


_DDL_LOG_RANKER_META = """
CREATE TABLE IF NOT EXISTS log_ranker_meta (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    model_path   TEXT NOT NULL,
    n_decisions  INTEGER NOT NULL DEFAULT 0,
    n_approved   INTEGER NOT NULL DEFAULT 0,
    n_rejected   INTEGER NOT NULL DEFAULT 0,
    auc          REAL,
    fit_at       TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""

# L8 tables are declared here so that any L9 code that opens the DB
# also surfaces the L8 schema (even before L8 ships). Empty tables
# carry no operational cost.

_DDL_LOG_REGIME_MODELS = """
CREATE TABLE IF NOT EXISTS log_regime_models (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    service      TEXT NOT NULL,
    n_regimes    INTEGER NOT NULL,
    model_blob   BLOB NOT NULL,
    fit_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(service, fit_at)
);
"""

_DDL_LOG_TRAJECTORY_REGIMES = """
CREATE TABLE IF NOT EXISTS log_trajectory_regimes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trajectory_id TEXT NOT NULL,
    regime_id     INTEGER NOT NULL,
    posterior     REAL NOT NULL CHECK(posterior BETWEEN 0.0 AND 1.0),
    UNIQUE(trajectory_id, regime_id)
);
"""

_DDLS = (
    ("log_ranker_meta",          _DDL_LOG_RANKER_META),
    ("log_regime_models",        _DDL_LOG_REGIME_MODELS),
    ("log_trajectory_regimes",   _DDL_LOG_TRAJECTORY_REGIMES),
)


_PROPOSAL_COLUMNS_L8 = (
    # L8: regime tag travels on the LOG_EVENT proposal row so the review
    # queue can render "Regime 2 of 3" without a join. Nullable so any
    # row written before L8 fits (or by other proposal kinds) survives.
    ("regime_tag",        "TEXT"),
    ("regime_posterior",  "REAL"),
    # L13: per-bin sparkline data (JSON list) for rate-deviation
    # proposals. UI renders inline; absent for non-rate kinds.
    ("rate_sparkline",    "TEXT"),
)


# L13: new detection_strategy value we need to accept. The schema's
# CHECK constraint is strict, so we probe whether the table already
# accepts it and rebuild via the standard SQLite rename-create-copy
# dance otherwise. Pattern lifted from db/migrations/log_rca_proposals.
_NEW_STRATEGY = "GP_RATE_DEVIATION"

_NEW_STRATEGY_TABLE_DDL = """
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
                         'DRIFT_ON_NEW_TEMPLATE',
                         'GP_RATE_DEVIATION')),
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
    regime_tag         TEXT,
    regime_posterior   REAL,
    rate_sparkline     TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);
"""


def _strategy_check_accepts(conn: sqlite3.Connection, strategy: str) -> bool:
    """Probe — wrapped in a SAVEPOINT we always roll back. Returns
    True if the CHECK constraint already accepts the strategy."""
    sp = "log_discovery_v2_probe"
    try:
        conn.execute(f"SAVEPOINT {sp}")
        conn.execute(
            "INSERT INTO ontology_evolution_proposals "
            "(proposal_id, proposal_type, title, candidate_turtle, "
            " evidence_sparql, detection_strategy) "
            "VALUES (?, 'LOG_EVENT', 'probe', ':x a owl:Class .', "
            "        'ASK { ?s ?p ?o }', ?)",
            (f"__probe_{strategy}", strategy),
        )
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            conn.execute(f"RELEASE SAVEPOINT {sp}")
        except sqlite3.Error:
            pass


def _rebuild_proposals_table(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("ALTER TABLE ontology_evolution_proposals "
                     "RENAME TO _ontology_evolution_proposals_old_v13")
        conn.execute(_NEW_STRATEGY_TABLE_DDL)
        old_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(_ontology_evolution_proposals_old_v13)"
        )]
        new_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(ontology_evolution_proposals)"
        )]
        shared = [c for c in old_cols if c in new_cols]
        col_list = ", ".join(shared)
        conn.execute(
            f"INSERT INTO ontology_evolution_proposals ({col_list}) "
            f"SELECT {col_list} FROM _ontology_evolution_proposals_old_v13"
        )
        conn.execute("DROP TABLE _ontology_evolution_proposals_old_v13")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def migrate(conn: sqlite3.Connection) -> dict:
    """Apply the migration. Returns
    ``{'tables_created': [...], 'columns_added': [...]}`` for logging.
    Idempotent: re-running reports empty lists."""
    created = []
    cols_added = []
    existing = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for name, ddl in _DDLS:
        if name not in existing:
            conn.execute(ddl)
            created.append(name)

    strategy_rebuilt = False
    if "ontology_evolution_proposals" in existing:
        proposal_cols = {
            r[1] for r in conn.execute(
                "PRAGMA table_info(ontology_evolution_proposals)"
            )
        }
        for col, decl in _PROPOSAL_COLUMNS_L8:
            if col not in proposal_cols:
                conn.execute(
                    f"ALTER TABLE ontology_evolution_proposals "
                    f"ADD COLUMN {col} {decl}"
                )
                cols_added.append(col)

        # L13: relax detection_strategy CHECK to admit GP_RATE_DEVIATION.
        if not _strategy_check_accepts(conn, _NEW_STRATEGY):
            _rebuild_proposals_table(conn)
            strategy_rebuilt = True

    conn.commit()
    return {
        "tables_created":    created,
        "columns_added":     cols_added,
        "strategy_rebuilt":  strategy_rebuilt,
    }


__all__ = ["migrate"]
