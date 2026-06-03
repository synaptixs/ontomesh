/* wizard/static/js/components/live_events.js — P0.3
 *
 * Wraps EventSource('/api/events/stream') with:
 *   - Auto-reconnect on connection drop (3 s exponential backoff,
 *     capped at 30 s).
 *   - Typed handlers per event kind so call sites register one
 *     callback for "metric", another for "drift", etc.
 *   - A small status display the wizard chrome can render
 *     ("Live · 2 events" / "Disconnected · retrying").
 *
 * Usage:
 *
 *   import { LiveEvents } from "{{ url_for('static',
 *         filename='js/components/live_events.js') }}";
 *   const live = new LiveEvents();
 *   live.on('metric', e => refreshDriftDashboard(e));
 *   live.on('drift',  e => showToast(`Drift: ${e.message}`));
 *   live.start();
 */

export class LiveEvents {
  constructor(url = "/api/events/stream") {
    this.url = url;
    this.handlers = new Map();          // kind → Set<callback>
    this.es = null;
    this.retryDelay = 3000;
    this.maxRetryDelay = 30000;
    this.eventsReceived = 0;
    this.state = "idle";                // "idle" / "connecting" / "open" / "closed"
    this._stateListeners = new Set();
  }

  // ── Public API ──────────────────────────────────────────────

  /**
   * Register a handler for one event kind. Returns an unsubscribe
   * function — call it to stop receiving that kind.
   */
  on(kind, cb) {
    if (!this.handlers.has(kind)) this.handlers.set(kind, new Set());
    this.handlers.get(kind).add(cb);
    return () => this.handlers.get(kind)?.delete(cb);
  }

  /**
   * Subscribe to connection-state changes ("idle" / "connecting" /
   * "open" / "closed"). Useful for status badges.
   */
  onStateChange(cb) {
    this._stateListeners.add(cb);
    return () => this._stateListeners.delete(cb);
  }

  /**
   * Open the EventSource. Idempotent — calling start() while
   * already connected is a no-op.
   */
  start() {
    if (this.es && this.state === "open") return;
    this._setState("connecting");
    try {
      this.es = new EventSource(this.url);
    } catch (e) {
      this._setState("closed");
      this._scheduleRetry();
      return;
    }
    this.es.addEventListener("open", () => {
      this._setState("open");
      this.retryDelay = 3000;          // reset backoff on success
    });
    this.es.addEventListener("error", () => {
      this._setState("closed");
      this._scheduleRetry();
    });
    // The "message" event is the unnamed default; we route every
    // server-sent event by its named kind.
    this.es.addEventListener("message", e => this._dispatch("message", e));
    // Register a thin proxy for any kind we expect a server to emit.
    // EventSource requires the listener to be added BEFORE the named
    // event arrives, so we register the common kinds eagerly.
    ["hello", "metric", "drift", "status"].forEach(kind => {
      this.es.addEventListener(kind, e => this._dispatch(kind, e));
    });
  }

  stop() {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this._setState("idle");
  }

  // ── Internals ──────────────────────────────────────────────

  _dispatch(kind, ev) {
    this.eventsReceived++;
    let data = ev.data;
    try { data = JSON.parse(ev.data); } catch (_) { /* leave as string */ }
    const set = this.handlers.get(kind);
    if (!set) return;
    set.forEach(cb => {
      try { cb(data, ev); }
      catch (e) { console.warn(`LiveEvents handler for ${kind}:`, e); }
    });
  }

  _setState(state) {
    if (this.state === state) return;
    this.state = state;
    this._stateListeners.forEach(cb => {
      try { cb(state); } catch (_) {}
    });
  }

  _scheduleRetry() {
    setTimeout(() => {
      if (this.state !== "open") this.start();
    }, this.retryDelay);
    this.retryDelay = Math.min(this.retryDelay * 2, this.maxRetryDelay);
  }
}

export default LiveEvents;
