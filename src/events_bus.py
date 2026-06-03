"""
src/events_bus.py — P0.3
────────────────────────
In-memory publish/subscribe bus for live UI updates.

Any toolkit code can ``publish(kind, payload)`` and every connected
SSE subscriber receives the event. Used by:

  - :mod:`metrics` — every ``record_metric`` call publishes a
    ``metric`` event so the wizard's drift dashboard can tick.
  - The drift alerter — fires ``drift`` events when ECE / ARI / AUC
    cross thresholds (rendered as a toast on the client).
  - The L13 GP rate-anomaly scan + L9 ranker refit + T1.1 LLM rename
    endpoints — emit ``status`` events so panel badges update
    without a polling loop.

Design contract
───────────────
- **Single-process.** Backed by a list of ``queue.Queue``s — one
  per active SSE subscriber. Fine for the Flask dev server and a
  single-tenant gunicorn worker. Multi-process production needs
  Redis pub/sub or similar; the API on this module stays the same.
- **Thread-safe.** ``publish`` is called from any phase code path
  (often a worker thread); subscribers run on the request thread
  that holds the SSE connection. A lock guards the subscriber list.
- **Non-blocking publishers.** A slow subscriber's full queue gets
  the event silently dropped — we never block ``record_metric``
  on a stuck browser tab.
- **Bounded memory.** Each subscriber queue caps at 256 pending
  events; dropped events log a warning but don't crash.
"""

from __future__ import annotations

import datetime as _dt
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


_MAX_QUEUE_SIZE = 256


@dataclass
class Subscriber:
    """One SSE client's queue + identifier. The bus hands one of
    these back from :meth:`EventBus.subscribe`; the SSE generator
    drains its queue."""
    id:    str
    queue: "queue.Queue[Dict[str, Any]]" = field(
        default_factory=lambda: queue.Queue(maxsize=_MAX_QUEUE_SIZE),
    )

    def get(self, *, timeout: float = 20.0):
        """Block until an event arrives or ``timeout`` elapses. Returns
        ``None`` on timeout so the caller can emit a keep-alive ping."""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


class EventBus:
    """Simple in-memory pub/sub. Single instance per Python process."""

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._subscribers: List[Subscriber] = []
        self._dropped_count: int = 0
        self._published_count: int = 0

    # ── Subscription ────────────────────────────────────────────────────

    def subscribe(self) -> Subscriber:
        sub = Subscriber(id=str(uuid.uuid4())[:8])
        with self._lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers
                                  if s.id != sub.id]

    # ── Publication ────────────────────────────────────────────────────

    def publish(self, kind: str, payload: Dict[str, Any]) -> None:
        """Send an event to every subscriber. The event shape is
        ``{"kind": str, "ts": ISO-string, **payload}`` — the kind
        and ts are added automatically.

        Never raises. A subscriber whose queue is full silently
        drops the event so the publisher (often a phase code path)
        is never blocked by a slow consumer.
        """
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

    # ── Introspection ───────────────────────────────────────────────────

    @property
    def n_subscribers(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "n_subscribers":   len(self._subscribers),
                "n_published":     self._published_count,
                "n_dropped":       self._dropped_count,
            }


# ── Module-level singleton ──────────────────────────────────────────────


_bus_instance: EventBus = EventBus()
_init_lock = threading.Lock()


def get_bus() -> EventBus:
    """Return the process-wide bus. Created on first import."""
    return _bus_instance


def publish(kind: str, payload: Dict[str, Any] = None) -> None:
    """Module-level convenience — most call sites use this rather
    than reaching for ``get_bus().publish``."""
    get_bus().publish(kind, payload or {})


def reset_bus_for_tests() -> None:
    """Wipe subscribers + counters. Pytest fixtures call this so
    tests don't leak state between cases."""
    global _bus_instance
    with _init_lock:
        _bus_instance = EventBus()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="seconds",
    )


__all__ = [
    "EventBus", "Subscriber",
    "get_bus", "publish", "reset_bus_for_tests",
]
