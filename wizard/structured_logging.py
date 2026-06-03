"""wizard/structured_logging.py — P3.4

JSON access logging + X-Request-Id correlation.

Every log line emitted by the wizard's request lifecycle ends up as
a one-line JSON object that downstream collectors (Loki, Datadog,
Splunk, CloudWatch) can index without regex.  Every line carries:

    - ``ts``         ISO-8601 UTC timestamp.
    - ``level``      "info" / "warning" / "error" / etc.
    - ``logger``     module name that emitted the line.
    - ``message``    the human-readable summary.
    - ``request_id`` correlation ID, propagated end-to-end via
                     the X-Request-Id header.  Generated when the
                     incoming request didn't carry one.
    - any kwargs passed via the ``extra={}`` dict on the call.

Public surface
- ``install(app, logger=...)`` — wires Flask's ``before_request`` /
  ``after_request`` to inject the request_id and emit the access
  log line.  Idempotent; safe to call multiple times.
- ``get_request_id() -> str`` — the canonical accessor used by the
  /ready endpoint and any code that wants to log within a request.

The module is import-safe even when python-json-logger isn't
installed (the bare logging stdlib runs instead), so older
deployments don't break on import.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional


_REQUEST_ID_HEADER = "X-Request-Id"
_INSTALLED = False


# ── JSON formatter (best-effort) ──────────────────────────────────────


class _JsonFormatter(logging.Formatter):
    """Tiny self-contained fallback when python-json-logger isn't
    available.  Loses some niceties (custom field renames, message
    extras) but never errors at import time."""

    def format(self, record):                                         # noqa: A003
        import json
        payload: Dict[str, Any] = {
            "ts":      _dt.datetime.fromtimestamp(
                           record.created, _dt.timezone.utc,
                       ).isoformat(timespec="milliseconds"),
            "level":   record.levelname.lower(),
            "logger":  record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Include any record attributes that look like custom extras.
        for k, v in record.__dict__.items():
            if k in ("args", "asctime", "created", "exc_info",
                     "exc_text", "filename", "funcName", "levelname",
                     "levelno", "lineno", "message", "module",
                     "msecs", "msg", "name", "pathname", "process",
                     "processName", "relativeCreated", "stack_info",
                     "thread", "threadName"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except TypeError:
                payload[k] = repr(v)
        return json.dumps(payload, default=str)


def _pick_formatter() -> logging.Formatter:
    """Prefer python-json-logger when available; fall back gracefully."""
    try:
        from pythonjsonlogger import jsonlogger                       # noqa: F401
        return jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "asctime": "ts",
                            "name": "logger"},
            json_default=str,
            timestamp=True,
        )
    except Exception:                                                 # noqa: BLE001
        return _JsonFormatter()


# ── Request-context shim ──────────────────────────────────────────────


def get_request_id() -> str:
    """Return the current request's correlation ID, or 'no-request'
    if called outside an active Flask request context."""
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, "request_id", None):
            return g.request_id
    except Exception:                                                 # noqa: BLE001
        pass
    return "no-request"


class _RequestIdFilter(logging.Filter):
    """Logging filter that injects ``request_id`` onto every record so
    the JSON formatter picks it up."""

    def filter(self, record):                                          # noqa: A003
        record.request_id = get_request_id()
        return True


# ── Install hook ──────────────────────────────────────────────────────


def install(app, logger: Optional[logging.Logger] = None) -> None:
    """Wire JSON logging + X-Request-Id middleware onto a Flask app.

    Call once at module import (after the Flask ``app`` is created).
    Subsequent calls are no-ops so reimports during testing don't
    duplicate handlers."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    target = logger or logging.getLogger()
    target.setLevel(os.environ.get("ONTOMESH_LOGLEVEL", "info").upper())

    # Replace any existing handlers with our JSON one.  Idempotency
    # is enforced by the _INSTALLED guard above, so this only happens
    # on the first call.
    for h in list(target.handlers):
        target.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_pick_formatter())
    handler.addFilter(_RequestIdFilter())
    target.addHandler(handler)

    # Werkzeug's access log is replaced by our before/after_request
    # hooks so we can include the request_id and the elapsed time.
    werkzeug = logging.getLogger("werkzeug")
    werkzeug.setLevel(logging.WARNING)        # we emit our own access log

    access = logging.getLogger("ontomesh.access")

    @app.before_request
    def _stash_request_id():
        from flask import g, request
        rid = request.headers.get(_REQUEST_ID_HEADER) or \
              uuid.uuid4().hex[:16]
        g.request_id = rid
        g._req_start = time.perf_counter()

    @app.after_request
    def _emit_access_log(response):
        from flask import g, request
        elapsed_ms = round(
            (time.perf_counter() - getattr(g, "_req_start",
                                            time.perf_counter())) * 1000.0,
            2,
        )
        # Echo the request-id back so callers can correlate.
        response.headers[_REQUEST_ID_HEADER] = getattr(
            g, "request_id", "no-request",
        )
        # Don't log /live & /ready every 30 s — they spam the log
        # without adding signal.  Probes show up in metrics instead.
        if request.path not in ("/live", "/ready", "/health"):
            access.info(
                "%s %s %s",
                request.method, request.path, response.status_code,
                extra={
                    "method":      request.method,
                    "path":        request.path,
                    "status":      response.status_code,
                    "elapsed_ms":  elapsed_ms,
                    "remote_addr": request.remote_addr,
                    "user_agent":  request.headers.get("User-Agent", ""),
                },
            )
        return response
