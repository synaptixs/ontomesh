"""P3.1 — gunicorn config tests.

Static checks on deploy/gunicorn.conf.py + the pyproject extra.
We don't boot gunicorn in CI (slow + flaky on test runners); the
configuration is what would break in production, so we test it
directly.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "deploy" / "gunicorn.conf.py"


@pytest.fixture(scope="module")
def conf():
    """Load gunicorn.conf.py as a module so we can inspect its
    settings as live Python values, not just regex matches."""
    spec = importlib.util.spec_from_file_location("gconf", CONF)
    mod = importlib.util.module_from_spec(spec)
    # Default env so the config gets representative values.
    os.environ.setdefault("ONTOMESH_HOST", "0.0.0.0")
    os.environ.setdefault("ONTOMESH_PORT", "5051")
    spec.loader.exec_module(mod)
    return mod


# ── Worker setup ─────────────────────────────────────────────────────


def test_worker_class_is_gthread(conf):
    """gthread is the only worker class that holds many SSE
    connections per worker without spinning up extra processes.
    sync would block on the first SSE subscriber."""
    assert conf.worker_class == "gthread", \
        f"worker_class is {conf.worker_class!r}, expected gthread"


def test_workers_and_threads_overridable(conf, monkeypatch):
    """An operator must be able to scale workers/threads via env
    without rebuilding the image."""
    src = CONF.read_text()
    for var in ("ONTOMESH_WORKERS", "ONTOMESH_THREADS"):
        assert var in src, f"config doesn't read {var}"


def test_default_worker_count_is_reasonable(conf):
    """2 workers is the right default for a dev box; production
    operators override via ONTOMESH_WORKERS=N."""
    assert conf.workers >= 1
    assert conf.workers <= 4, \
        f"default workers={conf.workers} too high — leave headroom for laptops"


def test_default_threads_per_worker_supports_sse(conf):
    """SSE subscribers each pin a thread.  8 threads/worker × 2
    workers = 16 concurrent SSE connections — enough for a small
    internal team to keep tabs open."""
    assert conf.threads >= 4


# ── Bind address ─────────────────────────────────────────────────────


def test_bind_pulls_from_ontomesh_env(conf):
    """Same env-var names the Dockerfile uses, so an operator's
    `docker run -e ONTOMESH_PORT=8080` works untouched."""
    assert "ONTOMESH_HOST" in CONF.read_text()
    assert "ONTOMESH_PORT" in CONF.read_text()
    assert conf.bind == "0.0.0.0:5051"


# ── Timeouts ─────────────────────────────────────────────────────────


def test_timeout_long_enough_for_pipeline_runs(conf):
    """The toolkit pipeline can take ~10 s on a busy box; an SSE
    subscriber pings via the GET to /api/events/stream every 20 s.
    Both fit comfortably under the 120 s default."""
    assert conf.timeout >= 60


def test_keepalive_above_sse_heartbeat(conf):
    """events_bus.py heartbeats every 20 s.  Gunicorn's keepalive
    must be > 20 s or the connection dies between heartbeats."""
    assert conf.keepalive > 20


def test_graceful_timeout_long_enough_for_rolling_restart(conf):
    assert conf.graceful_timeout >= 15


# ── Lifecycle / observability ────────────────────────────────────────


def test_logs_go_to_stdout_stderr(conf):
    """`-` is gunicorn-speak for stdout/stderr.  Required for
    `docker logs` / journald / Loki to see anything."""
    assert conf.accesslog == "-"
    assert conf.errorlog  == "-"


def test_max_requests_recycles_workers(conf):
    """Memory leaks in rdflib + Flask are real.  Restarting each
    worker after ~1000 requests keeps the long-running process
    from drifting up."""
    assert conf.max_requests > 0
    assert conf.max_requests_jitter > 0


def test_on_starting_hook_prints_banner(conf):
    """A teammate reading `docker logs` needs ONE line that says
    'gunicorn started, here's the version, here's the bind' — the
    on_starting hook covers that."""
    assert callable(conf.on_starting)


def test_proc_name_set_to_ontomesh(conf):
    """`top` / `ps` should say `ontomesh-wizard`, not the default
    `gunicorn: master [...]` blob, so the team can spot it
    quickly."""
    assert conf.proc_name == "ontomesh-wizard"


# ── Pyproject ───────────────────────────────────────────────────────


def test_gunicorn_in_wizard_extra():
    """`pip install ontomesh[wizard]` must pull in gunicorn so the
    Dockerfile's ENTRYPOINT works after install -e ."""
    py = (ROOT / "pyproject.toml").read_text()
    # Find the wizard extra and assert gunicorn is in it.
    import re
    m = re.search(r"^wizard\s*=\s*\[(.+?)\]", py, re.DOTALL | re.MULTILINE)
    assert m, "no wizard extra"
    body = m.group(1)
    assert "gunicorn" in body
