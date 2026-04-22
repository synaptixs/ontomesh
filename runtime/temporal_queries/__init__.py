"""
temporal_queries — Parameterised SPARQL templates for the memory layer.

Templates (fill {{PARAM}} placeholders before execution):
    TQ-01  Point-in-time ontology snapshot
    TQ-02  Sliding-window KPI aggregation
    TQ-03  Bi-temporal query (valid-time × transaction-time)
    TQ-04  Temporal diff between two agent flavors
    TQ-05  Provenance invalidation chain

Usage::

    from runtime.temporal_queries import load_template, fill_template

    sparql = fill_template("TQ-01", {
        "AT_TIMESTAMP": "2026-04-10T02:00:00Z",
        "ENTITY_IRI":   "AMF-East-01",
    })
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_template(name: str) -> str:
    """Load a SPARQL template by short name (e.g. ``"TQ-01"``).

    Args:
        name: Template name prefix, e.g. ``"TQ-01"`` or ``"TQ-01-point-in-time-snapshot"``.

    Returns:
        Raw SPARQL template string with ``{{PARAM}}`` placeholders.

    Raises:
        FileNotFoundError: If no matching template file is found.
    """
    for fname in sorted(os.listdir(_HERE)):
        if fname.startswith(name) and fname.endswith(".sparql"):
            with open(os.path.join(_HERE, fname), "r", encoding="utf-8") as fh:
                return fh.read()
    raise FileNotFoundError(
        f"No SPARQL template matching '{name}' in {_HERE}"
    )


def fill_template(name: str, params: dict) -> str:
    """Load a template and substitute ``{{PARAM}}`` placeholders.

    Args:
        name: Template name prefix.
        params: Dict mapping placeholder names (without braces) to values.

    Returns:
        Ready-to-execute SPARQL string.
    """
    template = load_template(name)
    for key, value in params.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def list_templates() -> list:
    """Return a sorted list of available template names."""
    return sorted(
        fname[:-7]
        for fname in os.listdir(_HERE)
        if fname.endswith(".sparql")
    )
