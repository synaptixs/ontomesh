"""L9 — Active-learning ranker.

Covers:
- Feature extraction is total: missing fields → NaN, malformed → NaN.
- An unfitted ranker is a no-op (rerank preserves input order).
- Below MIN_DECISIONS, fit() does not train (graceful cold-start).
- Above MIN_DECISIONS, fit() separates a clearly-noisy slice from
  a clearly-useful slice (acceptance gate proxy).
- Cross-validated AUC ≥ 0.75 on a separable synthetic set
  (matches roadmap §3.L9 acceptance gate).
- save/load round-trips the fitted pipeline.
- The L8 regime feature is handled gracefully when absent.
- fit_from_conn writes log_ranker_meta + lets list_candidates use
  the ranker without exploding.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("sklearn")

from db.migrations.log_discovery_v2 import migrate as v2_migrate  # noqa: E402
from wizard import log_review                                     # noqa: E402
from wizard.review_ranker import (                                # noqa: E402
    MIN_DECISIONS, ReviewRanker, extract_features, fit_from_conn,
    latest_meta, load_decisions,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_conn():
    """Fresh in-memory DB with the project schema + v2 migration."""
    c = sqlite3.connect(":memory:")
    with open(ROOT / "db" / "schema.sql") as f:
        c.executescript(f.read())
    v2_migrate(c)
    return c


def _insert_proposal(conn, *, pid, kind="LOG_EVENT", title="x",
                     confidence=0.5, ev_vol=0.5, ev_rec=0.5,
                     cross=0.0, risk=0.0, status="PENDING"):
    conn.execute(
        "INSERT INTO ontology_evolution_proposals "
        "(proposal_id, proposal_type, title, candidate_turtle, evidence_sparql,"
        " detection_strategy, confidence_score, dim_evidence_volume,"
        " dim_evidence_recency, dim_cross_domain, dim_consistency_risk, status) "
        "VALUES (?, ?, ?, ':x a owl:Class .', 'ASK {}',"
        " 'LOG_TEMPLATE_CLUSTERING', ?, ?, ?, ?, ?, ?)",
        (pid, kind, title, confidence, ev_vol, ev_rec, cross, risk, status),
    )


def _synthetic_decisions(n_approved=30, n_rejected=30, seed=0):
    """Build a separable synthetic decision set.

    Approved rows: high confidence, high evidence_volume, low risk.
    Rejected rows: low confidence, low evidence_volume, high risk.
    Logistic regression should crush this.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n_approved):
        rows.append({
            "id": i, "proposal_id": f"a{i}", "kind": "LOG_EVENT",
            "title": "approved candidate row example",
            "confidence_score": 0.7 + rng.random() * 0.3,
            "dim_evidence_volume": 0.7 + rng.random() * 0.3,
            "dim_evidence_recency": 0.6 + rng.random() * 0.4,
            "dim_cross_domain": 0.5 + rng.random() * 0.5,
            "dim_consistency_risk": rng.random() * 0.3,
            "status": "APPROVED", "created_at": "2026-05-28 00:00:00",
            "__label__": 1,
        })
    for i in range(n_rejected):
        rows.append({
            "id": 1000 + i, "proposal_id": f"r{i}", "kind": "LOG_EVENT",
            "title": "rejected noise",
            "confidence_score": rng.random() * 0.3,
            "dim_evidence_volume": rng.random() * 0.3,
            "dim_evidence_recency": rng.random() * 0.3,
            "dim_cross_domain": rng.random() * 0.3,
            "dim_consistency_risk": 0.7 + rng.random() * 0.3,
            "status": "REJECTED", "created_at": "2026-05-28 00:00:00",
            "__label__": 0,
        })
    rng.shuffle(rows)
    return rows


# ── Feature extraction ────────────────────────────────────────────────


def test_features_empty_proposal_yields_all_nans_or_zeros():
    feats = extract_features({})
    # No NaNs leak as None — all should be float.
    for v in feats.values():
        assert isinstance(v, float)
    # kind one-hots default to 0 when kind is missing.
    assert feats["kind_LOG_EVENT"] == 0.0
    assert feats["kind_LOG_ENTITY"] == 0.0


