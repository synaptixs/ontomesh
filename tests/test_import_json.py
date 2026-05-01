"""Unit + route tests for wizard.importer (issue #16, step 1).

Covers the three JSON shapes (wizard / cli / schema), the validation
tiers (errors / warnings / suggestions), and the two HTTP routes
(/api/import and /api/import/commit).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wizard import importer as imp     # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "import"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ── Shape detection + normalisers ────────────────────────────────────────

def test_detect_format_json_by_extension():
    assert imp._detect_format(b"{}", "auto", "x.json") == "json"


def test_detect_format_sql_by_content():
    assert imp._detect_format(b"-- a script\nCREATE TABLE foo (id INT);", "auto", None) == "sql"


def test_detect_format_json_by_leading_brace():
    assert imp._detect_format(b"  \n{ \"x\": 1 }", "auto", None) == "json"


def test_wizard_session_round_trip():
    r = imp.parse_and_validate(_read("wizard_session_good.json"), filename="wizard_session_good.json")
    assert r.ok, r.errors
    assert r.format == "json-wizard"
    s = r.session
    assert s["domain"]["name"] == "Smart Building Operations"
    # entities + events kept in their separate lists
    assert len(s["entities"]) == 3
    assert len(s["events"]) == 1
    assert {e["label"] for e in s["entities"]} == {"Building", "Floor", "Tenant"}
    # cqs preserved
    assert len(s["competency_questions"]) == 1


def test_cli_session_normalised_to_wizard_shape():
    r = imp.parse_and_validate(_read("cli_session_retail.json"), filename="cli_session_retail.json")
    assert r.format == "json-cli", r.format
    s = r.session
    # Domain renamed
    assert s["domain"]["name"] == "Retail Operations"
    assert s["domain"]["industry"] == "retail_operations"
    # is_event flag splits flat list into entities vs events
    labels = {e["label"] for e in s["entities"]}
    assert labels == {"Customer", "Order"}
    assert {e["label"] for e in s["events"]} == {"Purchase Event"}
    # cqs become structured records
    assert s["competency_questions"][0]["id"] == "CQ-01"
    assert s["competency_questions"][0]["priority"] == "Medium"
    # No errors blocking
    assert r.ok, r.errors


def test_schema_shape_builds_entities_events_and_relationships():
    r = imp.parse_and_validate(_read("schema_payments.json"), filename="schema_payments.json")
    assert r.format == "json-schema", r.format
    s = r.session
    # 'transaction_log' has _log → routed to events; 'customer' is an entity
    assert any(e["label"] == "Customer" for e in s["entities"])
    assert any(e["label"] == "Transaction Log" for e in s["events"])
    # FK promoted to a relationship
    rel = [r for r in s["relationships"] if r["from_entity"] == "Transaction Log"]
    assert rel and rel[0]["to_entity"] == "Customer"
    # Property descriptions carried through
    cust = next(e for e in s["entities"] if e["label"] == "Customer")
    email = next(p for p in cust["properties"] if p["name"] == "email")
    assert email["type"] == "VARCHAR"


# ── Validation: errors block ──────────────────────────────────────────────

def test_broken_session_emits_blocking_errors():
    r = imp.parse_and_validate(_read("wizard_session_broken.json"))
    codes = {e.code for e in r.errors}
    assert "MISSING_DOMAIN_NAME" in codes
    assert "DUPLICATE_ENTITY"    in codes
    assert "UNSAFE_ENTITY_NAME"  in codes        # "Customer A" has space
    assert "REL_BAD_ENDPOINT"    in codes        # "DoesNotExist"
    assert not r.ok


def test_invalid_json_returns_clean_error():
    r = imp.parse_and_validate(b"{not valid: json,}", filename="bad.json")
    codes = {e.code for e in r.errors}
    assert "INVALID_JSON" in codes
    assert not r.ok


def test_root_must_be_object():
    r = imp.parse_and_validate(b"[1, 2, 3]", filename="x.json")
    assert any(e.code == "ROOT_NOT_OBJECT" for e in r.errors)


def test_no_entities_is_blocking():
    raw = json.dumps({"domain": {"name": "X"}, "entities": [], "events": []}).encode()
    r = imp.parse_and_validate(raw)
    assert any(e.code == "NO_ENTITIES" for e in r.errors)


# ── Validation: warnings allow ─────────────────────────────────────────────

def test_orphan_and_missing_iri_warnings():
    raw = json.dumps({
        "domain": {"name": "Test"},
        "entities": [
            {"label": "A", "description": "first"},
            {"label": "B", "description": "lonely"},
        ],
        "events": [],
        "relationships": [
            {"from_entity": "A", "label": "is",  "to_entity": "A"}
        ],
        "competency_questions": [],
    }).encode()
    r = imp.parse_and_validate(raw)
    codes = {w.code for w in r.warnings}
    assert "MISSING_BASE_IRI" in codes
    assert "NO_CQS"           in codes
    assert "ORPHAN_ENTITY"    in codes        # B has no edges
    assert r.ok                                # warnings don't block


# ── Validation: suggestions ───────────────────────────────────────────────

def test_sensitivity_suggestion_for_pii_entity():
    raw = json.dumps({
        "domain": {"name": "Health"},
        "entities": [
            {"label": "Patient", "description": "x", "sensitivity": "Internal"},
            {"label": "Building", "description": "y", "sensitivity": "Internal"},
        ],
        "relationships": [{"from_entity": "Patient", "label": "in", "to_entity": "Building"}],
    }).encode()
    r = imp.parse_and_validate(raw)
    sug_codes = {s.code for s in r.suggestions}
    assert "SUGGEST_SENSITIVITY" in sug_codes
    # Suggestion should target the Patient entity, not Building
    sug_msgs = [s.message for s in r.suggestions if s.code == "SUGGEST_SENSITIVITY"]
    assert any("Patient" in m for m in sug_msgs)
    assert not any("Building" in m for m in sug_msgs)


def test_event_naming_suggestion():
    raw = json.dumps({
        "domain": {"name": "X"},
        "entities": [
            {"label": "Audit Log", "description": "x", "is_event": False},
        ],
    }).encode()
    r = imp.parse_and_validate(raw)
    assert any(s.code == "SUGGEST_EVENT" for s in r.suggestions)


def test_property_sensitivity_suggestion():
    raw = json.dumps({
        "domain": {"name": "X"},
        "entities": [{
            "label": "User", "description": "x",
            "properties": [
                {"name": "id"},
                {"name": "password"},     # → Restricted
                {"name": "email"},        # → Confidential
            ],
        }],
    }).encode()
    r = imp.parse_and_validate(raw)
    sugs = [s for s in r.suggestions if s.code == "SUGGEST_PROPERTY_SENSITIVITY"]
    fields = {s.location for s in sugs}
    assert any("password" in s.message for s in sugs)
    assert any("email"    in s.message for s in sugs)


# ── Stats + diff ──────────────────────────────────────────────────────────

def test_stats_describes_session():
    r = imp.parse_and_validate(_read("wizard_session_good.json"))
    st = r.stats
    assert st["entities"] == 3 and st["events"] == 1
    assert st["relationships"] == 2 and st["competency_questions"] == 1
    assert st["entity_description_coverage_pct"] == 100


def test_diff_against_existing_session():
    existing = json.loads(_read("wizard_session_good.json"))
    new = dict(existing)
    new["entities"] = [
        *existing["entities"],
        {"label": "Sensor", "description": "added"},
    ]
    raw = json.dumps(new).encode()
    r = imp.parse_and_validate(raw, existing_session=existing)
    assert r.diff["added"]["entities"] == 1
    assert r.diff["removed"]["entities"] == 0


# ── SQL stub ──────────────────────────────────────────────────────────────

def test_sql_path_returns_not_implemented_error():
    r = imp.parse_and_validate(b"CREATE TABLE foo (id INT);", filename="x.sql")
    assert any(e.code == "SQL_NOT_IMPLEMENTED" for e in r.errors)


# ── HTTP routes (Flask test client) ──────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    # Isolate the wizard's session file under a tmp dir so tests don't
    # clobber a developer's running wizard state.
    monkeypatch.setenv("WIZARD_SESSION_FILE", str(tmp_path / "session.json"))
    # The app module reads SESSION_FILE at import time; reload it after
    # the env var is set.
    import importlib, wizard.app as app_mod
    app_mod.SESSION_FILE = str(tmp_path / "session.json")
    importlib.reload(app_mod) if False else None
    return app_mod.app.test_client()


def test_route_import_multipart(client, tmp_path):
    f = (FIXTURES / "wizard_session_good.json").open("rb")
    try:
        rv = client.post("/api/import",
                         data={"file": (f, "wizard_session_good.json"),
                               "format": "json"},
                         content_type="multipart/form-data")
    finally:
        f.close()
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["format"] == "json-wizard"
    assert body["session"]["domain"]["name"] == "Smart Building Operations"


def test_route_import_json_body(client):
    payload = {"content": (FIXTURES / "cli_session_retail.json").read_text(),
               "format": "json", "filename": "cli_session_retail.json"}
    rv = client.post("/api/import", json=payload)
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["format"] == "json-cli"


def test_route_import_then_commit(client):
    payload = {"content": (FIXTURES / "wizard_session_good.json").read_text(),
               "format": "json"}
    rv = client.post("/api/import", json=payload); body = rv.get_json()
    assert body["ok"]
    rv2 = client.post("/api/import/commit", json={"session": body["session"]})
    assert rv2.status_code == 200
    saved = client.get("/api/session").get_json()
    assert saved["domain"]["name"] == "Smart Building Operations"


def test_route_commit_refuses_invalid_session(client):
    bad = {"domain": {"name": ""}, "entities": []}
    rv = client.post("/api/import/commit", json={"session": bad})
    assert rv.status_code == 400
    body = rv.get_json()
    assert "errors" in body and any(e["code"] == "MISSING_DOMAIN_NAME" for e in body["errors"])
