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


# ── SQL parser (sqlglot) ──────────────────────────────────────────────────

sqlglot = pytest.importorskip("sqlglot")


def test_sql_postgres_parses_three_tables():
    r = imp.parse_and_validate(_read("postgres_orders.sql"), filename="postgres_orders.sql")
    assert r.format == "sql", r.errors
    assert r.stats["table_count"] == 3
    assert r.stats["sql_dialect"] == "postgres"   # detected from BIGSERIAL
    s = r.session
    # Customers + Orders are entities; order_event_log routes to events.
    entity_labels = {e["label"] for e in s["entities"]}
    event_labels  = {e["label"] for e in s["events"]}
    assert "Customers" in entity_labels
    assert "Orders"    in entity_labels
    assert "Order Event Log" in event_labels


def test_sql_postgres_fk_becomes_relationship():
    r = imp.parse_and_validate(_read("postgres_orders.sql"))
    # orders.customer_id REFERENCES customers(id) → "Orders → references → Customers"
    rels = r.session["relationships"]
    assert any(rel["from_entity"] == "Orders" and rel["to_entity"] == "Customers"
               for rel in rels), rels
    # table-level FK (order_event_log → orders)
    assert any(rel["from_entity"] == "Order Event Log" and rel["to_entity"] == "Orders"
               for rel in rels)


def test_sql_postgres_xsd_type_mapping():
    r = imp.parse_and_validate(_read("postgres_orders.sql"))
    customers = next(e for e in r.session["entities"] if e["label"] == "Customers")
    by_name = {p["name"]: p for p in customers["properties"]}
    # Plain types map to their XSD equivalents (carried via type field — UI shows "VARCHAR"
    # but the XSD is recorded for OWL/SHACL generation downstream).
    assert by_name["email"]["type"].upper().startswith("VARCHAR")
    assert by_name["created_at"]["type"].upper().startswith("TIMESTAMP")


def test_sql_mysql_dialect_detected_and_parsed():
    r = imp.parse_and_validate(_read("mysql_payments.sql"), filename="mysql_payments.sql")
    assert r.format == "sql"
    assert r.stats["sql_dialect"] == "mysql"
    labels = {e["label"] for e in r.session["entities"]}
    assert "Accounts" in labels and "Transactions" in labels
    # FK → relationship even when declared at table level
    rels = r.session["relationships"]
    assert any(rel["from_entity"] == "Transactions" and rel["to_entity"] == "Accounts" for rel in rels)


def test_sql_sensitivity_suggestion_from_pii_columns():
    r = imp.parse_and_validate(_read("postgres_orders.sql"))
    # customers.email → property-level Confidential suggestion
    sug = [s for s in r.suggestions if s.code == "SUGGEST_PROPERTY_SENSITIVITY"]
    assert any("email" in s.message for s in sug)


def test_sql_no_create_table_returns_clean_error():
    r = imp.parse_and_validate(b"-- just a comment\nDROP TABLE foo;", filename="empty.sql")
    assert r.format == "sql"
    assert any(e.code == "NO_TABLES" for e in r.errors)


def test_sql_invalid_returns_parse_error():
    r = imp.parse_and_validate(b"CREATE TABLE   not    valid syntax\n;", filename="x.sql")
    # Either NO_TABLES (sqlglot tolerated it but produced nothing) or SQL_PARSE.
    assert any(e.code in ("SQL_PARSE", "NO_TABLES") for e in r.errors)


# ── Step 4: comment extraction ────────────────────────────────────────────

def test_postgres_comment_on_column_overrides_inline():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    users = next(e for e in r.session["entities"] if e["label"] == "Users")
    by_name = {p["name"]: p for p in users["properties"]}
    # COMMENT ON COLUMN users.email wins over no inline comment.
    assert "Primary contact address" in by_name["email"].get("description", "")


def test_postgres_comment_on_table_attaches_to_entity():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    tenants = next(e for e in r.session["entities"] if e["label"] == "Tenants")
    assert "customer organisation" in tenants["description"].lower()


def test_postgres_inline_dash_dash_comment_attaches_to_column():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    tenants = next(e for e in r.session["entities"] if e["label"] == "Tenants")
    by_name = {p["name"]: p for p in tenants["properties"]}
    # `id INTEGER PRIMARY KEY,    -- Surrogate identifier.`
    assert "Surrogate identifier" in by_name["id"].get("description", "")


def test_postgres_block_comment_above_column():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    tenants = next(e for e in r.session["entities"] if e["label"] == "Tenants")
    by_name = {p["name"]: p for p in tenants["properties"]}
    # The /* ... */ block sits on the line above is_isolated.
    assert "Single-tenant" in by_name["is_isolated"].get("description", "")


def test_mysql_inline_comment_keyword_attaches():
    r = imp.parse_and_validate(_read("mysql_with_inline_comments.sql"))
    products = next(e for e in r.session["entities"] if e["label"] == "Products")
    by_name = {p["name"]: p for p in products["properties"]}
    assert "Stock-keeping unit" in by_name["sku"].get("description", "")
    assert "Customer-facing"   in by_name["title"].get("description", "")
    assert "minor currency"    in by_name["price_cents"].get("description", "")


