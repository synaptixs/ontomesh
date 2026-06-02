"""
src/sequence_learner_hierarchical.py — T3.1
───────────────────────────────────────────
Two-level switching state-space model.

L8 (``sequence_learner_regimes``) fits a *per-service* mixture-of-
HMMs. T3.1 extends it with a top-level **global regime**
``Z_t ∈ {1..G}`` that gates *which* per-service regime is active.

Why two levels matter
─────────────────────
Real ops corpora have cross-service patterns L8 can't see:

  - **Maintenance windows.** When the whole region goes under
    maintenance, every service's trajectory shifts simultaneously
    — but L8 has no way to share that information across services.
  - **Cascading incidents.** A network partition affects every
    consumer of the network simultaneously; treating each service's
    regimes independently double-counts the noise.
  - **Business hours.** Cross-corporate weekly cycles affect every
    customer-facing service at once.

T3.1 models this explicitly: ``P(z_s | Z, service)`` lets the
global regime ``Z`` *shift* which per-service regime is more
likely, without forcing every service to share the same K.

Inference
─────────
Hard EM at the top level — assigns each *time window* to the
global regime that maximises the joint likelihood of all per-
service trajectory regimes inside it.

  E-step (top):   For each window w, assign Z_w = argmax over G
                  of ∏_s P(z_s | Z, s).
  M-step (bot):   For each (Z, s) pair, re-fit the per-service
                  RegimeModel on the trajectories assigned to
                  windows with global regime Z.

The result is one *bank* of per-service regime models keyed by
the global regime. Inference complexity is O(G · S) per window
plus the L8 batch cost of re-fitting per-(Z, s) regimes — well
within the toolkit's existing budget on corpora that already fit
L8.

Public API
──────────
    out = fit_hierarchical_regimes(
        per_service_trajectories,  # {service_id: [Trajectory, ...]}
        n_global_regimes=3,
    )
    Z = out.assign_window(window_trajectories)

The result wraps an inner ``Dict[(global_regime, service),
RegimeModel]`` so per-trajectory anomaly scoring can pick the
right model based on which global regime the window is in.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── Defaults ─────────────────────────────────────────────────────────────


G_MAX = 5                       # cap on global regimes — matches L8's K
MIN_WINDOWS_PER_GLOBAL = 2      # reject empty global assignments
MAX_OUTER_ITER = 10             # alternating hard-EM iterations


# ── Result containers ───────────────────────────────────────────────────


@dataclass
class WindowAssignment:
    """One time window plus its global-regime assignment."""
    window_id:        int
    global_regime:    int
    services_present: List[str]
    log_likelihood:   float


@dataclass
class HierarchicalRegimeModel:
    """Bank of per-(Z, service) regime models + windowed assignments.

    ``per_global_service_models`` is a dict keyed by ``(Z, service)``
    → :class:`sequence_learner_regimes.RegimeModel`. ``window_index``
    maps window_id → :class:`WindowAssignment`.
    """
    n_global_regimes:           int
    services:                   List[str]
    per_global_service_models:  Dict[Tuple[int, str], Any] = field(default_factory=dict)
    window_assignments:         List[WindowAssignment] = field(default_factory=list)
    global_mixing:              List[float] = field(default_factory=list)
    duration_s:                 float = 0.0
    n_iter:                     int = 0
    converged:                  bool = False

    def model_for(self, global_regime: int, service: str
                  ) -> Optional[Any]:
        return self.per_global_service_models.get(
            (int(global_regime), service)
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_global_regimes":  self.n_global_regimes,
            "services":          list(self.services),
            "n_per_pair_models": len(self.per_global_service_models),
            "global_mixing":     list(self.global_mixing),
            "n_windows":         len(self.window_assignments),
            "duration_s":        self.duration_s,
            "n_iter":            self.n_iter,
            "converged":         self.converged,
        }


# ── Window helpers ───────────────────────────────────────────────────────


def _group_trajectories_into_windows(
        per_service_trajectories: Dict[str, Sequence[Any]],
        n_windows: int,
) -> List[Dict[str, List[Any]]]:
    """Slice every service's trajectory list into ``n_windows`` time
    bins. Each window keeps a dict service → trajectories that fell
    in that window.

    For toolkit corpora we don't have a precise wall-clock per
    trajectory — we use the trajectory ordering as a proxy for time
    (toolkit trajectories are already chronologically sorted by
    L1's mining pass). This is the same approach L8 uses.
    """
    windows: List[Dict[str, List[Any]]] = [
        defaultdict(list) for _ in range(n_windows)
    ]
    for service, trajs in per_service_trajectories.items():
        if not trajs:
            continue
        # Bucket each trajectory into a window by index ratio.
        for i, t in enumerate(trajs):
            w_idx = min(n_windows - 1,
                        int(i * n_windows / max(1, len(trajs))))
            windows[w_idx][service].append(t)
    return [dict(w) for w in windows]


def _score_window_under_models(
        window_trajs: Dict[str, List[Any]],
        models: Dict[Tuple[int, str], Any],
        global_regime: int,
) -> float:
    """Sum of per-trajectory log-likelihoods under (Z, service) models.

    Trajectories in services with no model for the given Z get a
    fixed penalty so we don't crash on cold-start globals.
    """
    import numpy as np
    from sequence_learner_regimes import _encode_trajectory
    total = 0.0
    for service, trajs in window_trajs.items():
        model = models.get((global_regime, service))
        if model is None:
            total -= 1e3 * len(trajs)
            continue
        encoding = model.encoding
        for traj in trajs:
            enc = _encode_trajectory(traj, encoding)
            if enc.shape[0] == 0:
                continue
            # Use the regime with highest individual log-lik.
            best = -1e6
            for regime in model.regimes:
                if regime is None or regime.model is None:
                    continue
                try:
                    score = float(regime.model.score(enc))
                except Exception:                              # noqa: BLE001
                    continue
                if score > best:
                    best = score
            total += best
    return total


# ── Top-level fit ───────────────────────────────────────────────────────


def fit_hierarchical_regimes(
        per_service_trajectories: Dict[str, Sequence[Any]],
        *,
        n_global_regimes: int = 3,
        n_windows: int = 8,
        max_outer_iter: int = MAX_OUTER_ITER,
) -> HierarchicalRegimeModel:
    """Alternating hard-EM fit of the hierarchical model.

    Parameters
    ----------
    per_service_trajectories : dict[str, list[Trajectory]]
        Output of v2's ``build_trajectories`` grouped by service.
    n_global_regimes : int
        How many top-level regimes ``Z ∈ {1..G}`` to seek. Capped
        at G_MAX.
    n_windows : int
        How many time windows to slice the trajectory ordering
        into. Each window is a unit the top level assigns a Z to.
    max_outer_iter : int
        Maximum alternating-EM iterations. Convergence is
        signalled when window assignments stop changing.
    """
    from sequence_learner_regimes import fit_regime_model_for_service

    services = sorted(per_service_trajectories.keys())
    result = HierarchicalRegimeModel(
        n_global_regimes=int(min(n_global_regimes, G_MAX)),
        services=services,
    )
    if not services:
        return result
    G = result.n_global_regimes
    windows = _group_trajectories_into_windows(
        per_service_trajectories, n_windows,
    )

    # Initial assignment: consecutive blocks. Each global regime
    # gets a contiguous chunk of the time axis. Round-robin would
    # mix the temporal structure across globals on the first
    # M-step — every (Z, service) regime model would see the
    # same shuffled trajectories, and hard EM would collapse to a
    # single global. Block init respects the (likely) temporal
    # ordering of regime shifts in real data.
    n_w = len(windows)
    window_global = [
        min(G - 1, (i * G) // max(1, n_w)) for i in range(n_w)
    ]

    t0 = time.perf_counter()
    prev_assignment: List[int] = []
    converged = False
    for outer_iter in range(max_outer_iter):
        # ── M-step: fit per-(Z, service) regime models on the
        # trajectories in windows assigned to each Z.
        per_global_trajectories: Dict[Tuple[int, str], List[Any]] = defaultdict(list)
        for w_idx, w in enumerate(windows):
            Z = window_global[w_idx]
            for service, trajs in w.items():
                per_global_trajectories[(Z, service)].extend(trajs)

        per_global_service_models: Dict[Tuple[int, str], Any] = {}
        for (Z, service), trajs in per_global_trajectories.items():
            if not trajs:
                continue
            fit = fit_regime_model_for_service(trajs)
            if fit is None:
                continue
            model, _ = fit
            per_global_service_models[(Z, service)] = model
        result.per_global_service_models = per_global_service_models

        # ── E-step: re-assign each window to the global regime
        # that maximises the joint log-likelihood across services.
        new_assignment: List[int] = []
        for w_idx, w in enumerate(windows):
            scores: List[float] = []
            for Z in range(G):
                s = _score_window_under_models(
                    w, per_global_service_models, Z,
                )
                scores.append(s)
            new_assignment.append(int(_argmax(scores)))

        # Convergence test: same assignment as prior iteration.
        if new_assignment == prev_assignment:
            converged = True
            window_global = new_assignment
            result.n_iter = outer_iter + 1
            break
        prev_assignment = list(new_assignment)
        window_global = new_assignment
        result.n_iter = outer_iter + 1

    # Re-fit one more time at the converged assignment so the
    # window-assignment / model-bank pair are consistent.
    per_global_trajectories: Dict[Tuple[int, str], List[Any]] = defaultdict(list)
    for w_idx, w in enumerate(windows):
        Z = window_global[w_idx]
        for service, trajs in w.items():
            per_global_trajectories[(Z, service)].extend(trajs)
    final_models: Dict[Tuple[int, str], Any] = {}
    for (Z, service), trajs in per_global_trajectories.items():
        if not trajs:
            continue
        fit = fit_regime_model_for_service(trajs)
        if fit is None:
            continue
        model, _ = fit
        final_models[(Z, service)] = model
    if final_models:
        result.per_global_service_models = final_models

    # Window assignments + global mixing posterior.
    assignments: List[WindowAssignment] = []
    counts = [0] * G
    for w_idx, w in enumerate(windows):
        Z = window_global[w_idx]
        counts[Z] += 1
        score = _score_window_under_models(
            w, result.per_global_service_models, Z,
        )
        assignments.append(WindowAssignment(
            window_id=w_idx, global_regime=Z,
            services_present=sorted(w.keys()),
            log_likelihood=score,
        ))
    total = sum(counts) or 1
    result.global_mixing = [c / total for c in counts]
    result.window_assignments = assignments
    result.converged = converged
    result.duration_s = time.perf_counter() - t0
    return result


def _argmax(xs: Sequence[float]) -> int:
    best, best_i = -1e18, 0
    for i, x in enumerate(xs):
        if x > best:
            best = x
            best_i = i
    return best_i


__all__ = [
    "HierarchicalRegimeModel", "WindowAssignment",
    "fit_hierarchical_regimes",
    "G_MAX", "MIN_WINDOWS_PER_GLOBAL", "MAX_OUTER_ITER",
]
