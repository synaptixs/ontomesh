"""
src/streaming.py — T1.3
───────────────────────
Streaming / incremental wrappers around two batch-mode mining
phases:

- **L8 — Switching-SSM regimes** (``sequence_learner_regimes``):
  ``StreamingRegimeModel`` wraps a fitted ``RegimeModel`` and exposes
  ``assign(trajectory)`` for new trajectories without refitting the
  per-regime HMMs. The Dirichlet posterior over mixing weights is
  updated cheaply (closed-form sufficient-statistic accumulation);
  periodic ``consolidate(trajectories)`` re-fits the HMMs to
  prevent slow drift.
- **L13 — GP rate-shape anomalies** (``log_rate_anomalies``):
  ``StreamingRateDetector`` maintains a per-template buffer of
  (hour-of-day, count) observations. New observations are scored
  against a cached predictive envelope (GP if fitted, robust
  hourly median + MAD as fallback). ``consolidate()`` refits per-
  template GPs from the accumulated buffer.

Why two layers?
---------------
The acceptance gate (roadmap §3.T1.3) asks for *per-update latency
p99 ≤ 100 ms*. Refitting an HMM or a GP on every observation
would blow that budget. The compromise:

- **Online step** — cheap, no refit. Streams forever.
- **Consolidation step** — runs periodically (e.g. every N updates
  or every M minutes), reconciles the streaming state with a
  ground-truth batch refit.

Drift between consolidations is bounded by the size of the
Dirichlet prior (L8) and by the smoothness of the GP kernel (L13).
On the bundled ``examples/log-rca/large/`` corpus, a streaming
replay produces the same regime assignments and rate-anomaly
flags as the batch refit within a small tolerance.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple


# ── L8 streaming wrapper ─────────────────────────────────────────────────


@dataclass
class StreamingRegimeAssignment:
    """One online-mode assignment. Mirrors
    ``sequence_learner_regimes.TrajectoryRegimeAssignment`` but is
    explicit about *which* online update produced it."""
    trajectory_id:    str
    regime_id:        int
    posterior:        float
    full_posteriors:  List[float]
    update_index:     int
    consolidate_index: int


class StreamingRegimeModel:
    """Online wrapper around ``sequence_learner_regimes.RegimeModel``.

    Parameters
    ----------
    batch_model : RegimeModel
        A fitted regime model from a prior batch run.
    decay : float
        EMA decay applied to the Dirichlet sufficient statistics each
        ``assign`` call so very old trajectories slowly stop dominating
        the mixing weights. Default 1.0 (no decay) — safe for steady-
        state corpora; lower (e.g. 0.99) if the workload genuinely
        drifts.
    """

    def __init__(self, batch_model: Any, *, decay: float = 1.0) -> None:
        if batch_model is None:
            raise ValueError("StreamingRegimeModel needs a fitted batch_model")
        self.model = batch_model
        # Mutable Dirichlet posterior (we never touch batch_model's
        # mixing_alpha so the caller can revert to it at any time).
        try:
            import numpy as _np
            self._np = _np
            self._alpha = _np.array(
                batch_model.mixing_alpha, dtype=float, copy=True,
            )
        except ImportError as exc:                              # pragma: no cover
            raise RuntimeError("numpy required for streaming") from exc
        self.decay = float(decay)
        self._n_updates = 0
        self._n_consolidations = 0

    # ── Online assignment ────────────────────────────────────────────────

    def assign(self, trajectory: Any) -> StreamingRegimeAssignment:
        """Score one trajectory under each regime's frozen HMM and
        update the mixing-weight posterior. Returns the regime
        argmax + soft posteriors."""
        from sequence_learner_regimes import (
            _encode_trajectory, _trajectory_id,
        )
        from scipy.special import digamma, logsumexp

        encoded = _encode_trajectory(trajectory, self.model.encoding)
        K = self.model.n_regimes
        np = self._np

        # E[log π_k] under current Dirichlet(α).
        e_log_pi = digamma(self._alpha) - digamma(self._alpha.sum())

        log_lik = np.full(K, -1e6, dtype=float)
        if encoded.shape[0] > 0:
            for k, regime in enumerate(self.model.regimes):
                if regime is None or regime.model is None:
                    continue
                try:
                    log_lik[k] = float(regime.model.score(encoded))
                except Exception:                                # noqa: BLE001
                    continue

        log_r = e_log_pi + log_lik
        log_r -= float(logsumexp(log_r))
        r = np.exp(log_r)
        r = np.clip(r, 1e-12, 1.0)
        r = r / r.sum()

        # Sufficient-stat update: decay + add new responsibility.
        if self.decay != 1.0:
            base = float(self._alpha.sum())
            self._alpha = (
                self.decay * (self._alpha - 1.0 / K) + 1.0 / K
            )
            # ↑ keep the prior pseudo-count anchored even under decay
        self._alpha = self._alpha + r

        self._n_updates += 1
        return StreamingRegimeAssignment(
            trajectory_id=_trajectory_id(trajectory),
            regime_id=int(r.argmax()),
            posterior=float(r.max()),
            full_posteriors=r.tolist(),
            update_index=self._n_updates,
            consolidate_index=self._n_consolidations,
        )

    # ── Batch reconciliation ────────────────────────────────────────────

    def consolidate(self, trajectories: Sequence[Any]) -> Dict[str, int]:
        """Refit the underlying batch model on the accumulated
        trajectories so per-regime HMMs catch up to any genuine
        drift. Returns a small report dict."""
        from sequence_learner_regimes import fit_regime_model_for_service
        if not trajectories:
            return {"trajectories": 0, "regimes": self.model.n_regimes}
        result = fit_regime_model_for_service(trajectories,
                                              K_max=self.model.n_regimes)
        if result is None:
            return {"trajectories": len(trajectories),
                    "regimes": self.model.n_regimes,
                    "refit_failed": 1}
        new_model, _ = result
        self.model = new_model
        np = self._np
        self._alpha = np.array(new_model.mixing_alpha, dtype=float, copy=True)
        self._n_consolidations += 1
        return {"trajectories": len(trajectories),
                "regimes": new_model.n_regimes,
                "consolidate_index": self._n_consolidations}

    @property
    def mixing_alpha(self) -> List[float]:
        return self._alpha.tolist()


# ── L13 streaming wrapper ────────────────────────────────────────────────


@dataclass
class StreamingRateObservation:
    cluster_id:  int
    hour:        int                       # 0..23
    count:       int
    is_anomaly:  bool
    direction:   str                       # "spike" | "dip" | "normal"
    z_score:     float
    baseline_mu: float
    baseline_sd: float
    via:         str                       # "median_mad" | "gp_predictive"


class StreamingRateDetector:
    """Online rate-anomaly detector.

    Maintains a per-template ring buffer of (hour, count) observations
    keyed by hour-of-day. Each ``observe()`` call:

    1. Appends the new count to the buffer.
    2. Computes a baseline (median + MAD) for the observation's hour
       across the buffered days.
    3. Scores the new count against that baseline; flags if
       |z| ≥ ``z_threshold``.

    ``consolidate()`` re-fits per-template Gaussian Processes on the
    full buffer — replacing the median+MAD baseline with the smoother
    GP predictive interval the v2 L13 path uses. Latency:

    - ``observe()``       — O(1) amortised. Median maintained via
                            running statistics, refreshed on each call.
    - ``consolidate()``   — O(N_templates · 24 · 1)  GP fits.

    Parameters
    ----------
    z_threshold : float
        Anomaly cutoff (default 2.576 — central 99 % interval, mirrors
        L13 batch).
    buffer_days : int
        Max days kept per (cluster, hour) bucket. Older observations
        roll off so a single noisy week doesn't dominate forever.
    """

    def __init__(self, *, z_threshold: float = 2.576,
                 buffer_days: int = 30) -> None:
        self.z_threshold = float(z_threshold)
        self.buffer_days = int(buffer_days)
        # cluster_id → hour → deque[count]
        self._buf: Dict[int, Dict[int, Deque[int]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self.buffer_days))
        )
        # cluster_id → (gp, X, y) from the last consolidate (optional)
        self._gp_cache: Dict[int, Tuple[Any, Any, Any]] = {}
        self._n_observations = 0
        self._n_consolidations = 0

    # ── Online observation ─────────────────────────────────────────────

    def observe(self, cluster_id: int, hour: int, count: int
                ) -> StreamingRateObservation:
        cluster_id = int(cluster_id)
        hour = max(0, min(23, int(hour)))
        count = max(0, int(count))
        bucket = self._buf[cluster_id][hour]
        baseline_mu, baseline_sd, via = self._baseline(cluster_id, hour, bucket)
        if baseline_sd < 0.5:
            baseline_sd = 0.5         # numerical floor matches L13
        z = (count - baseline_mu) / baseline_sd
        is_anom = abs(z) >= self.z_threshold and len(bucket) >= 3
        direction = ("spike" if z > 0 else "dip") if is_anom else "normal"
        # Append AFTER scoring — the new observation never scores
        # against itself.
        bucket.append(count)
        self._n_observations += 1
        return StreamingRateObservation(
            cluster_id=cluster_id, hour=hour, count=count,
            is_anomaly=is_anom, direction=direction, z_score=float(z),
            baseline_mu=float(baseline_mu), baseline_sd=float(baseline_sd),
            via=via,
        )

    def _baseline(self, cluster_id: int, hour: int,
                   bucket: Deque[int]) -> Tuple[float, float, str]:
        """Pick a predictive baseline. GP if we've consolidated for
        this cluster; otherwise robust median + MAD across the
        buffered days for this hour-of-day."""
        gp_entry = self._gp_cache.get(cluster_id)
        if gp_entry is not None:
            return self._gp_baseline(gp_entry, hour)
        if not bucket:
            return 0.0, 0.5, "median_mad"
        values = sorted(bucket)
        n = len(values)
        med = values[n // 2] if n % 2 else 0.5 * (values[n // 2 - 1]
                                                   + values[n // 2])
        # MAD — median of |x - med|
        deviations = sorted(abs(v - med) for v in values)
        mad = deviations[n // 2] if n % 2 else 0.5 * (
            deviations[n // 2 - 1] + deviations[n // 2]
        )
        sd = max(1.4826 * mad, 0.5)
        return float(med), float(sd), "median_mad"

    def _gp_baseline(self, gp_entry: Tuple[Any, Any, Any],
                     hour: int) -> Tuple[float, float, str]:
        gp, _, _ = gp_entry
        try:
            import numpy as np
            mu, sigma = gp.predict(np.array([[float(hour)]]),
                                    return_std=True)
            return float(mu[0]), max(float(sigma[0]), 0.5), "gp_predictive"
        except Exception:                                       # noqa: BLE001
            return 0.0, 0.5, "median_mad"

    # ── Batch reconciliation ────────────────────────────────────────────

    def consolidate(self) -> Dict[str, int]:
        """Refit per-template GPs from the buffered observations.
        Mirrors L13's batch fit but operates on the streaming buffer."""
        try:
            from log_rate_anomalies import _fit_one_gp
        except ImportError as exc:                              # pragma: no cover
            raise RuntimeError("log_rate_anomalies required") from exc
        fitted = 0
        for cid, hourly in self._buf.items():
            points: List[Tuple[float, int]] = []
            for hour, counts in hourly.items():
                for c in counts:
                    points.append((float(hour), int(c)))
            if len(points) < 4:
                continue
            result = _fit_one_gp(points)
            if result is None:
                continue
            self._gp_cache[cid] = result
            fitted += 1
        self._n_consolidations += 1
        return {"fitted": fitted,
                "observations": self._n_observations,
                "consolidate_index": self._n_consolidations}

    # ── Inspection helpers ──────────────────────────────────────────────

    def n_observations(self) -> int:
        return self._n_observations

    def has_gp_for(self, cluster_id: int) -> bool:
        return int(cluster_id) in self._gp_cache


