"""P2.1 — Dockerfile lint-style tests.

We don't actually `docker build` in CI (slow + requires the daemon).
Instead we statically verify the Dockerfile + .dockerignore follow
the rules the team agreed on:

- Multi-stage build (builder → runtime).
- Slim Python base.
- Non-root final user (uid 10001).
- HEALTHCHECK declared and hits /health.
- ENTRYPOINT runs the ``ontoforge-wizard`` console script (not a raw
  ``python wizard/app.py``) so the install surface and the runtime
  surface stay in sync.
- .dockerignore excludes the obvious context-bloaters.

The actual `docker build` smoke-test is documented in the README /
PR description and is run by hand before tagging a release.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


@pytest.fixture(scope="module")
def df_text() -> str:
    assert DOCKERFILE.exists(), "Dockerfile missing"
    return DOCKERFILE.read_text()


@pytest.fixture(scope="module")
def di_text() -> str:
    assert DOCKERIGNORE.exists(), ".dockerignore missing"
    return DOCKERIGNORE.read_text()


# ── Dockerfile structure ──────────────────────────────────────────────


def test_dockerfile_is_multi_stage(df_text):
    """Two FROM ... AS stages: builder, runtime."""
    stages = re.findall(r"^FROM\s+\S+\s+AS\s+(\w+)", df_text, re.MULTILINE)
    assert "builder" in stages, "missing builder stage"
    assert "runtime" in stages, "missing runtime stage"
    # The runtime stage must come SECOND so it's the default target.
    assert stages.index("builder") < stages.index("runtime")


def test_dockerfile_uses_slim_python_base(df_text):
    """Slim base — keeps the image small and signals intent."""
    bases = re.findall(r"^FROM\s+(\S+)", df_text, re.MULTILINE)
    assert any("python:3.12-slim" in b for b in bases), \
        f"expected python:3.12-slim base, found {bases}"


def test_runtime_stage_is_non_root(df_text):
    """USER must be set to a non-root account (we use 'ontomesh').
    Skipping the USER line is a common security-review failure."""
    # The last USER directive wins; check that it's not root.
    user_lines = [l for l in df_text.splitlines()
                  if l.strip().startswith("USER ")]
    assert user_lines, "no USER directive — the container would run as root"
    last = user_lines[-1].strip()
    assert "root" not in last.lower(), f"runtime user is root: {last}"
    assert "ontomesh" in last


def test_dockerfile_has_healthcheck(df_text):
    # Find the actual HEALTHCHECK *directive* (start-of-line), not
    # any commentary that mentions the word.
    m = re.search(r"^HEALTHCHECK\b.*", df_text, re.MULTILINE)
    assert m, "no HEALTHCHECK directive"
    after = df_text[m.start():]
    head  = "\n".join(after.splitlines()[:4])
    # P3.3 — Dockerfile probe moved from /health to the cheaper /live;
    # /health stays as a back-compat alias so older monitors don't
    # break.  Either is acceptable here.
    assert "/live" in head or "/health" in head
    assert "curl" in head


def test_entrypoint_uses_gunicorn(df_text):
    """P3.1 — ENTRYPOINT must invoke gunicorn (the production WSGI
    server), not Flask's dev server.  The image is shipped to real
    customers; running with `app.run()` would print "WARNING: This
    is a development server" on every boot."""
    ep_lines = [l for l in df_text.splitlines()
                if l.strip().startswith("ENTRYPOINT")]
    assert ep_lines, "no ENTRYPOINT"
    last = ep_lines[-1]
    assert "gunicorn" in last, \
        f"ENTRYPOINT doesn't use gunicorn: {last}"
    # The config file pulls every operator-tunable knob from env
    # vars (workers / threads / timeout / port).
    assert "gunicorn.conf.py" in last
    # And the WSGI app reference is the canonical wizard.app:app.
    assert "wizard.app:app" in last


def test_runtime_exposes_5051(df_text):
    """EXPOSE 5051 advertises the wizard port so orchestrators can
    auto-detect.  Default ONTOMESH_PORT also = 5051."""
    assert re.search(r"^EXPOSE\s+5051\b", df_text, re.MULTILINE), \
        "missing EXPOSE 5051"
    assert "ONTOMESH_PORT=5051" in df_text


def test_persistent_data_dir_declared(df_text):
    """A volume mount point is the convention for stateful state."""
    assert "ONTOMESH_DATA_DIR=/data" in df_text
    assert 'mkdir -p "${ONTOMESH_DATA_DIR}"' in df_text


def test_python_unbuffered_set(df_text):
    """Without PYTHONUNBUFFERED, stdout buffering hides log lines from
    `docker logs` until the buffer fills."""
    assert "PYTHONUNBUFFERED=1" in df_text


def test_no_apt_lists_left_in_image(df_text):
    """Every apt-get install must be followed by rm -rf /var/lib/apt/lists/*
    so the apt cache doesn't bloat the image."""
    apt_blocks = re.findall(
        r"RUN apt-get update.*?(?=\n[A-Z]|\nUSER|\nFROM)",
        df_text, re.DOTALL,
    )
    for block in apt_blocks:
        assert "rm -rf /var/lib/apt/lists/*" in block, \
            f"apt cache not cleaned in:\n{block}"


# ── .dockerignore ─────────────────────────────────────────────────────


@pytest.mark.parametrize("pattern", [
    ".git",
    "__pycache__",
    "*.pyc",
    "tests/",
    ".pytest_cache",
    "output/",
    "benchmarks/out/",
    ".wizard_session.json",
    "Dockerfile",
])
def test_dockerignore_excludes(di_text, pattern):
    """Every listed pattern must be in .dockerignore so the build
    context stays lean."""
    lines = [l.strip() for l in di_text.splitlines() if l.strip()]
    assert pattern in lines, \
        f".dockerignore missing {pattern!r}; build context will include it"


def test_dockerignore_re_admits_readme(di_text):
    """README is excluded by ``*.md`` then re-admitted via ``!README.md``
    because pyproject.toml reads it for the long_description."""
    assert "!README.md" in di_text


# ── Pyproject ↔ Dockerfile parity ─────────────────────────────────────


def test_dockerfile_installs_wizard_extra():
    """The wizard image MUST install the [wizard] extra so Flask is
    present.  Without it, the entrypoint immediately crashes with
    ModuleNotFoundError: flask."""
    df_text = DOCKERFILE.read_text()
    # Either ".[wizard]" or "-e .[wizard]" is fine.
    assert "[wizard]" in df_text, \
        "Dockerfile doesn't install the [wizard] extra"


def test_console_scripts_match_dockerfile_entrypoint():
    """The script name in ENTRYPOINT must exist in pyproject.toml's
    [project.scripts] table — otherwise the image starts but can't
    run anything."""
    py = (ROOT / "pyproject.toml").read_text()
    # Whitespace before `=` may vary; check for the script name
    # followed by '=' allowing any spaces in between.
    assert re.search(r"\bontoforge-wizard\s*=\s*\"", py), \
        "ontoforge-wizard not declared in [project.scripts]"
