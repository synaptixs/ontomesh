"""
federation.boundary — Workstream 3, Component 4
=================================================
Sensitivity enforcement at the cross-enterprise federation boundary.

Every triple flowing in from a partner's SPARQL endpoint passes through
:func:`validate_federated_results`.  The check enforces three
orthogonal invariants:

  1. **Class whitelist** — the subject / object classes must be in the
     partner's declared ``exposedClasses`` list.
  2. **Sensitivity tier** — the returned tier must be ≤ the partner's
     ``max_shareable_tier``, and ``Restricted`` must *never* cross.
  3. **Provenance attribution** — every returned row must carry a
     ``prov:wasAttributedTo`` annotation pointing at the partner IRI.

Violations are recorded into the existing ``semantic_loss_log`` table
with ``loss_type = FEDERATION_BOUNDARY_VIOLATION`` and escalated to the
governance queue.  The sanitized result set is returned to the caller
so that subsequent joins only see triples that passed the boundary.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))

_TIER_RANK = {
    "Public":       0,
    "Internal":     1,
    "Confidential": 2,
    "Restricted":   3,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _record_violation(
    db_path: str,
    *,
    partner_iri: str,
    rule: str,
    detail: str,
    severity: str = "HIGH",
) -> None:
    """Append a FEDERATION_BOUNDARY_VIOLATION entry to the semantic loss log.

    Silently skips if the table is absent (e.g. CI environments using a
    minimal schema subset) so boundary enforcement still runs.
    """
    conn = _connect(db_path)
    try:
        conn.execute("""
            INSERT INTO semantic_loss_log
              (table_name, column_name, loss_type, description,
               severity, remediation, detected_at, resolved)
            VALUES (?, ?, 'FEDERATION_BOUNDARY_VIOLATION', ?, ?, ?, ?, 0)
        """, (
            "federation_query_log",
            None,
            f"[{rule}] partner={partner_iri} — {detail}",
            severity,
            "Review partner capability manifest and update registry "
            "exposed_classes / max_shareable_tier if legitimate.",
            _utcnow(),
        ))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def _class_in_whitelist(candidate: str, exposed: Iterable[str]) -> bool:
    if not candidate:
        return False
    exposed = set(exposed or [])
    if not exposed:
        return False
    return candidate in exposed


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def validate_federated_results(
    db_path: str,
    *,
    partner: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate a set of federated rows against the partner's manifest.

    Args:
        partner: row from ``federation_partners`` (already parsed — its
                 ``exposed_classes`` is a Python list).
        rows:    list of dicts representing each inbound result row.
                 Each row may carry ``owl_class``, ``sensitivity_tier``,
                 and ``prov_agent`` keys.

    Returns:
        ``{"ok": bool, "accepted": [...], "rejected": [...], "violations": [...]}``
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []

    partner_iri = partner.get("partner_iri") or partner.get("partner_id") or ""
    exposed = partner.get("exposed_classes") or []
    max_tier = partner.get("max_shareable_tier") or "Internal"
    max_rank = _TIER_RANK.get(max_tier, 1)

    for row in rows:
        row_violations: List[str] = []
        # (1) RESTRICTED must never cross — absolute block
        tier = row.get("sensitivity_tier") or "Internal"
        tier_rank = _TIER_RANK.get(tier, 1)
        if tier == "Restricted":
            row_violations.append("RESTRICTED_TIER_BLOCKED")
        elif tier_rank > max_rank:
            row_violations.append(f"TIER_EXCEEDS_AGREEMENT[{tier}>{max_tier}]")

        # (2) class whitelist
        owl_class = row.get("owl_class") or row.get("@type")
        if not _class_in_whitelist(owl_class, exposed):
            row_violations.append(f"CLASS_NOT_WHITELISTED[{owl_class}]")

        # (3) provenance attribution
        prov_agent = row.get("prov_agent") or row.get("prov:wasAttributedTo")
        if not prov_agent:
            row_violations.append("MISSING_PROV_ATTRIBUTION")
        elif partner_iri and partner_iri not in str(prov_agent):
            row_violations.append(
                f"PROV_MISMATCH[expected={partner_iri},got={prov_agent}]"
            )

        if row_violations:
            rejected.append(row)
            for rule in row_violations:
                violations.append({
                    "partner_iri": partner_iri,
                    "rule": rule,
                    "row": row,
                })
                _record_violation(
                    db_path,
                    partner_iri=partner_iri,
                    rule=rule,
                    detail=f"row={json.dumps(row, default=str)[:200]}",
                    severity="CRITICAL" if "RESTRICTED" in rule else "HIGH",
                )
        else:
            # Attach canonical provenance annotation for downstream
            # consumers that may round-trip the row.
            stamped = dict(row)
            stamped.setdefault("fed:sourcePartner", partner_iri)
            stamped.setdefault("fed:sensitivityTier", tier)
            accepted.append(stamped)

    return {
        "ok": not violations,
        "accepted":   accepted,
        "rejected":   rejected,
        "violations": violations,
        "partner_iri": partner_iri,
        "checked_at":  _utcnow(),
    }


def escalate_to_governance(
    db_path: str,
    violations: List[Dict[str, Any]],
) -> int:
    """Write a governance-queue proposal for the most severe violations.

    Piggy-backs on the Workstream 2 proposal store: every cluster of
    violations from one partner becomes a ``NEW_CONSTRAINT`` evolution
    proposal tagged ``FEDERATION_BOUNDARY_VIOLATION`` so domain experts
    can review whether the partner's exposure agreement should be
    tightened.
    """
    if not violations:
        return 0
    conn = _connect(db_path)
    inserted = 0
    by_partner: Dict[str, List[Dict[str, Any]]] = {}
    for v in violations:
        by_partner.setdefault(v.get("partner_iri", ""), []).append(v)

    for partner_iri, items in by_partner.items():
        proposal_id = str(uuid.uuid4())
        title = f"Federation boundary violation cluster — {partner_iri or 'unknown'}"
        summary_rules = sorted({i["rule"] for i in items})
        turtle = (
            f"# Boundary violation evidence ({len(items)} rows)\n"
            f"# Partner: {partner_iri}\n"
            f"# Rules:   {', '.join(summary_rules)}\n"
            "# Recommend tightening partner registry entry."
        )
        sparql = (
            "PREFIX fed: <https://ontology.example.com/federation/>\n"
            "SELECT ?x WHERE { ?x fed:sourcePartner "
            f"<{partner_iri}> . ?x fed:sensitivityTier ?t . "
            "FILTER (?t = \"Restricted\" || ?t = \"Confidential\") }"
        )
        try:
            conn.execute("""
                INSERT INTO ontology_evolution_proposals
                  (proposal_id, proposal_type, title, candidate_turtle,
                   evidence_sparql, detection_strategy, confidence_score,
                   dim_evidence_volume, status, created_at, updated_at)
                VALUES (?, 'NEW_CONSTRAINT', ?, ?, ?, 'SHACL_VIOLATION_ACCUMULATION',
                        ?, ?, 'PENDING', ?, ?)
            """, (
                proposal_id, title, turtle, sparql,
                min(1.0, 0.5 + 0.1 * len(items)),
                float(len(items)),
                _utcnow(), _utcnow(),
            ))
            inserted += 1
        except sqlite3.OperationalError:
            # Evolution store not present — just log and continue.
            pass
    conn.commit()
    conn.close()
    return inserted
