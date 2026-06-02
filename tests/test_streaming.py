"""T1.3 — Streaming / incremental mining.

Acceptance gates (roadmap §3.T1.3):
- Streaming replay produces the same regime assignments and rate-
  anomaly flags as a batch refit (within tolerance).
- Per-update latency p99 ≤ 100 ms.

This file covers both wrappers (L8 + L13) plus the latency helper.
"""

from __future__ import annotations

import datetime as _dt
import math
import random
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("hmmlearn")
pytest.importorskip("sklearn")
pytest.importorskip("scipy")

from sequence_learner import Trajectory                              # noqa: E402
from sequence_learner_regimes import (                               # noqa: E402
    fit_regime_model_for_service, score_regime_anomalies,
    _trajectory_id,
)
from streaming import (                                              # noqa: E402
    LatencyReport, StreamingRateDetector, StreamingRegimeModel,
    measure_latency,
)


# ── Synthetic corpora ─────────────────────────────────────────────────


def _two_regime_corpus(n_per_regime=12, seed=0):
    """Same fixture L8 tests use. Two visibly distinct patterns."""
    rng = random.Random(seed)
    trajs = []
    for i in range(n_per_regime):
        pattern_a = [1, 2, 3, 4, 5, rng.choice([2, 3]), 4, 5]
        trajs.append(Trajectory(
            service="svc-a", host=f"ha{i:02d}",
            cluster_ids=pattern_a,
            timestamps=[f"2026-05-28 10:00:00.{i:03d}{j:02d}"
                        for j in range(len(pattern_a))],
        ))
    for i in range(n_per_regime):
        pattern_b = [10, 11, 12, 13, 14, rng.choice([11, 12]), 13, 14]
        trajs.append(Trajectory(
            service="svc-a", host=f"hb{i:02d}",
            cluster_ids=pattern_b,
            timestamps=[f"2026-05-28 02:00:00.{i:03d}{j:02d}"
                        for j in range(len(pattern_b))],
        ))
    return trajs


def _diurnal_extractions(days=7, cluster_ids=(1,), seed=0,
                         base_rate=4, spike_at=None, spike_count=80):
    rng = random.Random(seed)
    start = _dt.date(2026, 4, 6)
    out = []
    for day in range(days):
        d = start + _dt.timedelta(days=day)
        for hour in range(24):
            b = base_rate * (
                0.2 + 0.8 * max(0, math.sin((hour - 4) / 24.0 * 3.1416))
            )
            n = max(0, int(round(rng.gauss(max(1.0, b), 0.6))))
            for cid in cluster_ids:
                for _ in range(n):
                    out.append({
                        "cluster_id": cid,
                        "ts": (f"{d.isoformat()} {hour:02d}:"
                               f"{rng.randint(0,59):02d}:00"),
                    })
            if spike_at is not None:
                sd, sh, scid = spike_at
                if day == sd and hour == sh:
                    for _ in range(spike_count):
                        out.append({
                            "cluster_id": scid,
                            "ts": (f"{d.isoformat()} {hour:02d}:"
                                   f"{rng.randint(0,59):02d}:00"),
                        })
    return out


# ── L8 — StreamingRegimeModel ─────────────────────────────────────────


def test_streaming_regime_assigns_same_regime_as_batch():
    """The hero acceptance gate: streaming replay produces the same
    regime assignments as the batch fit."""
    trajs = _two_regime_corpus(n_per_regime=12)
    result = fit_regime_model_for_service(trajs)
    assert result is not None
    batch_model, batch_assigns = result

    stream = StreamingRegimeModel(batch_model)
    batch_by_id = {a.trajectory_id: a.regime_id for a in batch_assigns}
    matches = 0
    for t in trajs:
        sa = stream.assign(t)
        if batch_by_id[sa.trajectory_id] == sa.regime_id:
            matches += 1
    # Allow a tiny margin — streaming uses the frozen HMMs which
    # were also the batch HMMs, so assignments should match in the
    # majority of cases.
    assert matches >= int(0.85 * len(trajs)), (
        f"streaming matched batch on {matches}/{len(trajs)} trajectories"
    )


def test_streaming_regime_update_index_increments():
    trajs = _two_regime_corpus(n_per_regime=10)
    model, _ = fit_regime_model_for_service(trajs)
    stream = StreamingRegimeModel(model)
    a1 = stream.assign(trajs[0])
    a2 = stream.assign(trajs[1])
    assert a1.update_index == 1
    assert a2.update_index == 2
    assert a1.consolidate_index == 0


def test_streaming_regime_consolidate_refits_and_bumps_counter():
    trajs = _two_regime_corpus(n_per_regime=10)
    model, _ = fit_regime_model_for_service(trajs)
    stream = StreamingRegimeModel(model)
    for t in trajs:
        stream.assign(t)
    report = stream.consolidate(trajs)
    assert report["trajectories"] == len(trajs)
    assert report.get("consolidate_index") == 1
    a = stream.assign(trajs[0])
    assert a.consolidate_index == 1


