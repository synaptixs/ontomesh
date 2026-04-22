"""
federation.partner_registry — Workstream 3, Component 1
========================================================
The partner registry is the single source of truth about who the
enterprise is federated with, what they expose, and how far that
relationship has progressed on the trust-bootstrap ladder.

Two back-ends are kept in step:

  * ``federation/partner_registry.json`` — human-readable, committed to
    source control, acts as the "Confidential" named-graph payload.
  * ``federation_partners`` table in ``db/enterprise.db`` — fast
    query path for the SPARQL router and the trust ledger.

Public entry points are consumed by ``toolkit.py --phase federate``,
the browser wizard, and the CI/CD governance gate.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

HERE          = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(HERE, "partner_registry.json")


def _registry_path() -> str:
    """Resolve the active registry path.

    The environment variable ``ONTOLOGY_FED_REGISTRY`` overrides the
    committed default so tests and CI runs never mutate the file that
    sits in source control.
    """
    return os.environ.get("ONTOLOGY_FED_REGISTRY", REGISTRY_PATH)

_ALLOWED_TIERS = {"Public", "Internal", "Confidential", "Restricted"}
_ALLOWED_STATES = {
    "PROPOSED", "HANDSHAKE_SENT", "COUNTERSIGNED",
    "ACTIVE", "EXPIRED", "REVOKED",
}

_DDL_PARTNERS = """
CREATE TABLE IF NOT EXISTS federation_partners (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_id         TEXT NOT NULL UNIQUE,
    partner_iri        TEXT NOT NULL UNIQUE,
    display_name       TEXT NOT NULL,
    sparql_endpoint    TEXT NOT NULL,
    manifest_url       TEXT,
    manifest_jsonld    TEXT,
    manifest_signature TEXT,
    public_key         TEXT NOT NULL,
    exposed_classes    TEXT,
    max_shareable_tier TEXT DEFAULT 'Internal'
                       CHECK(max_shareable_tier IN ('Public','Internal','Confidential','Restricted')),
    trust_state        TEXT DEFAULT 'PROPOSED'
                       CHECK(trust_state IN (
                         'PROPOSED','HANDSHAKE_SENT','COUNTERSIGNED','ACTIVE',
                         'EXPIRED','REVOKED')),
    valid_from         TEXT,
    valid_until        TEXT,
    registered_at      TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_PARTNERS)
    conn.commit()
    return conn


def _load_json_registry() -> Dict[str, Any]:
    path = _registry_path()
    if not os.path.isfile(path):
        return {"version": "1.0.0", "generated_at": _utcnow(), "partners": []}
    with open(path) as f:
        return json.load(f)


def _save_json_registry(data: Dict[str, Any]) -> None:
    data["generated_at"] = _utcnow()
    path = _registry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ─────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────


