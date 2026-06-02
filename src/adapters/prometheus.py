"""
src/adapters/prometheus.py — T1.2
─────────────────────────────────
Prometheus / metrics adapter.

Production usage: point at a Prometheus query endpoint; the adapter
issues range queries for the configured metric names, bins the
returned samples into a fixed-width grid, and surfaces each metric
as one node in the causal graph.

Test / offline usage: hand the adapter a list of pre-fetched
``PrometheusSample`` objects (we keep the live HTTP path optional
so tests stay hermetic).
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from observability_adapter import Adapter, NodeMeta


@dataclass(frozen=True)
class PrometheusSample:
    """One Prometheus sample. ``timestamp`` is a unix-epoch float."""
    metric:    str
    timestamp: float
    value:     float
    labels:    Tuple[Tuple[str, str], ...] = ()


@dataclass
class PrometheusAdapter:
    """Adapter for a fixed list of (metric, samples).

    Parameters
    ----------
    samples : list of PrometheusSample
        Pre-fetched samples (tests) OR fetched via an injected client
        (production — the client returns the same list shape).
    bin_seconds : float
        Bin width for the rate-series grid. Should match the PC
        algorithm's expected granularity (1 minute is a reasonable
        default for ops corpora).
    start_ts, end_ts : float | None
        Time range for the grid. When None, derived from the samples.
    """
    samples:     Sequence[PrometheusSample]
    bin_seconds: float = 60.0
    start_ts:    Optional[float] = None
    end_ts:      Optional[float] = None
    name:        str = "prometheus"
    n_bins:      int = field(default=0, init=False)

    def rate_series(self) -> Tuple[Dict[str, np.ndarray], Dict[str, NodeMeta]]:
        if not self.samples:
            self.n_bins = 0
            return {}, {}
        timestamps = [s.timestamp for s in self.samples]
        t0 = self.start_ts if self.start_ts is not None else min(timestamps)
        t1 = self.end_ts   if self.end_ts   is not None else max(timestamps)
        n_bins = max(1, int((t1 - t0) / self.bin_seconds) + 1)
        self.n_bins = n_bins

        by_metric: Dict[str, List[PrometheusSample]] = defaultdict(list)
        for s in self.samples:
            by_metric[s.metric].append(s)

        series: Dict[str, np.ndarray] = {}
        meta:   Dict[str, NodeMeta] = {}
        for metric, samples in by_metric.items():
            arr = np.zeros(n_bins, dtype=float)
            counts = np.zeros(n_bins, dtype=float)
            for s in samples:
                idx = min(n_bins - 1,
                          max(0, int((s.timestamp - t0) / self.bin_seconds)))
                arr[idx] += float(s.value)
                counts[idx] += 1.0
            # Mean per bin (so different sample frequencies don't bias
            # the magnitude). Bins with no samples stay 0.
            with np.errstate(divide="ignore", invalid="ignore"):
                mean = np.where(counts > 0, arr / counts, 0.0)
            node_id = f"metric:{metric}"
            series[node_id] = mean
            meta[node_id] = NodeMeta(
                node_id=node_id, kind="metric", name=metric,
                source="prometheus",
            )
        return series, meta


__all__ = ["PrometheusAdapter", "PrometheusSample"]
