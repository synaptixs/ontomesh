"""
compliance.assembler — Workstream 4, Component 2
=================================================
Evidence assembler.  Given a regulation ID, a decision IRI, and an
optional time range, assembles evidence for every requirement in the
regulation.

For each requirement, the assembler resolves ``artefact_type``:

  * ``SPARQL_CQ``                — reads output/reports/sparql_cq_test_results.csv
  * ``SHACL_SHAPE``              — checks for the named shape in
                                    output/shapes/*.ttl
  * ``PROV_O_CHAIN``             — walks observations table by source_ref
  * ``GOVERNANCE_SCORECARD_CRITERION`` — reads governance_scorecard.csv
  * ``OBSERVATION_RECORD``       — fetches the observation by IRI

The return is a list of evidence items, one per regulatory requirement,
with ``status``, ``source_query``, ``result`` and a short ``note``.

Evidence items are shaped so the bundle exporter can serialise them
straight into the signed JSON-LD envelope.
"""

from __future__ import annotations

import csv
import glob
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import registry

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


STATUS_SATISFIED     = "SATISFIED"
STATUS_INSUFFICIENT  = "INSUFFICIENT"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_MISSING       = "MISSING"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────
# Evidence resolvers — one per artefact_type
# ─────────────────────────────────────────────────────────────────────


def _eval_pass_expression(expr: Optional[str], ctx: Dict[str, Any]) -> bool:
    """Evaluate a tiny subset of Python expressions against ``ctx``.

    Supported forms:
      * ``"exists"``
      * ``"<field> in (<literal>, <literal>, ...)"``
      * ``"<field> >= <int>"`` / ``<=`` / ``==``
      * ``"chain_depth >= <int>"``

    Anything else returns ``False`` — callers should then set the
    evidence status to ``INSUFFICIENT`` rather than ``SATISFIED``.
    """
    if not expr:
        return False
    expr = expr.strip()
    if expr == "exists":
        return bool(ctx.get("exists"))

    m = re.match(r"^(\w+)\s+in\s+\((.+)\)$", expr)
    if m:
        field, vals = m.group(1), m.group(2)
        lits = [v.strip().strip("'").strip('"') for v in vals.split(",")]
        return str(ctx.get(field, "")) in lits

    m = re.match(r"^(\w+)\s*(>=|<=|==|>|<)\s*([0-9]+(?:\.[0-9]+)?)$", expr)
    if m:
        field, op, val = m.group(1), m.group(2), float(m.group(3))
        v = ctx.get(field)
        if v is None:
            return False
        try:
            vf = float(v)
        except (TypeError, ValueError):
            return False
        return (
            (op == ">=" and vf >= val)
            or (op == "<=" and vf <= val)
            or (op == "==" and vf == val)
            or (op == ">"  and vf >  val)
            or (op == "<"  and vf <  val)
        )

    return False


def _resolve_sparql_cq(req: Dict[str, Any], out_path: str) -> Dict[str, Any]:
    """Evidence from output/reports/sparql_cq_test_results.csv."""
    selector = req["evidence_selector"]
    csv_path = os.path.join(out_path, "reports", "sparql_cq_test_results.csv")
    source_query = ""
    sparql_file = os.path.join(REPO_ROOT, "tests", "sparql")
    hits = glob.glob(os.path.join(sparql_file, f"{selector}-*.sparql"))
    if hits:
        try:
            with open(hits[0]) as f:
                source_query = f.read()
        except OSError:
            pass

    if not os.path.isfile(csv_path):
        return {
            "status": STATUS_MISSING,
            "note":   f"SPARQL CQ results missing: {csv_path}",
            "source_query":  source_query,
            "source_file":   os.path.basename(hits[0]) if hits else "",
            "result": {},
        }

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    match = next((r for r in rows if r.get("cq_id") == selector), None)
    if not match:
        return {
            "status": STATUS_MISSING,
            "note":   f"SPARQL CQ '{selector}' not in results CSV.",
            "source_query":  source_query,
            "source_file":   os.path.basename(hits[0]) if hits else "",
            "result": {},
        }

    ok = _eval_pass_expression(req.get("pass_expression"), {
        "status":    match.get("status", ""),
        "row_count": int(match.get("row_count", "0") or 0),
    })
    return {
        "status": STATUS_SATISFIED if ok else STATUS_INSUFFICIENT,
        "note":   f"{selector} status={match.get('status')}  "
                  f"rows={match.get('row_count')}",
        "source_query":  source_query,
        "source_file":   os.path.basename(hits[0]) if hits else "",
        "result": match,
    }


