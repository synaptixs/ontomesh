"""P2.4 — Managed-runtime deployment-config tests.

Static checks on fly.toml, render.yaml, and deploy/cloudrun.yaml.
We don't actually deploy in CI (slow + needs cloud creds); instead
we verify each manifest:

- references the P2.1 Dockerfile (no per-target Dockerfile drift)
- exposes the wizard on the right port (5051)
- declares a /health probe
- pipes through ONTOMESH_HOST / ONTOMESH_PORT / ONTOMESH_DATA_DIR
- documents where to plug in ONTOMESH_DB_URL when moving to Postgres
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLY        = ROOT / "fly.toml"
RENDER     = ROOT / "render.yaml"
CLOUDRUN   = ROOT / "deploy" / "cloudrun.yaml"
DEPLOY_RM  = ROOT / "deploy" / "README.md"

yaml = pytest.importorskip("yaml")


# ── Fly.io ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def fly_text() -> str:
    assert FLY.exists(), "fly.toml missing"
    return FLY.read_text()


def test_fly_uses_repo_dockerfile(fly_text):
    assert 'dockerfile = "Dockerfile"' in fly_text


def test_fly_exposes_5051(fly_text):
    assert "internal_port  = 5051" in fly_text \
        or "internal_port = 5051"  in fly_text


def test_fly_has_health_check(fly_text):
    """P3.3 moved this from /health → /live (back-compat /health
    still works).  Accept either form so the test doesn't pin one
    legacy path forever."""
    assert 'path          = "/live"' in fly_text \
        or 'path = "/live"' in fly_text \
        or 'path          = "/health"' in fly_text \
        or 'path = "/health"' in fly_text


def test_fly_sets_ontomesh_env(fly_text):
    for key in ("ONTOMESH_HOST", "ONTOMESH_PORT", "ONTOMESH_DATA_DIR"):
        assert key in fly_text, f"fly.toml missing env {key}"


def test_fly_force_https(fly_text):
    assert "force_https    = true" in fly_text \
        or "force_https = true" in fly_text


def test_fly_documents_db_url(fly_text):
    """ONTOMESH_DB_URL should at least appear in a comment so an
    operator knows where to add it for Postgres."""
    assert "ONTOMESH_DB_URL" in fly_text


# ── Render ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def render_doc():
    assert RENDER.exists(), "render.yaml missing"
    return yaml.safe_load(RENDER.read_text())


def test_render_declares_one_web_service(render_doc):
    services = render_doc.get("services", [])
    web = [s for s in services if s.get("type") == "web"]
    assert len(web) == 1, f"expected one web service, got {len(web)}"


def test_render_uses_docker_runtime(render_doc):
    svc = render_doc["services"][0]
    assert svc["runtime"] == "docker"
    assert svc.get("dockerfilePath") == "./Dockerfile"


def test_render_has_health_check(render_doc):
    svc = render_doc["services"][0]
    # P3.3 — /live is cheaper and doesn't restart the pod on a DB
    # outage; /health stays for back-compat.
    assert svc.get("healthCheckPath") in ("/live", "/health")


def test_render_sets_ontomesh_env(render_doc):
    svc = render_doc["services"][0]
    env_keys = {e["key"] for e in svc.get("envVars", [])}
    for key in ("ONTOMESH_HOST", "ONTOMESH_PORT", "ONTOMESH_DATA_DIR"):
        assert key in env_keys, f"render.yaml missing env {key}"


def test_render_mounts_persistent_disk(render_doc):
    svc = render_doc["services"][0]
    disk = svc.get("disk", {})
    assert disk.get("mountPath") == "/data"
    assert disk.get("sizeGB", 0) >= 1


def test_render_documents_db_url():
    """render.yaml ships with ONTOMESH_DB_URL commented out + a
    `databases:` block in the same state so the user can flip both
    on together."""
    text = RENDER.read_text()
    assert "ONTOMESH_DB_URL" in text
    assert "databases:" in text


# ── Cloud Run ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def cloudrun_doc():
    assert CLOUDRUN.exists(), "deploy/cloudrun.yaml missing"
    return yaml.safe_load(CLOUDRUN.read_text())


def test_cloudrun_is_knative_service(cloudrun_doc):
    assert cloudrun_doc.get("apiVersion") == "serving.knative.dev/v1"
    assert cloudrun_doc.get("kind") == "Service"


def test_cloudrun_uses_ontomesh_image(cloudrun_doc):
    spec = cloudrun_doc["spec"]["template"]["spec"]
    containers = spec["containers"]
    assert len(containers) == 1
    img = containers[0]["image"]
    assert "ontomesh" in img.lower()


def test_cloudrun_exposes_5051(cloudrun_doc):
    container = cloudrun_doc["spec"]["template"]["spec"]["containers"][0]
    ports = container.get("ports", [])
    assert any(p.get("containerPort") == 5051 for p in ports), \
        f"cloudrun.yaml doesn't expose 5051: {ports}"


def test_cloudrun_has_health_probes(cloudrun_doc):
    container = cloudrun_doc["spec"]["template"]["spec"]["containers"][0]
    startup = container.get("startupProbe", {}).get("httpGet", {})
    live    = container.get("livenessProbe", {}).get("httpGet", {})
    # P3.3 — /live is cheaper than /health and explicitly does
    # NOT touch the DB.
    assert startup.get("path") in ("/live", "/health")
    assert live.get("path")    in ("/live", "/health")


def test_cloudrun_sse_safe_timeout(cloudrun_doc):
    """Cloud Run's per-request timeout caps SSE keepalive.  We bump
    it to 5 minutes — the absolute max is 60 min on Cloud Run gen2."""
    spec = cloudrun_doc["spec"]["template"]["spec"]
    assert spec.get("timeoutSeconds", 0) >= 300


def test_cloudrun_documents_cloudsql_pairing():
    """SQLite on Cloud Run loses state on cold start.  The manifest
    must explicitly call out Cloud SQL as the pairing."""
    text = CLOUDRUN.read_text()
    assert "Cloud SQL" in text
    assert "ONTOMESH_DB_URL" in text


# ── Comparison docs ───────────────────────────────────────────────────


def test_deploy_readme_present():
    assert DEPLOY_RM.exists(), "deploy/README.md missing"


def test_deploy_readme_covers_every_target():
    text = DEPLOY_RM.read_text()
    for target in ("Single container", "Docker Compose",
                   "Fly.io", "Render", "Cloud Run"):
        assert target in text, f"deploy/README.md missing {target}"


def test_deploy_readme_calls_out_sse_handling():
    """Multiple production teams have hit "SSE through nginx ingress
    silently buffers" — the comparison doc must call this out."""
    text = DEPLOY_RM.read_text()
    assert "SSE" in text or "Server-Sent Events" in text
    assert "buffer" in text.lower() or "stream" in text.lower()