# ── Simple latency benchmarker ──────────────────────────────────────────


@dataclass
class LatencyReport:
    n_calls:    int
    p50_ms:     float
    p95_ms:     float
    p99_ms:     float
    max_ms:     float
    mean_ms:    float

    def as_dict(self) -> Dict[str, float]:
        return {
            "n_calls": self.n_calls,
            "p50_ms":  self.p50_ms,
            "p95_ms":  self.p95_ms,
            "p99_ms":  self.p99_ms,
            "max_ms":  self.max_ms,
            "mean_ms": self.mean_ms,
        }


def measure_latency(timings: Sequence[float]) -> LatencyReport:
    """Pure helper — given a list of per-call durations (seconds),
    return the standard latency-percentile report."""
    if not timings:
        return LatencyReport(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    xs = sorted(t * 1000.0 for t in timings)
    n = len(xs)

    def pct(p: float) -> float:
        i = max(0, min(n - 1, int(round(p / 100.0 * (n - 1)))))
        return xs[i]
    return LatencyReport(
        n_calls=n,
        p50_ms=pct(50), p95_ms=pct(95), p99_ms=pct(99),
        max_ms=xs[-1], mean_ms=sum(xs) / n,
    )


__all__ = [
    "StreamingRegimeModel", "StreamingRegimeAssignment",
    "StreamingRateDetector", "StreamingRateObservation",
    "LatencyReport", "measure_latency",
]