def _resolve_shacl_shape(req: Dict[str, Any], out_path: str) -> Dict[str, Any]:
    """Evidence: named shape exists in any Turtle under output/shapes/."""
    selector = req["evidence_selector"]
    shapes_dir = os.path.join(out_path, "shapes")
    hits: List[str] = []
    if os.path.isdir(shapes_dir):
        for ttl in sorted(glob.glob(os.path.join(shapes_dir, "*.ttl"))):
            try:
                with open(ttl) as f:
                    text = f.read()
            except OSError:
                continue
            if selector in text:
                hits.append(os.path.basename(ttl))

    exists = bool(hits)
    ok = _eval_pass_expression(req.get("pass_expression"), {"exists": exists})
    return {
        "status": STATUS_SATISFIED if ok else STATUS_INSUFFICIENT,
        "note":   f"Shape '{selector}' found in {hits}" if exists
                  else f"Shape '{selector}' not found in output/shapes/",
        "source_query":  f"grep -l '{selector}' output/shapes/*.ttl",
        "source_file":   ",".join(hits),
        "result": {"exists": exists, "files": hits},
    }


def _walk_prov_chain(
    conn: sqlite3.Connection,
    decision_iri: Optional[str],
    max_hops: int = 4,
) -> List[Dict[str, Any]]:
    """Walk the observations table by source_ref to produce a PROV-O chain.

    The chain starts at the decision observation and follows
    ``source_ref`` links (treating them as IRIs that may themselves be
    observation_iri values).  Anonymous / external sources terminate
    the walk.
    """
    if not decision_iri:
        return []
    chain: List[Dict[str, Any]] = []
    seen = {decision_iri}
    cursor = decision_iri
    for _ in range(max_hops):
        row = conn.execute(
            "SELECT o.observation_iri, o.observation_type, "
            "       o.confidence_score, o.derivation_method, "
            "       o.source_ref, o.observed_at, ag.agent_iri, ag.name AS agent_name "
            "FROM observations o "
            "LEFT JOIN agents ag ON ag.id = o.recorded_by "
            "WHERE o.observation_iri = ? LIMIT 1",
            (cursor,),
        ).fetchone()
        if not row:
            break
        node = dict(row)
        chain.append(node)
        next_iri = node.get("source_ref")
        if not next_iri or next_iri in seen:
            break
        seen.add(next_iri)
        cursor = next_iri
    return chain


def _resolve_prov_chain(
    req: Dict[str, Any],
    db_path: str,
    decision_iri: Optional[str],
) -> Dict[str, Any]:
    if not decision_iri:
        return {
            "status": STATUS_NOT_APPLICABLE,
            "note":   "No decision IRI supplied — PROV-O chain skipped.",
            "source_query":  "decision_iri is None",
            "source_file":   "observations table",
            "result": {"chain_depth": 0, "chain": []},
        }
    if not os.path.isfile(db_path):
        return {
            "status": STATUS_MISSING,
            "note":   f"DB not found: {db_path}",
            "source_query":  "",
            "source_file":   "",
            "result": {"chain_depth": 0, "chain": []},
        }
    conn = _open_db(db_path)
    chain = _walk_prov_chain(conn, decision_iri)
    conn.close()
    ok = _eval_pass_expression(req.get("pass_expression"),
                               {"chain_depth": len(chain)})
    return {
        "status": STATUS_SATISFIED if ok else STATUS_INSUFFICIENT,
        "note":   f"PROV-O chain depth={len(chain)} for {decision_iri}",
        "source_query":
            "SELECT observation_iri, source_ref FROM observations "
            f"WHERE observation_iri = '{decision_iri}'",
        "source_file":   "observations + agents",
        "result": {"chain_depth": len(chain), "chain": chain,
                   "decision_iri": decision_iri},
    }


def _resolve_scorecard_criterion(
    req: Dict[str, Any],
    out_path: str,
) -> Dict[str, Any]:
    selector = req["evidence_selector"]
    csv_path = os.path.join(out_path, "reports", "governance_scorecard.csv")
    if not os.path.isfile(csv_path):
        return {
            "status": STATUS_MISSING,
            "note":   f"Governance scorecard missing: {csv_path}",
            "source_query":  "",
            "source_file":   os.path.basename(csv_path),
            "result": {},
        }
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    match = next((r for r in rows if r.get("criterion") == selector), None)
    if not match:
        return {
            "status": STATUS_MISSING,
            "note":   f"Scorecard criterion '{selector}' not found.",
            "source_query":  "",
            "source_file":   os.path.basename(csv_path),
            "result": {},
        }
    try:
        score = int(match.get("score", "0") or 0)
    except ValueError:
        score = 0
    ok = _eval_pass_expression(req.get("pass_expression"), {"score": score})
    return {
        "status": STATUS_SATISFIED if ok else STATUS_INSUFFICIENT,
        "note":   f"{selector} score={score} ({match.get('maturity')})",
        "source_query":  "",
        "source_file":   os.path.basename(csv_path),
        "result": match,
    }


