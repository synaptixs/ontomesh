"""``ontomesh-onboard`` console script — the interactive REPL wizard.

Wires the ``ontomesh-onboard`` console script declared in
``pyproject.toml`` to ``onboard.py``'s ``main()`` so:

    pip install -e .
    ontomesh-onboard --industry telecom

works identically to the historical:

    python3 onboard.py --industry telecom
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Console entry point for the ``ontomesh-onboard`` script."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    import onboard                                                    # noqa: E402
    onboard.main()


if __name__ == "__main__":
    main()
