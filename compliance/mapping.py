"""
compliance.mapping — Workstream 4, Component 4
================================================
Bidirectional regulation ↔ toolkit-artefact index.

Two lookup directions:

  * ``by_artefact(selector) -> list[regulations]``
  * ``by_regulation(reg_id) -> list[artefacts]``

Powers the gap analysis:

  * ``gap_analysis()`` — which requirements have no toolkit coverage?
                        — which toolkit criteria satisfy no regulation?

And the governance scorecard dimension:

  * ``coverage_score()`` — % of loaded regulations whose requirements
                           are all SATISFIED against the current run.
"""

from __future__ import annotations

import csv
import glob
import os
from typing import Any, Dict, List, Optional

from . import registry, assembler

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


def build_mapping_index(
    *,
    regulations_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce the two-direction index over every loaded regulation."""
    by_artefact: Dict[str, List[Dict[str, str]]] = {}
    by_regulation: Dict[str, List[Dict[str, str]]] = {}
    summary = []

    for item in registry.list_regulations(regulations_dir=regulations_dir):
        reg_id = item["regulation_id"]
        try:
            reg = registry.load_regulation(reg_id,
                                           regulations_dir=regulations_dir)
        except ValueError:
            continue
        by_regulation[reg_id] = []
        for req in reg["requirements"]:
            entry = {
                "req_id":        req["req_id"],
                "title":         req["title"],
                "artefact_type": req["artefact_type"],
                "selector":      req["evidence_selector"],
            }
            by_regulation[reg_id].append(entry)
            key = f"{req['artefact_type']}:{req['evidence_selector']}"
            by_artefact.setdefault(key, []).append({
                "regulation_id": reg_id,
                "req_id":        req["req_id"],
                "title":         req["title"],
            })
        summary.append({
            "regulation_id":     reg_id,
            "name":              reg.get("name"),
            "requirement_count": len(reg["requirements"]),
        })

    return {
        "regulations":    summary,
        "by_regulation":  by_regulation,
        "by_artefact":    by_artefact,
    }


def _collect_available_artefacts(
    out_path: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Return which artefact instances the toolkit produced in this run.

    Used by ``gap_analysis`` to find orphan toolkit criteria (present in
    the codebase but unused by any loaded regulation).
    """
    out = out_path or os.path.join(REPO_ROOT, "output")
    avail: Dict[str, List[str]] = {
        "SPARQL_CQ":                     [],
        "SHACL_SHAPE":                   [],
        "GOVERNANCE_SCORECARD_CRITERION": [],
    }
    # SPARQL CQs
    csv_path = os.path.join(out, "reports", "sparql_cq_test_results.csv")
    if os.path.isfile(csv_path):
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                cq = row.get("cq_id")
                if cq:
                    avail["SPARQL_CQ"].append(cq)
    # Governance scorecard
    gov_path = os.path.join(out, "reports", "governance_scorecard.csv")
    if os.path.isfile(gov_path):
        with open(gov_path) as f:
            for row in csv.DictReader(f):
                crit = row.get("criterion")
                if crit:
                    avail["GOVERNANCE_SCORECARD_CRITERION"].append(crit)
    # Shapes: scan every Turtle under output/shapes and capture any
    # subject that is declared as sh:NodeShape.  Works for both
    # "shapes:FooShape a sh:NodeShape" and ":ObservationAcceptanceGate a sh:NodeShape".
    import re as _re
    shape_re = _re.compile(
        r"(?m)^\s*([a-zA-Z_][\w:\-]*)\s+a\s+sh:NodeShape"
    )
    shapes_dir = os.path.join(out, "shapes")
    if os.path.isdir(shapes_dir):
        for ttl in sorted(glob.glob(os.path.join(shapes_dir, "*.ttl"))):
            try:
                with open(ttl) as f:
                    text = f.read()
            except OSError:
                continue
            for sym in shape_re.findall(text):
                # Strip any prefix like 'shapes:' / ':'
                bare = sym.split(":")[-1]
                if bare:
                    avail["SHACL_SHAPE"].append(bare)
    # Dedup
    for k in list(avail.keys()):
        avail[k] = sorted(set(avail[k]))
    return avail


def gap_analysis(
    *,
    regulations_dir: Optional[str] = None,
    out_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce the two-sided gap report:

      * ``uncovered_requirements``:
          regulatory requirements whose evidence artefact does not exist
          in this toolkit run.
      * ``orphan_artefacts``:
          toolkit criteria / CQs / shapes that no regulation references.
      * ``recommendations``:
          terse suggestions the UI can surface directly.
    """
    index = build_mapping_index(regulations_dir=regulations_dir)
    avail = _collect_available_artefacts(out_path=out_path)

    uncovered: List[Dict[str, Any]] = []
    for reg_id, reqs in index["by_regulation"].items():
        for r in reqs:
            art = r["artefact_type"]
            sel = r["selector"]
            # For PROV_O_CHAIN / OBSERVATION_RECORD evidence lives at
            # run-time per decision — not a static gap.
            if art in ("PROV_O_CHAIN", "OBSERVATION_RECORD"):
                continue
            if art not in avail or sel not in avail[art]:
                uncovered.append({
                    "regulation_id": reg_id,
                    "req_id":        r["req_id"],
                    "title":         r["title"],
                    "artefact_type": art,
                    "selector":      sel,
                })

    orphans: List[Dict[str, str]] = []
    used = set(index["by_artefact"].keys())
    for art, selectors in avail.items():
        for sel in selectors:
            if f"{art}:{sel}" not in used:
                orphans.append({"artefact_type": art, "selector": sel})

    recs: List[str] = []
    if uncovered:
        recs.append(
            f"{len(uncovered)} regulatory requirement(s) lack toolkit "
            "coverage — add the missing CQ/shape or map an existing one."
        )
    if orphans:
        recs.append(
            f"{len(orphans)} toolkit artefact(s) satisfy no regulation — "
            "document coverage or retire if redundant."
        )
    if not recs:
        recs.append("No gaps detected — all requirements covered.")

    return {
        "uncovered_requirements": uncovered,
        "orphan_artefacts":       orphans,
        "recommendations":        recs,
    }


def coverage_score(
    *,
    regulations_dir: Optional[str] = None,
    out_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate coverage over every loaded regulation.

    For each regulation, invoke :func:`compliance.assembler.assemble_evidence`
    (without a decision IRI — PROV-O requirements become NOT_APPLICABLE
    and are excluded from the ratio) and compute per-regulation coverage
    and the overall percentage of regulations at ≥80% coverage.
    """
    out = out_path or os.path.join(REPO_ROOT, "output")
    db  = db_path  or os.path.join(REPO_ROOT, "db", "enterprise.db")
    per_reg: List[Dict[str, Any]] = []
    all_ids = [r["regulation_id"] for r in
               registry.list_regulations(regulations_dir=regulations_dir)]
    full_cov = 0
    for reg_id in all_ids:
        try:
            ev = assembler.assemble_evidence(
                regulation_id=reg_id,
                decision_iri=None,
                db_path=db,
                out_path=out,
                regulations_dir=regulations_dir,
            )
        except ValueError:
            continue
        applicable = [e for e in ev["evidence"]
                      if e["status"] != assembler.STATUS_NOT_APPLICABLE]
        satisfied = [e for e in applicable
                     if e["status"] == assembler.STATUS_SATISFIED]
        pct = round((len(satisfied) / max(len(applicable), 1)) * 100)
        if pct >= 80:
            full_cov += 1
        per_reg.append({
            "regulation_id":   reg_id,
            "name":            ev.get("name"),
            "coverage":        pct,
            "applicable":      len(applicable),
            "satisfied":       len(satisfied),
        })

    total = len(per_reg) or 1
    return {
        "regulations":       per_reg,
        "total_regulations": len(per_reg),
        "regulations_at_80": full_cov,
        "coverage_percent":  round((full_cov / total) * 100),
    }