def test_streaming_regime_latency_under_budget():
    """p99 per-update latency ≤ 100 ms (roadmap §3.T1.3)."""
    trajs = _two_regime_corpus(n_per_regime=15)
    model, _ = fit_regime_model_for_service(trajs)
    stream = StreamingRegimeModel(model)
    timings = []
    for t in trajs:
        t0 = time.perf_counter()
        stream.assign(t)
        timings.append(time.perf_counter() - t0)
    report = measure_latency(timings)
    assert report.p99_ms <= 100.0, (
        f"L8 streaming p99 = {report.p99_ms:.1f} ms; budget 100 ms"
    )


def test_streaming_regime_decay_keeps_alpha_bounded():
    """With decay < 1, alpha shouldn't grow unboundedly even after
    many updates."""
    trajs = _two_regime_corpus(n_per_regime=10)
    model, _ = fit_regime_model_for_service(trajs)
    stream = StreamingRegimeModel(model, decay=0.95)
    for _ in range(100):
        stream.assign(trajs[0])
    # Without decay, alpha would grow by 100; with decay=0.95 it
    # converges to a bounded steady-state.
    assert max(stream.mixing_alpha) < 50.0


# ── L13 — StreamingRateDetector ───────────────────────────────────────


def test_streaming_rate_detects_spike_after_buffer_fills():
    """Build up a few days of baseline observations, then inject a
    spike — must flag."""
    det = StreamingRateDetector()
    # 6 days of normal counts (≈ 1–3) at hour 3
    rng = random.Random(0)
    for day in range(6):
        c = rng.choice([1, 2, 2, 3])
        det.observe(cluster_id=1, hour=3, count=c)
    # Day 7: huge spike
    obs = det.observe(cluster_id=1, hour=3, count=80)
    assert obs.is_anomaly is True
    assert obs.direction == "spike"
    assert obs.z_score > 2.0


def test_streaming_rate_buffer_warm_up_does_not_flag():
    """First few observations have an empty / tiny buffer — we must
    NOT flag them as anomalies; the detector waits to warm up."""
    det = StreamingRateDetector()
    obs1 = det.observe(cluster_id=2, hour=4, count=99)
    obs2 = det.observe(cluster_id=2, hour=4, count=98)
    # Below the (len(bucket) >= 3) threshold → never flagged.
    assert obs1.is_anomaly is False
    assert obs2.is_anomaly is False


def test_streaming_rate_normal_values_inside_band_dont_flag():
    det = StreamingRateDetector()
    rng = random.Random(0)
    for _ in range(20):
        obs = det.observe(cluster_id=3, hour=10,
                          count=rng.choice([5, 6, 7, 6, 5]))
    assert obs.is_anomaly is False


def test_streaming_rate_consolidate_caches_gp_for_eligible_templates():
    det = StreamingRateDetector()
    # Seed enough observations across multiple hours for L13's GP
    # fit to succeed.
    rng = random.Random(0)
    for day in range(7):
        for hour in range(24):
            count = max(0, int(round(4 + rng.gauss(0, 0.6))))
            det.observe(cluster_id=5, hour=hour, count=count)
    report = det.consolidate()
    assert report["fitted"] >= 1
    assert det.has_gp_for(5)


def test_streaming_rate_after_consolidate_uses_gp_baseline():
    det = StreamingRateDetector()
    rng = random.Random(0)
    for day in range(7):
        for hour in range(24):
            count = max(0, int(round(4 + rng.gauss(0, 0.6))))
            det.observe(cluster_id=6, hour=hour, count=count)
    det.consolidate()
    # Next observation should use the GP path now.
    obs = det.observe(cluster_id=6, hour=10, count=5)
    assert obs.via == "gp_predictive"


def test_streaming_rate_latency_under_budget():
    """p99 per-update latency ≤ 100 ms even after the buffer fills."""
    det = StreamingRateDetector()
    rng = random.Random(0)
    timings = []
    for day in range(7):
        for hour in range(24):
            t0 = time.perf_counter()
            det.observe(cluster_id=7, hour=hour, count=rng.choice([3, 4, 5]))
            timings.append(time.perf_counter() - t0)
    report = measure_latency(timings)
    assert report.p99_ms <= 100.0, (
        f"L13 streaming p99 = {report.p99_ms:.1f} ms; budget 100 ms"
    )


# ── Latency helper ────────────────────────────────────────────────────


def test_measure_latency_handles_empty_list():
    r = measure_latency([])
    assert r.n_calls == 0


def test_measure_latency_percentiles_are_monotonic():
    timings = [0.001, 0.002, 0.003, 0.004, 0.005,
               0.010, 0.020, 0.050, 0.100, 0.200]
    r = measure_latency(timings)
    assert r.p50_ms <= r.p95_ms <= r.p99_ms <= r.max_ms


# ── End-to-end mixed workload ─────────────────────────────────────────


def test_mixed_workload_both_wrappers_run_to_completion():
    """Sanity check: interleave L8 + L13 updates to confirm there's
    no shared mutable state between the two wrappers."""
    trajs = _two_regime_corpus(n_per_regime=10)
    model, _ = fit_regime_model_for_service(trajs)
    regime_stream = StreamingRegimeModel(model)
    rate_stream = StreamingRateDetector()
    for i, t in enumerate(trajs):
        regime_stream.assign(t)
        rate_stream.observe(cluster_id=i % 4, hour=i % 24, count=5 + (i % 3))
    assert regime_stream._n_updates == len(trajs)
    assert rate_stream.n_observations() == len(trajs)