def test_sql_column_description_coverage_in_stats():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    pct = r.stats.get("sql_column_description_coverage_pct")
    assert pct is not None and pct > 0


# ── Step 4: soft-FK suggestions ───────────────────────────────────────────

def test_soft_fk_suggested_for_user_id_with_no_declared_fk():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    softs = [s for s in r.suggestions if s.code == "SUGGEST_SOFT_FK"]
    # orders.user_id has no FOREIGN KEY but matches the users table → suggest.
    assert any("orders" in s.location and "user_id" in s.location for s in softs), softs
    assert any("Users" in s.fix_hint for s in softs)


def test_declared_fk_suppresses_soft_fk_for_same_column():
    # users.tenant_id has a real REFERENCES tenants(id) — no soft-FK suggestion.
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    softs = [s for s in r.suggestions if s.code == "SUGGEST_SOFT_FK"]
    assert not any("users" in s.location and "tenant_id" in s.location for s in softs)


def test_soft_fk_count_in_stats():
    r = imp.parse_and_validate(_read("postgres_with_comments.sql"))
    assert r.stats.get("soft_fk_count", 0) >= 1


def test_singular_of_plural_table_match():
    # mysql_with_inline_comments.sql has `inventory.warehouse_id` with no FK
    # and no `warehouses` table → no suggestion (we don't invent targets).
    # `inventory.product_id` has a declared FK → no suggestion either.
    r = imp.parse_and_validate(_read("mysql_with_inline_comments.sql"))
    softs = [s for s in r.suggestions if s.code == "SUGGEST_SOFT_FK"]
    # Sanity: no false positives in this fixture.
    assert not any("warehouse_id" in s.location for s in softs)
    assert not any("product_id"   in s.location for s in softs)


def test_pluralisation_helpers_round_trip():
    # English heuristics, not linguistics — we just need them to be
    # consistent enough that customer/customers and category/categories match.
    assert imp._singularise("customers") == "customer"
    assert imp._singularise("categories") == "category"
    assert imp._singularise("addresses")  == "address"
    assert "customers"  in imp._pluralise("customer")
    assert "categories" in imp._pluralise("category")


# ── Step 4: COMMENT ON TABLE survives across statements ───────────────────

def test_yaml_relationship_parser_handles_real_template_sentences():
    """Regression for the bug where energy_utilities and four other YAML
    templates loaded with un-parseable relationships, leaving the
    Graph tab empty. Every shipped template must round-trip to
    structured {from_entity, label, to_entity} dicts."""
    from wizard import app as wapp
    c = wapp.app.test_client()
    names = c.get('/api/templates').get_json()['templates']
    assert names, "no templates registered"
    for n in names:
        j = c.get('/api/template/' + n).get_json()
        rels = j.get('relationships') or []
        bad = [r for r in rels
               if isinstance(r, dict)
               and (not r.get('from_entity') or not r.get('to_entity'))]
        assert not bad, (
            f"template '{n}' has {len(bad)}/{len(rels)} un-parseable relationship(s): "
            + "; ".join(b.get('label', '') for b in bad))


def test_yaml_relationship_parser_unit():
    """Direct exercise of the helper for the trickiest patterns:
    space-stripped label, suffix alias, self-reference."""
    from wizard.app import _parse_relationship_sentence as P
    # space-stripped form ('GovernmentAgency' for 'Government Agency')
    r = P("A Citizen submits a ServiceApplication to a GovernmentAgency.",
          ["Citizen", "Service Application", "Government Agency"])
    assert r and r["from_entity"] == "Citizen" and r["to_entity"] == "Government Agency"
    # suffix alias ('Policy' → 'Insurance Policy')
    r = P("A Claim is lodged against exactly one Policy.",
          ["Insurance Policy", "Insurance Claim"])
    assert r and r["from_entity"] == "Insurance Claim" and r["to_entity"] == "Insurance Policy"
    # self-reference (parent → child tree shape)
    r = P("An Agency may be subordinate to another Agency.", ["Government Agency"])
    assert r and r["from_entity"] == r["to_entity"] == "Government Agency"
    # un-parseable: only one entity, no self-ref hint
    r = P("Generic prose without entity names.", ["Foo", "Bar"])
    assert r is None


def test_comment_on_table_works_when_placed_at_end():
    # The fixture puts COMMENT ON TABLE *after* every CREATE TABLE — ensure
    # the regex pass picks it up regardless of position.
    sql = b"""
CREATE TABLE x (id INT);
CREATE TABLE y (id INT);
COMMENT ON TABLE x IS 'first table';
COMMENT ON TABLE y IS 'second table';
"""
    r = imp.parse_and_validate(sql, filename="x.sql")
    descs = {e["label"]: e["description"] for e in r.session["entities"]}
    assert descs.get("X") == "first table"
    assert descs.get("Y") == "second table"


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
