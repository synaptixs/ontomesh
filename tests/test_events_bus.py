"""P0.3 — In-memory event bus.

Tests publish/subscribe semantics, multi-subscriber fan-out,
slow-consumer protection, and the integration hook from
``metrics.record_metric``.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


from events_bus import (                                             # noqa: E402
    EventBus, get_bus, publish, reset_bus_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_bus():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


# ── Basic publish / subscribe ─────────────────────────────────────────


def test_publish_with_no_subscribers_does_not_raise():
    publish("test", {"k": 1})        # no listeners; must not throw
    assert get_bus().stats["n_published"] == 1


def test_one_subscriber_receives_published_event():
    bus = get_bus()
    sub = bus.subscribe()
    bus.publish("metric", {"phase": "L10", "value": 0.04})
    event = sub.get(timeout=1.0)
    assert event is not None
    assert event["kind"] == "metric"
    assert event["phase"] == "L10"
    assert event["value"] == 0.04
    assert "ts" in event


def test_publish_adds_ts_and_kind_fields():
    bus = get_bus()
    sub = bus.subscribe()
    bus.publish("drift", {})
    e = sub.get(timeout=1.0)
    assert e["kind"] == "drift"
    assert e["ts"].startswith("20")          # ISO year


def test_multi_subscriber_fan_out():
    bus = get_bus()
    s1, s2, s3 = bus.subscribe(), bus.subscribe(), bus.subscribe()
    bus.publish("status", {"x": 7})
    for sub in (s1, s2, s3):
        e = sub.get(timeout=1.0)
        assert e["x"] == 7
    assert bus.n_subscribers == 3


def test_unsubscribe_removes_from_fan_out():
    bus = get_bus()
    s1, s2 = bus.subscribe(), bus.subscribe()
    bus.unsubscribe(s1)
    bus.publish("metric", {"v": 1})
    assert s1.get(timeout=0.1) is None       # nothing for s1
    assert s2.get(timeout=1.0) is not None
    assert bus.n_subscribers == 1


def test_get_timeout_returns_none():
    sub = get_bus().subscribe()
    t0 = time.perf_counter()
    out = sub.get(timeout=0.1)
    elapsed = time.perf_counter() - t0
    assert out is None
    assert 0.05 < elapsed < 0.5


# ── Slow-consumer protection ──────────────────────────────────────────


def test_slow_subscriber_does_not_block_publishers():
    """A subscriber that never drains its queue must not block other
    subscribers or the publisher itself."""
    bus = get_bus()
    slow = bus.subscribe()
    fast = bus.subscribe()
    # Fill the slow subscriber's queue beyond capacity.
    for i in range(300):
        bus.publish("metric", {"i": i})
    # The fast subscriber still saw events; the bus didn't block.
    drained = 0
    while True:
        e = fast.get(timeout=0.05)
        if e is None:
            break
        drained += 1
        if drained > 250:
            break
    assert drained > 100
    # Dropped count reflects what couldn't fit on the slow subscriber.
    assert bus.stats["n_dropped"] > 0


# ── Thread safety ─────────────────────────────────────────────────────


def test_concurrent_publish_from_multiple_threads():
    bus = get_bus()
    sub = bus.subscribe()
    def _producer(start, n):
        for i in range(start, start + n):
            bus.publish("metric", {"i": i})
    threads = [threading.Thread(target=_producer, args=(t * 50, 50))
               for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seen = 0
    while True:
        e = sub.get(timeout=0.1)
        if e is None:
            break
        seen += 1
    # 4 threads × 50 events = 200.
    assert 100 <= seen <= 200


# ── Reset for tests ───────────────────────────────────────────────────


def test_reset_bus_clears_subscribers_and_counters():
    bus = get_bus()
    bus.subscribe()
    bus.publish("metric", {})
    assert bus.n_subscribers == 1
    reset_bus_for_tests()
    bus2 = get_bus()
    assert bus2.n_subscribers == 0
    assert bus2.stats["n_published"] == 0


# ── Integration: metrics.record_metric publishes a metric event ────────


def test_record_metric_publishes_metric_event_on_bus():
    """The hero integration: every record_metric call also fires
    a 'metric' event on the in-memory bus so the wizard's drift
    badges update without polling."""
    from db.migrations.v3_metrics import migrate as _v3_metrics
    from metrics import record_metric

    conn = sqlite3.connect(":memory:")
    _v3_metrics(conn)

    sub = get_bus().subscribe()
    record_metric(conn, "L10", "ece", 0.04, tags={"run": "test"})

    event = sub.get(timeout=1.0)
    assert event is not None
    assert event["kind"] == "metric"
    assert event["phase"] == "L10"
    assert event["name"]  == "ece"
    assert event["value"] == 0.04
    assert event["tags"]  == {"run": "test"}


def test_drift_alerter_publishes_drift_events():
    """When DriftAlerter.check() finds alerts, each one publishes
    a 'drift' event."""
    from db.migrations.v3_metrics import migrate as _v3_metrics
    from metrics import (DriftAlerter, MetricSnapshot, MetricStore)

    conn = sqlite3.connect(":memory:")
    _v3_metrics(conn)
    store = MetricStore(conn)
    # Three runs above the ECE threshold → an alert.
    for v in (0.06, 0.07, 0.08):
        store.record(MetricSnapshot(phase="L10", name="ece", value=v))

    sub = get_bus().subscribe()
    alerts = DriftAlerter(store).check()
    assert alerts                              # the check fired
    event = sub.get(timeout=1.0)
    assert event is not None
    assert event["kind"] == "drift"
    assert event["metric"] == "L10.ece"


# ── Stats ─────────────────────────────────────────────────────────────


def test_stats_track_counts_correctly():
    bus = get_bus()
    bus.subscribe()
    bus.subscribe()
    bus.publish("status", {})
    bus.publish("status", {})
    bus.publish("status", {})
    stats = bus.stats
    assert stats["n_subscribers"] == 2
    assert stats["n_published"] == 3
    assert stats["n_dropped"] == 0
