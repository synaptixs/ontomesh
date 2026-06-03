"""
db/migrations/v3_cq_translations.py — T3.3
──────────────────────────────────────────
Adds the ``cq_translations`` table — one row per (competency
question, generated SPARQL) pair. State carried per CQ:

  - ``sparql_query``     — the generated query text
  - ``source``           — ``"mock"`` / ``"anthropic"`` / ``"openai"``
                           / ``"manual"``
  - ``validation_status``— ``"OK"`` / ``"ZERO_HITS"`` / ``"SYNTAX_ERROR"``
                           / ``"TIMEOUT"`` / ``"PENDING"``
  - ``n_hits``           — rows returned when run against sample data
  - ``error_message``    — populated on syntax errors / timeouts
  - ``generated_at``     — ISO timestamp of the most recent run
  - ``ontology_version`` — owl:versionInfo at translation time

Idempotent; safe to re-run.
"""

from __future__ import annotations

import sqlite3


_DDL = """
CREATE TABLE IF NOT EXISTS cq_translations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cq_id               TEXT NOT NULL,
    cq_text             TEXT NOT NULL,
    sparql_query        TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'mock',
    validation_status   TEXT NOT NULL DEFAULT 'PENDING',
    n_hits              INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    ontology_version    TEXT,
    generated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(cq_id, ontology_version)
);
CREATE INDEX IF NOT EXISTS idx_cq_translations_status
    ON cq_translations(validation_status);
"""


def migrate(conn: sqlite3.Connection) -> dict:
    conn.executescript(_DDL)
    conn.commit()
    return {"tables_created": ["cq_translations"]}


__all__ = ["migrate"]
