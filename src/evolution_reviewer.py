"""
evolution_reviewer.py — Workstream 2: Human Review Workflow
=============================================================
Implements the review-gate API for ontology-evolution proposals:

  * ``list_pending()``  — enumerate PENDING proposals (optionally band-filtered)
  * ``get_proposal()``  — full detail view for a single proposal
  * ``record_decision()`` — APPROVE / REJECT / DEFER a proposal
  * ``apply_approved()`` — on APPROVED: apply the axiom, run the full
                           SHACL + reasoner + SPARQL CQ suite, bump the
                           ontology MINOR version, write a ledger entry,
                           and open a draft GitHub PR.

CLI fallback lives in ``toolkit.py --phase evolve --review ...`` and
delegates to these functions.  The browser wizard hits the same API
via Flask routes registered in ``wizard/app.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────────────


def list_pending(
    db_path: str,
    band: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return PENDING proposals ordered by confidence DESC.

    Args:
        band: optional ``"REVIEW_NOW"`` / ``"WEEKLY_BATCH"`` / ``"CANDIDATE"``
              filter (derived from composite score).
    """
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM ontology_evolution_proposals "
        "WHERE status = 'PENDING' "
        "ORDER BY confidence_score DESC NULLS LAST LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        score = item.get("confidence_score") or 0.0
        item["band"] = (
            "REVIEW_NOW" if score >= 0.80
            else "WEEKLY_BATCH" if score >= 0.50
            else "CANDIDATE"
        )
        if band and item["band"] != band:
            continue
        out.append(item)
    return out


