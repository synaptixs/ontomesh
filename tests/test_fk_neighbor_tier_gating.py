"""FK-neighbour fetch must obey the same controls as the primary query.

Regression tests for a confidentiality bypass: `_fk_neighbors` issued
`SELECT *` against tables discovered from `PRAGMA foreign_key_list`, so it
honoured neither the flavor's table allow-list nor the sensitivity ceiling
that `compile_sql` enforces on the primary query. Those column values flowed
into the materialized subgraph, which `POST /api/sparql` lets a caller query
directly — making the tier ceiling advisory on that path.

The demonstrating case: a search over `observations` at `max_tier="Internal"`
returned `agents.credential_expiry`, which the mapping classifies
`Confidential`.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.reasoning_search._loaders import Mapping          # noqa: E402
from runtime.reasoning_search.engine import _fk_neighbors      # noqa: E402


@pytest.fixture()
def db(tmp_path):
    """Two tables joined by an FK, the parent holding a Confidential column."""
    path = tmp_path / "t.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE agents (
            id INTEGER PRIMARY KEY,
            name TEXT,
            credential_expiry TEXT,
            secret_note TEXT
        );
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY,
            recorded_by INTEGER REFERENCES agents(id),
            value TEXT
        );
        INSERT INTO agents VALUES (1, 'NOC Engineer', '2027-01-01', 'do-not-share');
        INSERT INTO observations VALUES (1, 1, '18.7');
        """
    )
    con.commit()
    con.close()
    return str(path)


@pytest.fixture()
def mapping():
    m = Mapping()
    m.class_table = {"Agent": "agents", "ObservationRecord": "observations"}
    m.prop_col = {
        ("Agent", "hasName"): ("agents", "name"),
        ("Agent", "hasCredentialExpiry"): ("agents", "credential_expiry"),
        ("ObservationRecord", "hasValue"): ("observations", "value"),
    }
    m.tier = {
        "Agent": "Internal",
        "Agent.hasName": "Internal",
        "Agent.hasCredentialExpiry": "Confidential",
        "ObservationRecord.hasValue": "Internal",
    }
    return m


def _rows():
    return [{"id": 1, "recorded_by": 1, "value": "18.7"}]


def _columns_returned(edges):
    return {c for e in edges for c in e["row"]}


def test_confidential_column_withheld_below_its_tier(db, mapping):
    """The bypass itself: a Confidential column must not come back at Internal."""
    edges, _ = _fk_neighbors(db, "observations", _rows(), mapping=mapping,
                             allowed_tables={"observations", "agents"},
                             max_tier="Internal")
    assert edges, "the allow-listed neighbour should still be followed"
    cols = _columns_returned(edges)
    assert "credential_expiry" not in cols
    assert "hasName" not in cols  # ontology names never leak into row keys
    assert "name" in cols, "readable columns should still be projected"


def test_confidential_column_returned_at_its_own_tier(db, mapping):
    """Gating is a ceiling, not a blanket refusal."""
    edges, _ = _fk_neighbors(db, "observations", _rows(), mapping=mapping,
                             allowed_tables={"observations", "agents"},
                             max_tier="Confidential")
    assert "credential_expiry" in _columns_returned(edges)


def test_unmapped_column_never_returned(db, mapping):
    """`secret_note` is in the table but not in the mapping.

    `SELECT *` returned it. An unclassified column is treated as unreadable
    rather than public — nothing has said it is safe to expose.
    """
    edges, _ = _fk_neighbors(db, "observations", _rows(), mapping=mapping,
                             allowed_tables={"observations", "agents"},
                             max_tier="Restricted")
    assert "secret_note" not in _columns_returned(edges)


def test_table_outside_the_allow_list_is_not_followed(db, mapping):
    """A foreign key pointing outside the flavor is dropped, and reported."""
    edges, skipped = _fk_neighbors(db, "observations", _rows(), mapping=mapping,
                                   allowed_tables={"observations"},
                                   max_tier="Confidential")
    assert edges == []
    assert any(s["ref_table"] == "agents"
               and "allow-listed" in s["reason"] for s in skipped), skipped


def test_missing_mapping_fails_closed(db):
    """No mapping means no way to classify columns, so follow nothing."""
    edges, skipped = _fk_neighbors(db, "observations", _rows(), mapping=None,
                                   allowed_tables={"observations", "agents"},
                                   max_tier="Restricted")
    assert edges == []
    assert skipped, "the refusal should be reported, not silent"


def test_deidentification_applies_to_neighbour_rows(db, mapping):
    """Masking previously ran before neighbours were fetched, so missed them."""
    edges, _ = _fk_neighbors(db, "observations", _rows(), mapping=mapping,
                             allowed_tables={"observations", "agents"},
                             max_tier="Confidential",
                             deid_columns={"credential_expiry"})
    values = [e["row"].get("credential_expiry") for e in edges]
    assert values and all(v == "•••" for v in values), values
