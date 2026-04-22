"""
compliance.registry — Workstream 4, Component 1
================================================
Loads the regulatory requirement registry from JSON files under
``compliance/regulations/``.  Each regulation is a single JSON file
declaring its identity, jurisdiction, effective date, and a list of
evidentiary requirements.  Every requirement maps to one toolkit
artefact type:

  * ``SPARQL_CQ``                — a CQ test in ``tests/sparql/``
  * ``SHACL_SHAPE``              — a SHACL node shape
  * ``PROV_O_CHAIN``             — provenance chain for a decision IRI
  * ``GOVERNANCE_SCORECARD_CRITERION`` — a named scorecard row
  * ``OBSERVATION_RECORD``       — a single observation by IRI

The loader is strict: unknown artefact types are rejected so callers
never silently miss evidence.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Optional

HERE             = os.path.dirname(os.path.abspath(__file__))
REGULATIONS_DIR  = os.path.join(HERE, "regulations")

_ALLOWED_TYPES = {
    "SPARQL_CQ",
    "SHACL_SHAPE",
    "PROV_O_CHAIN",
    "GOVERNANCE_SCORECARD_CRITERION",
    "OBSERVATION_RECORD",
}


def _regulations_dir() -> str:
    return os.environ.get("ONTOLOGY_REGULATIONS_DIR", REGULATIONS_DIR)


def list_regulations(*, regulations_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return a summary list of every regulation on disk.

    Does not perform a full validation — only the identity fields are
    returned so callers (UI, CLI) can populate pickers cheaply.
    """
    d = regulations_dir or _regulations_dir()
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(d):
        return out
    for path in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            with open(path) as f:
                reg = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "regulation_id":     reg.get("regulation_id"),
            "name":              reg.get("name"),
            "short_name":        reg.get("short_name"),
            "jurisdiction":      reg.get("jurisdiction"),
            "effective_date":    reg.get("effective_date"),
            "last_verified_date": reg.get("last_verified_date"),
            "requirement_count": len(reg.get("requirements", [])),
            "path":              path,
        })
    return out


def load_regulation(
    regulation_id: str,
    *,
    regulations_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Load and validate a regulation by ID.

    Raises ``ValueError`` if the regulation is missing or malformed.
    """
    d = regulations_dir or _regulations_dir()
    path = os.path.join(d, f"{regulation_id}.json")
    if not os.path.isfile(path):
        raise ValueError(f"regulation not found: {regulation_id}")
    with open(path) as f:
        reg = json.load(f)

    required_top = ("regulation_id", "name", "jurisdiction", "requirements")
    for key in required_top:
        if key not in reg:
            raise ValueError(f"{regulation_id}: missing '{key}'")
    if reg["regulation_id"] != regulation_id:
        raise ValueError(
            f"{regulation_id}: file id mismatch "
            f"(file says '{reg['regulation_id']}')"
        )

    for req in reg["requirements"]:
        for key in ("req_id", "title", "artefact_type", "evidence_selector"):
            if key not in req:
                raise ValueError(
                    f"{regulation_id}: requirement missing '{key}' "
                    f"({req.get('req_id', '(no-id)')})"
                )
        if req["artefact_type"] not in _ALLOWED_TYPES:
            raise ValueError(
                f"{regulation_id}: requirement {req['req_id']} has "
                f"unknown artefact_type '{req['artefact_type']}'. "
                f"Allowed: {sorted(_ALLOWED_TYPES)}"
            )

    return reg


def regulation_path(regulation_id: str,
                    *, regulations_dir: Optional[str] = None) -> str:
    d = regulations_dir or _regulations_dir()
    return os.path.join(d, f"{regulation_id}.json")


def write_regulation(reg: Dict[str, Any],
                     *, regulations_dir: Optional[str] = None) -> str:
    """Persist a custom regulation (extensibility point for enterprises
    that maintain in-house frameworks)."""
    d = regulations_dir or _regulations_dir()
    os.makedirs(d, exist_ok=True)
    if "regulation_id" not in reg:
        raise ValueError("regulation dict missing 'regulation_id'")
    path = os.path.join(d, f"{reg['regulation_id']}.json")
    with open(path, "w") as f:
        json.dump(reg, f, indent=2)
        f.write("\n")
    return path
