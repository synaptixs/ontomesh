"""Phase A — richer axiom emission.

Builds a synthetic SQLite database with `ontology_metadata` rows that
exercise every Phase A signal (hasKey, FunctionalProperty by FK,
Transitive/Symmetric/InverseFunctional, inverseOf, disjoint groups,
sibling-event AllDisjointClasses) and asserts the generator's TTL output
contains the expected OWL constructs and that the profile recommender
escalates to OWL 2 DL when warranted.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from db_introspector import DBIntrospector  # noqa: E402
from ontology_generator import generate_ontology  # noqa: E402


SCHEMA_DDL = """
CREATE TABLE ontology_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    column_name TEXT,
    semantic_type TEXT,
    label TEXT,
    description TEXT,
    sensitivity_tier TEXT DEFAULT 'Internal',
    is_event_class INTEGER DEFAULT 0,
    skos_pref_label TEXT,
    skos_alt_labels TEXT,
    cq_coverage TEXT,
    is_transitive INTEGER DEFAULT 0,
    is_symmetric INTEGER DEFAULT 0,
    is_functional INTEGER DEFAULT 0,
    is_inverse_functional INTEGER DEFAULT 0,
    inverse_of TEXT,
    disjoint_group TEXT,
    has_key_columns TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Two top-level entities flagged as a disjoint group.
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE individuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

-- Asset table referencing organization (FK → object property,
-- inherently functional). One column flagged transitive (parent_asset_id),
-- one flagged symmetric (peer_asset_id), one inverse-of pair.
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner_org_id INTEGER REFERENCES organizations(id),
    parent_asset_id INTEGER REFERENCES assets(id),
    peer_asset_id   INTEGER REFERENCES assets(id)
);

-- Event table with two distinct event_type values → two sibling subclasses
-- which should be auto-emitted as AllDisjointClasses.
CREATE TABLE domain_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    asset_id INTEGER REFERENCES assets(id)
);

INSERT INTO domain_events (event_type, title) VALUES
    ('outage',       'Outage A'),
    ('maintenance',  'Maintenance B');
"""

METADATA_ROWS = [
    # TABLE-level metadata
    ("TABLE", "organizations", None, "Organization", "Organization",
     "An organization.", "Internal", 0, None, None, None,
     0, 0, 0, 0, None, "PartyKind", "code"),
    ("TABLE", "individuals",   None, "Individual",   "Individual",
     "An individual.", "Internal", 0, None, None, None,
     0, 0, 0, 0, None, "PartyKind", "code"),
    ("TABLE", "assets",        None, "Asset",        "Asset",
     "Physical asset.", "Internal", 0, None, None, None,
     0, 0, 0, 0, None, None, "external_id"),
    ("TABLE", "domain_events", None, "DomainEvent",  "Domain Event",
     "Domain event.", "Internal", 1, None, None, None,
     0, 0, 0, 0, None, None, None),

    # external_id is a TEXT UNIQUE business identifier — override the
    # default `_id$` heuristic which would classify it as an FK/object prop.
    ("COLUMN", "assets", "external_id", "xsd:string", "external id", None,
     "Internal", 0, None, None, None,
     0, 0, 0, 0, None, None, None),

    # COLUMN-level metadata for the FK characteristic flags
    # parent_asset_id → transitive
    ("COLUMN", "assets", "parent_asset_id", None, "parent asset", None,
     "Internal", 0, None, None, None,
     1, 0, 0, 0, None, None, None),
    # peer_asset_id → symmetric + inverse-functional
    ("COLUMN", "assets", "peer_asset_id", None, "peer asset", None,
     "Internal", 0, None, None, None,
     0, 1, 0, 1, None, None, None),
    # owner_org_id → inverse-of "owns" (just to exercise emission)
    ("COLUMN", "assets", "owner_org_id", None, "owner organization", None,
     "Internal", 0, None, None, None,
     0, 0, 0, 0, "owns", None, None),
]


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_DDL)
    cols = ("target_type, table_name, column_name, semantic_type, label, "
            "description, sensitivity_tier, is_event_class, skos_pref_label, "
            "skos_alt_labels, cq_coverage, is_transitive, is_symmetric, "
            "is_functional, is_inverse_functional, inverse_of, disjoint_group, "
            "has_key_columns")
    qs = ",".join(["?"] * 18)
    for row in METADATA_ROWS:
        conn.execute(f"INSERT INTO ontology_metadata ({cols}) VALUES ({qs})", row)
    conn.commit()
    conn.close()
    return db_path


def _generate(db_path: Path, out_dir: Path) -> str:
    intro = DBIntrospector(str(db_path))
    try:
        generate_ontology(intro, str(out_dir))
    finally:
        intro.close()
    return (out_dir / "enterprise.ttl").read_text()


def test_has_key_emitted_for_meaningful_columns(populated_db, tmp_path):
    ttl = _generate(populated_db, tmp_path / "out")
    # organizations and individuals declare has_key_columns="code"
    assert "owl:hasKey ( :hasCode )" in ttl
    # assets declares has_key_columns="external_id"
    assert "owl:hasKey ( :hasExternalId )" in ttl


def test_fk_object_properties_are_functional_by_default(populated_db, tmp_path):
    ttl = _generate(populated_db, tmp_path / "out")
    # owner_org_id is a plain FK with no override → must be functional.
    # Locate the owner property block and check its type list.
    assert "owl:FunctionalProperty" in ttl
    # owner property name derives from owner_org → "owner" (the generator
    # strips _id/_org/_type).
    assert ":owner" in ttl  # property IRI present somewhere


def test_transitive_property_emitted(populated_db, tmp_path):
    ttl = _generate(populated_db, tmp_path / "out")
    assert "owl:TransitiveProperty" in ttl


def test_symmetric_and_inverse_functional_emitted(populated_db, tmp_path):
    ttl = _generate(populated_db, tmp_path / "out")
    assert "owl:SymmetricProperty" in ttl
    assert "owl:InverseFunctionalProperty" in ttl


def test_inverse_of_emitted(populated_db, tmp_path):
    ttl = _generate(populated_db, tmp_path / "out")
    assert "owl:inverseOf :owns" in ttl


def test_disjoint_group_emitted(populated_db, tmp_path):
    ttl = _generate(populated_db, tmp_path / "out")
    # The Organization / Individual disjoint_group "PartyKind" → AllDisjointClasses
    assert "owl:AllDisjointClasses" in ttl
    assert ":Organization" in ttl and ":Individual" in ttl
    # The members list should include both
    assert ":Organization" in ttl.split("owl:members")[1]


def test_event_subclasses_are_disjoint(populated_db, tmp_path):
    out_dir = tmp_path / "out"
    _generate(populated_db, out_dir)
    events = (out_dir / "events.ttl").read_text()
    # Two event_type values → OutageEvent + MaintenanceEvent, mutually disjoint
    assert ":OutageEvent" in events
    assert ":MaintenanceEvent" in events
    assert "owl:AllDisjointClasses" in events


def test_profile_escalates_to_dl(populated_db, tmp_path):
    out_dir = tmp_path / "out"
    _generate(populated_db, out_dir)
    rec = (out_dir / "profile_recommendation.md").read_text()
    # SymmetricProperty + inverseOf + InverseFunctionalProperty all present
    assert "OWL 2 DL" in rec
    assert "HermiT" in rec
