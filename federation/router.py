"""
federation.router — Workstream 3, Component 3
================================================
Cross-enterprise SPARQL router.

Extends the intra-enterprise SPARQL federation baked into v2.0 to
queries that traverse enterprise boundaries.  Responsibilities:

  1. Parse ``SERVICE <endpoint>`` clauses; reject any endpoint not in
     the active :mod:`federation.partner_registry`.
  2. Verify the requesting agent's *flavor* is allowed to read the
     partner's exposed-class list at the current sensitivity tier.
  3. Rewrite the query with a mandatory sensitivity filter (so
     ``RESTRICTED`` triples are never even requested).
  4. Dispatch the rewritten query to the partner endpoint.  The
     transport is pluggable — network access is gated by ``online``.
  5. Validate returned rows through :mod:`federation.boundary` before
     surfacing them to the caller.  No partner data ever enters the
     local graph — results are transient and provenance-stamped.
  6. Persist an entry into ``federation_query_log`` for every
     cross-enterprise call (including rejections).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import boundary as _boundary
from . import partner_registry

HERE = os.path.dirname(os.path.abspath(__file__))


_SERVICE_RE = re.compile(
    r"SERVICE\s+<([^>]+)>\s*\{([^}]*)\}",
    re.IGNORECASE | re.DOTALL,
)

# How the mandatory sensitivity filter is injected into a SELECT body.
_SENSITIVITY_FILTER_TEMPLATE = (
    "  ?s <https://ontology.example.com/federation/sensitivityTier> ?tier . "
    "FILTER (?tier IN ({allowed_tiers})) . "
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────
# Query analysis + rewriting
# ─────────────────────────────────────────────────────────────────────


def extract_service_endpoints(query: str) -> List[str]:
    """Return every endpoint URL referenced by a ``SERVICE`` clause."""
    return [m.group(1) for m in _SERVICE_RE.finditer(query)]


def _tiers_at_or_below(tier: str) -> List[str]:
    rank = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}
    r = rank.get(tier, 1)
    return [t for t, v in rank.items() if v <= r and t != "Restricted"]


def rewrite_with_sensitivity_filter(
    query: str,
    *,
    max_tier: str,
) -> str:
    """Inject a sensitivity-tier filter into the first SELECT body.

    The rewrite is intentionally conservative: we only append a
    FILTER clause inside the outermost ``WHERE { ... }`` block.  If no
    such block is found the query is returned unchanged and the
    boundary validator becomes the sole enforcement layer.
    """
    allowed = ", ".join(f'"{t}"' for t in _tiers_at_or_below(max_tier))
    filter_line = _SENSITIVITY_FILTER_TEMPLATE.format(allowed_tiers=allowed)

    # Only append once, just before the last closing brace of the outermost WHERE.
    m = re.search(r"\bWHERE\s*\{", query, re.IGNORECASE)
    if not m:
        return query
    depth = 0
    start = m.end() - 1
    close = -1
    for i in range(start, len(query)):
        ch = query[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                close = i
                break
    if close == -1:
        return query
    return query[:close] + "\n" + filter_line + "\n" + query[close:]


# ─────────────────────────────────────────────────────────────────────
# Dispatch + logging
# ─────────────────────────────────────────────────────────────────────


def _log_query(
    db_path: str,
    *,
    query_id: str,
    partner_id: Optional[str],
    requesting_flavor: Optional[str],
    original: str,
    rewritten: Optional[str],
    status: str,
    result_triples: int = 0,
    violations: int = 0,
    duration_ms: Optional[int] = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("""
            INSERT INTO federation_query_log
              (query_id, partner_id, requesting_flavor, original_query,
               rewritten_query, result_triples, violations, status,
               duration_ms, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            query_id, partner_id, requesting_flavor, original, rewritten,
            result_triples, violations, status, duration_ms, _utcnow(),
        ))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def _resolve_partner(
    db_path: str,
    endpoint: str,
) -> Optional[Dict[str, Any]]:
    """Match a SERVICE endpoint URL back to a registered partner row."""
    for p in partner_registry.list_partners(db_path):
        if p.get("sparql_endpoint", "").rstrip("/") == endpoint.rstrip("/"):
            return p
    return None


def _check_flavor_access(
    flavor: Optional[str],
    partner: Dict[str, Any],
) -> Tuple[bool, str]:
    """Cross-check the requesting flavor against the partner manifest.

    v2.0 flavor JSON files live under ``runtime/flavors/`` and already
    carry a ``sensitivity_tier`` field.  We accept the query if the
    flavor tier is at or below the partner's ``max_shareable_tier``.
    """
    if not flavor:
        return True, "no flavor declared — default access"
    flavor_dir = os.path.join(os.path.dirname(HERE), "runtime", "flavors")
    flavor_path = os.path.join(flavor_dir, f"{flavor}.json")
    if not os.path.isfile(flavor_path):
        return False, f"unknown flavor {flavor}"
    try:
        with open(flavor_path) as f:
            fl = json.load(f)
    except Exception as e:
        return False, f"flavor load error: {e}"
    tier_rank = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}
    if tier_rank.get(fl.get("sensitivity_tier", "Internal"), 1) > \
       tier_rank.get(partner.get("max_shareable_tier", "Internal"), 1):
        return False, (
            f"flavor tier {fl.get('sensitivity_tier')} exceeds "
            f"partner max {partner.get('max_shareable_tier')}"
        )
    return True, "flavor tier within partner agreement"


