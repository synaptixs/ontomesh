"""
src/metrics.py — T2.6
─────────────────────
Per-phase quality metrics, persistent history, drift alerting, and
Prometheus exposition.

Why this exists
───────────────
Before T2.3 auto-approval can be trusted, the operator needs
visibility into whether the underlying mining quality is *stable*.
Each phase L8 … L13 + the T1.1 ranker has a quantitative quality
signal we can sample on every run:

- L8 — regime stability (Adjusted Rand Index between consecutive runs)
- L9 — ranker cross-validated AUC
- L10 — Expected Calibration Error
- L11 — causal-edge Jaccard stability between runs
- L12 — mean merge-candidate distance (corpus drift indicator)
- L13 — false-positive rate (engineer feedback)
- T1.1 — LLM-name accept rate (does the engineer keep the LLM names?)

Each call site records a ``MetricSnapshot`` via :meth:`MetricStore.record`.
A drift alerter watches the last K runs of each metric and fires
when calibration / stability degrades below thresholds. Snapshots
also serialise to the standard Prometheus exposition format so an
external ``node_exporter`` / Grafana picks them up.

Storage is the same SQLite proposal-store used by the rest of the
toolkit — no new infrastructure required. The Grafana template
in ``ops/grafana/dashboard.json`` exposes the standard panels.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ── Defaults: drift thresholds (roadmap §3.T2.6) ─────────────────────────

DRIFT_ECE_THRESHOLD = 0.05            # L10
DRIFT_ECE_CONSECUTIVE = 3
DRIFT_ARI_FLOOR = 0.70                # L8 regime stability
DRIFT_AUC_DROP = 0.10                 # L9 ranker AUC drop
DRIFT_JACCARD_FLOOR = 0.60            # L11 causal-edge stability
DRIFT_MERGE_DISTANCE_RISE = 0.15      # L12 corpus-drift indicator


# ── Data shapes ──────────────────────────────────────────────────────────


@dataclass
class MetricSnapshot:
    """A single value emitted by one phase on one run."""
    phase:       str          # "L8" / "L10" / "T1.1" / ...
    name:        str          # "ari" / "ece" / "ranker_auc" / ...
    value:       float
    tags:        Dict[str, str] = field(default_factory=dict)
    run_id:      Optional[str] = None
    recorded_at: Optional[str] = None    # ISO; filled by the store

    def as_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase, "name": self.name,
            "value": self.value, "tags": dict(self.tags),
            "run_id": self.run_id, "recorded_at": self.recorded_at,
        }


@dataclass
class DriftAlert:
    """An emitted alert. ``severity`` is the routing hint Grafana
    keys off (P1..P4)."""
    metric:    str             # "L10.ece" / "L8.ari" / ...
    severity:  int             # 1 = highest
    message:   str
    recent:    List[float] = field(default_factory=list)
    threshold: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric, "severity": self.severity,
            "message": self.message,
            "recent": list(self.recent),
            "threshold": self.threshold,
        }


# ── Metric store (SQLite) ────────────────────────────────────────────────


class MetricStore:
    """Thin wrapper over the ``pipeline_metrics`` table. Use this
    everywhere a phase emits a metric.

    Concurrency: SQLite handles multiple readers and one writer per
    connection. Each phase call site opens its own connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        if not self._table_exists():
            from db.migrations.v3_metrics import migrate
            migrate(conn)

    def _table_exists(self) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='pipeline_metrics'"
        ).fetchone() is not None

    def record(self, snapshot: MetricSnapshot) -> None:
        if not self._table_exists():
            return
        ts = snapshot.recorded_at or _now_iso()
        self.conn.execute(
            "INSERT INTO pipeline_metrics "
            "(phase, metric_name, value, tags_json, run_id, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot.phase, snapshot.name, float(snapshot.value),
             json.dumps(snapshot.tags or {}), snapshot.run_id, ts),
        )
        self.conn.commit()
        snapshot.recorded_at = ts

    def history(self, phase: str, name: str,
                *, limit: int = 30) -> List[MetricSnapshot]:
        if not self._table_exists():
            return []
        rows = self.conn.execute(
            "SELECT phase, metric_name, value, tags_json, run_id, recorded_at "
            "FROM pipeline_metrics "
            "WHERE phase = ? AND metric_name = ? "
            "ORDER BY id DESC LIMIT ?",
            (phase, name, int(limit)),
        ).fetchall()
        out: List[MetricSnapshot] = []
        for r in rows:
            tags = {}
            try:
                tags = json.loads(r[3] or "{}")
            except Exception:                                       # noqa: BLE001
                tags = {}
            out.append(MetricSnapshot(
                phase=r[0], name=r[1], value=float(r[2]),
                tags=tags, run_id=r[4], recorded_at=r[5],
            ))
        return list(reversed(out))                  # ascending by recorded_at

    def latest(self, phase: str, name: str) -> Optional[MetricSnapshot]:
        h = self.history(phase, name, limit=1)
        return h[-1] if h else None

    def all_metrics(self) -> List[MetricSnapshot]:
        """Latest snapshot per (phase, name) pair — what the
        Prometheus exposition prints."""
        if not self._table_exists():
            return []
        rows = self.conn.execute(
            "SELECT phase, metric_name, value, tags_json, run_id, recorded_at "
            "FROM pipeline_metrics m "
            "WHERE id = (SELECT MAX(id) FROM pipeline_metrics "
            "             WHERE phase=m.phase AND metric_name=m.metric_name) "
            "ORDER BY phase, metric_name"
        ).fetchall()
        return [_row_to_snapshot(r) for r in rows]


