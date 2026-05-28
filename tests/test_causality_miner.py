"""L3 — Granger + TE causality gate."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("statsmodels")
pytest.importorskip("numpy")

import numpy as np  # noqa: E402

from causality_miner import (  # noqa: E402
    GRANGER_P_THRESHOLD, TE_Z_THRESHOLD,
    build_rate_series, find_causality_candidates,
    granger_test, transfer_entropy,
)


# ── build_rate_series ───────────────────────────────────────────────────


def test_rate_series_bins_extractions_correctly():
    extractions = [
        {"cluster_id": 1, "ts": "2026-05-07T09:00:00Z", "slots": []},
        {"cluster_id": 1, "ts": "2026-05-07T09:00:00Z", "slots": []},
        {"cluster_id": 2, "ts": "2026-05-07T09:00:05Z", "slots": []},
    ]
    series, bs, n_bins = build_rate_series(extractions, bin_seconds=1.0)
    assert bs == 1.0
    assert n_bins == 6
    assert series[1][0] == 2 and series[1][5] == 0
    assert series[2][0] == 0 and series[2][5] == 1


def test_rate_series_handles_empty_extractions():
    series, _, n_bins = build_rate_series([])
    assert series == {} and n_bins == 0


# ── Granger ──────────────────────────────────────────────────────────────


def _causal_xy(n: int = 80, seed: int = 0):
    """x random, y is x shifted by 2 + small noise — true x→y."""
    rng = np.random.default_rng(seed)
    x = rng.poisson(2.0, size=n)
    y = np.concatenate([[0, 0], x[:-2]]) + rng.poisson(0.3, size=n)
    return x, y


def test_granger_detects_known_causal_relationship():
    x, y = _causal_xy()
    res = granger_test(x, y, max_lag=3)
    assert res.ok
    assert res.p_value < GRANGER_P_THRESHOLD


def test_granger_rejects_reverse_direction():
    x, y = _causal_xy()
    res = granger_test(y, x, max_lag=3)
    assert not res.ok
    assert res.p_value > GRANGER_P_THRESHOLD


def test_granger_rejects_unrelated_series():
    rng = np.random.default_rng(1)
    u = rng.poisson(2.0, size=80)
    v = rng.poisson(2.0, size=80)
    res = granger_test(u, v, max_lag=3)
    assert not res.ok


def test_granger_handles_too_few_bins_gracefully():
    res = granger_test(np.array([1, 2]), np.array([2, 3]), max_lag=3)
    assert not res.ok
    assert "too few bins" in (res.error or "")


# ── Transfer entropy ───────────────────────────────────────────────────


def test_transfer_entropy_z_high_for_causal():
    x, y = _causal_xy()
    z = transfer_entropy(x, y, lag=2)
    assert z > TE_Z_THRESHOLD


def test_transfer_entropy_z_low_for_unrelated():
    rng = np.random.default_rng(7)
    u = rng.poisson(2.0, size=80)
    v = rng.poisson(2.0, size=80)
    z = transfer_entropy(u, v, lag=2)
    assert z < TE_Z_THRESHOLD


# ── Triangulation gate end-to-end ──────────────────────────────────────


def _seed_edges_and_extractions():
    """Build a small in-memory DB with one strong directed edge and
    one fluke directed edge that passes PMI/temporal but no statistical
    test."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE log_entity_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src TEXT, dst TEXT, pmi REAL, cooccurrence_count INTEGER,
            temporal_lead_ratio REAL, directed INTEGER, created_at TEXT,
            UNIQUE(src, dst)
        );
    """)
    conn.execute(
        "INSERT INTO log_entity_edges (src, dst, pmi, cooccurrence_count, "
        "temporal_lead_ratio, directed) VALUES "
        "('cause', 'effect', 4.0, 50, 0.95, 1), "
        "('rand_a', 'rand_b', 4.0, 50, 0.95, 1)"
    )
    conn.commit()

    # Extractions: 80 records building the causal series for cluster 1
    # and unrelated noise for clusters 3/4.
    extractions = []
    rng = np.random.default_rng(0)
    x = rng.poisson(2.0, size=80)
    y = np.concatenate([[0, 0], x[:-2]]) + rng.poisson(0.3, size=80)
    base_ts = 1700000000
    for i in range(80):
        for _ in range(int(x[i])):
            extractions.append({
                "cluster_id": 1, "ts": _iso(base_ts + i),
                "slots": ["cause"], "trace_id": None,
            })
        for _ in range(int(y[i])):
            extractions.append({
                "cluster_id": 2, "ts": _iso(base_ts + i),
                "slots": ["effect"], "trace_id": None,
            })
    # Independent noise feeding the second edge (rand_a, rand_b).
    rng2 = np.random.default_rng(99)
    for i in range(80):
        for _ in range(int(rng2.poisson(1.0))):
            extractions.append({
                "cluster_id": 3, "ts": _iso(base_ts + i),
                "slots": ["rand_a"], "trace_id": None,
            })
        for _ in range(int(rng2.poisson(1.0))):
            extractions.append({
                "cluster_id": 4, "ts": _iso(base_ts + i),
                "slots": ["rand_b"], "trace_id": None,
            })
    return conn, extractions


def _iso(epoch_seconds: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def test_triangulation_keeps_causal_drops_random():
    conn, extractions = _seed_edges_and_extractions()
    try:
        candidates = find_causality_candidates(extractions, conn)
        pairs = {(c.src, c.dst) for c in candidates}
        assert ("cause", "effect") in pairs
        assert ("rand_a", "rand_b") not in pairs
    finally:
        conn.close()


def test_triangulation_records_via_field():
    conn, extractions = _seed_edges_and_extractions()
    try:
        for c in find_causality_candidates(extractions, conn):
            if (c.src, c.dst) == ("cause", "effect"):
                assert c.via in ("granger", "transfer-entropy")
                assert c.confidence > 0.4
                break
        else:
            pytest.fail("cause → effect candidate missing")
    finally:
        conn.close()