def _resolve_observation_record(
    req: Dict[str, Any],
    db_path: str,
    decision_iri: Optional[str],
) -> Dict[str, Any]:
    iri = req.get("evidence_selector") or decision_iri
    if not iri:
        return {
            "status": STATUS_NOT_APPLICABLE,
            "note":   "No observation IRI supplied.",
            "source_query":  "",
            "source_file":   "",
            "result": {},
        }
    conn = _open_db(db_path)
    row = conn.execute(
        "SELECT observation_iri, observation_type, confidence_score, "
        "       derivation_method, observed_at, source_ref "
        "FROM observations WHERE observation_iri = ?",
        (iri,),
    ).fetchone()
    conn.close()
    if not row:
        return {
            "status": STATUS_MISSING,
            "note":   f"Observation not found: {iri}",
            "source_query":  f"observation_iri = '{iri}'",
            "source_file":   "observations",
            "result": {},
        }
    return {
        "status": STATUS_SATISFIED,
        "note":   f"Observation found: {iri}",
        "source_query":  f"observation_iri = '{iri}'",
        "source_file":   "observations",
        "result": dict(row),
    }


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def assemble_evidence(
    *,
    regulation_id: str,
    decision_iri: Optional[str] = None,
    db_path: Optional[str] = None,
    out_path: Optional[str] = None,
    time_range: Optional[Tuple[str, str]] = None,
    regulations_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble an evidence package for ``regulation_id``.

    Returns a dict with:
      * ``regulation_id``, ``name``, ``jurisdiction``
      * ``decision_iri``, ``time_range``, ``assembled_at``
      * ``evidence``: list of items (one per requirement)
      * ``summary``:  counts by status + overall coverage ratio
    """
    reg = registry.load_regulation(regulation_id, regulations_dir=regulations_dir)
    db  = db_path or os.path.join(REPO_ROOT, "db", "enterprise.db")
    out = out_path or os.path.join(REPO_ROOT, "output")

    evidence: List[Dict[str, Any]] = []
    for req in reg["requirements"]:
        artefact = req["artefact_type"]
        if   artefact == "SPARQL_CQ":
            ev = _resolve_sparql_cq(req, out)
        elif artefact == "SHACL_SHAPE":
            ev = _resolve_shacl_shape(req, out)
        elif artefact == "PROV_O_CHAIN":
            ev = _resolve_prov_chain(req, db, decision_iri)
        elif artefact == "GOVERNANCE_SCORECARD_CRITERION":
            ev = _resolve_scorecard_criterion(req, out)
        elif artefact == "OBSERVATION_RECORD":
            ev = _resolve_observation_record(req, db, decision_iri)
        else:  # pragma: no cover — registry rejects unknown types
            ev = {
                "status": STATUS_MISSING,
                "note":   f"Unknown artefact_type: {artefact}",
                "source_query":  "",
                "source_file":   "",
                "result": {},
            }
        evidence.append({
            "req_id":         req["req_id"],
            "title":          req["title"],
            "description":    req.get("description", ""),
            "artefact_type":  artefact,
            "evidence_selector": req["evidence_selector"],
            "status":         ev["status"],
            "note":           ev.get("note", ""),
            "source_query":   ev.get("source_query", ""),
            "source_file":    ev.get("source_file", ""),
            "result":         ev.get("result", {}),
        })

    counts: Dict[str, int] = {}
    for ev in evidence:
        counts[ev["status"]] = counts.get(ev["status"], 0) + 1
    total = len(evidence)
    satisfied = counts.get(STATUS_SATISFIED, 0)
    coverage = round((satisfied / max(total, 1)) * 100)

    return {
        "regulation_id":     reg["regulation_id"],
        "name":              reg.get("name"),
        "short_name":        reg.get("short_name"),
        "jurisdiction":      reg.get("jurisdiction"),
        "effective_date":    reg.get("effective_date"),
        "last_verified_date": reg.get("last_verified_date"),
        "decision_iri":      decision_iri,
        "time_range":        list(time_range) if time_range else None,
        "assembled_at":      _utcnow(),
        "evidence":          evidence,
        "summary": {
            "total_requirements": total,
            "counts":             counts,
            "coverage_percent":   coverage,
            "satisfied":          satisfied,
        },
    }
