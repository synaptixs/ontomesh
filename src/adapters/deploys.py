"""
src/adapters/deploys.py — T1.2
──────────────────────────────
Deploy / config-change / incident-event adapter.

Point events (deploys, kubernetes rollouts, feature-flag flips,
PagerDuty incidents, …) become a rate-series node that is mostly
zero with sharp 1.0 spikes at event times. This is the canonical
shape the PC algorithm needs to identify deploys as **causes** —
without it the toolkit can spot anomalies but cannot attribute
them to operator actions.

Each event carries optional ``half_life_seconds`` — when set, the
spike decays exponentially across subsequent bins so a 12-minute
config rollout still shows up as a sustained signal rather than
an isolated 1-bin spike.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from observability_adapter import Adapter, NodeMeta


@dataclass(frozen=True)
class DeployEvent:
    """One point event. ``kind`` is free-text but conventionally one
    of {``deploy``, ``config_change``, ``incident``, ``rollback``,
    ``feature_flag``}.

    Optional ``half_life_seconds`` smears the event across multiple
    bins via an exponential decay. Useful for slow rollouts.
    """
    name:                str
    kind:                str
    timestamp:           float
    half_life_seconds:   Optional[float] = None
    service:             Optional[str] = None


@dataclass
class DeploysAdapter:
    events:      Sequence[DeployEvent]
    bin_seconds: float = 60.0
    start_ts:    Optional[float] = None
    end_ts:      Optional[float] = None
    name:        str = "deploys"
    n_bins:      int = field(default=0, init=False)
    # Group events by name (so multiple deploys of the same service
    # contribute to one node) by default. Set False for one node
    # per event (high-cardinality, only useful for small corpora).
    group_by_name: bool = True

    def rate_series(self) -> Tuple[Dict[str, np.ndarray], Dict[str, NodeMeta]]:
        if not self.events:
            self.n_bins = 0
            return {}, {}
        timestamps = [e.timestamp for e in self.events]
        t0 = self.start_ts if self.start_ts is not None else min(timestamps)
        t1 = self.end_ts   if self.end_ts   is not None else max(timestamps)
        n_bins = max(1, int((t1 - t0) / self.bin_seconds) + 1)
        self.n_bins = n_bins

        # Group events.
        buckets: Dict[str, List[DeployEvent]] = defaultdict(list)
        for ev in self.events:
            key = ev.name if self.group_by_name else f"{ev.name}@{ev.timestamp}"
            buckets[key].append(ev)

        series: Dict[str, np.ndarray] = {}
        meta:   Dict[str, NodeMeta] = {}
        for label, group in buckets.items():
            arr = np.zeros(n_bins, dtype=float)
            for ev in group:
                start_idx = min(n_bins - 1,
                                max(0, int((ev.timestamp - t0) / self.bin_seconds)))
                if ev.half_life_seconds and ev.half_life_seconds > 0:
                    decay_per_bin = math.exp(
                        -self.bin_seconds * math.log(2.0)
                        / float(ev.half_life_seconds)
                    )
                    val = 1.0
                    for idx in range(start_idx, n_bins):
                        arr[idx] += val
                        val *= decay_per_bin
                        if val < 1e-4:
                            break
                else:
                    arr[start_idx] += 1.0
            kind_tag = group[0].kind
            node_id = f"deploy:{label}"
            series[node_id] = arr
            meta[node_id] = NodeMeta(
                node_id=node_id, kind="deploy", name=label,
                source="deploys", unit="events/bin",
                tags=tuple(filter(None, (kind_tag, group[0].service))),
            )
        return series, meta


__all__ = ["DeploysAdapter", "DeployEvent"]
