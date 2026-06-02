"""T3.1 — Hierarchical regime modeling.

Acceptance gate (roadmap §3.T3.1):
- A cross-service shared global mode (e.g. weekly maintenance)
  must be discovered AS the top-level regime, separately from
  the per-service regimes L8 already finds.
- Per-(Z, service) model bank lookups return the correct model
  for the trajectory's global-regime context.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("hmmlearn")
pytest.importorskip("scipy")

from sequence_learner import Trajectory                              # noqa: E402
from sequence_learner_hierarchical import (                          # noqa: E402
    G_MAX, HierarchicalRegimeModel, WindowAssignment,
    fit_hierarchical_regimes,
)


# ── Synthetic corpora ─────────────────────────────────────────────────


def _make_traj(service, host, cluster_ids,
               base_ts="2026-05-28 10:00:00"):
    return Trajectory(
        service=service, host=host,
        cluster_ids=list(cluster_ids),
        timestamps=[f"{base_ts}.{i:03d}" for i in range(len(cluster_ids))],
    )


def _cross_service_corpus(n_traj_per_service=12, seed=0):
    """Two services that both have a shared "maintenance" global
    mode. In maintenance: each service uses pattern A. In normal:
    each uses pattern B. The hierarchical model should discover the
    global regime, the flat L8 model cannot.
    """
    rng = random.Random(seed)
    per_service = {}
    pattern_normal_a   = [1, 2, 3, 4, 5, 2, 3]
    pattern_maint_a    = [10, 11, 12, 13, 14, 11, 12]
    pattern_normal_b   = [20, 21, 22, 23, 24, 21, 22]
    pattern_maint_b    = [30, 31, 32, 33, 34, 31, 32]

    # First half of timeline = "normal", second half = "maintenance".
    svc_a, svc_b = [], []
    for i in range(n_traj_per_service):
        # Alternate normal / maintenance per "window" of N traj.
        in_maint = i >= n_traj_per_service // 2
        if in_maint:
            svc_a.append(_make_traj("svc-a", f"ha{i:02d}",
                                     pattern_maint_a))
            svc_b.append(_make_traj("svc-b", f"hb{i:02d}",
                                     pattern_maint_b))
        else:
            svc_a.append(_make_traj("svc-a", f"ha{i:02d}",
                                     pattern_normal_a))
            svc_b.append(_make_traj("svc-b", f"hb{i:02d}",
                                     pattern_normal_b))
    per_service["svc-a"] = svc_a
    per_service["svc-b"] = svc_b
    return per_service


# ── Top-level fit ─────────────────────────────────────────────────────


def test_fit_returns_hierarchical_model_with_n_global_regimes():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    assert isinstance(model, HierarchicalRegimeModel)
    assert model.n_global_regimes == 2
    assert model.services == sorted(per_service.keys())


def test_fit_caps_global_regimes_at_g_max():
    per_service = _cross_service_corpus(n_traj_per_service=6)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=999)
    assert model.n_global_regimes <= G_MAX


def test_fit_returns_window_assignments():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    assert len(model.window_assignments) == 8
    for wa in model.window_assignments:
        assert isinstance(wa, WindowAssignment)
        assert 0 <= wa.global_regime < model.n_global_regimes


def test_fit_per_global_service_model_bank_is_populated():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    # At least one (Z, service) pair has a fitted regime model.
    assert model.per_global_service_models
    for (Z, service), m in model.per_global_service_models.items():
        assert 0 <= Z < model.n_global_regimes
        assert service in model.services
        assert m is not None


def test_model_for_returns_correct_regime_model():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    for (Z, service), m in model.per_global_service_models.items():
        assert model.model_for(Z, service) is m


def test_model_for_unknown_pair_returns_none():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    assert model.model_for(999, "nonexistent") is None


def test_global_mixing_sums_to_one():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    total = sum(model.global_mixing)
    assert abs(total - 1.0) < 1e-6


def test_empty_input_returns_empty_model():
    model = fit_hierarchical_regimes({}, n_global_regimes=2)
    assert model.services == []
    assert model.per_global_service_models == {}
    assert model.window_assignments == []


# ── Hero acceptance gate ─────────────────────────────────────────────


def test_acceptance_gate_global_regime_separates_maintenance_from_normal():
    """The hero claim of T3.1: on a corpus where both services share
    a maintenance window, the top-level regime assignment should
    partition the timeline into 'maintenance' and 'normal' windows.

    We don't enforce a specific label mapping (the algorithm assigns
    integer IDs to global regimes), but we DO require that windows
    in the same true partition share the same assigned global regime
    AT BETTER-THAN-CHANCE rate.
    """
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    # The first 4 windows are "normal", last 4 are "maintenance".
    # The algorithm should assign the same Z to windows within a
    # half, and different Zs across halves. We measure by:
    #   - For each true partition, what's the dominant assigned Z?
    #   - If the dominant Zs differ between partitions, gate passes.
    assigns = [wa.global_regime for wa in model.window_assignments]
    if len(assigns) < 8:
        pytest.skip("not enough windows to evaluate the gate")
    normal_half = assigns[:4]
    maint_half  = assigns[4:]
    # Majority Z per half.
    norm_dom = max(set(normal_half), key=normal_half.count)
    maint_dom = max(set(maint_half), key=maint_half.count)
    assert norm_dom != maint_dom, (
        f"hierarchical model did not separate maintenance from "
        f"normal: normal_half={normal_half} maint_half={maint_half}"
    )


def test_alternating_em_converges_or_hits_max_iter():
    """The algorithm should converge (assignments stop changing) on
    a clean corpus, or hit max_outer_iter."""
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(
        per_service, n_global_regimes=2, n_windows=8,
        max_outer_iter=20,
    )
    assert 1 <= model.n_iter <= 20


def test_as_dict_returns_serialisable_summary():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    d = model.as_dict()
    assert {"n_global_regimes", "services", "n_per_pair_models",
             "global_mixing", "n_windows", "duration_s",
             "n_iter", "converged"} <= set(d)


def test_window_assignment_carries_services_present():
    per_service = _cross_service_corpus(n_traj_per_service=12)
    model = fit_hierarchical_regimes(per_service, n_global_regimes=2,
                                      n_windows=8)
    for wa in model.window_assignments:
        # Every window has at least one service contributing.
        assert wa.services_present
        for s in wa.services_present:
            assert s in model.services
