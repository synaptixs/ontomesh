"""``ontomesh`` console script — the headless pipeline CLI.

Wires the ``ontomesh`` console script declared in ``pyproject.toml``
to the existing ``toolkit.py`` ``main()`` function so:

    pip install -e .
    ontomesh --phase reason
    ontomesh --db custom.db --out ./out

works identically to the historical:

    python3 toolkit.py --phase reason
    python3 toolkit.py --db custom.db --out ./out

We deliberately do NOT duplicate argument parsing — ``toolkit.py``
owns the flag surface.  The shim is sys.argv-transparent: whatever
you pass after ``ontomesh`` reaches argparse in toolkit.py untouched.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Console entry point for the ``ontomesh`` script."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)

    argv = sys.argv[1:]
    # ``ontomesh search …`` routes to the reasoning-search CLI, leaving
    # toolkit.py's flag surface untouched.
    if argv and argv[0] == "search":
        from runtime.reasoning_search.cli import run                  # noqa: E402

        raise SystemExit(run(argv[1:]))

    # ``toolkit`` is at the repo root; importing it triggers no work,
    # the work happens in main().
    import toolkit                                                    # noqa: E402
    toolkit.main()


if __name__ == "__main__":
    main()
