"""``ontoforge-wizard`` console script — launches the Flask wizard.

Wires the ``ontoforge-wizard`` console script declared in
``pyproject.toml`` to ``wizard/app.py``'s ``main()`` so:

    pip install -e .
    ontoforge-wizard --port 5051

works identically to the historical:

    python3 wizard/app.py --port 5051
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Console entry point for the ``ontoforge-wizard`` script."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wizard_dir = os.path.join(here, "wizard")
    src_dir = os.path.join(here, "src")
    for p in (wizard_dir, src_dir, here):
        if p not in sys.path:
            sys.path.insert(0, p)
    # ``wizard/app.py`` exposes both ``app`` and ``main``.
    import app as _app                                                # noqa: E402
    _app.main()


if __name__ == "__main__":
    main()
