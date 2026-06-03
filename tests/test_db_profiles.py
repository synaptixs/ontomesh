"""Database-direct import — vendor catalogue, profile CRUD, endpoints."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wizard.db_profiles import (  # noqa: E402
    VENDORS, build_connection_string, delete_profile, get_profile,
    introspect_to_session, list_profiles, save_profile,
    probe_connection, vendor_list, vendor_required_fields,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


# ── Vendor catalogue ────────────────────────────────────────────────────


def test_vendor_list_covers_every_supported_driver():
    ids = {v["id"] for v in vendor_list()}
    assert ids == {"sqlite", "postgresql", "mysql", "mssql", "oracle", "db2"}


def test_every_vendor_declares_an_icon_label_description_and_fields():
    for v in vendor_list():
        assert v["icon"]
        assert v["label"]
        assert v["description"]
        assert isinstance(v["fields"], list) and v["fields"]


def test_every_vendor_has_at_least_one_required_field():
    for vid in VENDORS:
        assert vendor_required_fields(vid), f"{vid} has no required fields"


def test_sqlite_only_needs_db_path():
    assert vendor_required_fields("sqlite") == ["db_path"]


def test_postgres_required_fields_include_user_and_password():
    req = vendor_required_fields("postgresql")
    assert {"host", "port", "dbname", "user", "password"}.issubset(req)


# ── Connection-string assembly ──────────────────────────────────────────


def test_sqlite_url_uses_three_slashes_for_relative():
    url = build_connection_string("sqlite", {"db_path": "db/enterprise.db"})
    assert url.startswith("sqlite:///")


def test_postgres_url_escapes_special_chars_in_password():
    url = build_connection_string("postgresql", {
        "host": "db.local", "port": 5432, "dbname": "ops",
        "user": "u", "password": "p@ss!w0rd",
    })
    # The '@' and '!' must be url-escaped or the URL parser sees a host change.
    assert "%40" in url and "%21" in url
    assert "ops" in url


def test_oracle_url_handles_wallet_path_without_host():
    url = build_connection_string("oracle", {
        "user": "admin", "password": "X",
        "service_name": "ATP1",
        "wallet": "/wallet", "wallet_password": "wp",
    })
    assert "oracle://" in url and "ATP1" in url
    assert "wallet=%2Fwallet" in url   # path url-escaped


def test_build_url_raises_when_required_field_missing():
    with pytest.raises(ValueError, match="Missing required field"):
        build_connection_string("mysql", {"host": "x"})


def test_build_url_raises_on_unknown_vendor():
    with pytest.raises(ValueError, match="Unknown vendor"):
        build_connection_string("unsupported", {})


# ── Profile CRUD ────────────────────────────────────────────────────────


def test_save_and_list_round_trip(conn):
    saved = save_profile(conn, name="Prod replica", vendor="postgresql",
                         config={"host": "db.local", "port": 5432,
                                 "dbname": "ops", "user": "ro",
                                 "password": "s3cret"})
    listed = list_profiles(conn)
    assert len(listed) == 1
    assert listed[0].name == "Prod replica"
    # Listing path returns deobfuscated config — get_profile/list both decode.
    assert listed[0].config["password"] == "s3cret"
    assert listed[0].id == saved.id


def test_passwords_are_obfuscated_at_rest(conn):
    save_profile(conn, name="x", vendor="postgresql",
                 config={"host": "h", "port": 5432, "dbname": "d",
                         "user": "u", "password": "myplainsecret"})
    raw = conn.execute(
        "SELECT config_json FROM db_connection_profiles"
    ).fetchone()[0]
    # The plain password must NOT be readable in the stored JSON.
    assert "myplainsecret" not in raw
    # And the obfuscation prefix must be present.
    assert "obf:" in raw


def test_save_then_update_keeps_single_row(conn):
    p = save_profile(conn, name="x", vendor="sqlite",
                     config={"db_path": "/tmp/a.db"})
    save_profile(conn, profile_id=p.id, name="x", vendor="sqlite",
                 config={"db_path": "/tmp/b.db"})
    rows = list_profiles(conn)
    assert len(rows) == 1
    assert rows[0].config["db_path"] == "/tmp/b.db"


def test_delete_profile(conn):
    p = save_profile(conn, name="d", vendor="sqlite",
                     config={"db_path": "/tmp/x.db"})
    assert delete_profile(conn, p.id) is True
    assert get_profile(conn, p.id) is None
    assert delete_profile(conn, p.id) is False   # idempotent on missing


def test_save_rejects_empty_name(conn):
    with pytest.raises(ValueError):
        save_profile(conn, name="", vendor="sqlite",
                     config={"db_path": "/tmp/x.db"})


def test_save_rejects_unknown_vendor(conn):
    with pytest.raises(ValueError):
        save_profile(conn, name="x", vendor="nosuch", config={})


def test_to_dict_masks_secrets(conn):
    p = save_profile(conn, name="masked", vendor="postgresql",
                     config={"host": "h", "port": 5432, "dbname": "d",
                             "user": "u", "password": "topsecret"})
    payload = p.to_dict(mask_secrets=True)
    assert payload["config"]["password"] == "●●●●●●"
    # Non-secret fields pass through untouched.
    assert payload["config"]["user"] == "u"


# ── test_connection + introspect_to_session on real SQLite ─────────────


def test_test_connection_on_demo_sqlite():
    demo_db = ROOT / "db" / "enterprise.db"
    if not demo_db.is_file():
        pytest.skip("demo DB not present")
    res = probe_connection("sqlite", {"db_path": str(demo_db)})
    assert res.ok
    assert res.tables > 0
    assert res.duration_ms >= 0


def test_test_connection_reports_missing_file_cleanly():
    res = probe_connection("sqlite", {"db_path": "/nonexistent.db"})
    assert not res.ok
    assert "not found" in (res.error or "").lower() or \
           "could not" in (res.error or "").lower()


def test_introspect_to_session_lifts_tables_into_entities():
    demo_db = ROOT / "db" / "enterprise.db"
    if not demo_db.is_file():
        pytest.skip("demo DB not present")
    sess = introspect_to_session(
        "sqlite", {"db_path": str(demo_db)},
        domain_name="Demo", base_iri="https://demo/")
    assert sess["domain"]["name"] == "Demo"
    assert len(sess["entities"]) > 0
    # Every entity should carry a label and at least one property OR a
    # foreign-key relationship somewhere referencing it.
    assert all(e["label"] for e in sess["entities"])
    # source tag so the wizard can identify db-imports later.
    assert sess["_source"] == "db-import"


# ── Wizard endpoints register + round-trip ─────────────────────────────


def test_db_endpoints_register():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    routes = {r.rule for r in app_mod.app.url_map.iter_rules()}
    for path in (
        "/api/db/vendors",
        "/api/db/profiles",
        "/api/db/profiles/<int:profile_id>",
        "/api/db/test",
        "/api/db/import",
    ):
        assert path in routes, f"missing {path}"


def test_vendors_endpoint_returns_full_catalogue(monkeypatch):
    pytest.importorskip("flask")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    client = app_mod.app.test_client()
    res = client.get("/api/db/vendors")
    assert res.status_code == 200
    out = res.get_json()
    ids = {v["id"] for v in out["vendors"]}
    assert "sqlite" in ids and "postgresql" in ids


def test_profile_save_and_test_via_endpoints(tmp_path, monkeypatch):
    """End-to-end: POST a profile, list it, hit /api/db/test against it."""
    pytest.importorskip("flask")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    # Redirect ONTOLOGIES_DB to a tmp path so the test doesn't pollute.
    db_path = tmp_path / "ontologies.db"
    monkeypatch.setattr(app_mod, "ONTOLOGIES_DB", str(db_path))

    demo_db = ROOT / "db" / "enterprise.db"
    if not demo_db.is_file():
        pytest.skip("demo DB not present")

    client = app_mod.app.test_client()
    # Save a profile pointing at the demo SQLite file.
    res = client.post("/api/db/profiles", json={
        "name": "Demo SQLite",
        "vendor": "sqlite",
        "config": {"db_path": str(demo_db)},
    })
    assert res.status_code == 200
    pid = res.get_json()["profile"]["id"]

    # List back.
    res = client.get("/api/db/profiles")
    assert res.status_code == 200
    listed = res.get_json()["profiles"]
    assert any(p["id"] == pid for p in listed)

    # Test connection by profile id.
    res = client.post("/api/db/test", json={"profile_id": pid})
    assert res.status_code == 200
    test_out = res.get_json()
    assert test_out["ok"]
    assert test_out["tables"] > 0

    # Import — should return the ImportResult shape.
    res = client.post("/api/db/import", json={"profile_id": pid,
                                              "domain_name": "Demo"})
    assert res.status_code == 200
    out = res.get_json()
    assert out["ok"]
    assert out["format"] == "database"
    assert out["session"]["entities"]

    # Delete.
    res = client.delete(f"/api/db/profiles/{pid}")
    assert res.status_code == 200
    res = client.delete(f"/api/db/profiles/{pid}")
    assert res.status_code == 404      # already gone
