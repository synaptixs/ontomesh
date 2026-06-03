"""
src/adapters/otel.py — T1.2
───────────────────────────
OpenTelemetry span-event adapter.

Production usage: subscribe to an OTel collector; each received span
event becomes a SpanEvent and feeds the running adapter.

Test / offline usage: hand the adapter a list of pre-built
SpanEvents.

Modelling decision
------------------
A *span event* on ``service.operation`` (e.g. ``checkout.charge``)
is treated as one rate-series node. The series counts spans per
time bin — equivalent to a log template rate. This makes spans
peers of templates and metrics in the same causal graph.

Span errors become a separate node prefixed ``span_err:`` so the
PC algorithm can distinguish "this operation rate changed" from
"this operation started failing".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from observability_adapter import Adapter, NodeMeta


@dataclass(frozen=True)
class SpanEvent:
    """One span event. ``operation`` is the canonical
    ``service.operation`` qname; ``status`` is ``OK`` or ``ERROR``."""
    service:   str
    operation: str
    timestamp: float
    duration_ms: float = 0.0
    status:    str = "OK"

    @property
    def name(self) -> str:
        return f"{self.service}.{self.operation}"


@dataclass
class OtelAdapter:
    spans:       Sequence[SpanEvent]
    bin_seconds: float = 60.0
    start_ts:    Optional[float] = None
    end_ts:      Optional[float] = None
    name:        str = "otel"
    track_errors: bool = True
    n_bins:      int = field(default=0, init=False)

    def rate_series(self) -> Tuple[Dict[str, np.ndarray], Dict[str, NodeMeta]]:
        if not self.spans:
            self.n_bins = 0
            return {}, {}
        timestamps = [s.timestamp for s in self.spans]
        t0 = self.start_ts if self.start_ts is not None else min(timestamps)
        t1 = self.end_ts   if self.end_ts   is not None else max(timestamps)
        n_bins = max(1, int((t1 - t0) / self.bin_seconds) + 1)
        self.n_bins = n_bins

        rates: Dict[str, np.ndarray] = defaultdict(
            lambda: np.zeros(n_bins, dtype=float)
        )
        errors: Dict[str, np.ndarray] = defaultdict(
            lambda: np.zeros(n_bins, dtype=float)
        )

        for span in self.spans:
            idx = min(n_bins - 1,
                      max(0, int((span.timestamp - t0) / self.bin_seconds)))
            rates[span.name][idx] += 1.0
            if self.track_errors and span.status == "ERROR":
                errors[span.name][idx] += 1.0

        series: Dict[str, np.ndarray] = {}
        meta:   Dict[str, NodeMeta] = {}
        for op, arr in rates.items():
            node_id = f"span:{op}"
            series[node_id] = arr
            meta[node_id] = NodeMeta(
                node_id=node_id, kind="span", name=op,
                source="otel", unit="spans/bin",
            )
        if self.track_errors:
            for op, arr in errors.items():
                if arr.sum() == 0:
                    continue                          # no errors → no node
                node_id = f"span_err:{op}"
                series[node_id] = arr
                meta[node_id] = NodeMeta(
                    node_id=node_id, kind="span", name=f"{op} (errors)",
                    source="otel", unit="errors/bin",
                    tags=("error_only",),
                )
        return series, meta


__all__ = ["OtelAdapter", "SpanEvent"]
