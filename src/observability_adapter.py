"""
src/observability_adapter.py — T1.2
───────────────────────────────────
Multi-modal causal DAG.

The PC algorithm in :mod:`causality_dag` already takes
``Dict[node_id, np.ndarray]`` as input — it doesn't care whether
the time series came from logs, metrics, traces, or deploy events.
This module formalises that observation:

- Defines a common ``Adapter`` Protocol — each modality (Prometheus,
  OpenTelemetry, deploys, raw logs) implements ``rate_series()``.
- Tags each node with ``NodeMeta`` (kind / name / source) so the
  reviewer can colour-code the resulting PDAG.
- Merges series across adapters onto a common time grid, then hands
  the merged dict to ``learn_pdag``.
- Wraps the integer-keyed ``PDAG`` from L11 in a ``MultimodalPDAG``
  that exposes string-keyed edges and per-node metadata.

After this lands the toolkit stops being a *log* tool — it becomes
an *observability* RCA layer with one causal graph spanning logs,
metrics, traces, and deploy events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import numpy as np


# ── Common types ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeMeta:
    """Per-node provenance + UI-classification info."""
    node_id: str                         # globally unique key
    kind:    str                         # "log" | "metric" | "span" | "deploy"
    name:    str                         # human-readable label
    source:  str                         # "prometheus" | "otel" | "logs" | "deploys"
    unit:    Optional[str] = None        # e.g. "events/min", "ms"
    tags:    Tuple[str, ...] = ()        # arbitrary labels (service:foo)


class Adapter(Protocol):
    """Common interface implemented by each modality.

    ``rate_series()`` returns:
        (series, meta) where
        series : Dict[node_id, np.ndarray of shape (n_bins,)]
        meta   : Dict[node_id, NodeMeta]
    """

    name: str
    """Lower-case identifier ('prometheus' / 'otel' / ...)."""

    bin_seconds: float
    """Bin width — the merger uses it to resample to a common grid."""

    n_bins: int
    """Number of bins in this adapter's series. Set by the implementation
    after ``rate_series()`` is computed."""

    def rate_series(self) -> Tuple[Dict[str, np.ndarray], Dict[str, NodeMeta]]:
        ...


# ── Merging across adapters ──────────────────────────────────────────────


def merge_adapters(adapters: Sequence[Adapter],
                   *, target_bin_seconds: Optional[float] = None,
                   ) -> Tuple[Dict[str, np.ndarray], Dict[str, NodeMeta]]:
    """Run every adapter, resample each series to a common bin width,
    truncate to the shortest common length, and return one merged
    ``(series, meta)`` tuple ready for ``learn_pdag``.

    If ``target_bin_seconds`` is None, we use the *max* bin width across
    adapters (coarser is safer than finer for cross-modal alignment).
    """
    if not adapters:
        return {}, {}
    raw = []
    for a in adapters:
        series, meta = a.rate_series()
        raw.append((series, meta, getattr(a, "bin_seconds", 60.0)))

    bin_target = (target_bin_seconds
                  if target_bin_seconds is not None
                  else max(r[2] for r in raw))

    merged_series: Dict[str, np.ndarray] = {}
    merged_meta:   Dict[str, NodeMeta]   = {}
    lengths: List[int] = []
    for series, meta, bw in raw:
        ratio = bin_target / float(bw) if bw > 0 else 1.0
        # Integer down-sample factor (the simplest robust resampler).
        # When ratio == 1.0 we keep the series as-is.
        step = max(1, int(round(ratio)))
        for k, arr in series.items():
            if k in merged_series:
                # Collision on node_id — namespacing is the adapter's
                # responsibility; warn-and-skip is the safest fallback.
                continue
            if step > 1 and arr.size > step:
                # Block-average down-sample.
                trimmed = arr[: (arr.size // step) * step]
                resampled = trimmed.reshape(-1, step).mean(axis=1)
            else:
                resampled = arr.astype(float, copy=False)
            merged_series[k] = resampled
            lengths.append(resampled.size)
            if k in meta:
                merged_meta[k] = meta[k]

    if not lengths:
        return {}, {}
    n = min(lengths)
    if n < 1:
        return {}, merged_meta
    merged_series = {k: v[:n] for k, v in merged_series.items()}
    return merged_series, merged_meta


# ── Multimodal PDAG wrapper ──────────────────────────────────────────────


@dataclass
class MultimodalPDAG:
    """The L11 PDAG, lifted to string-keyed nodes with full metadata.

    The underlying ``causality_dag.PDAG`` still keys edges by integer
    indices (kept stable across calls). ``directed_edges_named`` and
    ``undirected_edges_named`` translate those back to NodeMeta so
    the caller never needs to keep the int↔str map.
    """
    pdag:     Any                                  # causality_dag.PDAG
    meta:     Dict[str, NodeMeta] = field(default_factory=dict)
    id_to_node: Dict[int, str] = field(default_factory=dict)
    node_to_id: Dict[str, int] = field(default_factory=dict)
    sepset:   Dict[Any, Any] = field(default_factory=dict)

    def directed_edges_named(self) -> List[Tuple[NodeMeta, NodeMeta]]:
        out: List[Tuple[NodeMeta, NodeMeta]] = []
        for (u, v) in sorted(self.pdag.directed):
            sn = self.id_to_node.get(int(u))
            tn = self.id_to_node.get(int(v))
            if not (sn and tn):
                continue
            out.append((self.meta.get(sn) or _placeholder(sn),
                        self.meta.get(tn) or _placeholder(tn)))
        return out

    def undirected_edges_named(self) -> List[Tuple[NodeMeta, NodeMeta]]:
        out: List[Tuple[NodeMeta, NodeMeta]] = []
        for (u, v) in sorted(self.pdag.undirected):
            sn = self.id_to_node.get(int(u))
            tn = self.id_to_node.get(int(v))
            if not (sn and tn):
                continue
            out.append((self.meta.get(sn) or _placeholder(sn),
                        self.meta.get(tn) or _placeholder(tn)))
        return out

    def has_edge_named(self, a: str, b: str) -> bool:
        ai = self.node_to_id.get(a)
        bi = self.node_to_id.get(b)
        if ai is None or bi is None:
            return False
        return self.pdag.has_edge(ai, bi)

    def parents_named(self, node_id: str) -> List[str]:
        nid = self.node_to_id.get(node_id)
        if nid is None:
            return []
        return [self.id_to_node[p] for p in self.pdag.parents(nid)
                if p in self.id_to_node]

    def node_kinds(self) -> Dict[str, str]:
        return {n: m.kind for n, m in self.meta.items()}


def _placeholder(name: str) -> NodeMeta:
    return NodeMeta(node_id=name, kind="unknown", name=name, source="unknown")


# ── Multimodal PC algorithm entrypoint ───────────────────────────────────


def learn_multimodal_pdag(adapters: Sequence[Adapter],
                          *, alpha: float = 0.01,
                          max_cond: int = 3,
                          target_bin_seconds: Optional[float] = None,
                          ) -> MultimodalPDAG:
    """End-to-end: run every adapter → merge → run the PC algorithm
    → return a ``MultimodalPDAG`` with NodeMeta on every node.

    Mirrors the cap policy from L11: conditioning sets ≤ 3, α=0.01
    by default (conservative — retains edges when uncertain).
    """
    from causality_dag import learn_pdag

    series_str, meta = merge_adapters(
        adapters, target_bin_seconds=target_bin_seconds,
    )
    # PDAG works on int keys. Build a stable str→int map.
    keys = sorted(series_str.keys())
    node_to_id = {k: i for i, k in enumerate(keys)}
    id_to_node = {i: k for k, i in node_to_id.items()}
    series_int = {node_to_id[k]: v for k, v in series_str.items()}

    pdag = learn_pdag(series_int, alpha=alpha, max_cond=max_cond)

    return MultimodalPDAG(
        pdag=pdag, meta=meta,
        id_to_node=id_to_node, node_to_id=node_to_id,
    )


__all__ = [
    "Adapter", "NodeMeta", "MultimodalPDAG",
    "merge_adapters", "learn_multimodal_pdag",
]
