"""
wizard/ontologies_store.py
──────────────────────────
SQLite-backed library of saved ontologies.

A saved ontology is identified by a unique slug built from
(domain, product, label). Each row holds the wizard session JSON
plus the generated artifacts (TTL / SHACL / SKOS) inlined as text,
so the Ontology Viewer can render them with a single read.

Schema lives in db/ontologies.db (auto-created on first use). The
file is per-user state and should not be committed.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

_LOCK = threading.Lock()


# ── Path / connection ───────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str) -> None:
    with _LOCK, _connect(db_path) as conn:
        conn.executescript(
            """
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
        )


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

def list_ontologies(db_path: str) -> list[dict[str, Any]]:
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT slug, domain, product, label, created_at, updated_at "
            "FROM ontology ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_ontology(db_path: str, slug: str) -> dict[str, Any] | None:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM ontology WHERE slug = ?", (slug,)
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["session"] = json.loads(out["session"])
    out["generated"] = json.loads(out["generated"]) if out["generated"] else {}
    return out


def save_ontology(
    db_path: str,
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

    with _LOCK, _connect(db_path) as conn:
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
        conn.commit()

    return {"slug": slug, "updated_at": now, "created": not existing}


def reharvest_ontology(db_path: str, slug: str, output_dir: str) -> dict[str, Any] | None:
    """Re-read current artifacts from output/ and overwrite this row's
    generated blob. Useful when the row was saved before new artifact
    types (e.g. JSON-LD) were added to the harvest list."""
    fresh = harvest_generated(output_dir)
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT slug FROM ontology WHERE slug = ?", (slug,)
        ).fetchone()
        if not existing:
            return None
        conn.execute(
            "UPDATE ontology SET generated = ?, updated_at = ? WHERE slug = ?",
            (json.dumps(fresh), now, slug),
        )
        conn.commit()
    return {"slug": slug, "updated_at": now, "harvested": sorted(fresh.keys())}


def delete_ontology(db_path: str, slug: str) -> bool:
    with _LOCK, _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM ontology WHERE slug = ?", (slug,))
        conn.commit()
        return cur.rowcount > 0


# ── Preferences ─────────────────────────────────────────────────────────────

def get_preferences(db_path: str) -> dict[str, Any]:
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM preference").fetchall()
    out: dict[str, Any] = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            out[r["key"]] = r["value"]
    return out


def set_preferences(db_path: str, updates: dict[str, Any]) -> dict[str, Any]:
    with _LOCK, _connect(db_path) as conn:
        for k, v in updates.items():
            conn.execute(
                "INSERT INTO preference (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v)),
            )
        conn.commit()
    return get_preferences(db_path)


# ── Artifact harvesting ─────────────────────────────────────────────────────

# Map of viewer-tab key → relative path under output/. The wizard's
# default pipeline writes these names; missing files are simply omitted
# from the saved bundle.
_DEFAULT_ARTIFACTS = {
    "ttl":        "ontology/enterprise.ttl",
    "shacl":      "shapes/enterprise-shapes.ttl",
    "skos":       "vocab/enterprise-skos.ttl",
    "events":     "ontology/events.ttl",
    "provenance": "ontology/provenance.ttl",
    "jsonld":     "jsonld/enterprise-context.json",
    # Phase D — materialised graph + per-triple lineage.
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
