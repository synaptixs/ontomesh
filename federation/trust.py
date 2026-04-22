"""
federation.trust — Workstream 3, Component 5
==============================================
Bilateral trust-bootstrap handshake between two federated enterprises.

Protocol state machine (per partner entry):

  PROPOSED
     │   handshake()  — send signed manifest, record MANIFEST_SENT
     ▼
  HANDSHAKE_SENT
     │   countersign() — counterparty verifies + countersigns
     ▼
  COUNTERSIGNED
     │   activate()    — bilateral agreement persisted; test query runs
     ▼
  ACTIVE       ── expires automatically on valid_until
     │
     ├─► EXPIRED        (time-based)
     └─► REVOKED        (revoke_partner)

All state transitions are append-only rows in ``federation_trust_ledger``;
the :mod:`federation.partner_registry` ``trust_state`` column is the
canonical current state.

No network I/O is performed by these helpers — integrations in
``toolkit.py --phase federate --handshake`` drive HTTP transport.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import _crypto, manifest as _manifest, partner_registry


HERE = os.path.dirname(os.path.abspath(__file__))


_DDL_LEDGER = """
CREATE TABLE IF NOT EXISTS federation_trust_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id           TEXT NOT NULL UNIQUE,
    partner_id         TEXT,
    event_type         TEXT NOT NULL
                       CHECK(event_type IN (
                         'MANIFEST_SENT','MANIFEST_RECEIVED','COUNTERSIGNED',
                         'ACTIVATED','TEST_QUERY','REVOKED','EXPIRED')),
    payload_hash       TEXT,
    signature          TEXT,
    note               TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_LEDGER)
    conn.commit()
    return conn


def _ledger_append(
    db_path: str,
    *,
    partner_id: Optional[str],
    event_type: str,
    payload_hash: Optional[str] = None,
    signature: Optional[str] = None,
    note: str = "",
) -> str:
    conn = _connect(db_path)
    event_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO federation_trust_ledger
          (event_id, partner_id, event_type, payload_hash,
           signature, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, partner_id, event_type, payload_hash,
          signature, note, _utcnow()))
    conn.commit()
    conn.close()
    return event_id


# ─────────────────────────────────────────────────────────────────────
# Protocol entry points
# ─────────────────────────────────────────────────────────────────────


def handshake(
    db_path: str,
    *,
    partner_iri: str,
    local_manifest: Dict[str, Any],
    secret_key_b64: str,
) -> Dict[str, Any]:
    """Step 1 — sign the local manifest and mark the partner HANDSHAKE_SENT.

    Returns the signed manifest ready to be POSTed to the partner's
    handshake endpoint.  Transport is the caller's responsibility.
    """
    partner = partner_registry.get_partner(db_path, partner_iri)
    if not partner:
        return {"ok": False, "reason": f"unknown partner {partner_iri}"}

    signed = _manifest.sign_manifest(local_manifest, secret_key_b64=secret_key_b64)
    payload = json.dumps(signed, sort_keys=True).encode("utf-8")
    payload_hash = hashlib.sha256(payload).hexdigest()

    partner_registry.update_trust_state(
        db_path, partner["partner_id"], "HANDSHAKE_SENT",
    )
    _ledger_append(
        db_path,
        partner_id=partner["partner_id"],
        event_type="MANIFEST_SENT",
        payload_hash=payload_hash,
        signature=signed.get("fed:signature"),
        note="Local manifest sent to partner for countersignature.",
    )
    return {"ok": True, "signed_manifest": signed,
            "partner_id": partner["partner_id"]}


