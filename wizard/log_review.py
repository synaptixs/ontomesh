"""
wizard/log_review.py — Phase L4
───────────────────────────────
Engineer-review surface for log-mined candidates.

Inputs (produced by L1 + L2):
  - ``log_templates`` — Drain-clustered message patterns
  - ``log_template_slots`` — per-slot type + sample distribution
  - ``log_entity_edges`` — PMI + temporal-direction graph
  - ``ontology_evolution_proposals`` rows with
    ``proposal_type='LOG_EVENT'`` from the HMM anomaly pass

Outputs:
  - One row per surfaceable candidate in
    ``ontology_evolution_proposals`` with proposal_type ∈
    {LOG_ENTITY, LOG_RELATIONSHIP, LOG_EVENT, LOG_CAUSAL_EDGE}.
  - On approval: the corresponding entry is appended to the wizard
    session under ``entities`` / ``events`` / ``relationships`` /
    ``causal_rules``.

Public API
──────────

    seed_from_mining(conn) -> dict     # convert L1/L2 outputs to proposals
    list_candidates(conn, kind, status, limit) -> list
    approve(conn, session, proposal_id, edits=None) -> dict
    reject(conn, proposal_id, note) -> dict
    merge(conn, session, proposal_id, into) -> dict

All write-paths are idempotent: re-running ``seed_from_mining`` after a
new ``--phase mine`` (or ``--phase sequence``) updates existing
proposals in place instead of duplicating them. Approvals are tracked
on the proposal row (``status='APPROVED'``) so the candidate doesn't
re-surface in a later mining run.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ── Confidence × consequence ordering (PRML Ch. 1 decision theory) ──────


SEVERITY_WEIGHT = {
    "CRITICAL": 1.0, "ERROR": 0.8, "WARN": 0.5, "WARNING": 0.5,
    "INFO": 0.2, "DEBUG": 0.05,
}


def _consequence_score(severity: Optional[str]) -> float:
    if not severity:
        return 0.3
    return SEVERITY_WEIGHT.get(severity.upper(), 0.3)


# ── Seed from mining outputs ────────────────────────────────────────────


def _stable_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _slot_qname(template: str, slot_idx: int, slot_type: str) -> str:
    """Suggest a class-or-property qname for a slot. Heuristic: take a
    short keyword from the template followed by Idx, with an `Iri` /
    `Code` suffix that hints at the data shape. The engineer can edit."""
    # Extract a stem from the first capitalised word in the template,
    # falling back to a generic name.
    tokens = re.findall(r"[A-Z][a-zA-Z0-9]+", template) or ["LogEntity"]
    stem = tokens[0][:24]
    if slot_type == "IRI":
        return f":{stem}Iri"
    if slot_type == "UUID":
        return f":{stem}Uuid"
    if slot_type == "IP":
        return f":{stem}Ip"
    if slot_type == "ENUM":
        return f":{stem}Code"
    return f":{stem}Field{slot_idx}"


def seed_from_mining(conn: sqlite3.Connection,
                     extractions: Optional[Sequence[dict]] = None
                     ) -> Dict[str, int]:
    """Convert log_templates / log_template_slots / log_entity_edges
    into ontology_evolution_proposals rows. Idempotent — re-runs upsert
    instead of duplicating, and any row already ``APPROVED`` /
    ``REJECTED`` is left untouched.

    If ``extractions`` is supplied (from a fresh L1 mining run), L3's
    causality miner runs to gate the directed edges:
      - edges that pass the (PMI + temporal + Granger/TE) triangulation
        become LOG_CAUSAL_EDGE with confidence reflecting all three;
      - edges that fail downgrade to LOG_RELATIONSHIP.
    When ``extractions`` is None we fall back to the L1-only path: every
    directed PMI edge → LOG_CAUSAL_EDGE (no statistical gating).
    """
    if not _table_exists(conn, "ontology_evolution_proposals"):
        return {"log_event": 0, "log_entity": 0, "log_relationship": 0,
                "log_causal_edge": 0}

    counts = {"log_event": 0, "log_entity": 0,
              "log_relationship": 0, "log_causal_edge": 0}

    # L3 — if we have the L1 extractions in hand, run the causality
    # miner and build a set of (src, dst) pairs that survived the
    # triangulation gate. Directed edges absent from this set will be
    # demoted to LOG_RELATIONSHIP below.
    causal_pairs: set = set()
    causal_meta: Dict[tuple, dict] = {}
    if extractions:
        try:
            import sys as _sys, os as _os
            _src = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__))), "src")
            if _src not in _sys.path:
                _sys.path.insert(0, _src)
            from causality_miner import find_causality_candidates  # noqa: E402
            cands = find_causality_candidates(extractions, conn)
            for c in cands:
                causal_pairs.add((c.src, c.dst))
                causal_meta[(c.src, c.dst)] = c.to_dict()
        except Exception:                       # noqa: BLE001 — never break seed
            pass

    # 1. LOG_EVENT — every non-merged template with hits ≥ 3 becomes
    #    a candidate event class.
    if _table_exists(conn, "log_templates"):
        for row in conn.execute(
            "SELECT id, cluster_id, template, sample_line, hits, severity, service "
            "FROM log_templates WHERE merged_into IS NULL AND hits >= 3"
        ):
            tmpl_id, cid, template, sample, hits, sev, svc = row
            pid = _stable_id(f"log-event:cluster:{cid}")
            title = f"Event template #{cid}: {template[:60]}"
            confidence = min(1.0, 0.4 + 0.05 * hits)
            consequence = _consequence_score(sev)
            candidate_turtle = (
                f"# Suggested OWL event class\n"
                f":Event_{cid} a owl:Class ;\n"
                f"  rdfs:subClassOf :DomainEvent ;\n"
                f'  rdfs:label "{(template or "")[:80]}" ;\n'
                f'  rdfs:comment "Sample: {(sample or "")[:200]}" .\n'
            )
            evidence_sparql = (
                f"PREFIX : <https://ontology.example.com/enterprise/>\n"
                f"ASK {{ ?e a :Event_{cid} }}\n"
            )
            _upsert_proposal(
                conn, pid,
                proposal_type="LOG_EVENT",
                title=title,
                candidate_turtle=candidate_turtle,
                evidence_sparql=evidence_sparql,
                detection_strategy="LOG_TEMPLATE_CLUSTERING",
                confidence_score=confidence,
                dim_evidence_volume=min(1.0, hits / 50.0),
                dim_evidence_recency=consequence,
                evidence_template_id=tmpl_id,
                evidence_sample=sample,
            )
            counts["log_event"] += 1

    # 2. LOG_ENTITY — each slot typed as IRI / UUID / ENUM becomes a
    #    candidate identifier property whose range is a new class.
    if _table_exists(conn, "log_template_slots"):
        for row in conn.execute(
            "SELECT s.id, s.template_id, s.slot_idx, s.type, s.distinct_count, "
            "       s.sample_count, s.top_values, s.pii_risk, "
            "       t.cluster_id, t.template "
            "FROM log_template_slots s "
            "JOIN log_templates t ON s.template_id = t.id "
            "WHERE s.type IN ('IRI', 'UUID', 'ENUM') AND t.merged_into IS NULL"
        ):
            (sid, tid, slot_idx, slot_type, distinct, samples, top, pii,
             cid, template) = row
            qname = _slot_qname(template, slot_idx, slot_type)
            pid = _stable_id(f"log-entity:{tid}:{slot_idx}:{qname}")
            title = f"Entity candidate {qname} ({slot_type})"
            candidate_turtle = (
                f"{qname} a owl:DatatypeProperty ;\n"
                f"  rdfs:label \"{qname[1:]}\" ;\n"
                f"  rdfs:comment \"Top values: {top}\" .\n"
            )
            evidence_sparql = (
                f"PREFIX : <https://ontology.example.com/enterprise/>\n"
                f"ASK {{ ?s {qname} ?o }}\n"
            )
            confidence = min(1.0, 0.5 + 0.05 * (samples / 10.0))
            _upsert_proposal(
                conn, pid,
                proposal_type="LOG_ENTITY",
                title=title,
                candidate_turtle=candidate_turtle,
                evidence_sparql=evidence_sparql,
                detection_strategy="LOG_TEMPLATE_CLUSTERING",
                confidence_score=confidence,
                dim_evidence_volume=min(1.0, samples / 20.0),
                dim_consistency_risk=0.8 if pii else 0.0,
                evidence_template_id=tid,
                evidence_sample=top,
            )
            counts["log_entity"] += 1

    # 3. LOG_RELATIONSHIP (undirected) and LOG_CAUSAL_EDGE (directed +
    #    triangulation-gated when L3 ran). Edges with `directed=1` but
    #    no causal_pairs entry are demoted to LOG_RELATIONSHIP — they
    #    co-occur and have a temporal lead but the past of `src` doesn't
    #    inform the future of `dst` beyond what `dst`'s own past does.
    if _table_exists(conn, "log_entity_edges"):
        for row in conn.execute(
            "SELECT src, dst, pmi, cooccurrence_count, temporal_lead_ratio, directed "
            "FROM log_entity_edges WHERE pmi >= 3.0"
        ):
            src, dst, pmi, count, lead, directed = row
            gated_causal = directed and (src, dst) in causal_pairs
            cmeta = causal_meta.get((src, dst))
            if gated_causal:
                ptype = "LOG_CAUSAL_EDGE"
                kind_key = "log_causal_edge"
                title = (f"Causal candidate: {src[:30]} → {dst[:30]} "
                         f"(PMI {pmi:.1f}, via {cmeta['via']})")
                strategy = "GRANGER_CAUSALITY"
                # Use the triangulated confidence — it blends all three signals.
                confidence = cmeta["confidence"]
            elif directed:
                # Directed by PMI temporal-ordering but failed statistical
                # gating — surface as a relationship instead so the
                # reviewer sees the signal without the causal claim.
                ptype = "LOG_RELATIONSHIP"
                kind_key = "log_relationship"
                title = (f"Relationship (directed but ungated): "
                         f"{src[:30]} → {dst[:30]} (PMI {pmi:.1f})")
                strategy = "PMI_TEMPORAL_ORDERING"
                confidence = min(1.0, 0.4 + (pmi - 3.0) / 10.0)
            else:
                ptype = "LOG_RELATIONSHIP"
                kind_key = "log_relationship"
                title = f"Relationship candidate: {src[:30]} ↔ {dst[:30]} (PMI {pmi:.1f})"
                strategy = "PMI_TEMPORAL_ORDERING"
                confidence = min(1.0, 0.4 + (pmi - 3.0) / 10.0)
            pid = _stable_id(f"{ptype.lower()}:{src}::{dst}")
            candidate_turtle = (
                f"# {ptype}\n# src={src}\n# dst={dst}\n"
                f"# PMI={pmi:.2f}  lead_ratio={lead}\n"
                + (f"# granger_p={cmeta['granger_p']:.4f} lag={cmeta['granger_lag']}\n"
                   f"# te_z={cmeta['te_z']:.2f}\n" if cmeta else "")
            )
            evidence_sparql = (
                f"PREFIX : <https://ontology.example.com/enterprise/>\n"
                f"ASK {{ ?a ?p ?b }}   # placeholder — edit at approval time\n"
            )
            _upsert_proposal(
                conn, pid,
                proposal_type=ptype,
                title=title,
                candidate_turtle=candidate_turtle,
                evidence_sparql=evidence_sparql,
                detection_strategy=strategy,
                confidence_score=confidence,
                dim_evidence_volume=min(1.0, count / 30.0),
                dim_cross_domain=min(1.0, pmi / 10.0),
                # Park the Granger p-value in dim_consistency_risk so
                # the UI panel can show it without parsing turtle.
                dim_consistency_risk=(1.0 - cmeta["granger_p"]) if cmeta else 0.0,
                evidence_sample=(f"{src} → {dst}"
                                 if gated_causal or directed
                                 else f"{src} ↔ {dst}"),
            )
            counts[kind_key] += 1

    conn.commit()
    return counts


def _upsert_proposal(conn: sqlite3.Connection, proposal_id: str,
                     *, proposal_type: str, title: str,
                     candidate_turtle: str, evidence_sparql: str,
                     detection_strategy: str,
                     confidence_score: float = 0.5,
                     dim_evidence_volume: float = 0.0,
                     dim_evidence_recency: float = 0.0,
                     dim_cross_domain: float = 0.0,
                     dim_consistency_risk: float = 0.0,
                     dim_schema_alignment: float = 0.0,
                     evidence_template_id: Optional[int] = None,
                     evidence_sample: Optional[str] = None,
                     ) -> None:
    """INSERT … ON CONFLICT update. Leaves status/reviewer_id alone so
    once an engineer touches a row, re-seeds don't clobber the decision.
    """
    conn.execute(
        "INSERT INTO ontology_evolution_proposals "
        "(proposal_id, proposal_type, title, candidate_turtle, "
        " evidence_sparql, detection_strategy, confidence_score, "
        " dim_evidence_volume, dim_evidence_recency, dim_cross_domain, "
        " dim_consistency_risk, dim_schema_alignment, "
        " evidence_template_id, evidence_sample) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(proposal_id) DO UPDATE SET "
        "  title = excluded.title, "
        "  candidate_turtle = excluded.candidate_turtle, "
        "  evidence_sparql = excluded.evidence_sparql, "
        "  confidence_score = excluded.confidence_score, "
        "  dim_evidence_volume = excluded.dim_evidence_volume, "
        "  dim_evidence_recency = excluded.dim_evidence_recency, "
        "  dim_cross_domain = excluded.dim_cross_domain, "
        "  dim_consistency_risk = excluded.dim_consistency_risk, "
        "  evidence_template_id = excluded.evidence_template_id, "
        "  evidence_sample = excluded.evidence_sample, "
        "  updated_at = datetime('now')",
        (proposal_id, proposal_type, title, candidate_turtle,
         evidence_sparql, detection_strategy, confidence_score,
         dim_evidence_volume, dim_evidence_recency, dim_cross_domain,
         dim_consistency_risk, dim_schema_alignment,
         evidence_template_id, evidence_sample),
    )


# ── Listing + review actions ────────────────────────────────────────────


_LOG_KINDS = ("LOG_ENTITY", "LOG_RELATIONSHIP", "LOG_EVENT", "LOG_CAUSAL_EDGE")


def list_candidates(conn: sqlite3.Connection, *,
                    kind: Optional[str] = None,
                    status: str = "PENDING",
                    limit: int = 50,
                    ranker: Any = None) -> List[dict]:
    """Return candidates sorted by (confidence_score × consequence).

    Consequence pulled from `dim_evidence_recency` which carries the
    severity-weight from `seed_from_mining`.

    If `ranker` is a fitted ``wizard.review_ranker.ReviewRanker``, the
    SQL-default order is replaced by the ranker's posterior. An
    unfitted or `None` ranker is a no-op — the L9 ordering only takes
    effect once a model has been trained.
    """
    if not _table_exists(conn, "ontology_evolution_proposals"):
        return []
    where = ["proposal_type IN ({})".format(
        ",".join(f"'{k}'" for k in _LOG_KINDS))]
    params: List[Any] = []
    if kind:
        where.append("proposal_type = ?")
        params.append(kind)
    if status and status != "ALL":
        where.append("status = ?")
        params.append(status)
    # L8 columns (regime_tag / regime_posterior) are pulled via a
    # tolerant subselect so the query still works against a DB whose
    # v2 migration hasn't run yet.
    has_regime = any(
        r[1] == "regime_tag" for r in conn.execute(
            "PRAGMA table_info(ontology_evolution_proposals)"
        )
    )
    extra_cols = (", regime_tag, regime_posterior" if has_regime
                  else ", NULL AS regime_tag, NULL AS regime_posterior")
    sql = (
        "SELECT id, proposal_id, proposal_type, title, candidate_turtle, "
        "       evidence_sparql, detection_strategy, confidence_score, "
        "       dim_evidence_volume, dim_evidence_recency, dim_cross_domain, "
        "       dim_consistency_risk, status, evidence_template_id, "
        "       evidence_sample, created_at, updated_at"
        f"      {extra_cols} "
        "FROM ontology_evolution_proposals "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY (confidence_score * (1.0 + dim_evidence_recency)) DESC "
        "LIMIT ?"
    )
    params.append(int(limit))
    out: List[dict] = []
    for r in conn.execute(sql, params):
        out.append({
            "id": r[0], "proposal_id": r[1], "kind": r[2], "title": r[3],
            "candidate_turtle": r[4], "evidence_sparql": r[5],
            "detection_strategy": r[6], "confidence_score": r[7],
            "dim_evidence_volume": r[8], "dim_evidence_recency": r[9],
            "dim_cross_domain": r[10], "dim_consistency_risk": r[11],
            "status": r[12], "evidence_template_id": r[13],
            "evidence_sample": r[14], "created_at": r[15],
            "updated_at": r[16],
            "regime_tag": r[17] if len(r) > 17 else None,
            "regime_posterior": r[18] if len(r) > 18 else None,
        })
    if ranker is not None and getattr(ranker, "is_fitted", lambda: False)():
        out = ranker.rerank(out)
    return out


def get_candidate(conn: sqlite3.Connection, proposal_id: str
                  ) -> Optional[dict]:
    row = conn.execute(
        "SELECT proposal_id, proposal_type, title, candidate_turtle, "
        "       confidence_score, evidence_template_id, evidence_sample, status "
        "FROM ontology_evolution_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "proposal_id": row[0], "kind": row[1], "title": row[2],
        "candidate_turtle": row[3], "confidence_score": row[4],
        "evidence_template_id": row[5], "evidence_sample": row[6],
        "status": row[7],
    }


def approve(conn: sqlite3.Connection,
            session: dict,
            proposal_id: str,
            *,
            edits: Optional[dict] = None,
            reviewer: str = "wizard-user") -> dict:
    """Mark `proposal_id` APPROVED and route the candidate into the
    session under entities / events / relationships / causal_rules
    based on its kind. ``edits`` is an optional dict the reviewer
    submits with name/label/description overrides.
    """
    cand = get_candidate(conn, proposal_id)
    if not cand:
        raise KeyError(proposal_id)
    edits = edits or {}

    kind = cand["kind"]
    entry = _build_session_entry(cand, edits)

    if kind == "LOG_EVENT":
        session.setdefault("events", []).append(entry)
    elif kind == "LOG_ENTITY":
        session.setdefault("entities", []).append(entry)
    elif kind == "LOG_RELATIONSHIP":
        session.setdefault("relationships", []).append(entry)
    elif kind == "LOG_CAUSAL_EDGE":
        session.setdefault("causal_rules", []).append(entry)

    conn.execute(
        "UPDATE ontology_evolution_proposals SET status='APPROVED', "
        "reviewer_id=?, reviewed_at=datetime('now') "
        "WHERE proposal_id=?",
        (reviewer, proposal_id),
    )
    conn.commit()
    return {"ok": True, "proposal_id": proposal_id,
            "kind": kind, "session_entry": entry}


def reject(conn: sqlite3.Connection, proposal_id: str,
           note: str = "",
           reviewer: str = "wizard-user") -> dict:
    conn.execute(
        "UPDATE ontology_evolution_proposals SET status='REJECTED', "
        "reviewer_id=?, review_note=?, reviewed_at=datetime('now') "
        "WHERE proposal_id=?",
        (reviewer, note, proposal_id),
    )
    conn.commit()
    return {"ok": True, "proposal_id": proposal_id, "status": "REJECTED"}


def merge(conn: sqlite3.Connection,
          session: dict,
          proposal_id: str,
          into_name: str,
          reviewer: str = "wizard-user") -> dict:
    """Approve `proposal_id` but route its evidence into an existing
    session entry (matched by name). Used when the candidate is a
    duplicate of something the user already authored.
    """
    cand = get_candidate(conn, proposal_id)
    if not cand:
        raise KeyError(proposal_id)
    bucket = {
        "LOG_EVENT": "events",
        "LOG_ENTITY": "entities",
        "LOG_RELATIONSHIP": "relationships",
        "LOG_CAUSAL_EDGE": "causal_rules",
    }[cand["kind"]]
    items = session.setdefault(bucket, [])
    target = next((it for it in items if it.get("name") == into_name
                   or it.get("label") == into_name), None)
    if target is None:
        # If nothing to merge into, fall back to plain approve.
        return approve(conn, session, proposal_id, reviewer=reviewer)
    samples = target.setdefault("evidence_samples", [])
    samples.append(cand.get("evidence_sample") or cand.get("title"))
    conn.execute(
        "UPDATE ontology_evolution_proposals SET status='APPROVED', "
        "reviewer_id=?, review_note=?, reviewed_at=datetime('now') "
        "WHERE proposal_id=?",
        (reviewer, f"merged-into:{into_name}", proposal_id),
    )
    conn.commit()
    return {"ok": True, "proposal_id": proposal_id, "merged_into": into_name}


def _build_session_entry(cand: dict, edits: dict) -> dict:
    """Map a proposal row to the session shape downstream wizard steps
    expect. Engineer edits override the heuristic defaults."""
    kind = cand["kind"]
    if kind == "LOG_EVENT":
        cid = cand["evidence_template_id"]
        default_name = f"event_{cid}" if cid else "log_event"
        return {
            "name": edits.get("name", default_name),
            "label": edits.get("label", cand["title"]),
            "description": edits.get("description",
                                     cand.get("evidence_sample") or ""),
            "source": "log-discovery",
            "proposal_id": cand["proposal_id"],
        }
    if kind == "LOG_ENTITY":
        return {
            "name": edits.get("name", "log_entity"),
            "label": edits.get("label", cand["title"]),
            "description": edits.get("description", ""),
            "sensitivity": edits.get("sensitivity", "Internal"),
            "source": "log-discovery",
            "proposal_id": cand["proposal_id"],
        }
    if kind == "LOG_RELATIONSHIP":
        # Pull src/dst out of the title we set during seed.
        return {
            "from_entity": edits.get("from_entity", "?"),
            "label": edits.get("label", "related to"),
            "to_entity": edits.get("to_entity", "?"),
            "source": "log-discovery",
            "proposal_id": cand["proposal_id"],
        }
    if kind == "LOG_CAUSAL_EDGE":
        # Carry cause_class / effect_class / window_seconds through to
        # the session so wizard.rules.compile_causal_rule can build a
        # proper SPARQL CONSTRUCT — the stub `candidate_turtle` is
        # comment-only and won't parse.
        return {
            "id": edits.get("id", cand["proposal_id"][:8]),
            "kind": "sparql",
            "label": edits.get("label", cand["title"]),
            "cause_class": edits.get("cause_class"),
            "effect_class": edits.get("effect_class"),
            "window_seconds": edits.get("window_seconds", 60),
            "body": edits.get("body"),       # optional override
            "enabled": True,
            "source": "log-discovery",
            "proposal_id": cand["proposal_id"],
        }
    return {}


def summary(conn: sqlite3.Connection) -> dict:
    """Headline numbers for the wizard's Log Discovery step panel."""
    if not _table_exists(conn, "ontology_evolution_proposals"):
        return {"available": False}
    by_kind: Dict[str, Dict[str, int]] = {}
    for r in conn.execute(
        "SELECT proposal_type, status, COUNT(*) "
        "FROM ontology_evolution_proposals "
        "WHERE proposal_type IN ({}) "
        "GROUP BY proposal_type, status".format(
            ",".join(f"'{k}'" for k in _LOG_KINDS))
    ):
        kind, status, count = r
        by_kind.setdefault(kind, {})[status] = count
    return {"available": True, "by_kind": by_kind}


__all__ = [
    "approve", "get_candidate", "list_candidates", "merge",
    "reject", "seed_from_mining", "summary",
]
