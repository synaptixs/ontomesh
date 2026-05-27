"""
causality_miner.py — Phase L3
─────────────────────────────
Gates the L1.5 directed PMI edges with a stricter causality test so the
LOG_CAUSAL_EDGE proposals surfaced to the engineer are statistically
defensible.

Three orthogonal signals must agree before an edge is emitted as
causal:

  1. **PMI ≥ τ_PMI** (from L1.4) — there's strong co-occurrence at all.
  2. **temporal_lead_ratio ≥ 0.7** (from L1.5) — direction is stable.
  3. **Granger p < 0.05 OR transfer-entropy z > 2** (this phase) — the
     past of the cause carries information about the future of the
     effect that the effect's own past does not.

Edges that fail #3 don't disappear — they downgrade to LOG_RELATIONSHIP
in the proposal store. The review queue still surfaces them, just
labeled as undirected.

CLI use is via the existing pipelines (``--phase mine`` /
``--phase sequence`` / ``--phase reseed-discovery``); this module is
imported, not run directly.

Bishop reference: PRML Ch. 11 (sampling for the bootstrap z-score in
TE) and Ch. 14 (combining models via gating).
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import numpy as np
    _NP_OK = True
except ImportError:                                  # pragma: no cover
    _NP_OK = False

try:
    from statsmodels.tsa.stattools import grangercausalitytests
    _SM_OK = True
except ImportError:                                  # pragma: no cover
    _SM_OK = False


# ── Defaults (tuned for the sample corpus; exported for visibility) ─────


BIN_SECONDS_DEFAULT = 1.0
"""Time-bin granularity for rate series."""

GRANGER_MAX_LAG_DEFAULT = 5
"""Maximum lag the Granger test sweeps."""

GRANGER_P_THRESHOLD = 0.05
"""Edge passes Granger if p < this at any tested lag."""

TE_Z_THRESHOLD = 2.0
"""Edge passes transfer-entropy if its bootstrap z-score exceeds this."""

MIN_BINS_FOR_GRANGER = 24
"""Below this many populated bins, skip Granger and rely on TE only."""


# ── Rate-series builder (L3.1) ──────────────────────────────────────────


def _parse_ts(ts: str) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def build_rate_series(extractions: Iterable[dict],
                      *, bin_seconds: float = BIN_SECONDS_DEFAULT
                      ) -> Tuple[Dict[int, "np.ndarray"], float, int]:
    """Bin each cluster_id's occurrences into a fixed-width time grid.

    Returns
    -------
    series : {cluster_id → np.array(count_per_bin)}
    bin_seconds : the size that was used (echoed for callers)
    n_bins : the grid width

    A flat empty grid is returned when ``extractions`` carries no
    valid timestamps.
    """
    if not _NP_OK:
        raise ImportError("numpy is required. Install via `pip install -e .[mining]`.")
    ts_cid: List[Tuple[float, int]] = []
    for ex in extractions:
        t = _parse_ts(ex.get("ts", ""))
        if t is None:
            continue
        cid = ex.get("cluster_id")
        if cid is None:
            continue
        ts_cid.append((t, cid))
    if not ts_cid:
        return {}, bin_seconds, 0
    t_min = min(t for t, _ in ts_cid)
    t_max = max(t for t, _ in ts_cid)
    n_bins = max(1, int(math.ceil((t_max - t_min) / bin_seconds)) + 1)

    series: Dict[int, "np.ndarray"] = {}
    for t, cid in ts_cid:
        idx = int((t - t_min) / bin_seconds)
        if idx >= n_bins:
            idx = n_bins - 1
        arr = series.get(cid)
        if arr is None:
            arr = np.zeros(n_bins, dtype=np.int32)
            series[cid] = arr
        arr[idx] += 1
    return series, bin_seconds, n_bins


# ── Granger (L3.1) ──────────────────────────────────────────────────────


@dataclass
class GrangerResult:
    p_value: float
    best_lag: int
    ok: bool
    error: Optional[str] = None


def granger_test(x: "np.ndarray", y: "np.ndarray",
                 *, max_lag: int = GRANGER_MAX_LAG_DEFAULT) -> GrangerResult:
    """Test whether the past of ``x`` Granger-causes ``y``.

    Returns the minimum p-value across lags 1..max_lag. ``ok=True`` if
    ``min p < GRANGER_P_THRESHOLD``. Suppresses statsmodels' verbose
    chi-squared exceptions on stationary-assumption failures — the
    caller falls back to transfer-entropy in those cases.
    """
    if not _SM_OK:
        return GrangerResult(p_value=1.0, best_lag=0, ok=False,
                             error="statsmodels not installed")
    if not _NP_OK:
        return GrangerResult(p_value=1.0, best_lag=0, ok=False,
                             error="numpy not installed")
    n = min(len(x), len(y))
    if n < MIN_BINS_FOR_GRANGER:
        return GrangerResult(p_value=1.0, best_lag=0, ok=False,
                             error=f"too few bins ({n})")

    # statsmodels expects columns [y, x] — yes that order, the docs are
    # confusing. Tests whether x's past helps predict y.
    data = np.column_stack([y[:n], x[:n]]).astype(float)
    safe_max = min(max_lag, max(1, (n // 4) - 1))
    try:
        # Newer statsmodels emits a FutureWarning about `verbose=` being
        # deprecated, and prints per-lag stats unless silenced. Suppress
        # both so the CLI output stays clean.
        import warnings as _w
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            # Try the keyword first; if statsmodels has already removed
            # `verbose`, fall back to the silent default.
            try:
                results = grangercausalitytests(data, maxlag=safe_max, verbose=False)
            except TypeError:
                results = grangercausalitytests(data, maxlag=safe_max)
    except Exception as exc:                # noqa: BLE001
        return GrangerResult(p_value=1.0, best_lag=0, ok=False,
                             error=str(exc)[:120])

    best_p = 1.0
    best_lag = 0
    for lag, (stats_dict, _) in results.items():
        # Use the F-test (ssr_ftest) p-value; falls through to chi2 if F absent.
        p = stats_dict.get("ssr_ftest", (0.0, 1.0))[1]
        if p < best_p:
            best_p = p
            best_lag = lag
    return GrangerResult(
        p_value=best_p, best_lag=best_lag,
        ok=(best_p < GRANGER_P_THRESHOLD),
    )


# ── Transfer entropy (L3.2) ─────────────────────────────────────────────


def _bin_series(arr: "np.ndarray", bins: int) -> "np.ndarray":
    """Bin a count series into ``bins`` ordinal buckets. Empty series
    gets all-zeros."""
    if arr.size == 0:
        return arr
    lo, hi = float(arr.min()), float(arr.max())
    if hi == lo:
        return np.zeros_like(arr, dtype=int)
    edges = np.linspace(lo, hi, bins + 1)
    return np.clip(np.digitize(arr, edges[1:-1]), 0, bins - 1)


def transfer_entropy(x: "np.ndarray", y: "np.ndarray",
                     *, lag: int = 1, bins: int = 4,
                     n_bootstrap: int = 100,
                     seed: int = 42) -> float:
    """Estimate the TE from x to y at the given lag with a bootstrap
    null. Returns a z-score: how many SDs above the shuffled-null mean
    is the observed TE. Values > 2 are commonly treated as significant.

    Implementation: binned plug-in estimator over the joint distribution
    P(y_t+1, y_t, x_t). Coarse but sufficient for the v1 gating signal.
    """
    if not _NP_OK:
        return 0.0
    n = min(len(x), len(y))
    if n < 8:
        return 0.0
    x = np.asarray(x)[:n]
    y = np.asarray(y)[:n]
    x_d = _bin_series(x, bins)
    y_d = _bin_series(y, bins)

    def _te(xd, yd):
        xt = xd[:-lag]
        yt = yd[:-lag]
        ytp = yd[lag:]
        # Joint and marginal counts via numpy histograms.
        jhist = np.zeros((bins, bins, bins))
        for a, b, c in zip(ytp, yt, xt):
            jhist[a, b, c] += 1
        N = jhist.sum() or 1
        p_yt_xt = jhist.sum(axis=0) / N
        p_yt = jhist.sum(axis=(0, 2)) / N
        p_ytp_yt = jhist.sum(axis=2) / N
        out = 0.0
        for a in range(bins):
            for b in range(bins):
                for c in range(bins):
                    p_abc = jhist[a, b, c] / N
                    if p_abc <= 0:
                        continue
                    denom = p_ytp_yt[a, b] * p_yt_xt[b, c]
                    if denom <= 0:
                        continue
                    num = p_abc * p_yt[b]
                    if num <= 0:
                        continue
                    out += p_abc * math.log(num / denom)
        return out

    observed = _te(x_d, y_d)
    rng = np.random.default_rng(seed)
    null = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        shuffled = rng.permutation(x_d)
        null[i] = _te(shuffled, y_d)
    mu = float(null.mean())
    sigma = float(null.std() or 1e-9)
    return (observed - mu) / sigma


# ── Triangulation gate (L3.3) ───────────────────────────────────────────


@dataclass
class CausalCandidate:
    src: str
    dst: str
    pmi: float
    temporal_lead_ratio: float
    granger_p: float
    granger_lag: int
    te_z: float
    confidence: float
    via: str            # "granger" | "transfer-entropy" | "none"

    def to_dict(self) -> dict:
        return {
            "src": self.src, "dst": self.dst, "pmi": self.pmi,
            "temporal_lead_ratio": self.temporal_lead_ratio,
            "granger_p": self.granger_p, "granger_lag": self.granger_lag,
            "te_z": self.te_z, "confidence": self.confidence, "via": self.via,
        }


def _slot_value_to_cluster_ids(extractions: Sequence[dict]
                               ) -> Dict[str, List[int]]:
    """For each slot value, list the cluster ids in which it appears.
    Used to translate L1 entity edges (src/dst are slot values) into
    cluster-id rate series that the Granger test can consume."""
    out: Dict[str, List[int]] = defaultdict(list)
    for ex in extractions:
        cid = ex.get("cluster_id")
        if cid is None:
            continue
        for v in ex.get("slots", []) or []:
            if v:
                out[str(v)].append(cid)
    return out


def find_causality_candidates(extractions: Sequence[dict],
                              conn: sqlite3.Connection,
                              *,
                              bin_seconds: float = BIN_SECONDS_DEFAULT,
                              max_lag: int = GRANGER_MAX_LAG_DEFAULT,
                              ) -> List[CausalCandidate]:
    """Apply the triangulation gate to the directed PMI edges
    persisted by L1.5.

    Returns one :class:`CausalCandidate` per edge that survives. Edges
    that fail are *not* returned — the caller (Phase L4 seeding)
    routes those to LOG_RELATIONSHIP instead.
    """
    if not _NP_OK:
        return []

    # 1. Pull directed PMI edges.
    rows = list(conn.execute(
        "SELECT src, dst, pmi, temporal_lead_ratio FROM log_entity_edges "
        "WHERE directed = 1 AND pmi >= 2.0"
    ))
    if not rows:
        return []

    # 2. Build the rate series we'll need. Keyed by cluster_id.
    series, _, n_bins = build_rate_series(extractions, bin_seconds=bin_seconds)
    if n_bins < 4:
        return []

    # 3. For each (src, dst) entity pair, map to the union rate series
    #    of the cluster ids that mention those slot values.
    value_to_cids = _slot_value_to_cluster_ids(extractions)

    def _value_series(value: str) -> Optional["np.ndarray"]:
        cids = value_to_cids.get(value, [])
        if not cids:
            return None
        acc = np.zeros(n_bins, dtype=float)
        for c in cids:
            if c in series:
                acc += series[c]
        return acc if acc.sum() > 0 else None

    candidates: List[CausalCandidate] = []
    for src, dst, pmi, lead in rows:
        if lead is None or lead < 0.7:
            continue
        x = _value_series(src)
        y = _value_series(dst)
        if x is None or y is None or len(x) < 4:
            continue
        # 4. Granger first, fall back to TE.
        g = granger_test(x, y, max_lag=max_lag)
        te_z = transfer_entropy(x, y)
        via = "none"
        if g.ok:
            via = "granger"
        elif te_z > TE_Z_THRESHOLD:
            via = "transfer-entropy"
        else:
            continue   # neither passed → demote to LOG_RELATIONSHIP

        confidence = _confidence_from_signals(pmi, lead, g, te_z, via)
        candidates.append(CausalCandidate(
            src=src, dst=dst, pmi=float(pmi),
            temporal_lead_ratio=float(lead),
            granger_p=float(g.p_value), granger_lag=int(g.best_lag),
            te_z=float(te_z), confidence=confidence, via=via,
        ))
    return candidates


def _confidence_from_signals(pmi: float, lead: float,
                             g: GrangerResult, te_z: float,
                             via: str) -> float:
    """Blend the three signals into a single confidence in [0, 1].
    PMI contributes log-ish, lead linearly, statistical test bonus."""
    pmi_term = min(1.0, max(0.0, (pmi - 2.0) / 8.0))
    lead_term = max(0.0, (lead - 0.7) / 0.3) if lead else 0.0
    if via == "granger":
        stat_term = max(0.0, 1.0 - g.p_value / GRANGER_P_THRESHOLD)
    elif via == "transfer-entropy":
        stat_term = min(1.0, te_z / (TE_Z_THRESHOLD * 2.0))
    else:
        stat_term = 0.0
    score = 0.4 * pmi_term + 0.3 * lead_term + 0.3 * stat_term
    return float(min(1.0, max(0.0, score)))


# ── Public summary helper ──────────────────────────────────────────────


def causal_set(candidates: Sequence[CausalCandidate]) -> set:
    """Return the (src, dst) pairs that survived the gate. The L4
    seeding step uses this to decide which edges are LOG_CAUSAL_EDGE
    vs LOG_RELATIONSHIP."""
    return {(c.src, c.dst) for c in candidates}


__all__ = [
    "BIN_SECONDS_DEFAULT",
    "CausalCandidate",
    "GRANGER_MAX_LAG_DEFAULT",
    "GRANGER_P_THRESHOLD",
    "GrangerResult",
    "TE_Z_THRESHOLD",
    "build_rate_series",
    "causal_set",
    "find_causality_candidates",
    "granger_test",
    "transfer_entropy",
]