def countersign(
    db_path: str,
    *,
    partner_iri: str,
    remote_manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Step 2 — verify a remote manifest and mark the partner COUNTERSIGNED.

    Called when the partner returns their signed manifest alongside the
    countersignature of ours.  Verification is pure Ed25519 — no
    external PKI.
    """
    partner = partner_registry.get_partner(db_path, partner_iri)
    if not partner:
        return {"ok": False, "reason": f"unknown partner {partner_iri}"}

    check = _manifest.verify_manifest(remote_manifest)
    if not check.get("ok"):
        _ledger_append(
            db_path,
            partner_id=partner["partner_id"],
            event_type="MANIFEST_RECEIVED",
            note=f"verification failed: {check.get('reason')}",
        )
        return {"ok": False, "reason": check.get("reason")}

    signature = remote_manifest.get("fed:signature")
    payload_hash = remote_manifest.get("fed:payloadSha256")

    partner_registry.update_trust_state(
        db_path, partner["partner_id"], "COUNTERSIGNED",
        manifest_jsonld=json.dumps(remote_manifest),
        manifest_signature=signature,
        valid_until=remote_manifest.get("fed:validUntil"),
    )
    _ledger_append(
        db_path,
        partner_id=partner["partner_id"],
        event_type="COUNTERSIGNED",
        payload_hash=payload_hash,
        signature=signature,
        note="Remote manifest verified + countersigned.",
    )
    return {"ok": True, "partner_id": partner["partner_id"],
            "expires": remote_manifest.get("fed:validUntil")}


def activate(
    db_path: str,
    *,
    partner_iri: str,
    test_query_passed: bool = True,
    note: str = "",
) -> Dict[str, Any]:
    """Step 3 — promote COUNTERSIGNED → ACTIVE after the test-query probe."""
    partner = partner_registry.get_partner(db_path, partner_iri)
    if not partner:
        return {"ok": False, "reason": f"unknown partner {partner_iri}"}
    if partner.get("trust_state") not in ("COUNTERSIGNED", "ACTIVE"):
        return {"ok": False, "reason": f"cannot activate from {partner.get('trust_state')}"}
    if not test_query_passed:
        return {"ok": False, "reason": "test query on Public-tier class failed"}

    partner_registry.update_trust_state(
        db_path, partner["partner_id"], "ACTIVE",
    )
    _ledger_append(
        db_path,
        partner_id=partner["partner_id"],
        event_type="ACTIVATED",
        note=note or "Test query on Public-tier class succeeded.",
    )
    return {"ok": True, "partner_id": partner["partner_id"],
            "trust_state": "ACTIVE"}


def run_test_query(
    db_path: str,
    *,
    partner_iri: str,
    test_class: Optional[str] = None,
) -> Dict[str, Any]:
    """Step 3a — synthesise a minimal Public-tier SPARQL probe.

    A real deployment dispatches this to the partner endpoint; we return
    the rendered query so the caller can send it over whatever transport
    they prefer.
    """
    partner = partner_registry.get_partner(db_path, partner_iri)
    if not partner:
        return {"ok": False, "reason": f"unknown partner {partner_iri}"}

    classes = partner.get("exposed_classes") or []
    target = test_class or (classes[0] if classes else None)
    if not target:
        return {"ok": False, "reason": "no exposed classes to probe"}

    query = (
        "PREFIX fed: <https://ontology.example.com/federation/>\n"
        f"SELECT ?s WHERE {{\n"
        f"  SERVICE <{partner['sparql_endpoint']}> {{\n"
        f"    ?s a <{target}> ; fed:sensitivityTier \"Public\" .\n"
        "  }\n"
        "} LIMIT 1"
    )
    _ledger_append(
        db_path,
        partner_id=partner["partner_id"],
        event_type="TEST_QUERY",
        note=f"Rendered probe against {target}.",
    )
    return {"ok": True, "probe_query": query,
            "partner_id": partner["partner_id"]}


def expire_overdue(db_path: str) -> int:
    """Mark every ACTIVE partner whose ``valid_until`` has passed as EXPIRED."""
    expired = 0
    now = _utcnow()
    for p in partner_registry.list_partners(db_path, state="ACTIVE"):
        vu = p.get("valid_until")
        if vu and vu < now:
            partner_registry.update_trust_state(
                db_path, p["partner_id"], "EXPIRED",
            )
            _ledger_append(
                db_path, partner_id=p["partner_id"],
                event_type="EXPIRED", note="valid_until elapsed",
            )
            expired += 1
    return expired


def ledger_history(
    db_path: str,
    *,
    partner_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    conn = _connect(db_path)
    if partner_id:
        rows = conn.execute(
            "SELECT * FROM federation_trust_ledger "
            "WHERE partner_id = ? ORDER BY created_at DESC LIMIT ?",
            (partner_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM federation_trust_ledger "
            "ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
