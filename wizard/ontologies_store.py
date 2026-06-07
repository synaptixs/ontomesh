"""
wizard/ontologies_store.py
──────────────────────────
Backend-agnostic library of saved ontologies and user preferences.

A saved ontology is identified by a unique slug built from
(domain, product, label). Each row holds the wizard session JSON
plus the generated artifacts (TTL / SHACL / SKOS) inlined as text.

Backend selection
─────────────────
Every public function takes a ``db`` argument that can be either:

  • A filesystem path                            → SQLite (default)
      "db/ontologies.db"   or  "/var/lib/ontomesh/ontologies.db"

  • A ``sqlite:///`` URL                         → SQLite
      "sqlite:///db/ontologies.db"

  • A ``postgresql://`` URL                      → Postgres (P2.3)
      "postgresql://user:pass@host/dbname"

The Postgres path is opt-in:
    pip install ontoforge[postgres]
    export ONTOMESH_DB_URL=postgresql://ontomesh:secret@db:5432/ontomesh

The SQLite path is the historical default and stays the only
dependency when ``psycopg`` isn't installed.

The wire schema is identical for both backends: one ``ontology``
table keyed on ``slug`` and one ``preference`` key/value store.
We use only SQL that both backends accept (``CREATE TABLE IF NOT
EXISTS``, ``INSERT … ON CONFLICT(key) DO UPDATE``, ``DELETE …
RETURNING`` is avoided), with placeholder conversion happening at
the cursor wrapper.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

_LOCK = threading.Lock()


# ── URL parsing + backend selection ─────────────────────────────────────────


def _normalize_url(db: str) -> str:
    """Accept either a bare filesystem path (legacy) or a DB-URL.
    Returns a canonical URL string."""
    if "://" in db:
        return db
    return "sqlite:///" + db


def _backend_kind(url: str) -> str:
    scheme = urlparse(url).scheme.lower()
    if scheme.startswith("postgres"):
        return "postgres"
    if scheme.startswith("sqlite") or not scheme:
        return "sqlite"
    raise ValueError(f"Unsupported DB URL scheme: {scheme!r}")


def _sqlite_path(url: str) -> str:
    """Extract a filesystem path from a sqlite URL.  Supports both
    ``sqlite:///relative/path`` and ``sqlite:////abs/path``."""
    parsed = urlparse(url)
    # urlparse drops one leading '/'; rebuild it.
    path = parsed.path
    # sqlite:///rel → parsed.path='/rel' → 'rel'
    # sqlite:////abs → parsed.path='//abs' → '/abs'
    if path.startswith("//"):
        return path[1:]                     # absolute
    return path.lstrip("/")                 # relative


# ── Connection wrapper ──────────────────────────────────────────────────────


class _ConnWrap:
    """Tiny wrapper over a DB-API connection that normalises
    placeholder syntax (``?`` → ``%s``) and dict-row access so the
    rest of the module is backend-agnostic."""

    def __init__(self, conn, kind: str):
        self._c = conn
        self._kind = kind

    def execute(self, sql: str, params: tuple = ()):
        if self._kind == "postgres":
            sql = _qmarks_to_pyformat(sql)
        cur = self._c.cursor()
        cur.execute(sql, params)
        return _CurWrap(cur)

    def executescript(self, sql: str):
        if self._kind == "postgres":
            # psycopg accepts multi-statement DDL via execute.
            self._c.cursor().execute(sql)
        else:
            self._c.executescript(sql)

    def commit(self):
        self._c.commit()

    def close(self):
        self._c.close()

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        # SQLite's "with conn" auto-commits on success and rolls back
        # on exception.  Replicate that for Postgres so the call sites
        # don't have to change.
        if et is None:
            try:
                self._c.commit()
            except Exception:
                pass
        else:
            try:
                self._c.rollback()
            except Exception:
                pass
        self.close()


class _CurWrap:
    """Cursor wrapper exposing ``fetchone() / fetchall()`` that
    return dict-like rows for both backends."""

    def __init__(self, cur):
        self._c = cur

    @property
    def rowcount(self):
        return self._c.rowcount

    def _row_to_dict(self, row):
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        # psycopg returns tuples by default; map via cursor.description.
        cols = [d[0] for d in self._c.description]
        return dict(zip(cols, row))

    def fetchone(self):
        return self._row_to_dict(self._c.fetchone())

    def fetchall(self):
        return [self._row_to_dict(r) for r in self._c.fetchall()]


_PARAM_PAT = re.compile(r"\?")


def _qmarks_to_pyformat(sql: str) -> str:
    """Convert SQLite-style ``?`` placeholders to psycopg's ``%s``."""
    return _PARAM_PAT.sub("%s", sql)


# ── Connect / init ──────────────────────────────────────────────────────────


def _connect(db: str) -> _ConnWrap:
    url = _normalize_url(db)
    kind = _backend_kind(url)
    if kind == "sqlite":
        path = _sqlite_path(url)
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return _ConnWrap(conn, "sqlite")
    if kind == "postgres":
        try:
            import psycopg                                            # noqa: F401
        except ImportError as exc:                                    # pragma: no cover
            raise RuntimeError(
                "Postgres backend requested but psycopg isn't installed. "
                "Run: pip install ontoforge[postgres]"
            ) from exc
        import psycopg                                                # noqa: F811
        conn = psycopg.connect(url)
        return _ConnWrap(conn, "postgres")
    raise ValueError(f"Unsupported backend: {kind}")


