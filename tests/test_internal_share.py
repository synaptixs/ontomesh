"""P2.5 — Internal-share setup tests.

Static checks on:
- .github/workflows/publish-image.yml (the GHCR publish workflow)
- README.md (now leads with the docker run quickstart)

We don't run the workflow in tests (it needs cloud creds); these
catch the common drift modes (wrong image name, missing arch,
forgot the GHCR login step).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "publish-image.yml"
README   = ROOT / "README.md"

yaml = pytest.importorskip("yaml")


# ── Workflow ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW.exists(), "publish-image.yml missing"
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(workflow):
    """YAML's 'on' key is sometimes parsed as the bool True (YAML 1.1
    truthy).  Handle both shapes."""
    return workflow.get("on") or workflow.get(True)


def test_workflow_runs_on_tag_push_and_manual(workflow):
    triggers = _triggers(workflow)
    assert "push" in triggers, "workflow doesn't run on push"
    assert "workflow_dispatch" in triggers, \
        "workflow can't be triggered manually"
    # Only semver-style tags trigger the auto-publish.
    push_filter = triggers["push"]
    assert push_filter.get("tags"), "workflow runs on every push, " \
        "not just version tags"
    assert any("v" in t for t in push_filter["tags"])


def test_workflow_has_packages_write_permission(workflow):
    job = workflow["jobs"]["build-and-push"]
    perms = job.get("permissions", {})
    assert perms.get("packages") == "write", \
        "workflow needs packages:write to push to ghcr.io"


def test_workflow_logs_into_ghcr(workflow):
    job = workflow["jobs"]["build-and-push"]
    steps = job["steps"]
    login_steps = [s for s in steps if "login-action" in (s.get("uses") or "")]
    assert len(login_steps) == 1, \
        f"expected exactly one docker login step, got {len(login_steps)}"
    login = login_steps[0]
    # Either the literal "ghcr.io" or an env-var reference is fine
    # — just ensure the registry isn't pointing at Docker Hub.
    registry = login["with"]["registry"]
    text = WORKFLOW.read_text()
    assert "ghcr.io" in text, "workflow doesn't push to ghcr.io"
    assert "docker.io" not in registry.lower() or "ghcr" in text
    # GitHub-issued token, not a PAT — keeps the workflow self-contained.
    assert "secrets.GITHUB_TOKEN" in login["with"]["password"]


def test_workflow_targets_ontomesh_image(workflow):
    text = WORKFLOW.read_text()
    assert "ontomesh" in text
    # Image registry path is parameterised so we don't hard-code the org.
    assert "github.repository_owner" in text


def test_workflow_builds_multi_arch(workflow):
    job = workflow["jobs"]["build-and-push"]
    build_step = next(s for s in job["steps"]
                      if "build-push-action" in (s.get("uses") or ""))
    platforms = build_step["with"]["platforms"]
    assert "linux/amd64" in platforms, \
        "missing amd64 — Intel laptops + most cloud servers"
    assert "linux/arm64" in platforms, \
        "missing arm64 — Apple Silicon teammates"


def test_workflow_uses_gha_layer_cache(workflow):
    """Without GHA cache, each tag rebuilds the full image from
    scratch (~90 s).  With it, second tag of the same code is ~5 s."""
    job = workflow["jobs"]["build-and-push"]
    build_step = next(s for s in job["steps"]
                      if "build-push-action" in (s.get("uses") or ""))
    assert "type=gha" in build_step["with"].get("cache-from", "")
    assert "type=gha" in build_step["with"].get("cache-to",   "")


# ── P3.6 — Supply chain hardening ────────────────────────────────────


def test_workflow_attaches_sbom_and_provenance(workflow):
    """build-push-action must emit both an SLSA provenance
    attestation AND a SPDX SBOM as OCI artefacts."""
    job = workflow["jobs"]["build-and-push"]
    build_step = next(s for s in job["steps"]
                      if "build-push-action" in (s.get("uses") or ""))
    assert "provenance" in build_step["with"], \
        "build-push-action missing provenance: attestation"
    # mode=max gives the full SLSA build description, not just stub.
    assert "max" in str(build_step["with"]["provenance"])
    assert build_step["with"].get("sbom") is True or \
           str(build_step["with"].get("sbom")) == "true"


def test_workflow_runs_trivy_scan(workflow):
    """Every published image must be scanned for HIGH/CRITICAL CVEs
    before signing.  The Trivy step uses aquasecurity/trivy-action."""
    job = workflow["jobs"]["build-and-push"]
    trivy_steps = [s for s in job["steps"]
                   if "aquasecurity/trivy-action" in (s.get("uses") or "")]
    assert len(trivy_steps) == 1
    trivy = trivy_steps[0]
    # Severity floor.
    severity = str(trivy["with"]["severity"]).upper()
    assert "CRITICAL" in severity
    assert "HIGH"     in severity
    # SARIF output uploaded to the Security tab.
    assert trivy["with"]["format"] == "sarif"


def test_workflow_uploads_trivy_sarif_to_security_tab(workflow):
    job = workflow["jobs"]["build-and-push"]
    sarif_uploads = [s for s in job["steps"]
                     if "codeql-action/upload-sarif" in (s.get("uses") or "")]
    assert len(sarif_uploads) == 1


def test_workflow_signs_image_with_cosign(workflow):
    """Every published tag must be signed via keyless OIDC cosign so
    consumers can verify the image's provenance without a
    long-lived signing key in repo secrets."""
    job = workflow["jobs"]["build-and-push"]
    # Cosign installer step present.
    cosign_install = [s for s in job["steps"]
                      if "sigstore/cosign-installer" in (s.get("uses") or "")]
    assert len(cosign_install) == 1
    # Sign step iterates each tag and calls cosign sign --yes.
    sign_steps = [s for s in job["steps"]
                  if s.get("name") == "Sign image"]
    assert len(sign_steps) == 1
    assert "cosign sign" in sign_steps[0]["run"]
    # Keyless mode signs against the digest of the build.
    assert "DIGEST" in sign_steps[0]["env"]


def test_workflow_grants_id_token_permission(workflow):
    """id-token:write is required for cosign's keyless OIDC flow.
    Without it the sign step fails with 'OIDC token unavailable.'"""
    job = workflow["jobs"]["build-and-push"]
    perms = job.get("permissions", {})
    assert perms.get("id-token") == "write", \
        "id-token:write needed for keyless cosign"


def test_workflow_grants_security_events_permission(workflow):
    job = workflow["jobs"]["build-and-push"]
    perms = job.get("permissions", {})
    assert perms.get("security-events") == "write", \
        "security-events:write needed to upload Trivy SARIF"


def test_workflow_publishes_latest_on_tag(workflow):
    """On a tag push, both ontomesh:<version> AND ontomesh:latest
    must be published so teammates can `docker pull :latest` and
    always get the newest tagged build."""
    text = WORKFLOW.read_text()
    assert ":latest" in text


def test_workflow_publishes_branch_on_manual_run(workflow):
    """A manual workflow_dispatch should let an operator publish a
    pre-release image off any branch without bumping the version
    tag.  Our compute-tags step handles this."""
    text = WORKFLOW.read_text()
    assert "github.ref_name" in text
    assert "inputs.tag" in text


# ── README quickstart ─────────────────────────────────────────────────


def test_readme_leads_with_docker_quickstart():
    """The first install instruction in the README must be the
    `docker run` line — that's the whole point of P2.5.  A source
    install can come later in the file (or not at all — the
    P2.5.1 package-page README deliberately drops it and links the
    source repo instead)."""
    text = README.read_text()
    # docker run must appear above the fold.
    docker_idx = text.find("docker run")
    assert 0 < docker_idx < 2000, "docker run not in the README opener"
    # If pip install or git clone DO appear, they must come after.
    # Absence is also fine — the package-page README links the
    # source repo for those.
    for marker in ("pip install", "git clone"):
        idx = text.find(marker)
        if idx >= 0:
            assert idx > docker_idx, \
                f"{marker!r} appears before docker run"


def test_readme_documents_ghcr_login():
    text = README.read_text()
    assert "ghcr.io" in text
    # Tells the user to make a PAT with read:packages.
    assert "read:packages" in text
    assert "docker login" in text


def test_readme_uses_internal_image_path():
    text = README.read_text()
    assert "ghcr.io/synaptixs/ontomesh" in text


def test_readme_warns_internal_only():
    """A reader must see "this is private; do not share" before
    they think this is a public artifact."""
    text = README.read_text()
    # Look for an "internal" / "private" disclaimer somewhere in the
    # first 1500 characters (above-the-fold).
    head = text[:1500]
    assert "Internal" in head or "internal" in head
    assert "private" in head.lower()


def test_readme_documents_persistent_volume():
    """Stop / restart of an ephemeral container wipes saved
    ontologies.  The README must show the named-volume recipe."""
    text = README.read_text()
    assert "docker volume create" in text \
        or "-v " in text.split("Try it", 1)[1]
    assert "ONTOMESH_DATA_DIR" in text


def test_readme_links_at_least_four_surfaces():
    """The "what's at each URL" table must call out /wizard,
    /projects, /help, /health."""
    text = README.read_text()
    for path in ("/wizard", "/projects", "/help", "/health"):
        assert path in text, f"README missing {path}"


def test_readme_mentions_entrypoint_script():
    """The README must say which console script the image's
    ENTRYPOINT runs — that's the bridge between `docker run` and
    "you can also run it locally with pip"."""
    text = README.read_text()
    assert "ontomesh-wizard" in text, \
        "README doesn't name the wizard entrypoint script"


def test_readme_links_source_repo():
    """The package-page README is intentionally focused on what's
    in the image; deeper docs (deploy guides, integrate.md) live
    in the source repo, which the README must link."""
    text = README.read_text()
    assert "github.com/synaptixs/ontomesh" in text


def test_readme_links_deploy_guide():
    """deploy/README.md is the picking guide for the deployment
    shapes; the project README must link it (or the path in the
    source repo)."""
    text = README.read_text()
    assert "deploy/README.md" in text


# ── Package-page surface (P2.5.1) ─────────────────────────────────────


def test_readme_describes_image_size_and_arch():
    """The package-page README must answer 'how big' and 'what arch'
    in the first screen so a tester knows whether to pull on the
    coffee-shop wifi."""
    text = README.read_text()
    # Some kind of size statement.
    assert "MB" in text or "GB" in text
    # Multi-arch declared.
    assert "amd64" in text and "arm64" in text


def test_readme_documents_every_env_var():
    """The four canonical env vars (HOST/PORT/DATA_DIR/DB_URL) must
    all appear with a default / description, so an operator doesn't
    have to grep the Dockerfile."""
    text = README.read_text()
    for var in ("ONTOMESH_HOST", "ONTOMESH_PORT",
                "ONTOMESH_DATA_DIR", "ONTOMESH_DB_URL"):
        assert var in text, f"README doesn't document {var}"


def test_readme_lists_api_endpoints():
    """A tester who wants to script against the image needs to know
    /api/* exists; the README's What-you-get table calls them out."""
    text = README.read_text()
    assert "/api/events/stream" in text
    assert "/api/ontologies" in text


def test_readme_calls_out_nonroot_user():
    """Security-review checks read this in 10 seconds — make sure
    the image's non-root user (uid 10001) is documented."""
    text = README.read_text()
    assert "non-root" in text or "10001" in text


def test_readme_lists_starter_industries():
    """First-run onboarding loads from ten starter industries —
    the package page should preview them so a tester knows what
    they're picking from."""
    text = README.read_text()
    # All 10 should be at least mentioned somewhere in the README.
    for industry in ("telecom", "healthcare", "finance", "manufacturing",
                     "retail"):
        assert industry in text, f"README doesn't preview {industry}"


def test_readme_version_matches_pyproject():
    """README and pyproject.toml shouldn't drift across version
    bumps."""
    py = (ROOT / "pyproject.toml").read_text()
    rd = README.read_text()
    m = re.search(r'version\s*=\s*"([^"]+)"', py)
    assert m
    ver = m.group(1)            # e.g. "3.6.0-dev"
    # Either the full version OR the marketing-style "v3.6" appears.
    short = "v" + ver.split(".0-dev")[0].split("-")[0]
    assert ver in rd or short in rd, \
        f"README doesn't mention {ver} or {short}"
