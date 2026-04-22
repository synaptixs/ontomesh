"""
compliance — Workstream 4 (Gen2): Regulatory AI Compliance Evidence Engine
==========================================================================

Turns the toolkit's existing governance outputs — PROV-O chains, SHACL
validation records, governance scorecard, SPARQL CQ results — into
on-demand, signed, machine-verifiable evidence packages mapped to
named regulatory frameworks.

Public entry points:

  * :mod:`compliance.registry`     — load regulation JSON files
  * :mod:`compliance.assembler`    — build evidence for a regulation
  * :mod:`compliance.bundle`       — sign, package, and verify bundles
  * :mod:`compliance.mapping`      — regulation ↔ toolkit artefact index
  * :mod:`compliance.dashboard`    — governance scorecard + UI helpers

CLI:
    python3 toolkit.py --phase comply --regulation eu-ai-act \\
        --decision https://ontology.example.com/enterprise/observation/obs-001
    python3 toolkit.py --phase comply --verify compliance/bundles/<bundle>.zip
    python3 toolkit.py --phase comply --list-regulations
    python3 toolkit.py --phase comply --gap-analysis
"""

from __future__ import annotations

from .registry import (  # noqa: F401
    list_regulations,
    load_regulation,
    REGULATIONS_DIR,
)
from .assembler import assemble_evidence  # noqa: F401
from .bundle import export_bundle, verify_bundle  # noqa: F401
from .mapping import (  # noqa: F401
    build_mapping_index,
    gap_analysis,
    coverage_score,
)

__all__ = [
    "list_regulations", "load_regulation", "REGULATIONS_DIR",
    "assemble_evidence", "export_bundle", "verify_bundle",
    "build_mapping_index", "gap_analysis", "coverage_score",
]
