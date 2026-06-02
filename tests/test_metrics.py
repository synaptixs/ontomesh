"""T2.6 — MLOps for the pipeline.

Tests MetricStore persistence, DriftAlerter rules, and Prometheus
exposition.

Acceptance gates (roadmap §3.T2.6):
- Snapshots emit + persist within 1 s.
- Drift alert fires when ECE > 0.05 for 3 consecutive runs.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from db.migrations.v3_metrics import migrate as v3_metrics_migrate     # noqa: E402
from metrics import (                                                  # noqa: E402
    DRIFT_ECE_CONSECUTIVE, DRIFT_ECE_THRESHOLD, DriftAlerter,
    DriftAlert, MetricSnapshot, MetricStore,
    emit_prometheus, record_metric,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _conn():
    c = sqlite3.connect(":memory:")
    v3_metrics_migrate(c)
    return c


def _record(store, phase, name, value, tags=None, run=None):
    store.record(MetricSnapshot(
        phase=phase, name=name, value=value,
        tags=tags or {}, run_id=run,
    ))


# ── Migration ─────────────────────────────────────────────────────────


def test_migration_creates_pipeline_metrics_table():
    c = sqlite3.connect(":memory:")
    out = v3_metrics_migrate(c)
    assert "pipeline_metrics" in out["tables_created"]
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='pipeline_metrics'"
    ).fetchall()
    assert rows


def test_migration_is_idempotent():
    c = sqlite3.connect(":memory:")
    v3_metrics_migrate(c)
    v3_metrics_migrate(c)         # no errors on re-run


# ── MetricStore ───────────────────────────────────────────────────────


def test_record_and_read_back():
    c = _conn()
    store = MetricStore(c)
    _record(store, "L10", "ece", 0.04)
    h = store.history("L10", "ece")
    assert len(h) == 1
    assert h[0].value == 0.04


def test_history_returns_ascending_by_recorded_at():
    c = _conn()
    store = MetricStore(c)
    for v in (0.01, 0.02, 0.03):
        _record(store, "L10", "ece", v)
    h = store.history("L10", "ece")
    assert [s.value for s in h] == [0.01, 0.02, 0.03]


def test_history_respects_limit():
    c = _conn()
    store = MetricStore(c)
    for v in range(10):
        _record(store, "L10", "ece", v * 0.01)
    h = store.history("L10", "ece", limit=3)
    assert len(h) == 3
    assert [s.value for s in h] == [0.07, 0.08, 0.09]


def test_latest_returns_most_recent():
    c = _conn()
    store = MetricStore(c)
    _record(store, "L10", "ece", 0.04)
    _record(store, "L10", "ece", 0.06)
    assert store.latest("L10", "ece").value == 0.06


def test_all_metrics_returns_one_per_pair():
    c = _conn()
    store = MetricStore(c)
    _record(store, "L8",  "ari",         0.85)
    _record(store, "L8",  "ari",         0.83)        # second run, same metric
    _record(store, "L10", "ece",         0.04)
    _record(store, "L9",  "ranker_auc",  0.82)
    out = store.all_metrics()
    pairs = {(s.phase, s.name): s.value for s in out}
    assert pairs[("L8", "ari")] == 0.83
    assert pairs[("L10", "ece")] == 0.04
    assert pairs[("L9", "ranker_auc")] == 0.82


def test_record_metric_helper_round_trips():
    c = _conn()
    record_metric(c, "T1.1", "name_keep_rate", 0.73,
                  tags={"reviewer": "alice"}, run_id="r-1")
    store = MetricStore(c)
    h = store.history("T1.1", "name_keep_rate")
    assert len(h) == 1
    assert h[0].tags == {"reviewer": "alice"}
    assert h[0].run_id == "r-1"


# ── Latency acceptance gate ───────────────────────────────────────────


def test_snapshot_emit_under_1_second():
    """Roadmap §3.T2.6 gate: snapshots emit within 1 s of phase
    completion."""
    c = _conn()
    store = MetricStore(c)
    t0 = time.perf_counter()
    for v in range(20):
        _record(store, "L10", "ece", v * 0.001)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, (
        f"20 metric snapshots took {elapsed:.3f}s; budget 1s"
    )


# ── DriftAlerter rules ────────────────────────────────────────────────


def test_ece_drift_alert_fires_after_3_bad_runs():
    """Hero acceptance gate: ECE > 0.05 for 3 consecutive runs → alert."""
    c = _conn()
    store = MetricStore(c)
    for v in (0.06, 0.07, 0.08):
        _record(store, "L10", "ece", v)
    alerts = DriftAlerter(store).check()
    assert any(a.metric == "L10.ece" for a in alerts)
    alert = next(a for a in alerts if a.metric == "L10.ece")
    assert alert.severity == 2
    assert "ECE" in alert.message


def test_ece_alert_does_not_fire_after_2_bad_runs():
    c = _conn()
    store = MetricStore(c)
    for v in (0.06, 0.07):
        _record(store, "L10", "ece", v)
    assert not any(a.metric == "L10.ece"
                   for a in DriftAlerter(store).check())


def test_ece_alert_does_not_fire_when_recent_is_clean():
    c = _conn()
    store = MetricStore(c)
    for v in (0.07, 0.06, 0.03):       # last run inside threshold
        _record(store, "L10", "ece", v)
    assert not any(a.metric == "L10.ece"
                   for a in DriftAlerter(store).check())


def test_ari_drift_alert_fires_on_low_stability():
    c = _conn()
    store = MetricStore(c)
    _record(store, "L8", "ari", 0.85)
    _record(store, "L8", "ari", 0.60)      # < floor
    alerts = DriftAlerter(store).check()
    assert any(a.metric == "L8.ari" for a in alerts)


def test_auc_drift_alert_fires_on_large_drop():
    c = _conn()
    store = MetricStore(c)
    for v in (0.92, 0.91, 0.78):           # drop > 0.10
        _record(store, "L9", "ranker_auc", v)
    alerts = DriftAlerter(store).check()
    assert any(a.metric == "L9.ranker_auc" for a in alerts)


def test_jaccard_drift_alert_fires_below_floor():
    c = _conn()
    store = MetricStore(c)
    _record(store, "L11", "edge_jaccard", 0.85)
    _record(store, "L11", "edge_jaccard", 0.45)
    alerts = DriftAlerter(store).check()
    assert any(a.metric == "L11.edge_jaccard" for a in alerts)


def test_merge_distance_drift_alert_fires_on_rise():
    c = _conn()
    store = MetricStore(c)
    for v in (0.25, 0.30, 0.45):           # rise > 0.15
        _record(store, "L12", "mean_merge_distance", v)
    alerts = DriftAlerter(store).check()
    assert any(a.metric == "L12.mean_merge_distance" for a in alerts)


def test_no_alerts_on_healthy_pipeline():
    c = _conn()
    store = MetricStore(c)
    for v in (0.03, 0.02, 0.04):
        _record(store, "L10", "ece", v)
    for v in (0.91, 0.90, 0.92):
        _record(store, "L9", "ranker_auc", v)
    _record(store, "L8", "ari", 0.85)
    _record(store, "L8", "ari", 0.87)
    _record(store, "L11", "edge_jaccard", 0.78)
    _record(store, "L11", "edge_jaccard", 0.82)
    for v in (0.25, 0.26, 0.27):
        _record(store, "L12", "mean_merge_distance", v)
    alerts = DriftAlerter(store).check()
    assert alerts == []


# ── Prometheus exposition ─────────────────────────────────────────────


def test_emit_prometheus_renders_help_and_type_lines():
    snapshots = [
        MetricSnapshot(phase="L10", name="ece", value=0.04),
        MetricSnapshot(phase="L8",  name="ari", value=0.85,
                       tags={"service": "payments"}),
    ]
    text = emit_prometheus(snapshots)
    assert "# HELP toolkit_l10_ece" in text
    assert "# TYPE toolkit_l10_ece gauge" in text
    assert "toolkit_l10_ece 0.04" in text
    assert 'service="payments"' in text


def test_emit_prometheus_handles_empty():
    assert emit_prometheus([]) == ""


def test_emit_prometheus_escapes_tag_special_chars():
    s = MetricSnapshot(
        phase="L1", name="x", value=1.0,
        tags={"label": 'with "quotes" and \\ slash'},
    )
    text = emit_prometheus([s])
    # Quotes escaped, backslash doubled.
    assert '\\"quotes\\"' in text
    assert "\\\\" in text


def test_drift_alert_dict_round_trip():
    a = DriftAlert(metric="L10.ece", severity=2, message="x",
                   recent=[0.06, 0.07, 0.08], threshold=0.05)
    d = a.as_dict()
    assert d["metric"] == "L10.ece"
    assert d["severity"] == 2
    assert d["recent"] == [0.06, 0.07, 0.08]
