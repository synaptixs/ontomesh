"""
graph_publisher.py — Phase 3 · Sprint S13
──────────────────────────────────────────
One-command upload of all Turtle artifacts to a graph store with
named-graph partitioning by sensitivity tier.

Supported stores:
  fuseki    — Apache Jena Fuseki  (SPARQL 1.1 Update + Graph Store Protocol)
  stardog   — Stardog             (SPARQL 1.1 Update)
  oxigraph  — Oxigraph            (SPARQL 1.1 Update)
  neptune   — Amazon Neptune      (SPARQL 1.1 Update, SigV4 signing)
  graphdb   — Ontotext GraphDB    (SPARQL 1.1 Update)

Named-graph partitioning follows sensitivity tiers:
  Public       → <https://ontology.example.com/graph/public>
  Internal     → <https://ontology.example.com/graph/internal>
  Confidential → <https://ontology.example.com/graph/confidential>
  Restricted   → <https://ontology.example.com/graph/restricted>
  (unset)      → <https://ontology.example.com/graph/default>

CLI:
  python3 toolkit.py --phase publish --store fuseki --endpoint http://host:3030/dataset
  python3 toolkit.py --phase publish --store neptune --endpoint https://my-cluster.neptune.amazonaws.com:8182
"""

from __future__ import annotations

import os
import glob
import json
import base64
import hashlib
import hmac
import datetime
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

BASE_IRI = "https://ontology.example.com"

NAMED_GRAPHS = {
    "Public":       f"{BASE_IRI}/graph/public",
    "Internal":     f"{BASE_IRI}/graph/internal",
    "Confidential": f"{BASE_IRI}/graph/confidential",
    "Restricted":   f"{BASE_IRI}/graph/restricted",
    "default":      f"{BASE_IRI}/graph/default",
}

# Map artifact files to sensitivity tiers
ARTIFACT_TIER_MAP = {
    "enterprise.ttl":               "Internal",
    "events.ttl":                   "Internal",
    "provenance.ttl":               "Internal",
    "tmf-sid-hierarchy.ttl":        "Public",
    "alignment.ttl":                "Public",
    "federation-config.ttl":        "Internal",
    "enterprise-shapes.ttl":        "Internal",
    "agent-gate.ttl":               "Internal",
    "conflict-resolution-shapes.ttl": "Internal",
    "enterprise-skos.ttl":          "Public",
}


def _read_turtle(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _sparql_update_insert(turtle: str, graph_iri: str) -> str:
    escaped = turtle.replace("\\", "\\\\").replace("'", "\\'")
    return f"INSERT DATA {{ GRAPH <{graph_iri}> {{ {escaped} }} }}"


def _http_sparql_update(endpoint: str, query: str,
                         auth_header: Optional[str] = None) -> bool:
    data = urllib.parse.urlencode({"update": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False


def _http_graph_store_put(base_endpoint: str, graph_iri: str,
                           turtle: str,
                           auth_header: Optional[str] = None) -> bool:
    """Graph Store Protocol — PUT replaces the named graph."""
    url = f"{base_endpoint}?graph={urllib.parse.quote(graph_iri, safe='')}"
    data = turtle.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"Content-Type": "text/turtle; charset=utf-8"},
    )
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status in (200, 201, 204)
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False


def _basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


# ── Neptune SigV4 signing ───────────────────────────────────────────────────

def _sign_neptune_request(endpoint: str, query: str,
                           region: str, access_key: str,
                           secret_key: str, session_token: str = "") -> dict:
    """AWS SigV4 signing for Neptune SPARQL Update endpoint."""
    now = datetime.datetime.utcnow()
    amz_date  = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    service   = "neptune-db"
    host      = urllib.parse.urlparse(endpoint).hostname or ""
    body      = urllib.parse.urlencode({"update": query})
    body_hash = hashlib.sha256(body.encode()).hexdigest()

    canonical_headers = f"content-type:application/x-www-form-urlencoded\nhost:{host}\nx-amz-date:{amz_date}\n"
    signed_headers    = "content-type;host;x-amz-date"
    if session_token:
        canonical_headers += f"x-amz-security-token:{session_token}\n"
        signed_headers    += ";x-amz-security-token"

    canonical_request = "\n".join([
        "POST",
        "/sparql",
        "",
        canonical_headers,
        signed_headers,
        body_hash,
    ])

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign   = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(
            _sign(
                _sign(f"AWS4{secret_key}".encode(), date_stamp),
                region,
            ),
            service,
        ),
        "aws4_request",
    )
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": auth,
        "x-amz-date": amz_date,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if session_token:
        headers["x-amz-security-token"] = session_token
    return headers


# ── Store adapters ──────────────────────────────────────────────────────────

def _publish_fuseki(endpoint: str, turtle: str, graph_iri: str,
                    user: str = "admin", password: str = "") -> bool:
    """Fuseki: Graph Store Protocol PUT to named graph."""
    data_endpoint = endpoint.rstrip("/") + "/data"
    auth = _basic_auth(user, password) if password else None
    return _http_graph_store_put(data_endpoint, graph_iri, turtle, auth)


def _publish_stardog(endpoint: str, turtle: str, graph_iri: str,
                     user: str = "admin", password: str = "admin") -> bool:
    """Stardog: SPARQL Update INSERT DATA into named graph."""
    update_endpoint = endpoint.rstrip("/") + "/update"
    auth = _basic_auth(user, password)
    query = _sparql_update_insert(turtle, graph_iri)
    return _http_sparql_update(update_endpoint, query, auth)