def _row_to_snapshot(r) -> MetricSnapshot:
    try:
        tags = json.loads(r[3] or "{}")
    except Exception:                                               # noqa: BLE001
        tags = {}
    return MetricSnapshot(
        phase=r[0], name=r[1], value=float(r[2]), tags=tags,
        run_id=r[4], recorded_at=r[5],
    )


# ── Drift alerter ────────────────────────────────────────────────────────


class DriftAlerter:
    """Watches recent history of each well-known metric; emits a
    ``DriftAlert`` when thresholds are breached. The rules mirror
    §3.T2.6:

    - L10.ece > 0.05 for 3 consecutive runs → P2 alert.
    - L8.ari < 0.70 between consecutive runs → P3 alert.
    - L9.auc drop > 0.10 over 3 runs → P3 alert.
    - L11.jaccard < 0.60 vs prior run → P3 alert.
    - L12.mean_distance rising > 0.15 over 3 runs → P4 alert.
    """

    def __init__(self, store: MetricStore) -> None:
        self.store = store

    def check(self) -> List[DriftAlert]:
        alerts: List[DriftAlert] = []
        alerts += self._check_ece()
        alerts += self._check_ari()
        alerts += self._check_auc()
        alerts += self._check_jaccard()
        alerts += self._check_merge_distance()
        # P0.3 — push every alert to the SSE bus so the wizard's
        # toast layer surfaces it without polling.
        if alerts:
            try:
                from events_bus import publish
                for a in alerts:
                    publish("drift", a.as_dict())
            except Exception:                                  # noqa: BLE001
                pass
        return alerts

    def _check_ece(self) -> List[DriftAlert]:
        h = [s.value for s in self.store.history("L10", "ece",
                                                  limit=DRIFT_ECE_CONSECUTIVE)]
        if len(h) < DRIFT_ECE_CONSECUTIVE:
            return []
        if all(v > DRIFT_ECE_THRESHOLD for v in h):
            return [DriftAlert(
                metric="L10.ece", severity=2,
                message=(f"calibration drifting: last "
                         f"{DRIFT_ECE_CONSECUTIVE} runs all show "
                         f"ECE > {DRIFT_ECE_THRESHOLD}"),
                recent=h, threshold=DRIFT_ECE_THRESHOLD,
            )]
        return []

    def _check_ari(self) -> List[DriftAlert]:
        h = [s.value for s in self.store.history("L8", "ari", limit=2)]
        if len(h) < 2:
            return []
        if h[-1] < DRIFT_ARI_FLOOR:
            return [DriftAlert(
                metric="L8.ari", severity=3,
                message=(f"regime assignments unstable vs prior run: "
                         f"ARI={h[-1]:.3f} < {DRIFT_ARI_FLOOR}"),
                recent=h, threshold=DRIFT_ARI_FLOOR,
            )]
        return []

    def _check_auc(self) -> List[DriftAlert]:
        h = [s.value for s in self.store.history("L9", "ranker_auc",
                                                  limit=3)]
        if len(h) < 3:
            return []
        if (max(h) - h[-1]) > DRIFT_AUC_DROP:
            return [DriftAlert(
                metric="L9.ranker_auc", severity=3,
                message=(f"ranker AUC dropped {max(h) - h[-1]:.3f} "
                         f"over last 3 runs (now {h[-1]:.3f})"),
                recent=h, threshold=DRIFT_AUC_DROP,
            )]
        return []

    def _check_jaccard(self) -> List[DriftAlert]:
        h = [s.value for s in self.store.history("L11", "edge_jaccard",
                                                  limit=2)]
        if len(h) < 2:
            return []
        if h[-1] < DRIFT_JACCARD_FLOOR:
            return [DriftAlert(
                metric="L11.edge_jaccard", severity=3,
                message=(f"causal-graph stability degraded: Jaccard "
                         f"{h[-1]:.3f} < {DRIFT_JACCARD_FLOOR}"),
                recent=h, threshold=DRIFT_JACCARD_FLOOR,
            )]
        return []

    def _check_merge_distance(self) -> List[DriftAlert]:
        h = [s.value for s in self.store.history("L12", "mean_merge_distance",
                                                  limit=3)]
        if len(h) < 3:
            return []
        if h[-1] - h[0] > DRIFT_MERGE_DISTANCE_RISE:
            return [DriftAlert(
                metric="L12.mean_merge_distance", severity=4,
                message=(f"template-space drifting: mean merge-candidate "
                         f"distance rose {h[-1] - h[0]:.3f} over 3 runs"),
                recent=h, threshold=DRIFT_MERGE_DISTANCE_RISE,
            )]
        return []


