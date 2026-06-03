"""P3.5 — Prometheus /metrics exporter tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("flask")
pytest.importorskip("prometheus_client")


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Endpoint ────────────────────────────────────────────────────────


def test_metrics_endpoint_returns_200(client):
    rv = client.get("/metrics")
    assert rv.status_code == 200


def test_metrics_endpoint_uses_prometheus_content_type(client):
    rv = client.get("/metrics")
    ct = rv.headers["Content-Type"]
    assert "text/plain" in ct
    assert "version=" in ct


# ── Core metrics ────────────────────────────────────────────────────


def test_metric_http_requests_total_present(client):
    client.get("/api/templates")
    body = client.get("/metrics").get_data(as_text=True)
    assert "ontomesh_http_requests_total" in body
    assert 'method="GET"' in body
    assert 'path="/api/templates"' in body
    assert 'status="200"' in body


def test_metric_http_request_duration_seconds_present(client):
    client.get("/api/templates")
    body = client.get("/metrics").get_data(as_text=True)
    assert "ontomesh_http_request_duration_seconds" in body
    # Histogram has the standard sub-families.
    assert "ontomesh_http_request_duration_seconds_bucket" in body
    assert "ontomesh_http_request_duration_seconds_count"  in body
    assert "ontomesh_http_request_duration_seconds_sum"    in body


def test_metric_sse_subscribers_present(client):
    body = client.get("/metrics").get_data(as_text=True)
    assert "ontomesh_sse_subscribers" in body


def test_metric_drift_events_total_appears_after_observe(client):
    from wizard.metrics_exporter import observe_drift
    observe_drift("L10.ece")
    body = client.get("/metrics").get_data(as_text=True)
    assert "ontomesh_drift_events_total" in body


def test_metric_pipeline_runs_total_appears_after_observe(client):
    from wizard.metrics_exporter import observe_pipeline_run
    observe_pipeline_run("mine")
    observe_pipeline_run("reason")
    body = client.get("/metrics").get_data(as_text=True)
    assert "ontomesh_pipeline_runs_total" in body
    assert 'phase="mine"' in body or 'phase="reason"' in body


# ── Path-label normalisation ────────────────────────────────────────


def test_path_label_collapses_help_routes(client):
    client.get("/help/domain")
    client.get("/help/events")
    client.get("/help/entities")
    body = client.get("/metrics").get_data(as_text=True)
    assert 'path="/help/<slug>"' in body
    assert 'path="/help/domain"'   not in body
    assert 'path="/help/events"'   not in body
    assert 'path="/help/entities"' not in body


def test_path_label_collapses_api_template_routes(client):
    client.get("/api/template/healthcare")
    body = client.get("/metrics").get_data(as_text=True)
    assert 'path="/api/template/<name>"' in body
    assert 'path="/api/template/healthcare"' not in body


def test_metrics_endpoint_excluded_from_its_own_histogram(client):
    """If /metrics counted itself we'd get a self-replicating series
    on every Prometheus scrape (every 15 s)."""
    client.get("/metrics")
    client.get("/metrics")
    body = client.get("/metrics").get_data(as_text=True)
    assert 'path="/metrics"' not in body


# ── Installation guard ─────────────────────────────────────────────


def test_install_idempotent():
    from wizard.metrics_exporter import install
    from app import app
    # Re-installing would otherwise raise Duplicated-timeseries.
    install(app)
    install(app)
    install(app)


# ── Pyproject ──────────────────────────────────────────────────────


def test_prometheus_client_in_wizard_extra():
    py = (ROOT / "pyproject.toml").read_text()
    assert "prometheus-client" in py
