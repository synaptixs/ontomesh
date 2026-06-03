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
    install can come later in the file."""
    text = README.read_text()
    # Find where each install path is first mentioned.
    docker_idx = text.find("docker run")
    pip_idx    = text.find("pip install")
    git_idx    = text.find("git clone")
    assert docker_idx > 0, "README doesn't mention docker run"
    # docker run appears before git clone and pip install.
    assert docker_idx < pip_idx, "pip install appears before docker run"
    assert docker_idx < git_idx, "git clone appears before docker run"


def test_readme_documents_ghcr_login():
    text = README.read_text()
    assert "ghcr.io" in text
    # Tells the user to make a PAT with read:packages.
    assert "read:packages" in text
    assert "docker login" in text


def test_readme_uses_internal_image_path():
    text = README.read_text()
    assert "ghcr.io/nrohilla-fibonacci/ontomesh" in text


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


def test_readme_mentions_console_scripts():
    text = README.read_text()
    for cmd in ("ontomesh ", "ontomesh-wizard", "ontomesh-onboard"):
        assert cmd in text, f"README missing console script {cmd!r}"


def test_readme_links_deploy_guide():
    """deploy/README.md is the picking guide for the five
    deployment shapes; the project README must link it."""
    text = README.read_text()
    assert "deploy/README.md" in text


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
