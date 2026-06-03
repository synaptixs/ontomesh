"""P2.2 — Docker Compose stack lint-style tests.

Static checks on compose.yml + the Caddy config so a regression in
either file is caught at PR time without needing to spin up the
stack in CI.

The actual `docker compose up` smoke test is documented in the
README / PR description and is run by hand before tagging a
release.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPOSE   = ROOT / "compose.yml"
CADDYFILE = ROOT / "deploy" / "Caddyfile"

yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def compose():
    assert COMPOSE.exists(), "compose.yml missing"
    return yaml.safe_load(COMPOSE.read_text())


@pytest.fixture(scope="module")
def caddy_text() -> str:
    assert CADDYFILE.exists(), "deploy/Caddyfile missing"
    return CADDYFILE.read_text()


# ── Compose structure ────────────────────────────────────────────────


def test_compose_declares_wizard_and_caddy(compose):
    services = compose.get("services", {})
    assert "wizard" in services, "no wizard service"
    assert "caddy"  in services, "no caddy service"


def test_wizard_service_uses_p21_image(compose):
    svc = compose["services"]["wizard"]
    # Uses the ontomesh image; version templated via env so we can
    # bump without editing two files.
    image = svc.get("image", "")
    assert "ontomesh" in image
    assert "${ONTOMESH_VERSION" in image
    # Build context is the repo root so a fresh clone + `docker
    # compose up --build` works.
    assert svc.get("build", {}).get("context") == "."
    assert svc["build"].get("dockerfile") == "Dockerfile"


def test_wizard_runs_as_non_root(compose):
    """The Compose definition mirrors the Dockerfile's uid 10001."""
    svc = compose["services"]["wizard"]
    assert svc.get("user") == "10001:10001", \
        f"wizard service runs as {svc.get('user')!r}, expected 10001:10001"


def test_wizard_has_healthcheck(compose):
    svc = compose["services"]["wizard"]
    hc = svc.get("healthcheck", {})
    assert hc, "wizard has no healthcheck stanza"
    test = " ".join(hc.get("test", []))
    # P3.3 — cheaper /live probe; /health stays for back-compat.
    assert "/live" in test or "/health" in test
    assert "curl" in test


def test_wizard_persistent_volume_mounted(compose):
    """The wizard MUST mount /data so SQLite + saved ontologies
    survive `docker compose down`."""
    svc = compose["services"]["wizard"]
    volumes = svc.get("volumes", [])
    assert any("/data" in v for v in volumes), \
        f"wizard doesn't mount a volume at /data: {volumes}"
    # And the named volume itself is declared.
    top_vols = compose.get("volumes", {})
    assert "ontomesh-data" in top_vols


def test_wizard_resource_limits_set(compose):
    """A runaway pipeline shouldn't take down the host — memory and
    CPU caps are declared."""
    svc = compose["services"]["wizard"]
    limits = svc.get("deploy", {}).get("resources", {}).get("limits", {})
    assert limits.get("memory"), "wizard has no memory limit"
    assert limits.get("cpus"),   "wizard has no CPU limit"


# ── Caddy service ────────────────────────────────────────────────────


def test_caddy_uses_alpine_image(compose):
    """Caddy alpine is ~50 MB vs ~150 MB for the full image."""
    svc = compose["services"]["caddy"]
    assert "caddy:" in svc.get("image", "") and "alpine" in svc["image"]


def test_caddy_exposes_80_and_443(compose):
    svc = compose["services"]["caddy"]
    ports = svc.get("ports", [])
    assert any("80:80"   in p for p in ports)
    assert any("443:443" in p for p in ports)


def test_caddy_depends_on_healthy_wizard(compose):
    """Compose must hold off forwarding until the wizard is actually
    ready — otherwise the first request after `up -d` 502s."""
    svc = compose["services"]["caddy"]
    deps = svc.get("depends_on", {})
    # Compose accepts both list and dict forms; we use the dict
    # form so we can set condition: service_healthy.
    assert isinstance(deps, dict), \
        "caddy depends_on should be a dict (so it can pin to service_healthy)"
    assert deps.get("wizard", {}).get("condition") == "service_healthy"


def test_caddy_mounts_caddyfile_readonly(compose):
    svc = compose["services"]["caddy"]
    volumes = svc.get("volumes", [])
    caddyfile_mounts = [v for v in volumes if "Caddyfile" in v]
    assert caddyfile_mounts, "Caddyfile not mounted"
    assert any(":ro" in m for m in caddyfile_mounts), \
        "Caddyfile mount should be read-only"


def test_caddy_state_volumes_declared(compose):
    """Cert + ACME state must persist or Caddy re-issues on every up."""
    top_vols = compose.get("volumes", {})
    assert "caddy-data"   in top_vols
    assert "caddy-config" in top_vols


# ── Caddyfile content ────────────────────────────────────────────────


def test_caddyfile_reverse_proxies_to_wizard(caddy_text):
    assert "reverse_proxy wizard:5051" in caddy_text


def test_caddyfile_sets_sse_safe_timeouts(caddy_text):
    """Long-lived /api/events/stream connections need a generous
    read_timeout (24 h) or Caddy will close them.  This is the most
    common production gotcha for SSE — verify it's set."""
    assert "read_timeout" in caddy_text
    assert "24h" in caddy_text


def test_caddyfile_strips_server_header(caddy_text):
    """Don't advertise the server stack in response headers."""
    assert "-Server" in caddy_text


def test_caddyfile_sets_security_headers(caddy_text):
    for header in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
    ):
        assert header in caddy_text, f"Caddyfile missing {header}"


def test_caddyfile_uses_env_var_domain(caddy_text):
    """{$ONTOMESH_DOMAIN} lets a single Caddyfile serve both local
    HTTP-only and production HTTPS without edits."""
    assert "{$ONTOMESH_DOMAIN}" in caddy_text


# ── Legacy compose moved aside ───────────────────────────────────────


def test_legacy_compose_renamed():
    """The pre-Ontomesh multi-service demo (toolkit + oxigraph + shacl
    + api-gateway, port 5000) used to live at docker-compose.yml,
    which conflicted with Compose v2's auto-discovery of our new
    compose.yml.  Verify it's been renamed out of the way."""
    new_path    = ROOT / "compose.yml"
    legacy_path = ROOT / "docker-compose.legacy.yml"
    bad_path    = ROOT / "docker-compose.yml"
    assert new_path.exists()
    assert legacy_path.exists() or not bad_path.exists(), \
        "rename docker-compose.yml to docker-compose.legacy.yml so " \
        "Compose v2 picks up compose.yml automatically"
    if legacy_path.exists() and bad_path.exists():
        pytest.fail("both compose.yml/docker-compose.yml AND "
                    "docker-compose.legacy.yml exist — pick one")