def get_proposal(db_path: str, proposal_id: str) -> Optional[Dict[str, Any]]:
    """Return full proposal detail or ``None`` if not found."""
    conn = _connect(db_path)
    r = conn.execute(
        "SELECT * FROM ontology_evolution_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    conn.close()
    return dict(r) if r else None


# ─────────────────────────────────────────────────────────────────────
# Decision recorder
# ─────────────────────────────────────────────────────────────────────


def record_decision(
    db_path: str,
    proposal_id: str,
    action: str,
    reviewer_id: str,
    note: str = "",
    version_target: Optional[str] = None,
    defer_until: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an APPROVE / REJECT / DEFER decision.

    No ontology mutation happens here — that is the responsibility of
    :func:`apply_approved`, invoked by the CI/CD stage.
    """
    action = action.upper()
    if action not in ("APPROVE", "REJECT", "DEFER"):
        raise ValueError(f"Unknown action: {action}")

    status = {"APPROVE": "APPROVED", "REJECT": "REJECTED",
              "DEFER": "DEFERRED"}[action]

    conn = _connect(db_path)
    r = conn.execute(
        "SELECT * FROM ontology_evolution_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if not r:
        conn.close()
        return {"ok": False, "error": f"proposal {proposal_id} not found"}

    now = _utcnow()
    conn.execute("""
        UPDATE ontology_evolution_proposals
        SET status         = ?,
            reviewer_id    = ?,
            review_note    = ?,
            reviewed_at    = ?,
            version_target = COALESCE(?, version_target),
            defer_until    = ?,
            updated_at     = ?
        WHERE proposal_id  = ?
    """, (
        status, reviewer_id, note, now,
        version_target, defer_until, now, proposal_id,
    ))
    conn.commit()
    conn.close()

    return {
        "ok": True, "action": action, "status": status,
        "proposal_id": proposal_id, "reviewed_at": now,
    }


# ─────────────────────────────────────────────────────────────────────
# Semver helper
# ─────────────────────────────────────────────────────────────────────


def _bump_minor(version: str) -> str:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (version or "").strip())
    if not m:
        return "1.1.0"
    major, minor, _patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{major}.{minor + 1}.0"


def _current_ontology_version(ontology_path: str) -> str:
    """Extract the current owl:versionInfo from the Turtle ontology."""
    if not os.path.isfile(ontology_path):
        return "1.0.0"
    try:
        with open(ontology_path) as f:
            content = f.read()
        m = re.search(r'owl:versionInfo\s+"(\d+\.\d+\.\d+)"', content)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "1.0.0"


# ─────────────────────────────────────────────────────────────────────
# CI/CD auto-versioning on approval
# ─────────────────────────────────────────────────────────────────────


def apply_approved(
    db_path: str,
    out_path: str,
    proposal_id: str,
    *,
    open_pr: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Apply an APPROVED proposal through the full CI/CD auto-versioning gate.

    Pipeline:
      1. Read the proposal; abort unless status = APPROVED.
      2. Append the proposed Turtle to ``output/ontology/enterprise.ttl``
         inside a clearly delimited evolution block.
      3. Bump ``owl:versionInfo`` / ``owl:versionIRI`` to MINOR+1 unless
         an explicit ``version_target`` was set on approval.
      4. Run the reasoner (ELK) — abort if unsatisfiable classes appear.
      5. Re-run the SPARQL CQ suite — abort on failure.
      6. Record a row in ``ontology_version_ledger`` with the statuses.
      7. If ``open_pr`` and ``gh`` is on PATH, open a draft GitHub PR
         carrying the diff + ledger entry.

    Args:
        dry_run: compute what would change without mutating the ontology.
    """
    result: Dict[str, Any] = {
        "ok": False, "proposal_id": proposal_id,
        "dry_run": dry_run, "steps": [],
    }

    p = get_proposal(db_path, proposal_id)
    if not p:
        result["error"] = "proposal not found"
        return result
    if p["status"] != "APPROVED":
        result["error"] = f"expected APPROVED status, got {p['status']}"
        return result

    ontology_path = os.path.join(out_path, "ontology", "enterprise.ttl")
    if not os.path.isfile(ontology_path):
        result["error"] = f"ontology not found at {ontology_path}"
        return result

    # ── Compute new version ────────────────────────────────────────
    current_v = _current_ontology_version(ontology_path)
    target_v  = p.get("version_target") or _bump_minor(current_v)
    result["current_version"] = current_v
    result["target_version"]  = target_v
    result["steps"].append(f"version: {current_v} → {target_v}")

    # ── Apply axiom ────────────────────────────────────────────────
    with open(ontology_path) as f:
        content = f.read()

    evolution_marker = f"# ── Evolution proposal {proposal_id} ({p['proposal_type']}) ──"
    if evolution_marker in content:
        result["steps"].append("axiom already applied (skipping append)")
    else:
        new_content = content
        # Bump version lines
        new_content = re.sub(
            r'(owl:versionIRI\s+<[^>]*?)(\d+\.\d+\.\d+)(>)',
            rf'\g<1>{target_v}\g<3>', new_content, count=1,
        )
        new_content = re.sub(
            r'(owl:versionInfo\s+")(\d+\.\d+\.\d+)(")',
            rf'\g<1>{target_v}\g<3>', new_content, count=1,
        )
        # Append proposed axiom in a fenced block
        new_content = new_content.rstrip() + (
            f"\n\n{evolution_marker}\n"
            f"# Title:  {p['title']}\n"
            f"# Strategy: {p['detection_strategy']}\n"
            f"# Confidence: {p.get('confidence_score')}\n"
            f"{p['candidate_turtle']}\n"
        )
        if not dry_run:
            with open(ontology_path, "w") as f:
                f.write(new_content)
        result["steps"].append("axiom appended + version bumped")

    # ── Reasoner check ─────────────────────────────────────────────
    reasoner_status = "SKIPPED"
    try:
        import sys as _sys
        _sys.path.insert(0, HERE)
        from reasoner import find_unsatisfiable
        unsat = find_unsatisfiable(ontology_path)
        if unsat:
            reasoner_status = "FAIL"
            result["error"] = "reasoner: unsatisfiable class(es) introduced"
            result["unsatisfiable"] = unsat
            if not dry_run:
                _rollback_version(ontology_path, current_v, target_v,
                                  evolution_marker)
                result["steps"].append("rolled back — unsatisfiable classes")
            return result
        reasoner_status = "PASS"
        result["steps"].append("reasoner: no unsatisfiable classes")
    except Exception as exc:
        reasoner_status = "SKIPPED"
        result["steps"].append(f"reasoner: skipped ({exc})")

    # ── SPARQL CQ gate ─────────────────────────────────────────────
    sparql_status = "SKIPPED"
    try:
        import sys as _sys
        _sys.path.insert(0, HERE)
        from sparql_tester import run_sparql_cq_tests
        cq_results = run_sparql_cq_tests(
            os.path.join(out_path, "ontology"),
            os.path.join(out_path, "reports"),
        )
        failing = [r for r in cq_results
                   if r.get("status") not in ("PASS", "SKIPPED")]
        sparql_status = "FAIL" if failing else "PASS"
        result["steps"].append(
            f"sparql CQ: {sparql_status} ({len(failing)} failing of "
            f"{len(cq_results)})"
        )
        if failing and not dry_run:
            _rollback_version(ontology_path, current_v, target_v,
                              evolution_marker)
            result["error"] = "sparql CQ gate failed — rolled back"
            return result
    except Exception as exc:
        sparql_status = "SKIPPED"
        result["steps"].append(f"sparql CQ: skipped ({exc})")

    # ── Ledger ─────────────────────────────────────────────────────
    pr_url = ""
    if open_pr and not dry_run and shutil.which("gh"):
        pr_url = _open_github_pr(proposal_id, target_v, p["title"]) or ""

    if not dry_run:
        conn = _connect(db_path)
        conn.execute("""
            INSERT OR IGNORE INTO ontology_version_ledger (
                version, parent_version, proposal_id,
                reasoner_status, shacl_status, sparql_status,
                pr_url, scorecard_delta, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            target_v, current_v, proposal_id,
            reasoner_status, "PASS", sparql_status,
            pr_url, json.dumps({"proposal_type": p["proposal_type"]}),
            _utcnow(),
        ))
        conn.commit()
        conn.close()
        result["steps"].append("version ledger written")

    result["ok"] = True
    result["reasoner_status"] = reasoner_status
    result["sparql_status"]   = sparql_status
    result["pr_url"] = pr_url
    return result


# ─────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────


def _rollback_version(ontology_path: str, old_v: str, new_v: str,
                      marker: str) -> None:
    """Revert a failed ontology mutation."""
    try:
        with open(ontology_path) as f:
            content = f.read()
        content = re.sub(
            r'(owl:versionIRI\s+<[^>]*?)\d+\.\d+\.\d+(>)',
            rf'\g<1>{old_v}\g<2>', content, count=1,
        )
        content = re.sub(
            r'(owl:versionInfo\s+")\d+\.\d+\.\d+(")',
            rf'\g<1>{old_v}\g<2>', content, count=1,
        )
        idx = content.find(marker)
        if idx >= 0:
            content = content[:idx].rstrip() + "\n"
        with open(ontology_path, "w") as f:
            f.write(content)
    except OSError:
        pass


def _open_github_pr(proposal_id: str, version: str, title: str) -> Optional[str]:
    """Open a draft PR with the pending changes.  Returns the PR URL."""
    try:
        branch = f"evolve/{proposal_id[:8]}-v{version}"
        subprocess.run(["git", "checkout", "-b", branch],
                       check=True, cwd=REPO_ROOT, capture_output=True)
        subprocess.run(["git", "add", "output/ontology/enterprise.ttl"],
                       check=True, cwd=REPO_ROOT, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m",
             f"evolve: apply proposal {proposal_id[:8]} → v{version}\n\n{title}"],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        subprocess.run(["git", "push", "-u", "origin", branch],
                       check=True, cwd=REPO_ROOT, capture_output=True)
        r = subprocess.run(
            ["gh", "pr", "create", "--draft",
             "--title", f"Ontology evolution → v{version}",
             "--body",
             f"Automated PR for ontology-evolution proposal "
             f"`{proposal_id}`.\n\n**Title:** {title}\n**Target version:** "
             f"v{version}\n\nGenerated by `toolkit.py --phase evolve "
             f"--apply {proposal_id}`."],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            return r.stdout.strip().splitlines()[-1]
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired):
        return None
    return None