def test_features_known_kind_is_one_hot():
    feats = extract_features({"kind": "LOG_RELATIONSHIP", "title": "a b c"})
    assert feats["kind_LOG_RELATIONSHIP"] == 1.0
    assert feats["kind_LOG_EVENT"] == 0.0
    assert feats["title_token_count"] == 3.0


def test_features_regime_absent_is_nan_not_crash():
    feats = extract_features({"kind": "LOG_EVENT", "confidence_score": 0.5})
    # regime_id is the L8 hook — must survive its absence.
    import math
    assert math.isnan(feats["regime_id"])


# ── Cold-start behaviour ──────────────────────────────────────────────


def test_unfitted_ranker_is_noop():
    rk = ReviewRanker()
    assert not rk.is_fitted()
    cands = [{"proposal_id": "x", "confidence_score": 0.1},
             {"proposal_id": "y", "confidence_score": 0.9}]
    out = rk.rerank(cands)
    # Order preserved.
    assert [c["proposal_id"] for c in out] == ["x", "y"]
    # Score is neutral (0.5) — used for tie-breaks elsewhere.
    assert rk.score(cands[0]) == 0.5


def test_fit_below_min_decisions_does_not_train():
    rk = ReviewRanker()
    # Use 5 rows of each label — well below MIN_DECISIONS.
    decisions = _synthetic_decisions(n_approved=5, n_rejected=5)
    assert len(decisions) < MIN_DECISIONS
    meta = rk.fit(decisions)
    assert not rk.is_fitted()
    assert meta.n_decisions == len(decisions)


def test_fit_with_single_class_does_not_train():
    rk = ReviewRanker()
    # 30 approved, 0 rejected — logistic regression undefined.
    decisions = _synthetic_decisions(n_approved=30, n_rejected=0)
    rk.fit(decisions)
    assert not rk.is_fitted()


# ── Acceptance gate — does it actually rerank? ────────────────────────


def test_fit_separates_approved_from_rejected_pattern():
    rk = ReviewRanker()
    rk.fit(_synthetic_decisions())
    assert rk.is_fitted()

    # Score an obviously-approved-style row and an obviously-noisy row.
    good = {"kind": "LOG_EVENT", "confidence_score": 0.95,
            "dim_evidence_volume": 0.95, "dim_evidence_recency": 0.95,
            "dim_cross_domain": 0.8, "dim_consistency_risk": 0.05,
            "title": "high quality"}
    noisy = {"kind": "LOG_EVENT", "confidence_score": 0.05,
             "dim_evidence_volume": 0.05, "dim_evidence_recency": 0.05,
             "dim_cross_domain": 0.05, "dim_consistency_risk": 0.95,
             "title": "noise"}
    assert rk.score(good) > rk.score(noisy)


def test_rerank_pushes_noise_to_bottom():
    rk = ReviewRanker()
    rk.fit(_synthetic_decisions())
    # Mixed PENDING queue: 5 good-looking + 5 noisy-looking.
    cands = []
    for i in range(5):
        cands.append({"proposal_id": f"g{i}", "kind": "LOG_EVENT",
                      "confidence_score": 0.9, "dim_evidence_volume": 0.9,
                      "dim_evidence_recency": 0.9, "dim_cross_domain": 0.7,
                      "dim_consistency_risk": 0.1, "title": "good"})
    for i in range(5):
        cands.append({"proposal_id": f"n{i}", "kind": "LOG_EVENT",
                      "confidence_score": 0.1, "dim_evidence_volume": 0.1,
                      "dim_evidence_recency": 0.1, "dim_cross_domain": 0.1,
                      "dim_consistency_risk": 0.9, "title": "noise"})
    out = rk.rerank(cands)
    # All five good rows should land in the top half.
    top_half_ids = {c["proposal_id"] for c in out[:5]}
    assert all(pid.startswith("g") for pid in top_half_ids)


