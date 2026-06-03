"""P3.3 — Liveness + readiness probe tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

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


# ── /live ────────────────────────────────────────────────────────────


def test_live_returns_200_with_alive_status(client):
    rv = client.get("/live")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "alive"


def test_live_reports_version(client):
    rv = client.get("/live")
    body = rv.get_json()
    assert "version" in body
    assert body["version"].startswith("3.")


def test_live_reports_timestamp(client):
    rv = client.get("/live")
    body = rv.get_json()
    assert "timestamp" in body
    assert body["timestamp"].startswith("20")           # ISO year


def test_live_does_not_touch_dependencies(client):
    """The whole point of /live is that it doesn't probe DB / Redis.
    Patch the store's list function to raise — /live must still 200
    so a k8s livenessProbe doesn't restart the pod over a DB outage."""
    with mock.patch("wizard.ontologies_store.list_ontologies",
                    side_effect=RuntimeError("DB down")):
        rv = client.get("/live")
    assert rv.status_code == 200


# ── /ready ───────────────────────────────────────────────────────────


def test_ready_returns_200_when_everything_up(client):
    rv = client.get("/ready")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "ready"


def test_ready_reports_each_dependency(client):
    rv = client.get("/ready")
    body = rv.get_json()
    checks = body["checks"]
    assert "store"  in checks
    assert "events" in checks
    # Each check reports a backend identifier so an operator can see
    # whether the wizard is on SQLite or Postgres at a glance.
    assert checks["store"]["backend"] in ("sqlite", "postgres")
    assert checks["events"]["backend"] in ("memory", "redis")


def test_ready_503s_when_store_down(client):
    """If the saved-ontologies store is unreachable, /ready must
    return 503 so a load balancer stops routing traffic — but the
    pod stays alive so it can recover."""
    with mock.patch("wizard.ontologies_store.list_ontologies",
                    side_effect=RuntimeError("DB unreachable")):
        rv = client.get("/ready")
    assert rv.status_code == 503
    body = rv.get_json()
    assert body["status"] == "not_ready"
    assert body["checks"]["store"]["ok"] is False
    # The error message is included so the operator can debug.
    assert "DB unreachable" in body["checks"]["store"]["error"]


def test_ready_stable_response_shape(client):
    """Monitoring parses this JSON; the keys must be stable so a
    schema change is a deliberate decision."""
    body = client.get("/ready").get_json()
    for key in ("status", "checks", "version", "timestamp"):
        assert key in body
    for check in body["checks"].values():
        assert "ok" in check


# ── /health (back-compat) ────────────────────────────────────────────


def test_health_still_returns_200_for_back_compat(client):
    """The pre-P3.3 endpoint stays so existing monitors don't break."""
    rv = client.get("/health")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True


# ── Deployment configs use /live ────────────────────────────────────


def test_dockerfile_healthcheck_uses_live():
    text = (ROOT / "Dockerfile").read_text()
    # The HEALTHCHECK directive should now hit /live, not /health.
    healthcheck_line = next(
        l for l in text.splitlines() if l.strip().startswith("CMD curl")
    )
    assert "/live" in healthcheck_line, \
        "Dockerfile HEALTHCHECK still hits /health (should be /live)"


def test_compose_healthcheck_uses_live():
    text = (ROOT / "compose.yml").read_text()
    seg = text.split("wizard:", 1)[1].split("redis:", 1)[0]
    assert "/live" in seg


def test_fly_healthcheck_uses_live():
    text = (ROOT / "fly.toml").read_text()
    assert 'path          = "/live"' in text or 'path = "/live"' in text


def test_render_healthcheck_uses_live():
    text = (ROOT / "render.yaml").read_text()
    assert "healthCheckPath: /live" in text


def test_cloudrun_probes_use_live():
    text = (ROOT / "deploy" / "cloudrun.yaml").read_text()
    # Both startupProbe and livenessProbe should now hit /live.
    # Count occurrences of `path: /live` — expect at least 2.
    assert text.count("path: /live") >= 2
