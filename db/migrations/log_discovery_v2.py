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
)


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

    conn.commit()
    return {"tables_created": created, "columns_added": cols_added}


__all__ = ["migrate"]