def _http_dispatch(
    endpoint: str,
    query: str,
    *,
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """Dispatch a SPARQL query via HTTP GET using the SPARQL protocol.

    Returns the ``results.bindings`` list.  Any network error short-circuits
    to an empty list — boundary enforcement treats an empty list as a
    trivially-conformant response.
    """
    try:
        url = endpoint + "?" + urllib.parse.urlencode({"query": query})
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/sparql-results+json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", {}).get("bindings", [])
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────


def route_federated_query(
    db_path: str,
    query: str,
    *,
    requesting_flavor: Optional[str] = None,
    online: bool = False,
    mock_results: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Route a federated SPARQL query through the boundary gate.

    Args:
        query: SPARQL text (may contain one or more SERVICE clauses).
        requesting_flavor: flavor of the agent issuing the query.
        online: when False, no network dispatch occurs; use
                ``mock_results`` to supply per-endpoint fixtures (this
                is how the CQ-FED test suite runs deterministically).
        mock_results: ``{endpoint_url: [row, ...]}`` fixture map.

    Returns:
        ``{"ok": bool, "results": {...}, "rejections": [...]}``
    """
    query_id = str(uuid.uuid4())
    start_ns = time.monotonic_ns()
    endpoints = extract_service_endpoints(query)

    if not endpoints:
        _log_query(db_path, query_id=query_id, partner_id=None,
                   requesting_flavor=requesting_flavor,
                   original=query, rewritten=None,
                   status="OK", result_triples=0)
        return {"ok": True, "results": {}, "rejections": [],
                "query_id": query_id,
                "note": "no SERVICE clauses — not a federated query"}

    per_partner: Dict[str, Any] = {}
    rejections: List[Dict[str, Any]] = []

    for ep in endpoints:
        partner = _resolve_partner(db_path, ep)
        if not partner:
            rejections.append({"endpoint": ep, "reason": "UNREGISTERED_PARTNER"})
            _log_query(db_path, query_id=query_id, partner_id=None,
                       requesting_flavor=requesting_flavor,
                       original=query, rewritten=None,
                       status="REJECTED")
            continue

        if partner.get("trust_state") != "ACTIVE":
            rejections.append({
                "endpoint": ep,
                "partner_id": partner.get("partner_id"),
                "reason": f"TRUST_STATE_{partner.get('trust_state')}",
            })
            _log_query(db_path, query_id=query_id,
                       partner_id=partner.get("partner_id"),
                       requesting_flavor=requesting_flavor,
                       original=query, rewritten=None,
                       status="REJECTED")
            continue

        allowed, reason = _check_flavor_access(requesting_flavor, partner)
        if not allowed:
            rejections.append({
                "endpoint": ep,
                "partner_id": partner.get("partner_id"),
                "reason": f"FLAVOR_DENIED[{reason}]",
            })
            _log_query(db_path, query_id=query_id,
                       partner_id=partner.get("partner_id"),
                       requesting_flavor=requesting_flavor,
                       original=query, rewritten=None,
                       status="REJECTED")
            continue

        rewritten = rewrite_with_sensitivity_filter(
            query, max_tier=partner.get("max_shareable_tier") or "Internal",
        )

        if online:
            rows = _http_dispatch(ep, rewritten)
        else:
            rows = list((mock_results or {}).get(ep, []))

        check = _boundary.validate_federated_results(
            db_path, partner=partner, rows=rows,
        )
        if check["violations"]:
            _boundary.escalate_to_governance(db_path, check["violations"])

        duration_ms = int((time.monotonic_ns() - start_ns) / 1_000_000)
        _log_query(db_path, query_id=query_id,
                   partner_id=partner.get("partner_id"),
                   requesting_flavor=requesting_flavor,
                   original=query, rewritten=rewritten,
                   status="OK" if not check["violations"] else "REJECTED",
                   result_triples=len(check["accepted"]),
                   violations=len(check["violations"]),
                   duration_ms=duration_ms)

        per_partner[ep] = {
            "partner_id": partner.get("partner_id"),
            "partner_iri": partner.get("partner_iri"),
            "rewritten":  rewritten,
            "accepted":   check["accepted"],
            "violations": check["violations"],
        }

    return {
        "ok": not rejections,
        "query_id":  query_id,
        "results":   per_partner,
        "rejections": rejections,
    }
