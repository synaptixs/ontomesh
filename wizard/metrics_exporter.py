"""wizard/metrics_exporter.py — P3.5

Prometheus exporter wired into the wizard's Flask app.

Exposes::

    GET /metrics

…in the Prometheus text format the standard scraper reads.  The
metric set is intentionally small and focused on what an SRE
needs to alert on:

    ontomesh_http_requests_total{method, path, status}        counter
    ontomesh_http_request_duration_seconds{method, path}      histogram
    ontomesh_sse_subscribers                                  gauge
    ontomesh_drift_events_total{metric}                       counter
    ontomesh_pipeline_runs_total{phase}                       counter
    ontomesh_search_requests_total{status, provider, cached}  counter
    ontomesh_search_duration_seconds{provider}                histogram
    ontomesh_search_result_rows_total                         counter
    ontomesh_search_derived_facts_total                       counter
    ontomesh_search_subgraph_triples_total                    counter

The exporter is multi-worker safe via ``MultiProcessCollector``
when gunicorn is running with workers > 1.  Set the env var
``PROMETHEUS_MULTIPROC_DIR`` to a writable directory in that case;
the Dockerfile points it at ``/tmp/ontomesh-prom-multiproc``.

Public surface
- ``install(app)``  — registers /metrics + before/after_request hooks.
                       Idempotent.
- ``observe_drift(metric: str)`` — call site for the drift alerter.
- ``observe_pipeline_run(phase: str)`` — call site for pipeline kickoffs.
- ``update_sse_subscribers(count: int)`` — periodically refreshed
  from the events_bus.get_bus().n_subscribers.
"""

from __future__ import annotations

import os
import time
from typing import Optional

# Lazy imports so this module is import-safe without prometheus_client.
_INSTALLED = False
_metrics_registered = False


# Module-level metric handles, populated by _register_metrics().
HTTP_REQUESTS_TOTAL = None        # Counter
HTTP_REQUEST_LATENCY = None       # Histogram
SSE_SUBSCRIBERS = None            # Gauge
DRIFT_EVENTS_TOTAL = None         # Counter
PIPELINE_RUNS_TOTAL = None        # Counter
SEARCH_REQUESTS_TOTAL = None      # Counter — reasoning search
SEARCH_LATENCY = None             # Histogram
SEARCH_ROWS_TOTAL = None          # Counter
SEARCH_DERIVED_TOTAL = None       # Counter
SEARCH_TRIPLES_TOTAL = None       # Counter


