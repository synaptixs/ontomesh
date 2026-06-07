"""
src/events_bus.py — P0.3 + P3.2
─────────────────────────────────
Backend-agnostic publish/subscribe bus for live UI updates.

Any toolkit code can ``publish(kind, payload)`` and every connected
SSE subscriber — across all workers and replicas — receives the
event.  Two backends ship:

- **In-memory** (default).  ``queue.Queue`` per subscriber, single
  process.  Zero extra dependencies, perfect for single-worker dev
  setups and the Compose-on-laptop path.

- **Redis pub/sub** (opt-in).  Activated by setting the env var
  ``ONTOMESH_REDIS_URL`` (e.g. ``redis://redis:6379/0``).  Events
  published on any worker are received by subscribers on every
  worker AND every replica.  Required for multi-worker gunicorn
  and multi-replica k8s; pulled in by the ``[redis]`` extra
  (``pip install ontoforge[redis]``).

The choice is per-process; switching backends needs a restart.
If ``ONTOMESH_REDIS_URL`` is set but the redis package isn't
installed OR the URL is unreachable, the bus logs a warning and
falls back to in-memory so the wizard keeps booting.

Used by
- :mod:`metrics` — every ``record_metric`` call publishes a
  ``metric`` event so the wizard's drift dashboard can tick.
- The drift alerter — fires ``drift`` events when ECE / ARI / AUC
  cross thresholds (rendered as a toast on the client).
- The L13 / L9 / T1.1 status emitters.

API
- ``get_bus()`` returns the singleton (lazily picks the backend).
- ``publish(kind, payload)`` is the module-level convenience.
- ``reset_bus_for_tests()`` wipes the singleton + Redis stats key.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import queue
import sys
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_MAX_QUEUE_SIZE   = 256
_REDIS_CHANNEL    = "ontomesh:events"
_REDIS_STATS_KEY  = "ontomesh:bus:stats"


# ── In-memory backend ──────────────────────────────────────────────────


@dataclass
class Subscriber:
    """One SSE client's queue + identifier.  In-memory backend hands
    one back from :meth:`EventBus.subscribe`."""
    id:    str
    queue: "queue.Queue[Dict[str, Any]]" = field(
        default_factory=lambda: queue.Queue(maxsize=_MAX_QUEUE_SIZE),
    )

    def get(self, *, timeout: float = 20.0):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """No-op for the in-memory backend; kept for interface
        parity with the Redis backend."""
        return None


class EventBus:
    """Simple in-memory pub/sub.  Single Python process only."""

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._subscribers: List[Subscriber] = []
        self._dropped_count: int = 0
        self._published_count: int = 0

    def subscribe(self) -> Subscriber:
        sub = Subscriber(id=str(uuid.uuid4())[:8])
        with self._lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers
                                  if s.id != sub.id]
        sub.close()

    def publish(self, kind: str, payload: Dict[str, Any]) -> None:
        event = {
            "kind": kind,
            "ts":   _now_iso(),
            **(payload or {}),
        }
        with self._lock:
            self._published_count += 1
            for sub in list(self._subscribers):
                try:
                    sub.queue.put_nowait(event)
                except queue.Full:
                    self._dropped_count += 1

    @property
    def n_subscribers(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "backend":         "memory",
                "n_subscribers":   len(self._subscribers),
                "n_published":     self._published_count,
                "n_dropped":       self._dropped_count,
            }


# ── Redis backend ──────────────────────────────────────────────────────


class _RedisSubscriber:
    """One SSE client's Redis pubsub handle.  ``get`` blocks up to
    ``timeout`` for the next message; returns the deserialised event
    dict or None on timeout."""

    def __init__(self, sub_id: str, pubsub, channel: str) -> None:
        self.id        = sub_id
        self._pubsub   = pubsub
        self._channel  = channel

    def get(self, *, timeout: float = 20.0):
        msg = self._pubsub.get_message(
            timeout=timeout, ignore_subscribe_messages=True,
        )
        if not msg or msg.get("type") != "message":
            return None
        try:
            data = msg["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            return json.loads(data)
        except (KeyError, ValueError, UnicodeDecodeError):
            return None

    def close(self) -> None:
        try:
            self._pubsub.unsubscribe(self._channel)
            self._pubsub.close()
        except Exception:                                             # noqa: BLE001
            pass


class RedisEventBus:
    """Multi-process pub/sub via Redis.  Same interface as
    :class:`EventBus`; events published on any process reach
    subscribers on every process."""

    def __init__(self, url: str) -> None:
        import redis                                                  # noqa: F401
        self._url      = url
        self._client   = redis.Redis.from_url(url, decode_responses=False)
        self._channel  = _REDIS_CHANNEL
        self._stats    = _REDIS_STATS_KEY
        # Fail-fast at construction so we fall back to in-memory if
        # Redis is unreachable, rather than crashing the wizard.
        self._client.ping()

    def subscribe(self) -> _RedisSubscriber:
        ps = self._client.pubsub(ignore_subscribe_messages=True)
        ps.subscribe(self._channel)
        # Redis pub/sub registers the SUBSCRIBE on the connection
        # buffer only when a read is issued — without this flush a
        # caller that publishes immediately after subscribing can
        # race past the registration and the event is lost.
        # ignore_subscribe_messages=True discards the confirmation.
        ps.get_message(timeout=1.0)
        return _RedisSubscriber(
            sub_id=str(uuid.uuid4())[:8],
            pubsub=ps,
            channel=self._channel,
        )

    def unsubscribe(self, sub: _RedisSubscriber) -> None:
        sub.close()

    def publish(self, kind: str, payload: Dict[str, Any]) -> None:
        event = {
            "kind": kind,
            "ts":   _now_iso(),
            **(payload or {}),
        }
        try:
            self._client.publish(self._channel, json.dumps(event))
            self._client.hincrby(self._stats, "n_published", 1)
        except Exception:                                             # noqa: BLE001
            try:
                self._client.hincrby(self._stats, "n_dropped", 1)
            except Exception:                                         # noqa: BLE001
                pass

    @property
    def n_subscribers(self) -> int:
        try:
            result = self._client.execute_command(
                "PUBSUB", "NUMSUB", self._channel,
            )
            return int(result[1]) if len(result) >= 2 else 0
        except Exception:                                             # noqa: BLE001
            return 0

    @property
    def stats(self) -> Dict[str, int]:
        try:
            raw = self._client.hgetall(self._stats) or {}
            def _i(key):
                return int(raw.get(key, raw.get(key.encode("utf-8"), 0)))
            return {
                "backend":       "redis",
                "url":           self._url,
                "n_subscribers": self.n_subscribers,
                "n_published":   _i("n_published"),
                "n_dropped":     _i("n_dropped"),
            }
        except Exception:                                             # noqa: BLE001
            return {
                "backend":       "redis",
                "url":           self._url,
                "n_subscribers": 0,
                "n_published":   0,
                "n_dropped":     0,
            }


# ── Module-level singleton ──────────────────────────────────────────────


_bus_instance: Optional[Any] = None
_init_lock = threading.Lock()


def _create_bus():
    """Pick the backend based on ONTOMESH_REDIS_URL.  Falls back to
    in-memory if Redis is requested but unreachable / not installed
    so the wizard never fails to boot because of a misconfig."""
    url = os.environ.get("ONTOMESH_REDIS_URL")
    if not url:
        return EventBus()
    try:
        bus = RedisEventBus(url)
        print(
            f"[events_bus] Redis backend OK: {url}",
            file=sys.stderr, flush=True,
        )
        return bus
    except Exception as exc:                                          # noqa: BLE001
        print(
            f"[events_bus] WARNING: Redis init failed ({exc!r}); "
            f"falling back to in-memory.  Multi-worker / multi-"
            f"replica fan-out will be incorrect until this is fixed.",
            file=sys.stderr, flush=True,
        )
        return EventBus()


def get_bus():
    """Return the process-wide bus.  Created lazily so the env-var
    pick happens AFTER gunicorn has set up the worker process."""
    global _bus_instance
    if _bus_instance is not None:
        return _bus_instance
    with _init_lock:
        if _bus_instance is None:
            _bus_instance = _create_bus()
    return _bus_instance


def publish(kind: str, payload: Dict[str, Any] = None) -> None:
    """Module-level convenience — most call sites use this rather
    than reaching for ``get_bus().publish``."""
    get_bus().publish(kind, payload or {})


def reset_bus_for_tests() -> None:
    """Wipe the singleton + (if Redis) clear the cumulative stats
    key.  Pytest fixtures call this so tests don't leak state."""
    global _bus_instance
    with _init_lock:
        if isinstance(_bus_instance, RedisEventBus):
            try:
                _bus_instance._client.delete(_REDIS_STATS_KEY)        # noqa: SLF001
            except Exception:                                         # noqa: BLE001
                pass
        _bus_instance = None


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="seconds",
    )


__all__ = [
    "EventBus", "RedisEventBus", "Subscriber",
    "get_bus", "publish", "reset_bus_for_tests",
]
