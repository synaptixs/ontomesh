"""L10 — Variational Bayesian HMM with categorical emissions.

Roadmap §3.L10 acceptance gates:

  1. Reliability diagram (10-bin) shows ECE < 0.05 on a held-out
     synthetic corpus.
  2. The 0.6 hand-tuned confidence floor is gone — calibrated
     confidence is a real posterior probability.
  3. Existing tests (test_sequence_learner.py) still pass with the
     EM path. (Covered in test_sequence_learner.py — not retested
     here; we just verify the VB path doesn't pollute that contract.)

This file also covers basic correctness: ELBO is finite and improves
during fitting; posterior predictive returns sane (μ, σ); model
averaging selects a K with finite ELBO.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("scipy")

from vb_hmm import (                                              # noqa: E402
    VBHMM, fit_vb_hmm_with_model_averaging, N_SAMPLES,
)


# ── Synthetic corpora ─────────────────────────────────────────────────


def _make_normal_corpus(n_seqs=40, seq_len=20, alphabet=6, seed=0):
    """Sequences sampled from a fixed 'normal' generator (a hard-coded
    HMM). Returns a list of int arrays."""
    rng = np.random.RandomState(seed)
    # Two-state generator: state 0 emits {0,1,2}, state 1 emits {3,4,5}.
    # Sticky transitions so sequences have runs (mimics log corpora).
    A_true = np.array([[0.85, 0.15], [0.15, 0.85]])
    B_true = np.array([
        [0.5, 0.3, 0.2, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.2, 0.3, 0.5],
    ])
    seqs = []
    for _ in range(n_seqs):
        z = 0 if rng.rand() < 0.5 else 1
        obs = []
        for _ in range(seq_len):
            obs.append(int(rng.choice(alphabet, p=B_true[z])))
            z = int(rng.choice(2, p=A_true[z]))
        seqs.append(np.asarray(obs, dtype=int))
    return seqs


def _make_anomaly_sequence(seq_len=20, alphabet=6, seed=99):
    """A sequence from a clearly DIFFERENT generator (uniform over
    the alphabet — high entropy, no state structure). VB-HMM trained
    on the normal corpus should rate this as anomalous."""
    rng = np.random.RandomState(seed)
    return np.asarray(rng.choice(alphabet, size=seq_len), dtype=int)


# ── Basic correctness ─────────────────────────────────────────────────


def test_fit_returns_finite_elbo():
    seqs = _make_normal_corpus(n_seqs=20, seq_len=15)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(seqs)
    elbo = vb.elbo()
    assert math.isfinite(elbo)


def test_fit_empty_sequences_raises():
    with pytest.raises(ValueError):
        VBHMM(n_states=2, alphabet=6).fit([])
    with pytest.raises(ValueError):
        VBHMM(n_states=2, alphabet=6).fit([np.empty(0, dtype=int)])


def test_score_returns_finite_logZ_for_in_distribution():
    seqs = _make_normal_corpus(n_seqs=30, seq_len=20)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(seqs)
    logZ = vb.score(seqs[0])
    assert math.isfinite(logZ)


def test_posterior_predictive_returns_sane_mu_sigma():
    seqs = _make_normal_corpus(n_seqs=30, seq_len=20)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(seqs)
    mu, sigma = vb.posterior_predictive_per_step_logL(seqs[0], n_samples=16)
    assert math.isfinite(mu)
    assert sigma >= 0.0
    # For a well-fit posterior on in-distribution data, sigma should
    # be a sane finite number (no exploded variance).
    assert sigma < 10.0


# ── No more 0.6 floor — calibrated confidence behaves like a probability ──


def test_calibrated_confidence_is_bounded_in_unit_interval():
    seqs = _make_normal_corpus(n_seqs=30, seq_len=20)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(seqs)
    threshold = -1.5     # arbitrary
    for s in seqs[:10]:
        c = vb.calibrated_confidence(s, threshold, n_samples=16)
        assert 0.0 <= c <= 1.0


def test_calibrated_confidence_is_higher_on_anomaly_than_normal():
    """The whole point: a sequence from a different generator
    should score higher anomaly-confidence than a sample from the
    training generator, even with no 0.6 floor."""
    seqs = _make_normal_corpus(n_seqs=40, seq_len=20)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(seqs)
    # Threshold at the 5th percentile of per-step logL across
    # training sequences (matches the v1 anomaly-threshold contract).
    per_step = [vb.score(s) / s.size for s in seqs]
    threshold = float(np.percentile(per_step, 5.0))

    normal_conf = np.mean([
        vb.calibrated_confidence(s, threshold, n_samples=16)
        for s in seqs
    ])
    anomaly_conf = np.mean([
        vb.calibrated_confidence(
            _make_anomaly_sequence(seq_len=20, alphabet=6, seed=s),
            threshold, n_samples=16,
        )
        for s in range(50, 60)
    ])
    assert anomaly_conf > normal_conf, (
        f"Anomalies should score higher confidence than normals; "
        f"got anomaly={anomaly_conf:.3f} normal={normal_conf:.3f}"
    )


def test_no_06_floor_in_confidence_path():
    """Sanity check that we can produce a confidence below 0.6 for
    clearly-not-anomalous data. The v1 code path would clamp this."""
    seqs = _make_normal_corpus(n_seqs=40, seq_len=20)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(seqs)
    # Pick a threshold so the in-distribution sequences sit well above
    # it — confidence should drop near zero.
    per_step = [vb.score(s) / s.size for s in seqs]
    threshold = float(np.percentile(per_step, 1.0)) - 1.0
    cs = [vb.calibrated_confidence(s, threshold, n_samples=16) for s in seqs]
    # At least some confidences must be below 0.6 — that's the proof
    # there's no hand-tuned floor.
    assert min(cs) < 0.6


# ── Model averaging ───────────────────────────────────────────────────


def test_model_averaging_returns_best_K():
    seqs = _make_normal_corpus(n_seqs=30, seq_len=20)
    model, elbo, results = fit_vb_hmm_with_model_averaging(
        seqs, alphabet=6, k_candidates=(2, 3, 4),
    )
    assert isinstance(model, VBHMM)
    assert math.isfinite(elbo)
    assert len(results) >= 1
    # Best result should have the highest ELBO of all candidates.
    assert elbo == max(r[1] for r in results)


# ── Acceptance gate: ECE < 0.05 on synthetic data ─────────────────────


def _compute_ece(confidences, labels, n_bins=10):
    """Expected Calibration Error with equal-width bins. Standard
    Naeini-2015 definition."""
    confidences = np.asarray(confidences, dtype=float)
    labels = np.asarray(labels, dtype=int)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(confidences)
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            in_bin = (confidences >= lo) & (confidences <= hi)
        else:
            in_bin = (confidences >= lo) & (confidences < hi)
        bin_size = int(in_bin.sum())
        if bin_size == 0:
            continue
        avg_conf = float(confidences[in_bin].mean())
        accuracy = float(labels[in_bin].mean())
        ece += (bin_size / n) * abs(avg_conf - accuracy)
    return ece


def test_ece_below_acceptance_threshold():
    """The hero acceptance gate from roadmap §3.L10:

    'Reliability diagram (10-bin) shows ECE < 0.05 on a held-out
     synthetic corpus.'

    We build a held-out set of normal + anomaly sequences with known
    labels, run calibrated_confidence on each, and check that the
    confidence is a well-calibrated probability of anomaly. Longer
    sequences sharpen the per-step logL distribution, and a generous
    Monte-Carlo sample count keeps the predictive variance estimate
    stable.
    """
    train = _make_normal_corpus(n_seqs=80, seq_len=40, seed=0)
    vb = VBHMM(n_states=2, alphabet=6, random_state=0).fit(train)

    per_step_train = [vb.score(s) / s.size for s in train]
    threshold = float(np.percentile(per_step_train, 5.0))

    # Held-out set: 40 normals + 40 anomalies, longer sequences so
    # the per-step logL separation is sharp.
    held_normal = _make_normal_corpus(n_seqs=40, seq_len=40, seed=1)
    held_anomaly = [
        _make_anomaly_sequence(seq_len=40, alphabet=6, seed=200 + i)
        for i in range(40)
    ]
    confidences = []
    labels = []
    n_samples = 64
    for s in held_normal:
        confidences.append(
            vb.calibrated_confidence(s, threshold, n_samples=n_samples))
        labels.append(0)
    for s in held_anomaly:
        confidences.append(
            vb.calibrated_confidence(s, threshold, n_samples=n_samples))
        labels.append(1)

    ece = _compute_ece(confidences, labels, n_bins=10)
    assert ece < 0.05, f"ECE {ece:.4f} ≥ 0.05 acceptance threshold"


# ── Integration: VB path through sequence_learner ─────────────────────


def test_sequence_learner_vb_path_produces_calibrated_confidence():
    """End-to-end check that ``mine_sequences(inference='vb')`` runs
    through fit + score and emits LOG_EVENT proposals whose
    confidence is the calibrated probability (not the 0.6 heuristic
    floor). Uses a tiny synthetic corpus to keep the test fast."""
    import sqlite3
    from sequence_learner import (
        Trajectory, fit_hmms, score_anomalies, build_trajectories,
    )

    # Build a corpus through the public sequence_learner API. We mix
    # one truly anomalous trajectory in with a stack of normals.
    rng = random.Random(0)
    extractions = []
    base_ts = "2026-05-28 10:00:00"
    normal = [1, 2, 3, 4, 5, 2, 3, 4, 5]
    for i in range(20):
        for j, cid in enumerate(normal):
            extractions.append({
                "service": "svc-a",
                "trace_id": f"h{i:02d}-x",
                "ts": f"{base_ts}.{i:03d}{j:02d}",
                "cluster_id": cid,
            })
    # One off-pattern trajectory (uniform-ish over a wider alphabet).
    weird = [9, 8, 7, 6, 9, 8, 7, 6, 9]
    for j, cid in enumerate(weird):
        extractions.append({
            "service": "svc-a",
            "trace_id": "hxx-x",
            "ts": f"{base_ts}.999{j:02d}",
            "cluster_id": cid,
        })

    trajectories = build_trajectories(extractions)
    fitted = fit_hmms(trajectories, inference="vb", min_states=2, max_states=3)
    assert "svc-a" in fitted

    hits = score_anomalies(trajectories, fitted)
    # VB confidences should not exactly equal the legacy heuristic
    # floor values 0.5 / 0.6 / 0.7 / 0.8 — those values are what the
    # EM path emits when the floor clamps. The VB path passes the
    # raw posterior probability through.
    for h in hits:
        assert h.confidence not in (0.5, 0.6, 0.7, 0.8), (
            f"VB confidence equals an EM heuristic floor: {h.confidence}"
        )
        assert 0.0 <= h.confidence <= 1.0
