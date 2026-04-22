"""
evolution_scorer.py — Workstream 2: Candidate Scoring Engine
==============================================================
Scores every PENDING proposal across five dimensions, writes the
composite back to the proposal row, and returns a per-dimension
breakdown.

Dimensions:
  1. evidence_volume      — how many distinct occurrences
  2. evidence_recency     — weighted toward recent observations
  3. cross_domain_support — spread across templates / flavors
  4. consistency_risk     — 1 − reasoner-hazard score (1.0 = safe)
  5. schema_alignment     — does something similar already exist?

Composite = weighted mean of the five, in [0.0, 1.0].

Bands:
  ≥ 0.80  → escalate immediately (REVIEW queue)
  0.50..0.80 → weekly review batch
  < 0.50 → stays as candidate (no automatic escalation)

Usage:
    from evolution_scorer import score_pending
    summary = score_pending(db_path="db/enterprise.db",
                            out_path="output")
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))


# ── Weighting of the five dimensions (must sum to 1.0) ──────────────
WEIGHTS = {
    "evidence_volume":    0.25,
    "evidence_recency":   0.20,
    "cross_domain":       0.20,
    "consistency_risk":   0.20,
    "schema_alignment":   0.15,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────
# Per-dimension scorers
# ─────────────────────────────────────────────────────────────────────


def _score_evidence_volume(conn: sqlite3.Connection, p: sqlite3.Row) -> float:
    """Use the seeded dim_evidence_volume unless absent, then re-derive.

    The monitor stamps a volume seed at insertion.  Here we re-estimate
    against the current observation store so the score stays fresh.
    """
    seeded = p["dim_evidence_volume"]
    if seeded is not None and seeded > 0.0:
        return min(1.0, float(seeded))
    # Fallback: count substring matches of the proposal title in value_text
    title = (p["title"] or "").split("—")[0].strip()[:40]
    if not title:
        return 0.0
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM observation_record "
            "WHERE value_text LIKE ?", (f"%{title}%",),
        ).fetchone()["n"]
    except sqlite3.DatabaseError:
        return 0.0
    return min(1.0, n / 30.0)


def _score_evidence_recency(conn: sqlite3.Connection, p: sqlite3.Row) -> float:
    """Exponential-decay score based on the latest ObservationRecord
    that matches the proposal keyword.

    Score is 1.0 if the most recent evidence is today; 0.5 at 30 days;
    ≈0 beyond 180 days.
    """
    title = (p["title"] or "").split("—")[0].strip()[:40]
    if not title:
        return 0.5  # neutral
    try:
        row = conn.execute(
            "SELECT MAX(generated_at) AS latest FROM observation_record "
            "WHERE value_text LIKE ?", (f"%{title}%",),
        ).fetchone()
        latest = row["latest"] if row else None
    except sqlite3.DatabaseError:
        latest = None
    if not latest:
        return 0.3  # low-but-nonzero
    try:
        then = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    except Exception:
        return 0.5
    age = (datetime.now(timezone.utc) - then).total_seconds() / 86400.0
    # 30-day half-life
    import math
    return max(0.0, min(1.0, math.exp(-age / 30.0)))


def _score_cross_domain(conn: sqlite3.Connection, p: sqlite3.Row) -> float:
    """Count the number of distinct source_ref flavors in which this
    keyword appears.  ≥ 3 flavors → 1.0; 1 flavor → 0.33."""
    title = (p["title"] or "").split("—")[0].strip()[:40]
    if not title:
        return 0.33
    try:
        r = conn.execute(
            "SELECT COUNT(DISTINCT source_ref) AS n FROM observation_record "
            "WHERE value_text LIKE ?", (f"%{title}%",),
        ).fetchone()
        n = r["n"] if r else 0
    except sqlite3.DatabaseError:
        n = 0
    if n <= 0:
        return 0.33
    return min(1.0, n / 3.0)


def _score_consistency_risk(p: sqlite3.Row) -> float:
    """Heuristic hazard score based on proposal_type.

    The reasoner is invoked *on approval* (CI/CD), so here we use a
    cheap structural proxy:
      NEW_CLASS / NEW_PROPERTY  → 0.80  (low-risk additions)
      NEW_CONSTRAINT            → 0.60  (may render some records invalid)
      DEPRECATE                 → 0.40  (removes axioms; highest risk)
    """
    return {
        "NEW_CLASS":      0.80,
        "NEW_PROPERTY":   0.80,
        "NEW_CONSTRAINT": 0.60,
        "DEPRECATE":      0.40,
    }.get(p["proposal_type"], 0.50)


def _score_schema_alignment(conn: sqlite3.Connection, p: sqlite3.Row) -> float:
    """Penalise proposals whose title shares a large substring with an
    existing table or metadata label (likely duplicate of known concept).

    1.0 = fully novel term; 0.3 = close match to something already modelled.
    """
    title_lc = (p["title"] or "").lower()
    if not title_lc:
        return 0.5
    try:
        rows = conn.execute(
            "SELECT DISTINCT table_name, label FROM ontology_metadata",
        ).fetchall()
    except sqlite3.DatabaseError:
        return 0.7
    best_overlap = 0.0
    for r in rows:
        for field in (r["table_name"], r["label"]):
            if not field:
                continue
            fl = field.lower()
            if fl in title_lc or title_lc in fl:
                best_overlap = max(best_overlap, 0.7)
            else:
                # crude Jaccard on tokens
                a, b = set(title_lc.split()), set(fl.split())
                if a and b:
                    jac = len(a & b) / len(a | b)
                    best_overlap = max(best_overlap, jac)
    # High overlap → low alignment-novelty score
    return max(0.3, 1.0 - best_overlap)


# ─────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────


def score_proposal(conn: sqlite3.Connection, p: sqlite3.Row) -> Dict[str, Any]:
    """Score a single PENDING proposal and return its dimensional breakdown."""
    dims = {
        "evidence_volume":  _score_evidence_volume(conn, p),
        "evidence_recency": _score_evidence_recency(conn, p),
        "cross_domain":     _score_cross_domain(conn, p),
        "consistency_risk": _score_consistency_risk(p),
        "schema_alignment": _score_schema_alignment(conn, p),
    }
    composite = sum(dims[k] * WEIGHTS[k] for k in WEIGHTS)
    composite = round(max(0.0, min(1.0, composite)), 3)

    band = "CANDIDATE"
    if composite >= 0.80:
        band = "REVIEW_NOW"
    elif composite >= 0.50:
        band = "WEEKLY_BATCH"

    return {
        "proposal_id":  p["proposal_id"],
        "title":        p["title"],
        "dimensions":   {k: round(v, 3) for k, v in dims.items()},
        "weights":      WEIGHTS,
        "composite":    composite,
        "band":         band,
    }


def score_pending(db_path: str, out_path: str) -> Dict[str, Any]:
    """Re-score every PENDING proposal, write summary + persist composites."""
    conn = _connect(db_path)
    pending = conn.execute(
        "SELECT * FROM ontology_evolution_proposals "
        "WHERE status = 'PENDING'"
    ).fetchall()

    scored: List[Dict[str, Any]] = []
    now = _utcnow()
    for p in pending:
        result = score_proposal(conn, p)
        dims = result["dimensions"]
        conn.execute("""
            UPDATE ontology_evolution_proposals SET
                confidence_score     = ?,
                dim_evidence_volume  = ?,
                dim_evidence_recency = ?,
                dim_cross_domain     = ?,
                dim_consistency_risk = ?,
                dim_schema_alignment = ?,
                updated_at           = ?
            WHERE proposal_id = ?
        """, (
            result["composite"],
            dims["evidence_volume"], dims["evidence_recency"],
            dims["cross_domain"], dims["consistency_risk"],
            dims["schema_alignment"], now, p["proposal_id"],
        ))
        scored.append(result)
    conn.commit()
    conn.close()

    summary = {
        "@context":     {"@vocab": "https://ontology.example.com/evolution/"},
        "@type":        "EvolutionScoringSummary",
        "generatedAt":  now,
        "pending_total": len(scored),
        "review_now":   sum(1 for s in scored if s["band"] == "REVIEW_NOW"),
        "weekly_batch": sum(1 for s in scored if s["band"] == "WEEKLY_BATCH"),
        "candidates":   sum(1 for s in scored if s["band"] == "CANDIDATE"),
        "weights":      WEIGHTS,
        "proposals":    sorted(scored, key=lambda s: -s["composite"]),
    }

    reports_dir = os.path.join(out_path, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    out_file = os.path.join(reports_dir, "evolution_scoring_summary.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  ✓ Evolution scoring summary → {out_file}")
    return summary
