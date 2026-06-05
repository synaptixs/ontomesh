"""Ontomesh — the ontology mesh for GraphRAG.

This package is the top-level public API surface that ships on PyPI
as ``ontomesh``.  Internally the toolkit's modules still live under
``src/`` for historical reasons; this package is a thin shim that
exposes the stable entry points (CLI, wizard launcher, onboarding)
through importable names so the install snippets on the landing page
actually work.

Module layout
-------------
``ontomesh``               — version, package metadata
``ontomesh.cli``           — ``ontomesh`` console script (full pipeline)
``ontomesh.wizard_entry``  — ``ontomesh-wizard`` console script (Flask UI)
``ontomesh.onboard_entry`` — ``ontomesh-onboard`` console script (REPL wizard)

The legacy entry points (``python3 toolkit.py`` and ``python3 onboard.py``)
remain on disk and behave identically — the console scripts merely call
their ``main()`` functions.

Stability
---------
These import paths are public from v3.5 onward.  Anything reachable from
``ontomesh.<x>`` is a long-term commitment; private helpers stay under
``src/``.  The current release pins to a single, simple surface so
SDK callers don't get tied to internals during the v3.x line.
"""

from __future__ import annotations

__version__ = "3.7.0"
__all__ = ["__version__"]
