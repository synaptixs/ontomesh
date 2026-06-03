"""
db/migrations/v3_metrics.py — T2.6
──────────────────────────────────
Adds the ``pipeline_metrics`` table. One row per emitted metric
snapshot — phase name, metric name, numeric value, optional tags
JSON, ISO timestamp. The :mod:`metrics` module appends to this
table; the drift alerter and Grafana endpoint read from it.

Idempotent; safe to call on a fresh DB or repeatedly.
"""

from __future__ import annotations

import sqlite3


_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phase         TEXT NOT NULL,
    metric_name   TEXT NOT NULL,
    value         REAL NOT NULL,
    tags_json     TEXT,
    run_id        TEXT,
    recorded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pipeline_metrics_phase_name
    ON pipeline_metrics(phase, metric_name);
CREATE INDEX IF NOT EXISTS idx_pipeline_metrics_recorded
    ON pipeline_metrics(recorded_at);
"""


def migrate(conn: sqlite3.Connection) -> dict:
    conn.executescript(_DDL)
    conn.commit()
    return {"tables_created": ["pipeline_metrics"]}


__all__ = ["migrate"]