def test_cv_auc_above_threshold_on_separable_data():
    """Roadmap §3.L9 acceptance gate: cross-validated AUC ≥ 0.75."""
    rk = ReviewRanker()
    meta = rk.fit(_synthetic_decisions(n_approved=40, n_rejected=40))
    assert rk.is_fitted()
    assert meta.auc is not None
    assert meta.auc >= 0.75, f"AUC {meta.auc} below acceptance threshold"


# ── Persistence ───────────────────────────────────────────────────────


def test_save_load_round_trip(tmp_path):
    rk = ReviewRanker()
    rk.fit(_synthetic_decisions())
    path = tmp_path / "ranker.pkl"
    rk.save(str(path))

    rk2 = ReviewRanker.load(str(path))
    assert rk2.is_fitted()
    # Same prediction (within floating-point) on the same row.
    probe = {"kind": "LOG_EVENT", "confidence_score": 0.9,
             "dim_evidence_volume": 0.9, "dim_evidence_recency": 0.9,
             "dim_cross_domain": 0.5, "dim_consistency_risk": 0.1,
             "title": "x"}
    assert abs(rk.score(probe) - rk2.score(probe)) < 1e-9


def test_load_or_none_returns_none_when_absent(tmp_path):
    assert ReviewRanker.load_or_none(str(tmp_path / "nope.pkl")) is None


# ── DB integration ────────────────────────────────────────────────────


def test_load_decisions_from_db():
    conn = _make_conn()
    _insert_proposal(conn, pid="a1", status="APPROVED")
    _insert_proposal(conn, pid="r1", status="REJECTED")
    _insert_proposal(conn, pid="p1", status="PENDING")  # ignored
    rows = load_decisions(conn)
    labels = {r["proposal_id"]: r["__label__"] for r in rows}
    assert labels == {"a1": 1, "r1": 0}


def test_fit_from_conn_records_meta(tmp_path):
    conn = _make_conn()
    # Seed enough decisions to fit (MIN_DECISIONS = 20).
    for i in range(15):
        _insert_proposal(conn, pid=f"a{i}", status="APPROVED",
                         confidence=0.9, ev_vol=0.9, ev_rec=0.9, risk=0.1)
    for i in range(15):
        _insert_proposal(conn, pid=f"r{i}", status="REJECTED",
                         confidence=0.1, ev_vol=0.1, ev_rec=0.1, risk=0.9)
    path = tmp_path / "ranker.pkl"
    summary = fit_from_conn(conn, str(path))
    assert summary["fitted"]
    assert summary["n_decisions"] == 30
    assert path.is_file()
    m = latest_meta(conn)
    assert m is not None
    assert m["n_decisions"] == 30


def test_list_candidates_with_ranker_changes_order(tmp_path):
    conn = _make_conn()
    # Fit on synthetic decisions...
    for i in range(15):
        _insert_proposal(conn, pid=f"a{i}", status="APPROVED",
                         confidence=0.9, ev_vol=0.9, ev_rec=0.9, risk=0.1)
    for i in range(15):
        _insert_proposal(conn, pid=f"r{i}", status="REJECTED",
                         confidence=0.1, ev_vol=0.1, ev_rec=0.1, risk=0.9)
    # ...then add PENDING candidates: one that "looks approved-ish",
    # one that "looks noisy", and put the noisy one at the SQL-top
    # by giving it confidence × recency higher than the good one.
    _insert_proposal(conn, pid="noisy", status="PENDING",
                     confidence=0.99, ev_vol=0.99, ev_rec=0.99, risk=0.99)
    _insert_proposal(conn, pid="good", status="PENDING",
                     confidence=0.8, ev_vol=0.8, ev_rec=0.8, risk=0.05)
    conn.commit()

    # No ranker → SQL default puts "noisy" first (higher conf × recency).
    plain = log_review.list_candidates(conn, status="PENDING", limit=10)
    assert plain[0]["proposal_id"] == "noisy"

    # With a fitted ranker the low-risk "good" row wins.
    path = tmp_path / "ranker.pkl"
    fit_from_conn(conn, str(path))
    rk = ReviewRanker.load(str(path))
    ranked = log_review.list_candidates(
        conn, status="PENDING", limit=10, ranker=rk)
    assert ranked[0]["proposal_id"] == "good"
    assert "ranker_score" in ranked[0]
