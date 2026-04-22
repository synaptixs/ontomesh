"""
federation.manifest — Workstream 3, Component 2
==================================================
Build, sign, and verify cross-enterprise capability manifests.

A *capability manifest* is the cryptographically signed JSON-LD
document a federated partner publishes at a well-known URI.  It
declares:

  * ``ontologyIri``          — the IRI of the ontology being exposed
  * ``exposedClasses``       — list of OWL class IRIs the partner serves
  * ``exposedProperties``    — whitelist of object/data properties
  * ``sensitivityByClass``   — per-class sensitivity tier
  * ``inboundShapes``        — SHACL shapes inbound queries must satisfy
  * ``validFrom`` / ``validUntil``  — manifest validity window
  * ``signerIri`` / ``publicKey``   — signing identity
  * ``signature``            — Ed25519 signature (b64) over a canonical digest

Verification is purely offline — no external PKI, no certificate
authority.  The public key is exchanged out-of-band during the trust
bootstrap handshake (:mod:`federation.trust`).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import _crypto

HERE          = os.path.dirname(os.path.abspath(__file__))
KEYS_DIR      = os.path.join(HERE, "keys")
MANIFESTS_DIR = os.path.join(HERE, "manifests")

MANIFEST_CONTEXT = {
    "fed":   "https://ontology.example.com/federation/",
    "owl":   "http://www.w3.org/2002/07/owl#",
    "rdfs":  "http://www.w3.org/2000/01/rdf-schema#",
    "sh":    "http://www.w3.org/ns/shacl#",
    "prov":  "http://www.w3.org/ns/prov#",
    "xsd":   "http://www.w3.org/2001/XMLSchema#",
    "dct":   "http://purl.org/dc/terms/",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─────────────────────────────────────────────────────────────────────
# Key generation
# ─────────────────────────────────────────────────────────────────────


def generate_keypair(
    *,
    key_name: str = "enterprise",
    keys_dir: str = KEYS_DIR,
) -> Dict[str, str]:
    """Generate an Ed25519 keypair and persist it under ``keys_dir``.

    The secret key is written mode 0600.  The public key is returned
    inline and also written as ``<key_name>.pub`` so partners can pull
    it out of band.
    """
    os.makedirs(keys_dir, exist_ok=True)
    sk_b64, pk_b64 = _crypto.generate_keypair()
    sk_path = os.path.join(keys_dir, f"{key_name}.sk")
    pk_path = os.path.join(keys_dir, f"{key_name}.pub")
    with open(sk_path, "w") as f:
        f.write(sk_b64 + "\n")
    os.chmod(sk_path, 0o600)
    with open(pk_path, "w") as f:
        f.write(pk_b64 + "\n")
    return {
        "ok":      True,
        "key_name": key_name,
        "sk_path":  sk_path,
        "pk_path":  pk_path,
        "public_key": pk_b64,
    }


def load_secret_key(key_name: str = "enterprise",
                    keys_dir: str = KEYS_DIR) -> Optional[str]:
    sk_path = os.path.join(keys_dir, f"{key_name}.sk")
    if not os.path.isfile(sk_path):
        return None
    with open(sk_path) as f:
        return f.read().strip()


def load_public_key(key_name: str = "enterprise",
                    keys_dir: str = KEYS_DIR) -> Optional[str]:
    pk_path = os.path.join(keys_dir, f"{key_name}.pub")
    if not os.path.isfile(pk_path):
        return None
    with open(pk_path) as f:
        return f.read().strip()


# ─────────────────────────────────────────────────────────────────────
# Manifest build + sign
# ─────────────────────────────────────────────────────────────────────


def build_manifest(
    *,
    enterprise_iri: str,
    ontology_iri: str,
    exposed_classes: List[str],
    exposed_properties: Optional[List[str]] = None,
    sensitivity_by_class: Optional[Dict[str, str]] = None,
    inbound_shapes: Optional[List[str]] = None,
    signer_iri: Optional[str] = None,
    public_key: Optional[str] = None,
    validity_days: int = 180,
) -> Dict[str, Any]:
    """Compose an unsigned capability manifest.

    ``signer_iri`` and ``public_key`` are embedded so the verifier can
    check the bundled signature without any side-channel lookup.
    """
    now = _utcnow()
    valid_until = now + timedelta(days=validity_days)
    manifest: Dict[str, Any] = {
        "@context": MANIFEST_CONTEXT,
        "@id":    enterprise_iri,
        "@type":  "fed:CapabilityManifest",
        "fed:manifestVersion":    "1.0.0",
        "fed:ontologyIri":        ontology_iri,
        "fed:exposedClasses":     list(exposed_classes),
        "fed:exposedProperties":  list(exposed_properties or []),
        "fed:sensitivityByClass": dict(sensitivity_by_class or {}),
        "fed:inboundShapes":      list(inbound_shapes or []),
        "fed:signerIri":          signer_iri or enterprise_iri,
        "fed:publicKey":          public_key or "",
        "dct:issued":             _iso(now),
        "fed:validFrom":          _iso(now),
        "fed:validUntil":         _iso(valid_until),
        "fed:signatureAlgorithm": "Ed25519",
    }
    return manifest


_SIGN_EXCLUDE = frozenset({"fed:signature", "fed:payloadSha256"})


def _canonical_bytes(manifest: Dict[str, Any]) -> bytes:
    """Deterministic digest payload.  Excludes any pre-existing signature
    and the derived payload hash so verify(sign(m)) = True for all ``m``."""
    shallow = {k: v for k, v in manifest.items() if k not in _SIGN_EXCLUDE}
    return json.dumps(shallow, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(
    manifest: Dict[str, Any],
    *,
    secret_key_b64: str,
) -> Dict[str, Any]:
    """Return a copy of ``manifest`` with ``fed:signature`` attached."""
    payload = _canonical_bytes(manifest)
    sig = _crypto.sign(payload, secret_key_b64)
    signed = dict(manifest)
    signed["fed:signature"] = sig
    signed["fed:payloadSha256"] = hashlib.sha256(payload).hexdigest()
    return signed


def verify_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Verify the Ed25519 signature of a capability manifest.

    Returns ``{'ok': True}`` on success; otherwise ``{'ok': False,
    'reason': <string>}``.
    """
    sig = manifest.get("fed:signature")
    pk  = manifest.get("fed:publicKey")
    if not sig or not pk:
        return {"ok": False, "reason": "missing signature or public key"}
    try:
        valid_until = manifest.get("fed:validUntil")
        if valid_until:
            dt = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if dt < _utcnow():
                return {"ok": False, "reason": "manifest expired"}
    except Exception:
        return {"ok": False, "reason": "invalid validUntil"}

    payload = _canonical_bytes(manifest)
    if not _crypto.verify(payload, sig, pk):
        return {"ok": False, "reason": "signature verification failed"}
    return {
        "ok": True,
        "signer": manifest.get("fed:signerIri"),
        "expires": valid_until,
    }


def write_manifest(
    manifest: Dict[str, Any],
    *,
    out_dir: str = MANIFESTS_DIR,
    filename: Optional[str] = None,
) -> str:
    """Persist a signed manifest under ``federation/manifests/`` by default."""
    os.makedirs(out_dir, exist_ok=True)
    name = filename or f"{manifest.get('@id', 'manifest').rstrip('/').split('/')[-1] or 'manifest'}.jsonld"
    path = os.path.join(out_dir, name)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return path


def load_manifest(path: str) -> Dict[str, Any]:
    with open(path) as f:
        return json.load(f)
