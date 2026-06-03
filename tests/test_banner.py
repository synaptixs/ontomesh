"""Boot-banner sanity tests.

The wizard's ``main()`` prints a banner before starting Flask.  In
v3.0 the banner read ``Ontology Toolkit — Ontology Studio (v3.0)``;
after P1.1 (rename to Ontomesh) and P2.1 (Docker image), it was
still saying that string in the container logs.  This test pins
the banner to the canonical brand + current version so a future
rename can't drift silently.
"""

from __future__ import annotations

import re
import sys
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("flask")


def _capture_banner():
    """Run ``main()`` with Flask stubbed; return captured stdout."""
    import app
    buf = StringIO()
    with mock.patch.object(app.app, "run") as _, \
         mock.patch.object(sys, "stdout", buf), \
         mock.patch.object(sys, "argv", ["ontomesh-wizard", "--port", "5099"]):
        app.main()
    return buf.getvalue()


def test_banner_uses_ontomesh_name():
    out = _capture_banner()
    assert "Ontomesh" in out
    # The pre-rename name MUST NOT appear in the banner.
    assert "Ontology Toolkit — Ontology Studio" not in out
    assert "v3.0" not in out


def test_banner_shows_canonical_tagline():
    out = _capture_banner()
    assert "the ontology mesh for GraphRAG" in out


def test_banner_shows_current_version():
    """Version is pulled from ontomesh.__version__ so it can't drift."""
    from ontomesh import __version__
    out = _capture_banner()
    assert __version__ in out


def test_banner_lists_all_surfaces():
    """A new user reads the banner and goes to /wizard or /projects.
    Both must be linked."""
    out = _capture_banner()
    for path in ("/wizard", "/projects", "/help", "/health"):
        assert path in out, f"banner missing {path}"


def test_banner_argparse_description_matches():
    """``--help`` output must also say Ontomesh, not Ontology Toolkit."""
    import app
    with mock.patch.object(sys, "argv", ["ontomesh-wizard", "--help"]):
        buf = StringIO()
        with mock.patch.object(sys, "stdout", buf), \
             mock.patch.object(app.app, "run"):
            try:
                app.main()
            except SystemExit:
                # argparse exits after --help
                pass
    text = buf.getvalue()
    assert "Ontomesh" in text
    assert "Ontology Toolkit — Ontology Studio" not in text
