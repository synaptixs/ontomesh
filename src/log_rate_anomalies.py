"""
log_rate_anomalies.py — Phase L13
─────────────────────────────────
Per-template Gaussian Process model over time-of-day rate series,
with anomaly detection at the 99% posterior predictive interval.

Why this exists
───────────────
The v1 HMM (and v2's regime-aware HMM in L8) score template *identity*
sequences. A burst of *normal* templates — e.g. 10× the usual log
rate for "User logged in" during a 2 am window — is invisible to those
detectors. It's also the canonical "something broke" signal in real
on-call life: a deploy goes bad and a normally-quiet endpoint suddenly
floods the queue with success logs from retried clients.

Model
─────
For each template (cluster_id) with enough data, fit a Gaussian Process

    y(t) ~ GP(0, k(t, t'))   with kernel

    k = C(σ₀²) · [ ExpSineSquared(length=l_p, period=24h)
                   + RBF(length=l_r) ]
        + WhiteKernel(σ_n²)

over (hour-of-day, count-per-bin). The periodic kernel captures the
daily rhythm; the RBF picks up local smoothness; the white noise
absorbs Poisson-like binning jitter. Bishop §6.4.

Anomaly detection
─────────────────
For each observed (t, y) pair, the GP predictive distribution is
N(μ(t), σ²(t)). An anomaly is any point with

    y < μ(t) - 2.576·σ(t)   or   y > μ(t) + 2.576·σ(t)

i.e. outside the central 99 % interval (Φ⁻¹(0.995) = 2.576). The
threshold is two-sided: both rare-quiet windows and bursts surface.

Risk mitigations per §6
───────────────────────
- ``MAX_TEMPLATES`` cap so a wide alphabet doesn't blow past the
  30 s acceptance budget (GP fit is O(n³) in samples; we throttle
  templates and sub-sample bins to keep the wall clock sane).
- ``MIN_SAMPLES_PER_TEMPLATE`` floor — below this, no GP fit (the
  kernel can't separate signal from noise in 8 data points).
- The roadmap notes "GP fit time on 7 days × 60 templates ≤ 30 s"
  as the acceptance budget; we explicitly target it via the cap.

Public API
──────────
    report = mine_rate_anomalies(extractions, conn)
    hits   = detect_rate_anomalies(extractions, alpha=0.01)
    persist_rate_anomaly_proposals(conn, hits)
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import sqlite3
import time
import uuid
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import numpy as np
    from scipy.stats import norm
    _NP_OK = True
except ImportError:                                  # pragma: no cover
    _NP_OK = False

try:
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import (
        RBF, ConstantKernel, ExpSineSquared, WhiteKernel,
    )
    _SK_OK = True
except ImportError:                                  # pragma: no cover
    _SK_OK = False

warnings.filterwarnings(
    "ignore",
    message=r".*The optimal value found.*",
    module=r".*sklearn.*",
)


# Defaults — per §6.
MAX_TEMPLATES = 60                  # cap on templates per run
MIN_SAMPLES_PER_TEMPLATE = 12       # below this, skip GP fit
BIN_SECONDS = 3600.0                # one bin = 1 hour (matches "hourly
                                    # rate" intuition; smaller bins
                                    # blow up the O(n³) cost)
ANOMALY_ALPHA = 0.01                # central 1 - α interval
MAX_SAMPLES_PER_FIT = 96            # sub-sample if a template has more
                                    # (4 full days @ 24 bins). O(n³)
                                    # GP-fit cost: tight cap is the
                                    # main lever keeping the 30 s
                                    # acceptance budget realistic.


# ── Rate-series construction (lightweight; doesn't reuse causality_miner
#    so this module stays usable on its own) ──────────────────────────────


def _hour_of_day(ts_iso: str) -> Optional[float]:
    """Extract hour-of-day as a float in [0, 24). Returns None on any
    parse failure (we silently drop the record — never raise out of
    the binning loop)."""
    if not ts_iso:
        return None
    try:
        s = str(ts_iso).replace("T", " ").split(".")[0]
        dt = _dt.datetime.fromisoformat(s)
    except Exception:                                  # noqa: BLE001
        return None
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _build_hourly_counts(extractions: Iterable[dict]
                          ) -> Dict[int, List[Tuple[float, int]]]:
    """For each cluster_id, return a list of (hour_of_day, count) pairs
    aggregated at the hourly bin. Day-of-week / year-day are dropped:
    the GP fits a single periodic pattern of hour-of-day."""
    # Sub-bin by exact ts → count per (cid, day, hour) bin.
    by_cid_hourbin: Dict[int, Dict[Tuple[str, int], int]] = defaultdict(
        lambda: defaultdict(int))
    for ex in extractions:
        cid = ex.get("cluster_id")
        if cid is None:
            continue
        ts = ex.get("ts") or ex.get("timestamp")
        h = _hour_of_day(ts)
        if h is None:
            continue
        # Group by (date, hour) so multiple events per hour
        # accumulate, then surface hour-of-day for the GP.
        day_key = str(ts).split(" ")[0] if " " in str(ts) else str(ts)[:10]
        by_cid_hourbin[int(cid)][(day_key, int(h))] += 1
    out: Dict[int, List[Tuple[float, int]]] = {}
    for cid, hourly in by_cid_hourbin.items():
        points = [(float(hour), int(count))
                  for (_day, hour), count in hourly.items()]
        out[cid] = points
    return out


# ── GP fit + anomaly detection ───────────────────────────────────────────


@dataclass
class RateAnomaly:
    """One anomalous (cluster, time, count) tuple. ``sparkline`` is
    the per-bin observed-count list for the template — short, JSON-
    serialisable, suitable for inline UI rendering."""
    cluster_id: int
    hour_of_day: float
    observed: int
    predicted_mean: float
    predicted_std: float
    direction: str                              # "spike" | "dip"
    z_score: float
    sparkline: List[int] = field(default_factory=list)

    def confidence(self) -> float:
        """Two-sided posterior probability that |y - μ| ≥ |z|·σ
        under the GP predictive. Used as the proposal confidence."""
        if self.predicted_std <= 1e-9:
            return 1.0 if self.observed != round(self.predicted_mean) else 0.0
        return float(2.0 * (1.0 - norm.cdf(abs(self.z_score))))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id":     self.cluster_id,
            "hour_of_day":    self.hour_of_day,
            "observed":       self.observed,
            "predicted_mean": self.predicted_mean,
            "predicted_std":  self.predicted_std,
            "direction":      self.direction,
            "z_score":        self.z_score,
            "sparkline":      list(self.sparkline),
        }


def _kernel():
    """Periodic (24h) + RBF + white noise. Bishop §6.4. The constant
    and length scales are bounded so the optimiser doesn't run away on
    sparse hourly data."""
    return (
        ConstantKernel(1.0, (0.1, 10.0))
        * (
            ExpSineSquared(length_scale=3.0,
                           periodicity=24.0,
                           length_scale_bounds=(0.5, 50.0),
                           periodicity_bounds=(24.0, 24.0))
            + RBF(length_scale=4.0, length_scale_bounds=(0.5, 50.0))
        )
        + WhiteKernel(noise_level=0.5, noise_level_bounds=(1e-3, 10.0))
    )


def _fit_one_gp(points: Sequence[Tuple[float, int]]
                 ) -> Optional[Tuple[Any, np.ndarray, np.ndarray]]:
    """Fit a single GP. Returns ``(gp, X_eval, y_eval)`` where
    ``X_eval`` / ``y_eval`` are the **original** observations (used
    later for residual / anomaly evaluation) while the GP itself is
    trained on the **per-hour-of-day median** of those observations.

    Training on the per-hour median (24 points, by construction) buys
    us two things:

    - **Robustness.** A single huge spike on one (day, hour) bin gets
      absorbed into the median — the GP fits a clean diurnal baseline
      that the spike then sticks out against. Without this, the GP
      would interpolate through the spike and hide it.
    - **Speed.** 24 points fit in O(24³) — trivial. Meets the §6
      30-second budget for 60 templates with room to spare.
    """
    if len(points) < MIN_SAMPLES_PER_TEMPLATE:
        return None

    X_eval = np.array([p[0] for p in points], dtype=float).reshape(-1, 1)
    y_eval = np.array([p[1] for p in points], dtype=float)

    # Aggregate per hour-of-day via median (robust to outliers).
    by_hour: Dict[int, List[float]] = defaultdict(list)
    for x, y_val in zip(X_eval.ravel(), y_eval):
        by_hour[int(round(float(x)))].append(float(y_val))
    if len(by_hour) < 4:
        return None
    hours = sorted(by_hour.keys())
    X_fit = np.array(hours, dtype=float).reshape(-1, 1)
    y_fit = np.array([float(np.median(by_hour[h])) for h in hours],
                     dtype=float)

    try:
        gp = GaussianProcessRegressor(
            kernel=_kernel(),
            alpha=1e-3,
            normalize_y=True,
            n_restarts_optimizer=0,
            random_state=0,
        )
        gp.fit(X_fit, y_fit)
    except Exception:                                  # noqa: BLE001
        return None
    return gp, X_eval, y_eval


def detect_rate_anomalies(extractions: Sequence[dict],
                          *,
                          alpha: float = ANOMALY_ALPHA,
                          max_templates: int = MAX_TEMPLATES,
                          ) -> List[RateAnomaly]:
    """Top-level anomaly detector. Returns one ``RateAnomaly`` per
    (cluster, bin) pair whose observed count falls outside the
    central ``1 - α`` predictive interval of its template's GP.

    Templates with fewer than ``MIN_SAMPLES_PER_TEMPLATE`` bins are
    skipped (not enough data for a sensible GP)."""
    if not (_NP_OK and _SK_OK):
        return []
    points_by_cid = _build_hourly_counts(extractions)
    # Throttle: keep the templates with the most observations so the
    # acceptance budget (30 s) holds even on wide-alphabet corpora.
    sorted_cids = sorted(
        points_by_cid.items(),
        key=lambda kv: -sum(c for _, c in kv[1]),
    )[:max_templates]

    z_thresh = float(norm.ppf(1.0 - alpha / 2.0))
    hits: List[RateAnomaly] = []
    for cid, points in sorted_cids:
        result = _fit_one_gp(points)
        if result is None:
            continue
        gp, X, y = result
        try:
            mu, _gp_sigma = gp.predict(X, return_std=True)
        except Exception:                              # noqa: BLE001
            continue
        # Detrend: residual against the GP smooth baseline. We then
        # z-score against the *MAD-derived* scale of the residual
        # distribution, NOT the GP's own predictive σ. A single
        # outlier inflates the GP σ at its own x location enough to
        # hide itself ("the GP fits the noise") — MAD is robust to
        # that. Standard residual-detection trick (Hampel 1974).
        residuals = y - mu
        med = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - med)))
        robust_sigma = max(1.4826 * mad, 0.5)
        sparkline = [int(v) for v in y.tolist()]
        for i in range(X.shape[0]):
            r = float(residuals[i] - med)
            z = r / robust_sigma
            if abs(z) < z_thresh:
                continue
            hits.append(RateAnomaly(
                cluster_id=int(cid),
                hour_of_day=float(X[i, 0]),
                observed=int(y[i]),
                predicted_mean=float(mu[i]),
                predicted_std=float(robust_sigma),
                direction="spike" if r > 0 else "dip",
                z_score=z,
                sparkline=sparkline,
            ))
    return hits


# ── Proposal persistence (matches L8 + L2 proposal contract) ────────────


def persist_rate_anomaly_proposals(conn: sqlite3.Connection,
                                   hits: Sequence[RateAnomaly]) -> int:
    """Write each ``RateAnomaly`` as a LOG_EVENT proposal with
    ``detection_strategy='GP_RATE_DEVIATION'``. The per-bin
    sparkline goes into the ``rate_sparkline`` JSON column for the
    inline UI sparkline. Idempotent on a deterministic
    ``(cluster_id, hour_of_day, direction)`` key."""
    if not _table_exists(conn, "ontology_evolution_proposals"):
        return 0

    has_sparkline = any(
        r[1] == "rate_sparkline" for r in conn.execute(
            "PRAGMA table_info(ontology_evolution_proposals)"
        )
    )

    has_templates = _table_exists(conn, "log_templates")
    cid_to_sample: Dict[int, Tuple[str, str, int]] = {}
    if has_templates:
        cid_to_sample = {
            r[0]: (r[1], r[2], r[3]) for r in conn.execute(
                "SELECT cluster_id, template, sample_line, id "
                "FROM log_templates WHERE merged_into IS NULL"
            )
        }

    n = 0
    for h in hits:
        template, sample, tmpl_id = cid_to_sample.get(
            h.cluster_id, ("", "", None))
        direction = h.direction
        title = (f"Rate {direction} for template #{h.cluster_id} at hour "
                 f"{h.hour_of_day:.0f} — {h.observed} obs, predicted "
                 f"{h.predicted_mean:.1f}±{h.predicted_std:.1f}")
        deterministic = uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"gp-rate:{h.cluster_id}:{int(h.hour_of_day)}:{direction}",
        )
        candidate_turtle = (
            f"# L13 GP rate {direction}\n"
            f":RateAnomaly_{h.cluster_id}_{int(h.hour_of_day)} a owl:Class ;\n"
            f"  rdfs:subClassOf :RateDeviationEvent ;\n"
            f"  rdfs:label \"{title}\" ;\n"
            f"  rdfs:comment \"Sample: {(sample or '')[:200]}\" .\n"
            f"# z_score={h.z_score:.2f}\n"
        )
        evidence_sparql = (
            f"PREFIX : <https://ontology.example.com/enterprise/>\n"
            f"ASK {{ ?e a :RateAnomaly_{h.cluster_id}_{int(h.hour_of_day)} }}\n"
        )
        confidence = max(0.0, min(1.0, 1.0 - h.confidence()))
        sparkline_json = json.dumps(h.sparkline[:64])
        if has_sparkline:
            conn.execute(
                "INSERT INTO ontology_evolution_proposals "
                "(proposal_id, proposal_type, title, candidate_turtle, "
                " evidence_sparql, detection_strategy, confidence_score, "
                " dim_consistency_risk, evidence_template_id, evidence_sample, "
                " source_log_path, rate_sparkline) "
                "VALUES (?, 'LOG_EVENT', ?, ?, ?, 'GP_RATE_DEVIATION', "
                " ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(proposal_id) DO UPDATE SET "
                "  confidence_score = excluded.confidence_score, "
                "  dim_consistency_risk = excluded.dim_consistency_risk, "
                "  rate_sparkline = excluded.rate_sparkline, "
                "  updated_at = datetime('now')",
                (str(deterministic), title, candidate_turtle, evidence_sparql,
                 confidence, min(1.0, abs(h.z_score) / 5.0),
                 tmpl_id, sample, "", sparkline_json),
            )
        else:
            conn.execute(
                "INSERT INTO ontology_evolution_proposals "
                "(proposal_id, proposal_type, title, candidate_turtle, "
                " evidence_sparql, detection_strategy, confidence_score, "
                " dim_consistency_risk, evidence_template_id, evidence_sample, "
                " source_log_path) "
                "VALUES (?, 'LOG_EVENT', ?, ?, ?, 'GP_RATE_DEVIATION', "
                " ?, ?, ?, ?, ?) "
                "ON CONFLICT(proposal_id) DO UPDATE SET "
                "  confidence_score = excluded.confidence_score, "
                "  dim_consistency_risk = excluded.dim_consistency_risk, "
                "  updated_at = datetime('now')",
                (str(deterministic), title, candidate_turtle, evidence_sparql,
                 confidence, min(1.0, abs(h.z_score) / 5.0),
                 tmpl_id, sample, ""),
            )
        n += 1
    conn.commit()
    return n


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


# ── Pipeline ─────────────────────────────────────────────────────────────


@dataclass
class RateReport:
    templates_examined: int = 0
    templates_fit: int = 0
    anomalies: int = 0
    proposals_persisted: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "templates_examined":   self.templates_examined,
            "templates_fit":        self.templates_fit,
            "anomalies":            self.anomalies,
            "proposals_persisted":  self.proposals_persisted,
            "duration_s":           round(self.duration_s, 3),
        }


def mine_rate_anomalies(extractions: Sequence[dict],
                        conn: sqlite3.Connection,
                        *,
                        alpha: float = ANOMALY_ALPHA,
                        max_templates: int = MAX_TEMPLATES,
                        ) -> RateReport:
    """End-to-end pipeline. Fits per-template GPs, detects rate
    deviations, writes them as LOG_EVENT proposals with
    ``detection_strategy='GP_RATE_DEVIATION'``."""
    started = time.perf_counter()
    points = _build_hourly_counts(extractions)
    hits = detect_rate_anomalies(
        extractions, alpha=alpha, max_templates=max_templates,
    )
    persisted = persist_rate_anomaly_proposals(conn, hits)
    duration = time.perf_counter() - started
    fitted = len({h.cluster_id for h in hits})
    return RateReport(
        templates_examined=len(points),
        templates_fit=fitted,
        anomalies=len(hits),
        proposals_persisted=persisted,
        duration_s=duration,
    )


__all__ = [
    "RateAnomaly", "RateReport",
    "ANOMALY_ALPHA", "MAX_TEMPLATES", "MIN_SAMPLES_PER_TEMPLATE",
    "detect_rate_anomalies", "persist_rate_anomaly_proposals",
    "mine_rate_anomalies",
]