def _register_metrics():
    """Create the four metric handles.  Re-entrant: safe to call
    multiple times during testing."""
    global HTTP_REQUESTS_TOTAL, HTTP_REQUEST_LATENCY, SSE_SUBSCRIBERS
    global DRIFT_EVENTS_TOTAL, PIPELINE_RUNS_TOTAL, _metrics_registered
    global SEARCH_REQUESTS_TOTAL, SEARCH_LATENCY, SEARCH_ROWS_TOTAL
    global SEARCH_DERIVED_TOTAL, SEARCH_TRIPLES_TOTAL
    if _metrics_registered:
        return
    from prometheus_client import Counter, Gauge, Histogram

    HTTP_REQUESTS_TOTAL = Counter(
        "ontomesh_http_requests_total",
        "Total HTTP requests handled, partitioned by method, path "
        "(coarse — the wizard's route table — not the raw URL) and "
        "response status code.",
        labelnames=("method", "path", "status"),
    )
    HTTP_REQUEST_LATENCY = Histogram(
        "ontomesh_http_request_duration_seconds",
        "End-to-end HTTP request latency.",
        labelnames=("method", "path"),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    SSE_SUBSCRIBERS = Gauge(
        "ontomesh_sse_subscribers",
        "Currently-active SSE subscribers as reported by "
        "events_bus.get_bus().n_subscribers.",
        multiprocess_mode="livesum",
    )
    DRIFT_EVENTS_TOTAL = Counter(
        "ontomesh_drift_events_total",
        "Drift events fired by DriftAlerter, partitioned by metric "
        "(e.g. L10.ece, L13.rate-anomaly).",
        labelnames=("metric",),
    )
    PIPELINE_RUNS_TOTAL = Counter(
        "ontomesh_pipeline_runs_total",
        "Toolkit pipeline-phase kickoffs, partitioned by phase "
        "(e.g. mine, reason, test, all).",
        labelnames=("phase",),
    )
    SEARCH_REQUESTS_TOTAL = Counter(
        "ontomesh_search_requests_total",
        "Reasoning-search requests, partitioned by status "
        "(ok/empty/blocked/ungrounded/error), provider, and whether the "
        "response was served from cache.",
        labelnames=("status", "provider", "cached"),
    )
    SEARCH_LATENCY = Histogram(
        "ontomesh_search_duration_seconds",
        "End-to-end reasoning-search latency, partitioned by provider.",
        labelnames=("provider",),
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    SEARCH_ROWS_TOTAL = Counter(
        "ontomesh_search_result_rows_total",
        "Total rows returned by reasoning searches.",
    )
    SEARCH_DERIVED_TOTAL = Counter(
        "ontomesh_search_derived_facts_total",
        "Total facts derived by the reasoner across searches.",
    )
    SEARCH_TRIPLES_TOTAL = Counter(
        "ontomesh_search_subgraph_triples_total",
        "Total subgraph triples materialized across searches.",
    )
    _metrics_registered = True


# ── Route-label normaliser ───────────────────────────────────────────


def _coarse_path(raw_path: str) -> str:
    """Collapse URLs with path params (``/help/<slug>``,
    ``/api/template/<name>``, ``/api/ontologies/<slug>/load``) into
    a single Prometheus label so we don't explode the time-series
    cardinality."""
    # Strip trailing slash for normalisation.
    p = raw_path.rstrip("/") or "/"
    # Known templated routes — order matters (most specific first).
    rules = [
        ("/api/ontologies/", lambda s:
            "/api/ontologies/<slug>" if "/load" not in s and "/reharvest" not in s
            else "/api/ontologies/<slug>/load" if "/load" in s
            else "/api/ontologies/<slug>/reharvest"),
        ("/api/template/",   lambda s: "/api/template/<name>"),
        ("/help/",           lambda s: "/help/<slug>"),
        ("/mockups/",        lambda s: "/mockups/<id>"),
    ]
    for prefix, rule in rules:
        if p.startswith(prefix):
            return rule(p)
    return p


# ── Install hook ──────────────────────────────────────────────────────


def install(app, *, refresh_interval_seconds: float = 5.0) -> None:
    """Wire /metrics + the request lifecycle hooks onto a Flask app.

    Idempotent.  If prometheus_client isn't installed, logs a warning
    and returns silently — the wizard keeps booting."""
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from prometheus_client import (
            CONTENT_TYPE_LATEST, generate_latest,
        )
    except ImportError:
        import sys as _sys
        print(
            "[metrics_exporter] prometheus-client not installed; "
            "/metrics endpoint disabled.  Install ontoforge[wizard] "
            "to enable.",
            file=_sys.stderr,
        )
        return

    _register_metrics()
    _INSTALLED = True

    @app.before_request
    def _start_timer():
        from flask import g
        g._metrics_start = time.perf_counter()

    @app.after_request
    def _record_metrics(response):
        try:
            from flask import g, request
        except Exception:                                             # noqa: BLE001
            return response
        # Don't count /metrics in the latency histogram — it'd
        # poison the percentile dashboards with a fast loop.
        if request.path == "/metrics":
            return response
        path  = _coarse_path(request.path)
        start = getattr(g, "_metrics_start", time.perf_counter())
        elapsed = time.perf_counter() - start
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()
        HTTP_REQUEST_LATENCY.labels(
            method=request.method,
            path=path,
        ).observe(elapsed)
        return response

    @app.route("/metrics")
    def metrics():
        # Refresh the SSE subscribers gauge each scrape.  Best-effort —
        # if the bus isn't initialised yet, the gauge keeps its old
        # value rather than crashing.
        try:
            import sys as _sys
            _src = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "src",
            )
            if _src not in _sys.path:
                _sys.path.insert(0, _src)
            from events_bus import get_bus
            SSE_SUBSCRIBERS.set(get_bus().n_subscribers)
        except Exception:                                             # noqa: BLE001
            pass
        from flask import Response
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


# ── External call-site shortcuts ──────────────────────────────────────


def observe_drift(metric: str) -> None:
    """Call from the drift alerter every time a threshold trips."""
    if DRIFT_EVENTS_TOTAL is not None:
        DRIFT_EVENTS_TOTAL.labels(metric=metric).inc()


def observe_pipeline_run(phase: str) -> None:
    """Call from toolkit.py / the pipeline kickoff path."""
    if PIPELINE_RUNS_TOTAL is not None:
        PIPELINE_RUNS_TOTAL.labels(phase=phase).inc()


def observe_search(*, status: str = "ok", provider: str = "", cached: bool = False,
                   latency_seconds: float = 0.0, rows: int = 0, derived: int = 0,
                   triples: int = 0) -> None:
    """Call from the /api/search route once per request. No-op without prometheus."""
    if SEARCH_REQUESTS_TOTAL is None:
        return
    SEARCH_REQUESTS_TOTAL.labels(
        status=status or "ok", provider=provider or "unknown",
        cached=str(bool(cached)).lower()).inc()
    if not cached:
        SEARCH_LATENCY.labels(provider=provider or "unknown").observe(latency_seconds)
        SEARCH_ROWS_TOTAL.inc(rows)
        SEARCH_DERIVED_TOTAL.inc(derived)
        SEARCH_TRIPLES_TOTAL.inc(triples)
