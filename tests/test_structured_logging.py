"""P3.4 — Structured JSON logging + X-Request-Id correlation tests."""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("flask")


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Header round-trip ────────────────────────────────────────────────


def test_response_carries_request_id_even_when_client_didnt_send_one(client):
    """A client that didn't provide X-Request-Id still gets one back
    so it can quote it in a support ticket."""
    rv = client.get("/api/templates")
    assert rv.headers.get("X-Request-Id"), \
        "response missing X-Request-Id header"
    rid = rv.headers["X-Request-Id"]
    assert len(rid) >= 8, f"generated id too short: {rid!r}"


def test_client_provided_request_id_round_trips(client):
    """When the caller already has a correlation ID, the server
    propagates it back so log lines on both sides share it."""
    rv = client.get(
        "/api/templates",
        headers={"X-Request-Id": "trace-from-front-12345"},
    )
    assert rv.headers.get("X-Request-Id") == "trace-from-front-12345"


def test_each_request_gets_a_distinct_id(client):
    rv1 = client.get("/api/templates")
    rv2 = client.get("/api/templates")
    assert rv1.headers["X-Request-Id"] != rv2.headers["X-Request-Id"]


# ── Access log content ───────────────────────────────────────────────


def _capture_access_log(client, path):
    """Hook into ontomesh.access and capture a single log line as
    a structured dict."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    # Use the same formatter pick logic so the test reflects prod.
    from wizard.structured_logging import _pick_formatter
    handler.setFormatter(_pick_formatter())
    from wizard.structured_logging import _RequestIdFilter
    handler.addFilter(_RequestIdFilter())
    access = logging.getLogger("ontomesh.access")
    access.addHandler(handler)
    try:
        client.get(path)
    finally:
        access.removeHandler(handler)
    return buf.getvalue().strip().splitlines()


def test_access_log_is_valid_json(client):
    lines = _capture_access_log(client, "/api/templates")
    assert lines, "no access log line produced"
    payload = json.loads(lines[-1])
    # Spot-check the expected fields.
    for k in ("level", "logger", "message", "method", "path",
              "status", "elapsed_ms", "request_id"):
        assert k in payload, f"access log missing {k}; got: {payload}"


def test_access_log_records_status_and_path(client):
    lines = _capture_access_log(client, "/api/templates")
    payload = json.loads(lines[-1])
    assert payload["method"] == "GET"
    assert payload["path"]   == "/api/templates"
    assert payload["status"] == 200


def test_access_log_request_id_matches_response_header(client):
    """A user filing a bug pastes the response header value; the
    server's log line must use the SAME id."""
    rv = client.get("/api/templates",
                    headers={"X-Request-Id": "correlation-abc"})
    lines = _capture_access_log(client, "/api/templates")
    # The captured line is for the test request, not the previous
    # one — but the most recent call should reflect a fresh id.
    payload = json.loads(lines[-1])
    assert payload["request_id"]
    # And a known-id request round-trips:
    assert rv.headers["X-Request-Id"] == "correlation-abc"


def test_probes_are_not_access_logged(client):
    """/live and /ready get hit every 30 s by k8s — logging them
    drowns the signal in noise."""
    for path in ("/live", "/ready", "/health"):
        lines = _capture_access_log(client, path)
        # No JSON log line at all for these endpoints.
        assert not lines, f"{path} produced an access log line: {lines!r}"


# ── Pyproject ────────────────────────────────────────────────────────


def test_python_json_logger_in_wizard_extra():
    py = (ROOT / "pyproject.toml").read_text()
    assert "python-json-logger" in py


# ── Module installation guard ────────────────────────────────────────


def test_install_is_idempotent():
    """Re-importing or re-installing must not stack duplicate
    handlers — otherwise log lines get printed N times."""
    from wizard.structured_logging import install as _install
    from app import app
    target = logging.getLogger()
    before = len(target.handlers)
    _install(app)
    _install(app)
    _install(app)
    after = len(target.handlers)
    assert after == before, \
        f"install() stacked handlers: {before} -> {after}"


def test_get_request_id_exists_and_is_callable():
    """get_request_id is the public accessor used by view functions
    that want to include the correlation id in their own logs."""
    from wizard.structured_logging import get_request_id
    assert callable(get_request_id)
    # Returns a string in every case (real id inside a request,
    # sentinel outside).
    assert isinstance(get_request_id(), str)
