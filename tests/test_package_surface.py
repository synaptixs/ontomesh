"""P1.2.5 — Package-surface + honest-landing tests.

Verifies that:

1.  The ``ontomesh`` Python package imports cleanly and exposes
    ``__version__``.
2.  Console scripts declared in ``pyproject.toml`` are reachable as
    importable ``main()`` callables (no PyPI/CI environment needed —
    just that the shim functions don't ImportError).
3.  The landing page no longer makes promises the codebase can't
    keep (no ``pip install ontomesh`` as the primary install path;
    no fabricated ``HybridRetriever`` import; no invented benchmark
    numbers).
4.  The benchmark runner produced ``benchmarks/last-run.json`` and
    the landing's stat numbers match it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("flask")


# ── Package surface ──────────────────────────────────────────────────


def test_ontomesh_package_imports():
    import ontomesh
    assert ontomesh.__version__.startswith("3.5"), \
        f"unexpected version {ontomesh.__version__!r}"


@pytest.mark.parametrize("modpath,attr", [
    ("ontomesh.cli",            "main"),
    ("ontomesh.wizard_entry",   "main"),
    ("ontomesh.onboard_entry",  "main"),
])
def test_console_script_entrypoints_importable(modpath, attr):
    """The functions referenced from pyproject.toml's
    [project.scripts] must be importable.  We don't *call* them
    (they'd block on Flask) — just confirm the shim resolves."""
    mod = __import__(modpath, fromlist=[attr])
    assert callable(getattr(mod, attr)), \
        f"{modpath}.{attr} is not callable"


def test_pyproject_declares_ontomesh_console_scripts():
    py = (ROOT / "pyproject.toml").read_text()
    for cmd in ("ontomesh ",
                "ontomesh-wizard ",
                "ontomesh-onboard "):
        assert cmd in py, f"console script {cmd.strip()!r} not declared"
    # And the package is included in the build.
    assert '"ontomesh*"' in py


# ── Benchmark ─────────────────────────────────────────────────────────


BENCH = ROOT / "benchmarks" / "last-run.json"


def test_benchmark_file_exists():
    assert BENCH.exists(), \
        "Run `python3 benchmarks/run_pipeline.py` to produce real numbers."


def test_benchmark_has_meaningful_numbers():
    data = json.loads(BENCH.read_text())
    assert data["ok"] is True
    # If the pipeline ever produces zero classes/properties, the
    # numbers we cite on the landing are wrong.
    assert data["owl_classes"]    > 50
    assert data["owl_properties"] > 100
    assert data["shacl_shapes"]   > 10
    assert 0 < data["elapsed_seconds"] < 120


# ── Honest landing ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def landing_body():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        rv = c.get("/")
    return rv.get_data(as_text=True)


def test_landing_no_longer_promises_unreleased_pypi(landing_body):
    """``pip install ontomesh`` from PyPI doesn't exist yet.  It MAY
    appear in the 'coming in v3.6' note, but MUST NOT be the primary
    install instruction in the hero install pill."""
    # The install pill should now say 'git clone' rather than 'pip install ontomesh'.
    pill_segment = landing_body.split('class="install"', 1)[1].split('</code>', 1)[0]
    assert "pip install ontomesh" not in pill_segment, \
        "install pill should NOT promise PyPI install yet"
    assert "git clone" in pill_segment


def test_landing_drops_fabricated_hybrid_retriever(landing_body):
    """The Python snippet used to import ``ontomesh.retrieval``
    which doesn't exist.  Make sure we didn't accidentally keep it."""
    assert "HybridRetriever"        not in landing_body
    assert "ontomesh.retrieval"     not in landing_body
    assert "from_bundle"            not in landing_body


def test_landing_uses_real_cli_commands(landing_body):
    """The snippet must reference commands that actually work after
    ``pip install -e .`` and a clone.  The Python snippet wraps each
    command word in a span for syntax-highlighting, so we look for
    fragments around the breaks."""
    # ontomesh CLI with --db flag (across the span boundary).
    assert "</span> --db" in landing_body
    # The wizard launcher.
    assert "ontomesh-wizard" in landing_body
    # And the log-mining phase.
    assert "--phase log" in landing_body


def test_landing_card_numbers_match_benchmark(landing_body):
    """Card stats must match what the benchmark produced — otherwise
    they're invented."""
    data = json.loads(BENCH.read_text())
    # Some of these are strings used verbatim on the page; if the
    # benchmark drifts, the landing must be regenerated too.
    assert str(data["owl_classes"])    in landing_body
    assert f"{data['owl_properties']:,}" in landing_body
    assert data["elapsed_human"]       in landing_body
    assert str(data["shacl_shapes"])   in landing_body


def test_trust_strip_is_open_standards_not_unverified_vendors(landing_body):
    """The trust strip should list open standards (OWL/SHACL/etc.) — we
    didn't ship verified integrations for every vector store on the
    previous list, so they were dropped."""
    assert "Built on open standards" in landing_body
    assert "OWL 2" in landing_body
    assert "SHACL" in landing_body
    # And we removed the unverified integration claims:
    assert "LlamaIndex" not in landing_body
    assert "LangChain"  not in landing_body