# ── Prometheus exposition ────────────────────────────────────────────────


def emit_prometheus(snapshots: Sequence[MetricSnapshot]) -> str:
    """Render the standard text-format exposition. One ``# HELP``
    line + one ``# TYPE`` line + one value line per (phase, name,
    tag-set) tuple. Conforms to the Prometheus content-type
    ``text/plain; version=0.0.4``."""
    lines: List[str] = []
    seen_help = set()
    for s in snapshots:
        prom_name = _prom_name(s.phase, s.name)
        if prom_name not in seen_help:
            lines.append(f"# HELP {prom_name} Toolkit phase {s.phase} "
                         f"metric: {s.name}")
            lines.append(f"# TYPE {prom_name} gauge")
            seen_help.add(prom_name)
        tag_str = _prom_tags(s.tags)
        lines.append(f"{prom_name}{tag_str} {s.value}")
    return "\n".join(lines) + ("\n" if lines else "")


def _prom_name(phase: str, name: str) -> str:
    p = (phase or "").lower().replace(".", "_").replace("-", "_")
    n = (name or "").lower().replace("-", "_")
    return f"toolkit_{p}_{n}"


def _prom_tags(tags: Dict[str, str]) -> str:
    if not tags:
        return ""
    parts = []
    for k, v in sorted(tags.items()):
        # Escape backslash, quote, newline per the Prometheus spec.
        v_esc = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        parts.append(f'{k}="{v_esc}"')
    return "{" + ",".join(parts) + "}"


# ── Helpers ──────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="seconds",
    )


# ── Convenience: record one metric quickly ───────────────────────────────


def record_metric(conn: sqlite3.Connection, phase: str, name: str,
                  value: float, *, tags: Optional[Dict[str, str]] = None,
                  run_id: Optional[str] = None) -> None:
    """One-call helper for phase code that wants to emit a metric
    without instantiating a MetricStore explicitly.

    P0.3 — also publishes a ``metric`` event on the in-memory bus
    so the wizard's drift dashboard ticks live. Bus publish is
    non-blocking and silently no-ops if the bus module isn't on
    the import path (keeps this module safe to import in CI envs
    that don't have the Flask runtime available)."""
    store = MetricStore(conn)
    store.record(MetricSnapshot(
        phase=phase, name=name, value=float(value),
        tags=tags or {}, run_id=run_id,
    ))
    try:
        from events_bus import publish
        publish("metric", {
            "phase":  phase,
            "name":   name,
            "value":  float(value),
            "tags":   dict(tags or {}),
            "run_id": run_id,
        })
    except Exception:                                          # noqa: BLE001
        pass


__all__ = [
    "MetricSnapshot", "MetricStore", "DriftAlert", "DriftAlerter",
    "emit_prometheus", "record_metric",
    "DRIFT_ECE_THRESHOLD", "DRIFT_ECE_CONSECUTIVE",
    "DRIFT_ARI_FLOOR", "DRIFT_AUC_DROP",
    "DRIFT_JACCARD_FLOOR", "DRIFT_MERGE_DISTANCE_RISE",
]
