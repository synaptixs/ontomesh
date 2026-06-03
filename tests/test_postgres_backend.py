"""P2.3 — Backend-agnostic ontologies_store tests.

Two flavours:

1. SQLite tests run unconditionally — they exercise the same code
   paths the wizard has always used.
2. Postgres tests run only when ``ONTOMESH_TEST_PG_URL`` is set in
   the environment (e.g. ``postgresql://test:test@localhost:5433/test``).
   CI sets this; locally we skip with a clear reason.

Every assertion runs identically against both backends so a SQL or
schema regression in one is caught immediately.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

from wizard import ontologies_store as store              # noqa: E402


PG_URL = os.environ.get("ONTOMESH_TEST_PG_URL")


# ── Backends parameterised ────────────────────────────────────────────


@pytest.fixture(params=["sqlite", "postgres"])
def backend_url(request, tmp_path):
    """Yield a clean DB URL for whichever backend the test wants."""
    if request.param == "sqlite":
        return str(tmp_path / "test_store.db")

    if not PG_URL:
        pytest.skip("ONTOMESH_TEST_PG_URL not set — Postgres backend "
                    "test skipped (run a local pg container and "
                    "export ONTOMESH_TEST_PG_URL=postgresql://...)")
    # Reset the live Postgres tables before every parameterised run.
    import psycopg
    with psycopg.connect(PG_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS ontology")
            cur.execute("DROP TABLE IF EXISTS preference")
        conn.commit()
    return PG_URL


# ── URL parsing ───────────────────────────────────────────────────────


def test_bare_path_is_treated_as_sqlite(tmp_path):
    """Back-compat: every existing call site passes a filesystem path."""
    url = store._normalize_url(str(tmp_path / "x.db"))
    assert url.startswith("sqlite:///")


def test_postgres_url_passes_through():
    u = "postgresql://u:p@h:5432/db"
    assert store._normalize_url(u) == u
    assert store._backend_kind(u) == "postgres"


def test_sqlite_url_passes_through(tmp_path):
    u = "sqlite:///" + str(tmp_path / "x.db")
    assert store._normalize_url(u) == u
    assert store._backend_kind(u) == "sqlite"


def test_unsupported_scheme_raises():
    with pytest.raises(ValueError):
        store._backend_kind("mongodb://h/d")


def test_qmarks_to_pyformat_conversion():
    assert store._qmarks_to_pyformat("SELECT * FROM x WHERE id=?") \
        == "SELECT * FROM x WHERE id=%s"
    assert store._qmarks_to_pyformat("INSERT INTO x VALUES (?, ?, ?)") \
        == "INSERT INTO x VALUES (%s, %s, %s)"


# ── Full lifecycle, parameterised over backend ────────────────────────


def test_init_db_idempotent(backend_url):
    """Calling init_db twice must not raise — common during reboots."""
    store.init_db(backend_url)
    store.init_db(backend_url)


def test_save_then_get_round_trips_session(backend_url):
    store.init_db(backend_url)
    payload = {"domain": {"name": "Demo"}, "entities": [{"name": "X"}]}
    res = store.save_ontology(
        backend_url,
        domain="telecom", product="my-product", label="my-label",
        session=payload, generated={"ttl": "@prefix : <#> ."},
    )
    assert res["created"] is True
    fetched = store.get_ontology(backend_url, res["slug"])
    assert fetched["session"]   == payload
    assert fetched["generated"] == {"ttl": "@prefix : <#> ."}
    assert fetched["domain"]  == "telecom"
    assert fetched["product"] == "my-product"
    assert fetched["label"]   == "my-label"


def test_list_orders_by_updated_desc(backend_url):
    store.init_db(backend_url)
    for label in ("first", "second", "third"):
        store.save_ontology(
            backend_url, domain="d", product="p", label=label,
            session={}, generated={},
        )
    rows = store.list_ontologies(backend_url)
    assert len(rows) == 3
    # Most-recent first.
    labels = [r["label"] for r in rows]
    assert labels[0] == "third"


def test_save_without_overwrite_raises_on_duplicate(backend_url):
    store.init_db(backend_url)
    store.save_ontology(
        backend_url, domain="d", product="p", label="l",
        session={}, generated={},
    )
    with pytest.raises(FileExistsError):
        store.save_ontology(
            backend_url, domain="d", product="p", label="l",
            session={}, generated={},
        )


def test_save_with_overwrite_succeeds(backend_url):
    store.init_db(backend_url)
    store.save_ontology(
        backend_url, domain="d", product="p", label="l",
        session={"v": 1}, generated={}, overwrite=False,
    )
    res = store.save_ontology(
        backend_url, domain="d", product="p", label="l",
        session={"v": 2}, generated={}, overwrite=True,
    )
    assert res["created"] is False
    got = store.get_ontology(backend_url, res["slug"])
    assert got["session"]["v"] == 2


def test_delete_removes_the_row(backend_url):
    store.init_db(backend_url)
    res = store.save_ontology(
        backend_url, domain="d", product="p", label="l",
        session={}, generated={},
    )
    assert store.delete_ontology(backend_url, res["slug"]) is True
    assert store.get_ontology(backend_url, res["slug"]) is None
    # Second delete is a no-op.
    assert store.delete_ontology(backend_url, res["slug"]) is False


def test_preferences_round_trip(backend_url):
    store.init_db(backend_url)
    store.set_preferences(backend_url,
                          {"landing.visible_domains": ["telecom","healthcare"]})
    got = store.get_preferences(backend_url)
    assert got["landing.visible_domains"] == ["telecom", "healthcare"]


def test_preferences_upsert(backend_url):
    """Writing the same key twice must replace, not append.  The
    INSERT … ON CONFLICT clause works in both backends — this proves
    it."""
    store.init_db(backend_url)
    store.set_preferences(backend_url, {"k": "v1"})
    store.set_preferences(backend_url, {"k": "v2"})
    assert store.get_preferences(backend_url) == {"k": "v2"}


# ── Pyproject integrity ───────────────────────────────────────────────


def test_postgres_extra_pulls_in_both_drivers():
    """The single `[postgres]` extra must pull in both psycopg2
    (used by src/db_connector.py for --phase 1 introspection) and
    psycopg3 (used by ontologies_store.py for the wizard store)."""
    py = (ROOT / "pyproject.toml").read_text()
    # Find the postgres extra line.  The list literal contains a
    # bracketed marker (psycopg[binary]) so we look up by scanning
    # forward from the key until the close of the outermost ].
    import re
    m = re.search(r"^postgres\s*=\s*\[", py, re.MULTILINE)
    assert m, "no postgres extra"
    # Walk to the matching close-bracket.
    depth, end = 1, m.end()
    while depth and end < len(py):
        c = py[end]
        if c == "[": depth += 1
        elif c == "]": depth -= 1
        end += 1
    body = py[m.end():end - 1]
    assert "psycopg2-binary" in body, body
    assert "psycopg[binary]" in body, body


# ── Env-var wiring ────────────────────────────────────────────────────


def test_app_reads_ontomesh_db_url(monkeypatch):
    """wizard/app.py picks up ONTOMESH_DB_URL at import time so
    operators can switch backends without code changes."""
    src = (ROOT / "wizard" / "app.py").read_text()
    assert "ONTOMESH_DB_URL" in src
    # Default falls back to the legacy SQLite path.
    assert 'os.environ.get(\n    "ONTOMESH_DB_URL"' in src \
        or "os.environ.get('ONTOMESH_DB_URL'" in src \
        or 'os.environ.get("ONTOMESH_DB_URL"' in src
