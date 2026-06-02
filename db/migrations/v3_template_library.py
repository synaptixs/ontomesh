"""
db/migrations/v3_template_library.py — T2.2
───────────────────────────────────────────
Cross-corpus template library schema.

Adds the ``template_library`` table — one row per canonical
template signature plus aggregated review history from all corpora
that have approved/rejected its matches. Privacy: rows store only
hashed token sets and slot-type vectors. **No raw log lines ever
land in this table** — a hard rule the toolkit's federation layer
relies on.

Idempotent.
"""

from __future__ import annotations

import sqlite3


_DDL = """
CREATE TABLE IF NOT EXISTS template_library (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    signature_hash      TEXT NOT NULL UNIQUE,
    tokens_hash         TEXT NOT NULL,
    slot_types_json     TEXT NOT NULL,
    n_tokens            INTEGER NOT NULL,
    n_slots             INTEGER NOT NULL,
    decisions_approved  INTEGER NOT NULL DEFAULT 0,
    decisions_rejected  INTEGER NOT NULL DEFAULT 0,
    source_corpora      TEXT,
    first_seen          TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_template_library_tokens
    ON template_library(tokens_hash);
"""


def migrate(conn: sqlite3.Connection) -> dict:
    conn.executescript(_DDL)
    conn.commit()
    return {"tables_created": ["template_library"]}


__all__ = ["migrate"]
