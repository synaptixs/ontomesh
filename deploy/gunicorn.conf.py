"""Ontomesh — gunicorn config (P3.1).

Tuned for the wizard's traffic profile:

- Mostly cheap JSON / template responses (5–20 ms).
- A long tail of /api/events/stream subscribers per browser tab,
  each held open for hours.
- Occasional toolkit-pipeline POSTs that take several seconds.

The combination means:

- **Worker class** = ``gthread`` — each worker can hold many SSE
  connections concurrently without spinning up more processes.
  ``sync`` would block on the first SSE subscriber; ``gevent``
  works but adds a monkey-patching dependency we don't need.
- **threads per worker** = 8 — enough for ~8 concurrent open SSE
  streams per worker before they block each other.
- **workers** = 2 by default (sized for a single-host dev box).
  Override with ``ONTOMESH_WORKERS`` for bigger boxes.
- **timeout** = 120 s — long enough for pipeline runs but short
  enough to recover from a wedged worker.
- **graceful_timeout** = 30 s — give in-flight requests a chance to
  drain before SIGKILL on rolling restart.
- **keepalive** = 75 s — slightly above the SSE heartbeat (20 s)
  so the LB has room to send the next event before the
  connection idles out.

Override any of these via environment variables (every gunicorn
setting can be set via ``GUNICORN_<NAME>`` too — we just wrap the
ones that matter most).
"""

from __future__ import annotations

import os


# ── Binding ──────────────────────────────────────────────────────────


bind = f"{os.environ.get('ONTOMESH_HOST', '0.0.0.0')}:" \
       f"{os.environ.get('ONTOMESH_PORT', '5051')}"

# ── Workers ──────────────────────────────────────────────────────────

# Threaded workers are the sweet spot for SSE + JSON traffic.
worker_class = "gthread"
workers      = int(os.environ.get("ONTOMESH_WORKERS", "2"))
threads      = int(os.environ.get("ONTOMESH_THREADS", "8"))

# Recycle workers after 1000 requests to slough off any per-process
# memory growth (Flask + rdflib are not airtight).
max_requests        = 1000
max_requests_jitter = 50

# ── Timeouts ─────────────────────────────────────────────────────────

# A toolkit --phase log run can take ~10 s on a busy box.
timeout            = int(os.environ.get("ONTOMESH_TIMEOUT",          "120"))
graceful_timeout   = int(os.environ.get("ONTOMESH_GRACEFUL_TIMEOUT",  "30"))
# Just above the SSE heartbeat interval (20 s in events_bus.py).
keepalive          = int(os.environ.get("ONTOMESH_KEEPALIVE",         "75"))

# ── Logging ──────────────────────────────────────────────────────────

# Stream to stdout / stderr so `docker logs` and journald work.
accesslog  = "-"
errorlog   = "-"
loglevel   = os.environ.get("ONTOMESH_LOGLEVEL", "info")
# Compact access-log format until P3.4 swaps it for JSON.
access_log_format = '%(h)s %(t)s "%(r)s" %(s)s %(L)s "%(f)s"'

# ── Process naming ───────────────────────────────────────────────────

proc_name = "ontoforge-wizard"

# ── Pre-flight banner ────────────────────────────────────────────────


def on_starting(server):                                              # noqa: ARG001
    """Print a single-line summary before workers boot.  This is the
    production analogue of the Flask dev-server boot banner in
    wizard/app.py:main()."""
    try:
        import ontoforge
        ver = ontoforge.__version__
    except Exception:                                                 # noqa: BLE001
        ver = "unknown"
    print(
        f"  Ontomesh v{ver} · gunicorn · "
        f"workers={workers} · threads={threads} · "
        f"bind={bind} · class={worker_class}",
        flush=True,
    )