def _publish_oxigraph(endpoint: str, turtle: str, graph_iri: str) -> bool:
    """Oxigraph: Graph Store Protocol PUT."""
    return _http_graph_store_put(endpoint.rstrip("/"), graph_iri, turtle)


def _publish_neptune(endpoint: str, turtle: str, graph_iri: str,
                     region: str = "us-east-1") -> bool:
    """Neptune: SigV4-signed SPARQL Update."""
    access_key   = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key   = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    session_token = os.environ.get("AWS_SESSION_TOKEN", "")
    if not access_key or not secret_key:
        print("    ⚠  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set — skipping SigV4")
        return False
    sparql_endpoint = endpoint.rstrip("/") + "/sparql"
    query   = _sparql_update_insert(turtle, graph_iri)
    headers = _sign_neptune_request(sparql_endpoint, query, region,
                                     access_key, secret_key, session_token)
    body = urllib.parse.urlencode({"update": query}).encode("utf-8")
    req  = urllib.request.Request(sparql_endpoint, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"    Neptune error: {e}")
        return False


def _publish_graphdb(endpoint: str, turtle: str, graph_iri: str,
                     user: str = "", password: str = "") -> bool:
    """GraphDB: Graph Store Protocol PUT."""
    auth = _basic_auth(user, password) if password else None
    return _http_graph_store_put(endpoint.rstrip("/"), graph_iri, turtle, auth)


# ── Main entry point ────────────────────────────────────────────────────────

STORE_FUNCS = {
    "fuseki":   _publish_fuseki,
    "stardog":  _publish_stardog,
    "oxigraph": _publish_oxigraph,
    "neptune":  _publish_neptune,
    "graphdb":  _publish_graphdb,
}


def run_publish(out_path: str, store: str, endpoint: str,
                user: str = "", password: str = "",
                region: str = "us-east-1",
                dry_run: bool = False) -> dict:
    """
    Upload all Turtle artifacts to the specified graph store.
    Returns a results dict with {file: {"graph": ..., "ok": bool}}.
    """
    if store not in STORE_FUNCS:
        raise ValueError(f"Unknown store '{store}'. Choose from: {list(STORE_FUNCS)}")

    publish_fn = STORE_FUNCS[store]
    results: dict = {}

    # Collect all .ttl artifacts
    artifact_dirs = [
        os.path.join(out_path, "ontology"),
        os.path.join(out_path, "shapes"),
        os.path.join(out_path, "vocab"),
    ]
    ttl_files: list[str] = []
    for d in artifact_dirs:
        ttl_files.extend(sorted(glob.glob(os.path.join(d, "*.ttl"))))

    if not ttl_files:
        print("  ⚠  No Turtle artifacts found in output/. Run the full pipeline first.")
        return results

    print(f"\n  Target store : {store}")
    print(f"  Endpoint     : {endpoint}")
    print(f"  Artifacts    : {len(ttl_files)} Turtle files")
    print(f"  Dry-run      : {dry_run}")
    print()

    # Group by sensitivity tier → named graph
    graph_batches: dict[str, list[tuple[str, str]]] = {}
    for path in ttl_files:
        fname = os.path.basename(path)
        tier  = ARTIFACT_TIER_MAP.get(fname, "default")
        graph = NAMED_GRAPHS[tier]
        graph_batches.setdefault(graph, []).append((fname, path))

    for graph_iri, files in graph_batches.items():
        tier_label = next(
            (t for t, g in NAMED_GRAPHS.items() if g == graph_iri), "default"
        )
        print(f"  Named graph  : <{graph_iri}>  [{tier_label}]")

        for fname, path in files:
            turtle = _read_turtle(path)
            if dry_run:
                size = len(turtle.encode("utf-8"))
                print(f"    [DRY-RUN] {fname:<45}  {size:>7} bytes  → {graph_iri}")
                results[fname] = {"graph": graph_iri, "ok": True, "dry_run": True}
                continue

            # Pass store-specific kwargs
            if store == "fuseki":
                ok = publish_fn(endpoint, turtle, graph_iri, user or "admin", password)
            elif store == "stardog":
                ok = publish_fn(endpoint, turtle, graph_iri, user or "admin", password or "admin")
            elif store == "neptune":
                ok = publish_fn(endpoint, turtle, graph_iri, region)
            elif store == "graphdb":
                ok = publish_fn(endpoint, turtle, graph_iri, user, password)
            else:
                ok = publish_fn(endpoint, turtle, graph_iri)

            icon = "✓" if ok else "✗"
            print(f"    {icon} {fname:<45}  → {graph_iri}  [{store}]")
            results[fname] = {"graph": graph_iri, "ok": ok}

    passed = sum(1 for r in results.values() if r["ok"])
    total  = len(results)
    print(f"\n  Published {passed}/{total} artifacts to {store}")
    return results


def generate_publish_summary(results: dict, out_path: str, store: str, endpoint: str):
    """Write a JSON summary of the publish run to output/reports/."""
    summary = {
        "store": store,
        "endpoint": endpoint,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "artifacts": results,
        "total": len(results),
        "succeeded": sum(1 for r in results.values() if r["ok"]),
    }
    rpt_dir = os.path.join(out_path, "reports")
    os.makedirs(rpt_dir, exist_ok=True)
    path = os.path.join(rpt_dir, "publish_summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  ✓ Publish summary → {path}")
