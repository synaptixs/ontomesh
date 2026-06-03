"""
src/adapters/logs.py — T1.2
───────────────────────────
Logs adapter — wraps the existing
:func:`causality_miner.build_rate_series` so log templates appear
alongside metrics / spans / deploys in the multimodal causal graph.

Templates from L1 (Drain clustering) are keyed by ``cluster_id``;
this adapter prepends ``log:`` to give them a globally-unique
node id consistent with the other adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

from observability_adapter import Adapter, NodeMeta


@dataclass
class LogsAdapter:
    """Wraps L1 extractions into the multimodal-adapter shape.

    ``extractions`` is the iterable of dicts produced by
    :class:`log_templates.LogTemplateMiner` — each row carries at
    least ``cluster_id`` and ``ts``.
    """
    extractions: Sequence[Dict[str, Any]]
    bin_seconds: float = 60.0
    name:        str = "logs"
    n_bins:      int = field(default=0, init=False)
    template_labels: Optional[Dict[int, str]] = None

    def rate_series(self) -> Tuple[Dict[str, np.ndarray], Dict[str, NodeMeta]]:
        if not self.extractions:
            self.n_bins = 0
            return {}, {}
        from causality_miner import build_rate_series
        series_int, _bs, n_bins = build_rate_series(
            self.extractions, bin_seconds=self.bin_seconds,
        )
        self.n_bins = n_bins
        out_series: Dict[str, np.ndarray] = {}
        out_meta:   Dict[str, NodeMeta] = {}
        for cid, arr in series_int.items():
            node_id = f"log:{cid}"
            out_series[node_id] = arr.astype(float, copy=False)
            label = (self.template_labels or {}).get(cid, f"template #{cid}")
            out_meta[node_id] = NodeMeta(
                node_id=node_id, kind="log", name=label,
                source="logs", unit="events/bin",
            )
        return out_series, out_meta


__all__ = ["LogsAdapter"]
