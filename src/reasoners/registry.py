"""
src/reasoners/registry.py — T2.1
────────────────────────────────
Reasoner registry + selection helpers.

The selection rule:
1. If the caller names a specific reasoner, use that one.
2. Otherwise pick by ontology profile:
     EL  → robot-elk (fastest) → owlrl (fallback)
     DL  → robot-hermit → owlrl
     RL  → owlrl
3. If the selected reasoner reports ``available()=False``, fall
   back to ``owlrl`` (the only adapter that's always available).

The registry is a thin dict — adding a new reasoner is one
``__init__.py`` import and one entry in ``_BUILTIN``.
"""

from __future__ import annotations

from typing import Dict, Optional

from .base import Reasoner
from .mock import MockReasoner
from .owlrl_adapter import OwlrlReasoner
from .robot_elk import RobotElkReasoner
from .robot_hermit import RobotHermitReasoner


_BUILTIN: Dict[str, Reasoner] = {
    "owlrl":         OwlrlReasoner(),
    "robot-elk":     RobotElkReasoner(),
    "robot-hermit":  RobotHermitReasoner(),
    "mock":          MockReasoner(),
}


AVAILABLE_REASONERS = sorted(_BUILTIN.keys())


def get_reasoner(name: Optional[str] = None,
                 *, profile: Optional[str] = None,
                 fallback: bool = True) -> Reasoner:
    """Return a Reasoner. If ``name`` is given, look it up; if it's
    not registered or its runtime is unavailable, fall back to
    ``owlrl`` (unless ``fallback=False``, in which case we return
    the named adapter regardless — useful for tests that want to
    assert "skipped" behaviour).

    When ``name`` is None, picks by ``profile`` via
    :func:`default_reasoner_for_profile`.
    """
    if name is None:
        name = default_reasoner_for_profile(profile)
    r = _BUILTIN.get(name)
    if r is None:
        if not fallback:
            raise KeyError(f"unknown reasoner: {name!r}; "
                           f"available: {AVAILABLE_REASONERS}")
        return _BUILTIN["owlrl"]
    if fallback and not r.available():
        # Slide down to the always-available pure-Python adapter.
        return _BUILTIN["owlrl"]
    return r


def default_reasoner_for_profile(profile: Optional[str]) -> str:
    """Pick the best adapter for the OWL 2 profile. ``profile`` is a
    free-text label (we accept anything containing 'EL' / 'DL' / 'RL');
    everything else defaults to owlrl."""
    p = (profile or "").upper()
    if "EL" in p:
        # Prefer ROBOT/ELK if available; owlrl is the no-Java fallback.
        return "robot-elk"
    if "DL" in p:
        return "robot-hermit"
    return "owlrl"


__all__ = [
    "AVAILABLE_REASONERS", "get_reasoner",
    "default_reasoner_for_profile",
]
