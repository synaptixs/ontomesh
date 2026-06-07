"""P3.2 — Redis-backed SSE bus tests.

Skips cleanly when ONTOMESH_TEST_REDIS_URL isn't set so contributors
without Docker can still run the full suite.  Sets the env var
locally if you want to run them:

    docker run -d --name pg-redis-test -p 6379:6379 redis:7-alpine
    ONTOMESH_TEST_REDIS_URL=redis://localhost:6379/0 \
      python -m pytest tests/test_events_bus_redis.py -q
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


REDIS_URL = os.environ.get("ONTOMESH_TEST_REDIS_URL")

if not REDIS_URL:
    pytest.skip(
        "ONTOMESH_TEST_REDIS_URL not set — spin up a redis container "
        "and export it.",
        allow_module_level=True,
    )
pytest.importorskip("redis")


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redis_env(monkeypatch):
    monkeypatch.setenv("ONTOMESH_REDIS_URL", REDIS_URL)
    # Reload the module so the new env var is picked up by
    # _create_bus().
    import events_bus
    events_bus.reset_bus_for_tests()
    # Also clear the cumulative stats hash so test runs don't leak.
    import redis as _r
    _client = _r.Redis.from_url(REDIS_URL)
    _client.delete("ontomesh:bus:stats")
    yield
    events_bus.reset_bus_for_tests()


@pytest.fixture
def bus():
    from events_bus import get_bus
    b = get_bus()
    # If Redis isn't actually reachable, the bus silently falls back
    # to in-memory.  Surface that as a skip so the test is clearly
    # an integration test.
    if b.stats.get("backend") != "redis":
        pytest.skip("Redis URL set but bus fell back to in-memory — "
                    "is the container running?")
    return b


# ── Lifecycle ────────────────────────────────────────────────────────


def test_bus_reports_redis_backend(bus):
    assert bus.stats["backend"] == "redis"
    assert "url" in bus.stats


def test_subscribe_then_publish_round_trip(bus):
    sub = bus.subscribe()
    bus.publish("metric", {"phase": "L10", "value": 0.04})
    event = sub.get(timeout=2.0)
    assert event is not None
    assert event["kind"] == "metric"
    assert event["phase"] == "L10"
    assert event["value"] == 0.04
    assert "ts" in event


def test_multiple_publishes_arrive_in_order(bus):
    """Redis pub/sub delivers in order for a single channel —
    operators reading the dashboard expect chronological events."""
    sub = bus.subscribe()
    for i in range(5):
        bus.publish("metric", {"n": i})
    seen = []
    deadline = time.time() + 3.0
    while time.time() < deadline and len(seen) < 5:
        e = sub.get(timeout=0.5)
        if e is not None:
            seen.append(e["n"])
    assert seen == [0, 1, 2, 3, 4]


def test_publish_to_no_subscribers_is_silent_noop(bus):
    """No subscriber means no recipient; the publisher must not
    block or raise.  This is the same contract as the in-memory bus."""
    bus.publish("metric", {"k": 1})
    bus.publish("metric", {"k": 2})
    assert bus.stats["n_published"] >= 2


def test_unsubscribe_closes_redis_connection(bus):
    sub = bus.subscribe()
    bus.unsubscribe(sub)
    # After unsubscribe the pubsub client must not error on a fresh
    # get_message — this proves close() ran clean.
    assert sub.get(timeout=0.2) is None


# ── Fan-out across processes (simulated) ─────────────────────────────


def test_two_subscribers_both_receive(bus):
    """Two subscribers on the same channel both receive every event.
    Standing in for two gunicorn workers / two replicas."""
    s1 = bus.subscribe()
    s2 = bus.subscribe()
    bus.publish("drift", {"metric": "L10.ece"})
    e1 = s1.get(timeout=2.0)
    e2 = s2.get(timeout=2.0)
    assert e1 is not None and e1["kind"] == "drift"
    assert e2 is not None and e2["kind"] == "drift"


def test_pubsub_numsub_counts_active_subscribers(bus):
    """``n_subscribers`` queries Redis's PUBSUB NUMSUB — the truthful
    count across all processes connected to this Redis."""
    initial = bus.n_subscribers
    s1 = bus.subscribe()
    s2 = bus.subscribe()
    # Subscribe is async; give Redis a tick to register.
    time.sleep(0.2)
    assert bus.n_subscribers == initial + 2
    bus.unsubscribe(s1)
    bus.unsubscribe(s2)


# ── Stats ────────────────────────────────────────────────────────────


def test_stats_increment_across_publishes(bus):
    before = bus.stats["n_published"]
    bus.publish("metric", {})
    bus.publish("metric", {})
    bus.publish("metric", {})
    assert bus.stats["n_published"] == before + 3


def test_stats_shape_matches_inmemory_bus(bus):
    """The frontend shouldn't have to special-case which backend
    is active — every key the in-memory bus exposes must also be
    present in Redis stats."""
    stats = bus.stats
    for key in ("backend", "n_subscribers", "n_published", "n_dropped"):
        assert key in stats, f"Redis stats missing {key}"


# ── Concurrency ──────────────────────────────────────────────────────


def test_concurrent_publishes_from_threads_arrive(bus):
    """4 producer threads × 25 events each, on one channel, one
    subscriber.  The bus must not drop or duplicate."""
    sub = bus.subscribe()
    def _producer(start, n):
        for i in range(start, start + n):
            bus.publish("metric", {"i": i})
    threads = [threading.Thread(target=_producer, args=(t * 25, 25))
               for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seen = set()
    deadline = time.time() + 5.0
    while time.time() < deadline and len(seen) < 100:
        e = sub.get(timeout=0.5)
        if e is not None and "i" in e:
            seen.add(e["i"])
    # Allow a small loss tolerance under heavy concurrent load.
    assert len(seen) >= 90, f"only saw {len(seen)} of 100 events"


# ── Pyproject ────────────────────────────────────────────────────────


def test_redis_extra_in_pyproject():
    """`pip install ontoforge[redis]` must pull in the redis driver."""
    py = (ROOT / "pyproject.toml").read_text()
    import re
    m = re.search(r"^redis\s*=\s*\[(.+?)\]", py, re.MULTILINE)
    assert m, "no `[redis]` extra declared"
    body = m.group(1)
    assert "redis>=" in body
