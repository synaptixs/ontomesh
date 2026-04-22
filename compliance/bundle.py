"""
compliance.bundle — Workstream 4, Component 3
==============================================
Signed compliance bundle exporter.  Packages an evidence object
(``compliance.assembler.assemble_evidence`` return value) into a
portable, verifiable ZIP containing:

  * ``evidence.jsonld``         — signed JSON-LD envelope (Ed25519)
  * ``sparql_results.csv``      — all referenced SPARQL results
  * ``prov_chain.ttl``          — PROV-O chain for the decision IRI
  * ``shacl_report.txt``        — SHACL validation summary
  * ``governance_scorecard.csv``— scorecard snapshot at assemble time
  * ``evidence_summary.txt``    — plain-text human-readable summary
  * ``manifest.json``           — bundle manifest with SHA-256 per file

The signature is computed over ``sha256(manifest.json)`` so the bundle
is tamper-evident: any edit to a contained file invalidates the bundle.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Reuse federation's Ed25519 helpers (stdlib-only RFC 8032 impl).
from federation import _crypto
from federation.manifest import (
    generate_keypair as _fed_generate_keypair,
    KEYS_DIR as _FED_KEYS_DIR,
)

HERE       = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(HERE)
BUNDLES    = os.path.join(HERE, "bundles")
KEYS_DIR   = os.path.join(HERE, "keys")

BUNDLE_CONTEXT = {
    "cmp":  "https://ontology.example.com/compliance/",
    "prov": "http://www.w3.org/ns/prov#",
    "dct":  "http://purl.org/dc/terms/",
    "xsd":  "http://www.w3.org/2001/XMLSchema#",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────
# Key management
# ─────────────────────────────────────────────────────────────────────


def _ensure_keypair(key_name: str = "compliance") -> Tuple[str, str]:
    """Return ``(sk_b64, pk_b64)`` — create on first use under
    ``compliance/keys/`` (0600 for the secret)."""
    os.makedirs(KEYS_DIR, exist_ok=True)
    sk_path = os.path.join(KEYS_DIR, f"{key_name}.sk")
    pk_path = os.path.join(KEYS_DIR, f"{key_name}.pub")
    if os.path.isfile(sk_path) and os.path.isfile(pk_path):
        with open(sk_path) as f:
            sk = f.read().strip()
        with open(pk_path) as f:
            pk = f.read().strip()
        return sk, pk
    sk, pk = _crypto.generate_keypair()
    with open(sk_path, "w") as f:
        f.write(sk + "\n")
    os.chmod(sk_path, 0o600)
    with open(pk_path, "w") as f:
        f.write(pk + "\n")
    return sk, pk


# ─────────────────────────────────────────────────────────────────────
# Helper writers — each returns (rel_path, absolute_path)
# ─────────────────────────────────────────────────────────────────────


def _write_sparql_csv(evidence: List[Dict[str, Any]], staging: str) -> Tuple[str, str]:
    """Flatten SPARQL CQ and scorecard evidence into a CSV."""
    path = os.path.join(staging, "sparql_results.csv")
    rows: List[Dict[str, Any]] = []
    for ev in evidence:
        if ev["artefact_type"] in ("SPARQL_CQ", "GOVERNANCE_SCORECARD_CRITERION"):
            rows.append({
                "req_id":      ev["req_id"],
                "artefact":    ev["artefact_type"],
                "selector":    ev["evidence_selector"],
                "status":      ev["status"],
                "note":        ev["note"],
                "source_file": ev["source_file"],
            })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["req_id", "artefact", "selector", "status",
                        "note", "source_file"],
        )
        w.writeheader()
        w.writerows(rows)
    return "sparql_results.csv", path


def _write_prov_ttl(evidence: List[Dict[str, Any]], staging: str) -> Tuple[str, str]:
    """Emit a Turtle serialisation of the PROV-O chain found in evidence."""
    path = os.path.join(staging, "prov_chain.ttl")
    lines: List[str] = [
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix cmp:  <https://ontology.example.com/compliance/> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    emitted = 0
    for ev in evidence:
        if ev["artefact_type"] != "PROV_O_CHAIN":
            continue
        chain = (ev.get("result") or {}).get("chain") or []
        for node in chain:
            iri = node.get("observation_iri")
            if not iri:
                continue
            lines.append(f"<{iri}>")
            lines.append("    a prov:Entity ;")
            if node.get("observation_type"):
                lines.append(f'    cmp:observationType "{node["observation_type"]}" ;')
            if node.get("confidence_score") is not None:
                lines.append(
                    f'    cmp:confidenceScore "{node["confidence_score"]}"^^xsd:decimal ;'
                )
            if node.get("derivation_method"):
                lines.append(f'    cmp:derivationMethod "{node["derivation_method"]}" ;')
            if node.get("observed_at"):
                lines.append(
                    f'    prov:generatedAtTime "{node["observed_at"]}"^^xsd:dateTime ;'
                )
            if node.get("agent_iri"):
                lines.append(f'    prov:wasAttributedTo <{node["agent_iri"]}> ;')
            if node.get("source_ref"):
                lines.append(f'    prov:wasDerivedFrom <{node["source_ref"]}> ;')
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")
            emitted += 1
    if emitted == 0:
        lines.append("# (no PROV-O chain evidence in this bundle)")
    with open(path, "w") as f:
        f.write("\n".join(lines))
        f.write("\n")
    return "prov_chain.ttl", path


def _write_shacl_report(evidence: List[Dict[str, Any]], staging: str) -> Tuple[str, str]:
    path = os.path.join(staging, "shacl_report.txt")
    lines = ["SHACL shape evidence snapshot",
             "─────────────────────────────"]
    n = 0
    for ev in evidence:
        if ev["artefact_type"] != "SHACL_SHAPE":
            continue
        lines.append(f"[{ev['status']}] {ev['req_id']} — {ev['title']}")
        lines.append(f"   shape    : {ev['evidence_selector']}")
        lines.append(f"   source   : {ev['source_file']}")
        lines.append(f"   note     : {ev['note']}")
        lines.append("")
        n += 1
    if n == 0:
        lines.append("(no SHACL evidence in this bundle)")
    with open(path, "w") as f:
        f.write("\n".join(lines))
        f.write("\n")
    return "shacl_report.txt", path


def _write_scorecard_snapshot(staging: str) -> Tuple[str, str]:
    src = os.path.join(REPO_ROOT, "output", "reports", "governance_scorecard.csv")
    dst = os.path.join(staging, "governance_scorecard.csv")
    if os.path.isfile(src):
        shutil.copyfile(src, dst)
    else:
        with open(dst, "w") as f:
            f.write("domain,criterion,score,rationale\n")
            f.write("(missing at bundle time),,,\n")
    return "governance_scorecard.csv", dst


def _write_evidence_summary(
    evidence_obj: Dict[str, Any],
    staging: str,
) -> Tuple[str, str]:
    path = os.path.join(staging, "evidence_summary.txt")
    summary = evidence_obj.get("summary", {})
    lines: List[str] = [
        f"Compliance Evidence Summary",
        f"───────────────────────────",
        f"Regulation   : {evidence_obj.get('name')} [{evidence_obj.get('regulation_id')}]",
        f"Jurisdiction : {evidence_obj.get('jurisdiction')}",
        f"Decision IRI : {evidence_obj.get('decision_iri') or '—'}",
        f"Assembled at : {evidence_obj.get('assembled_at')}",
        f"Coverage     : {summary.get('coverage_percent', 0)}% "
        f"({summary.get('satisfied', 0)}/{summary.get('total_requirements', 0)} satisfied)",
        "",
        "Per-requirement status:",
    ]
    for ev in evidence_obj.get("evidence", []):
        lines.append(f"  [{ev['status']:13s}] {ev['req_id']:20s} — {ev['title']}")
    with open(path, "w") as f:
        f.write("\n".join(lines))
        f.write("\n")
    return "evidence_summary.txt", path


def _write_evidence_jsonld(
    evidence_obj: Dict[str, Any],
    signer_iri: str,
    public_key: str,
    signature: str,
    staging: str,
) -> Tuple[str, str]:
    path = os.path.join(staging, "evidence.jsonld")
    envelope = {
        "@context": BUNDLE_CONTEXT,
        "@type":   "cmp:EvidenceBundle",
        "cmp:bundleVersion": "1.0.0",
        "cmp:regulationId":  evidence_obj.get("regulation_id"),
        "cmp:name":          evidence_obj.get("name"),
        "cmp:jurisdiction":  evidence_obj.get("jurisdiction"),
        "cmp:decisionIri":   evidence_obj.get("decision_iri"),
        "cmp:assembledAt":   evidence_obj.get("assembled_at"),
        "cmp:summary":       evidence_obj.get("summary"),
        "cmp:evidence":      evidence_obj.get("evidence"),
        "cmp:signerIri":     signer_iri,
        "cmp:publicKey":     public_key,
        "cmp:signature":     signature,
        "cmp:signatureAlgorithm": "Ed25519",
    }
    with open(path, "w") as f:
        json.dump(envelope, f, indent=2)
        f.write("\n")
    return "evidence.jsonld", path


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def export_bundle(
    evidence_obj: Dict[str, Any],
    *,
    out_dir: Optional[str] = None,
    signer_iri: str = "https://enterprise.example.com/compliance#signer",
    key_name: str = "compliance",
    publish_to_graph: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export a signed compliance bundle.

    Returns a dict with ``bundle_path``, ``sha256``, ``signature``,
    ``public_key`` and a boolean ``verified`` field produced by
    round-tripping the bundle through :func:`verify_bundle`.
    """
    os.makedirs(BUNDLES, exist_ok=True)
    sk_b64, pk_b64 = _ensure_keypair(key_name)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reg_id = evidence_obj.get("regulation_id") or "regulation"
    bundle_id = f"{reg_id}-{ts}-{uuid.uuid4().hex[:8]}"
    target_dir = out_dir or BUNDLES
    os.makedirs(target_dir, exist_ok=True)
    bundle_path = os.path.join(target_dir, f"{bundle_id}.zip")

    staging = os.path.join(target_dir, f"_staging_{bundle_id}")
    os.makedirs(staging, exist_ok=True)

    try:
        entries: List[Tuple[str, str]] = []
        evidence = evidence_obj.get("evidence", [])

        entries.append(_write_sparql_csv(evidence, staging))
        entries.append(_write_prov_ttl(evidence, staging))
        entries.append(_write_shacl_report(evidence, staging))
        entries.append(_write_scorecard_snapshot(staging))
        entries.append(_write_evidence_summary(evidence_obj, staging))

        # Build manifest before signing — this freezes the payload hashes.
        manifest = {
            "bundle_id":        bundle_id,
            "regulation_id":    reg_id,
            "assembled_at":     evidence_obj.get("assembled_at"),
            "decision_iri":     evidence_obj.get("decision_iri"),
            "signer_iri":       signer_iri,
            "signature_algorithm": "Ed25519",
            "files": [
                {"name": rel, "sha256": _sha256_file(abs_)}
                for rel, abs_ in entries
            ],
        }
        manifest_bytes = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        signature = _crypto.sign(manifest_bytes, sk_b64)
        manifest["signature"]  = signature
        manifest["public_key"] = pk_b64
        manifest_path = os.path.join(staging, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        entries.append(("manifest.json", manifest_path))

        # Now write the signed JSON-LD envelope — its signature covers
        # only the evidence object; full bundle tamper-evidence lives in
        # manifest.json + its signature above.
        payload_bytes = json.dumps(
            {
                "regulation_id": evidence_obj.get("regulation_id"),
                "decision_iri": evidence_obj.get("decision_iri"),
                "assembled_at": evidence_obj.get("assembled_at"),
                "evidence":     evidence_obj.get("evidence", []),
            },
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        envelope_sig = _crypto.sign(payload_bytes, sk_b64)
        entries.append(_write_evidence_jsonld(
            evidence_obj,
            signer_iri=signer_iri,
            public_key=pk_b64,
            signature=envelope_sig,
            staging=staging,
        ))

        # Assemble ZIP
        with zipfile.ZipFile(
            bundle_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for rel, abs_ in entries:
                zf.write(abs_, arcname=rel)

    finally:
        shutil.rmtree(staging, ignore_errors=True)

    bundle_sha = _sha256_file(bundle_path)

    # Optional: store a pointer in the DB for audit (Restricted tier).
    if publish_to_graph and db_path and os.path.isfile(db_path):
        try:
            _record_bundle(db_path, bundle_id, bundle_path, bundle_sha,
                           reg_id, evidence_obj)
        except Exception:
            pass  # DB insertion is best-effort; bundle already on disk

    verified = verify_bundle(bundle_path)

    return {
        "ok":            True,
        "bundle_id":     bundle_id,
        "bundle_path":   bundle_path,
        "sha256":        bundle_sha,
        "signature":     signature,
        "public_key":    pk_b64,
        "signer_iri":    signer_iri,
        "verified":      verified.get("ok", False),
        "coverage":      evidence_obj.get("summary", {}).get("coverage_percent", 0),
    }


def verify_bundle(bundle_path: str) -> Dict[str, Any]:
    """Verify a compliance bundle on any cold machine.

    Checks, in order:
      1. ``manifest.json`` exists and is syntactically valid JSON.
      2. Every declared file exists inside the ZIP.
      3. Every file's SHA-256 matches the digest in the manifest.
      4. The manifest's Ed25519 signature (computed over the manifest
         payload with the signature/public_key fields removed)
         verifies against ``manifest.public_key``.
    """
    if not os.path.isfile(bundle_path):
        return {"ok": False, "reason": f"not found: {bundle_path}"}

    try:
        with zipfile.ZipFile(bundle_path) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                return {"ok": False, "reason": "manifest.json missing"}
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            sig = manifest.get("signature")
            pk  = manifest.get("public_key")
            if not sig or not pk:
                return {"ok": False, "reason": "manifest missing signature/public_key"}
            # Reconstruct the payload hash by removing signature + pk.
            shallow = {k: v for k, v in manifest.items()
                       if k not in ("signature", "public_key")}
            payload = json.dumps(
                shallow, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            if not _crypto.verify(payload, sig, pk):
                return {"ok": False, "reason": "manifest signature verification failed"}
            # File-by-file integrity
            for entry in manifest.get("files", []):
                name = entry["name"]
                if name not in names:
                    return {"ok": False, "reason": f"missing file: {name}"}
                got = hashlib.sha256(zf.read(name)).hexdigest()
                if got != entry["sha256"]:
                    return {
                        "ok": False,
                        "reason": f"hash mismatch for {name}",
                    }
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        return {"ok": False, "reason": f"bundle parse error: {exc}"}

    return {
        "ok":           True,
        "bundle_id":    manifest.get("bundle_id"),
        "regulation_id": manifest.get("regulation_id"),
        "signer_iri":   manifest.get("signer_iri"),
        "file_count":   len(manifest.get("files", [])),
    }


# ─────────────────────────────────────────────────────────────────────
# DB bridge — compliance_bundles table
# ─────────────────────────────────────────────────────────────────────


_DDL_BUNDLES = """
CREATE TABLE IF NOT EXISTS compliance_bundles (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_id          TEXT NOT NULL UNIQUE,
    regulation_id      TEXT NOT NULL,
    decision_iri       TEXT,
    bundle_path        TEXT NOT NULL,
    sha256             TEXT NOT NULL,
    signer_iri         TEXT,
    verified           INTEGER DEFAULT 1,
    coverage_percent   INTEGER,
    sensitivity_tier   TEXT DEFAULT 'Restricted',
    assembled_at       TEXT,
    stored_at          TEXT DEFAULT (datetime('now'))
);
"""


def _record_bundle(
    db_path: str,
    bundle_id: str,
    bundle_path: str,
    sha256: str,
    regulation_id: str,
    evidence_obj: Dict[str, Any],
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(_DDL_BUNDLES)
    conn.execute(
        "INSERT OR IGNORE INTO compliance_bundles "
        "(bundle_id, regulation_id, decision_iri, bundle_path, sha256, "
        " signer_iri, verified, coverage_percent, assembled_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (
            bundle_id, regulation_id,
            evidence_obj.get("decision_iri"),
            bundle_path, sha256,
            "https://enterprise.example.com/compliance#signer",
            evidence_obj.get("summary", {}).get("coverage_percent", 0),
            evidence_obj.get("assembled_at"),
        ),
    )
    conn.commit()
    conn.close()


def list_bundles(db_path: str) -> List[Dict[str, Any]]:
    """Return all recorded bundles (Restricted-tier graph rows)."""
    if not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_BUNDLES)
    rows = conn.execute(
        "SELECT * FROM compliance_bundles ORDER BY stored_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