def register_partner(
    db_path: str,
    *,
    partner_iri: str,
    display_name: str,
    sparql_endpoint: str,
    public_key: str,
    exposed_classes: Optional[List[str]] = None,
    max_shareable_tier: str = "Internal",
    manifest_url: Optional[str] = None,
    manifest_jsonld: Optional[str] = None,
    manifest_signature: Optional[str] = None,
    valid_until: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new federation partner (or update on IRI collision).

    The new partner lands in ``trust_state = PROPOSED``.  A full
    :func:`federation.trust.handshake` transitions it to ACTIVE.
    """
    if max_shareable_tier not in _ALLOWED_TIERS:
        raise ValueError(f"invalid max_shareable_tier: {max_shareable_tier}")

    exposed = list(exposed_classes or [])
    partner_id = str(uuid.uuid4())

    conn = _connect(db_path)
    existing = conn.execute(
        "SELECT partner_id FROM federation_partners WHERE partner_iri = ?",
        (partner_iri,),
    ).fetchone()

    if existing:
        partner_id = existing["partner_id"]
        conn.execute("""
            UPDATE federation_partners
            SET display_name       = ?,
                sparql_endpoint    = ?,
                manifest_url       = ?,
                manifest_jsonld    = ?,
                manifest_signature = ?,
                public_key         = ?,
                exposed_classes    = ?,
                max_shareable_tier = ?,
                valid_until        = ?,
                updated_at         = ?
            WHERE partner_id       = ?
        """, (
            display_name, sparql_endpoint, manifest_url, manifest_jsonld,
            manifest_signature, public_key, json.dumps(exposed),
            max_shareable_tier, valid_until, _utcnow(), partner_id,
        ))
    else:
        conn.execute("""
            INSERT INTO federation_partners
              (partner_id, partner_iri, display_name, sparql_endpoint,
               manifest_url, manifest_jsonld, manifest_signature,
               public_key, exposed_classes, max_shareable_tier,
               trust_state, valid_from, valid_until, registered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?, ?)
        """, (
            partner_id, partner_iri, display_name, sparql_endpoint,
            manifest_url, manifest_jsonld, manifest_signature,
            public_key, json.dumps(exposed), max_shareable_tier,
            _utcnow(), valid_until, _utcnow(), _utcnow(),
        ))
    conn.commit()
    conn.close()

    # Mirror into the JSON registry (kept in source control)
    registry = _load_json_registry()
    partners = [p for p in registry.get("partners", [])
                if p.get("partner_iri") != partner_iri]
    partners.append({
        "partner_id":        partner_id,
        "partner_iri":       partner_iri,
        "display_name":      display_name,
        "sparql_endpoint":   sparql_endpoint,
        "manifest_url":      manifest_url,
        "public_key":        public_key,
        "exposed_classes":   exposed,
        "max_shareable_tier": max_shareable_tier,
        "trust_state":       "PROPOSED",
        "valid_from":        _utcnow(),
        "valid_until":       valid_until,
    })
    registry["partners"] = partners
    _save_json_registry(registry)

    return {
        "ok": True,
        "partner_id": partner_id,
        "partner_iri": partner_iri,
        "trust_state": "PROPOSED",
    }


def list_partners(
    db_path: str,
    *,
    state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return all registered partners (optionally filtered by trust state)."""
    conn = _connect(db_path)
    if state:
        rows = conn.execute(
            "SELECT * FROM federation_partners WHERE trust_state = ? "
            "ORDER BY registered_at DESC",
            (state,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM federation_partners ORDER BY registered_at DESC"
        ).fetchall()
    conn.close()

    out = []
    for r in rows:
        item = dict(r)
        if item.get("exposed_classes"):
            try:
                item["exposed_classes"] = json.loads(item["exposed_classes"])
            except Exception:
                item["exposed_classes"] = []
        out.append(item)
    return out


def get_partner(db_path: str, partner_id_or_iri: str) -> Optional[Dict[str, Any]]:
    """Fetch a partner by partner_id **or** partner_iri."""
    conn = _connect(db_path)
    r = conn.execute(
        "SELECT * FROM federation_partners "
        "WHERE partner_id = ? OR partner_iri = ?",
        (partner_id_or_iri, partner_id_or_iri),
    ).fetchone()
    conn.close()
    if not r:
        return None
    item = dict(r)
    if item.get("exposed_classes"):
        try:
            item["exposed_classes"] = json.loads(item["exposed_classes"])
        except Exception:
            item["exposed_classes"] = []
    return item


def update_trust_state(
    db_path: str,
    partner_id: str,
    new_state: str,
    *,
    manifest_jsonld: Optional[str] = None,
    manifest_signature: Optional[str] = None,
    valid_until: Optional[str] = None,
) -> Dict[str, Any]:
    """Advance a partner on the trust-bootstrap ladder."""
    if new_state not in _ALLOWED_STATES:
        raise ValueError(f"invalid trust_state: {new_state}")
    conn = _connect(db_path)
    conn.execute("""
        UPDATE federation_partners
        SET trust_state        = ?,
            manifest_jsonld    = COALESCE(?, manifest_jsonld),
            manifest_signature = COALESCE(?, manifest_signature),
            valid_until        = COALESCE(?, valid_until),
            updated_at         = ?
        WHERE partner_id       = ?
    """, (
        new_state, manifest_jsonld, manifest_signature,
        valid_until, _utcnow(), partner_id,
    ))
    conn.commit()
    conn.close()

    # Mirror into JSON registry
    registry = _load_json_registry()
    for p in registry.get("partners", []):
        if p.get("partner_id") == partner_id:
            p["trust_state"] = new_state
            if valid_until:
                p["valid_until"] = valid_until
    _save_json_registry(registry)

    return {"ok": True, "partner_id": partner_id, "trust_state": new_state}


def revoke_partner(db_path: str, partner_id: str, note: str = "") -> Dict[str, Any]:
    """Immediately revoke trust with a partner.  All future queries are denied."""
    return update_trust_state(db_path, partner_id, "REVOKED")