_DDL = """
CREATE TABLE IF NOT EXISTS ontology (
  slug        TEXT PRIMARY KEY,
  domain      TEXT NOT NULL,
  product     TEXT NOT NULL,
  label       TEXT NOT NULL,
  session     TEXT NOT NULL,
  generated   TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preference (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def init_db(db: str) -> None:
    with _LOCK, _connect(db) as conn:
        conn.executescript(_DDL)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Slug ────────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(part: str) -> str:
    s = _SLUG_RE.sub("-", (part or "").strip().lower()).strip("-")
    return s[:64]


def make_slug(domain: str, product: str, label: str) -> str:
    parts = [slugify(domain), slugify(product), slugify(label)]
    if not all(parts):
        raise ValueError("domain, product, and label are all required")
    return "__".join(parts)


# ── CRUD ────────────────────────────────────────────────────────────────────


def list_ontologies(db: str) -> list[dict[str, Any]]:
    with _LOCK, _connect(db) as conn:
        rows = conn.execute(
            "SELECT slug, domain, product, label, created_at, updated_at "
            "FROM ontology ORDER BY updated_at DESC"
        ).fetchall()
    return rows


def get_ontology(db: str, slug: str) -> dict[str, Any] | None:
    with _LOCK, _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM ontology WHERE slug = ?", (slug,)
        ).fetchone()
    if not row:
        return None
    row["session"] = json.loads(row["session"])
    row["generated"] = json.loads(row["generated"]) if row["generated"] else {}
    return row


def save_ontology(
    db: str,
    *,
    domain: str,
    product: str,
    label: str,
    session: dict,
    generated: dict | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    slug = make_slug(domain, product, label)
    now = _now()
    payload = json.dumps(session)
    artifacts = json.dumps(generated or {})

    with _LOCK, _connect(db) as conn:
        existing = conn.execute(
            "SELECT slug FROM ontology WHERE slug = ?", (slug,)
        ).fetchone()
        if existing and not overwrite:
            raise FileExistsError(slug)
        if existing:
            conn.execute(
                "UPDATE ontology SET domain=?, product=?, label=?, "
                "session=?, generated=?, updated_at=? WHERE slug=?",
                (domain, product, label, payload, artifacts, now, slug),
            )
        else:
            conn.execute(
                "INSERT INTO ontology (slug, domain, product, label, "
                "session, generated, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, domain, product, label, payload, artifacts, now, now),
            )

    return {"slug": slug, "updated_at": now, "created": not existing}


def reharvest_ontology(db: str, slug: str, output_dir: str) -> dict[str, Any] | None:
    """Re-read current artifacts from output/ and overwrite this row's
    generated blob."""
    fresh = harvest_generated(output_dir)
    now = _now()
    with _LOCK, _connect(db) as conn:
        existing = conn.execute(
            "SELECT slug FROM ontology WHERE slug = ?", (slug,)
        ).fetchone()
        if not existing:
            return None
        conn.execute(
            "UPDATE ontology SET generated = ?, updated_at = ? WHERE slug = ?",
            (json.dumps(fresh), now, slug),
        )
    return {"slug": slug, "updated_at": now, "harvested": sorted(fresh.keys())}


def delete_ontology(db: str, slug: str) -> bool:
    with _LOCK, _connect(db) as conn:
        cur = conn.execute("DELETE FROM ontology WHERE slug = ?", (slug,))
        return cur.rowcount > 0


# ── Preferences ─────────────────────────────────────────────────────────────


def get_preferences(db: str) -> dict[str, Any]:
    with _LOCK, _connect(db) as conn:
        rows = conn.execute("SELECT key, value FROM preference").fetchall()
    out: dict[str, Any] = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            out[r["key"]] = r["value"]
    return out


def set_preferences(db: str, updates: dict[str, Any]) -> dict[str, Any]:
    with _LOCK, _connect(db) as conn:
        for k, v in updates.items():
            conn.execute(
                "INSERT INTO preference (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v)),
            )
    return get_preferences(db)


# ── Artifact harvesting (unchanged) ─────────────────────────────────────────


_DEFAULT_ARTIFACTS = {
    "ttl":        "ontology/enterprise.ttl",
    "shacl":      "shapes/enterprise-shapes.ttl",
    "skos":       "vocab/enterprise-skos.ttl",
    "events":     "ontology/events.ttl",
    "provenance": "ontology/provenance.ttl",
    "jsonld":     "jsonld/enterprise-context.json",
    "materialised":         "ontology/materialised.ttl",
    "materialised_lineage": "ontology/materialised-lineage.ttl",
}


def harvest_generated(output_dir: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, rel in _DEFAULT_ARTIFACTS.items():
        path = os.path.join(output_dir, rel)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    out[key] = f.read()
            except Exception:
                pass
    return out
