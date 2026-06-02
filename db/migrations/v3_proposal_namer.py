"""
db/migrations/v3_proposal_namer.py
──────────────────────────────────
T1.1 migration — track which proposals have been LLM-named so we
re-run the namer only when needed, and so engineer edits are not
silently overwritten on the next pass.

Adds two columns to ``ontology_evolution_proposals``:

- ``name_source`` — one of ``auto`` (mechanical, the default),
  ``llm`` (named by ``wizard.proposal_namer``), or ``human``
  (engineer edited the title in the wizard). The ``rename`` pass
  only touches rows where ``name_source = 'auto'`` so prior LLM
  names and human edits stick.
- ``name_generated_at`` — ISO timestamp of the most recent rename.

Both columns are nullable and additive. Safe to call on a fresh DB
and safe to call repeatedly.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence


_PROPOSAL_COLUMNS_V3 = (
    ("name_source",        "TEXT DEFAULT 'auto'"),
    ("name_generated_at",  "TEXT"),
)


def migrate(conn: sqlite3.Connection) -> dict:
    """Apply the migration. Returns ``{'columns_added': [...]}``.
    Idempotent: re-running reports an empty list."""
    applied: list[str] = []

    if not _table_exists(conn, "ontology_evolution_proposals"):
        return {"columns_added": [], "skipped": True}

    existing = {
        row[1] for row in conn.execute(
            "PRAGMA table_info(ontology_evolution_proposals)"
        )
    }
    for name, decl in _PROPOSAL_COLUMNS_V3:
        if name in existing:
            continue
        conn.execute(
            f"ALTER TABLE ontology_evolution_proposals "
            f"ADD COLUMN {name} {decl}"
        )
        applied.append(name)

    conn.commit()
    return {"columns_added": applied}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


__all__ = ["migrate"]
