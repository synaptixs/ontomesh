"""
reasoner.py — Phase 1 / S3
────────────────────────────
ROBOT framework integration for OWL 2 reasoning over generated ontologies.

Responsibilities:
  1. run_reasoner()         — classify ontology with ELK (EL) or HermiT (DL)
  2. snapshot_hierarchy()   — save class hierarchy to a text manifest
  3. diff_hierarchy()       — compare manifests, fail on unexpected changes
  4. find_unsatisfiable()   — report unsatisfiable classes as CRITICAL findings

ROBOT is expected to be available as a CLI binary. Two discovery paths:
  - bin/robot  (bundled, zero-install)
  - robot      (on PATH — system install)

If ROBOT is unavailable the module degrades gracefully: all functions
return a result dict with status='SKIPPED' and a human-readable message.
"""

import os
import re
import subprocess
import shutil
from typing import List, Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
_BIN_ROBOT = os.path.join(REPO_ROOT, "bin", "robot")


def _robot_cmd() -> Optional[str]:
    """Return the path to a working ROBOT binary, or None if unavailable."""
    candidates = [_BIN_ROBOT, shutil.which("robot")]
    for path in candidates:
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        try:
            r = subprocess.run(
                [path, "--version"], capture_output=True, timeout=15
            )
            if r.returncode == 0:
                return path
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _run(cmd: List[str], cwd: str = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=300
    )


# ── Public API ───────────────────────────────────────────────────────────

def run_reasoner(ontology_path: str, output_path: str,
                 profile: str = "OWL 2 EL") -> Dict:
    """Classify the ontology with ROBOT.

    Args:
        ontology_path: Path to enterprise.ttl (or merged ontology)
        output_path:   Path for the classified output Turtle file
        profile:       'OWL 2 EL' → ELK reasoner, 'OWL 2 DL' → HermiT

    Returns a dict with keys: status, reasoner, output_path, message, findings
    """
    robot = _robot_cmd()
    if not robot:
        return {
            "status": "SKIPPED",
            "reasoner": None,
            "output_path": None,
            "message": (
                "ROBOT binary not found. Install from https://robot.obolibrary.org/ "
                "or place a robot binary in bin/robot."
            ),
            "findings": [],
        }

    reasoner = "ELK" if "EL" in profile.upper() else "HermiT"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        robot, "reason",
        "--reasoner", reasoner.lower(),
        "--input", ontology_path,
        "--output", output_path,
    ]
    try:
        result = _run(cmd)
    except (FileNotFoundError, OSError) as exc:
        return {
            "status": "SKIPPED",
            "reasoner": reasoner,
            "output_path": None,
            "message": (
                f"ROBOT binary could not be executed ({exc}). "
                "The wrapper script may have a bad shebang or Java is not installed. "
                "Structural checks will be used instead."
            ),
            "findings": [],
        }

    findings = []
    if result.returncode != 0:
        # Parse ROBOT stderr for unsatisfiable class messages
        for line in (result.stderr + result.stdout).splitlines():
            if "unsatisfiable" in line.lower() or "inconsistent" in line.lower():
                findings.append({
                    "severity": "CRITICAL",
                    "type": "UNSATISFIABLE_CLASS",
                    "description": line.strip(),
                    "remediation": "Review axiom constraints — a class has no possible instances.",
                })

    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "reasoner": reasoner,
        "output_path": output_path if result.returncode == 0 else None,
        "message": result.stderr.strip() or result.stdout.strip() or "OK",
        "findings": findings,
    }


def snapshot_hierarchy(classified_path: str, snapshot_path: str) -> Dict:
    """Extract and save the class hierarchy from a classified ontology.

    Uses ROBOT's export command to produce a tab-delimited class tree.
    Falls back to a simple grep-based extraction if ROBOT is unavailable.

    Returns dict with: status, snapshot_path, class_count, message
    """
    robot = _robot_cmd()
    os.makedirs(os.path.dirname(snapshot_path) or ".", exist_ok=True)

    if robot and os.path.isfile(classified_path):
        cmd = [
            robot, "export",
            "--input", classified_path,
            "--header", "ID|LABEL|SubClass Of",
            "--export", snapshot_path,
        ]
        result = _run(cmd)
        if result.returncode == 0:
            try:
                with open(snapshot_path) as f:
                    lines = f.readlines()
                class_count = max(0, len(lines) - 1)
            except OSError:
                class_count = 0
            return {
                "status": "PASS",
                "snapshot_path": snapshot_path,
                "class_count": class_count,
                "message": "Hierarchy snapshot written via ROBOT export.",
            }

    # Fallback: grep rdfs:subClassOf lines from the source Turtle
    source = classified_path if os.path.isfile(classified_path) else None
    if not source:
        return {
            "status": "SKIPPED",
            "snapshot_path": None,
            "class_count": 0,
            "message": "Source ontology not found — snapshot skipped.",
        }

    subclass_lines = []
    with open(source) as f:
        for line in f:
            if "rdfs:subClassOf" in line or "owl:Class" in line:
                subclass_lines.append(line.rstrip())

    with open(snapshot_path, "w") as f:
        f.write("\n".join(subclass_lines))

    return {
        "status": "PASS",
        "snapshot_path": snapshot_path,
        "class_count": sum(1 for l in subclass_lines if "owl:Class" in l),
        "message": "Hierarchy snapshot written via grep fallback (ROBOT unavailable).",
    }


def diff_hierarchy(old_snapshot: str, new_snapshot: str) -> Dict:
    """Compare two hierarchy snapshots and return any differences.

    Returns dict with: status, added, removed, changed, message
    A non-empty 'removed' list should fail the build (classes were dropped).
    An unexpected 'changed' list should trigger a review gate.
    """
    def _load(path: str) -> set:
        if not os.path.isfile(path):
            return set()
        with open(path) as f:
            return set(line.strip() for line in f if line.strip())

    old_lines = _load(old_snapshot)
    new_lines = _load(new_snapshot)

    added   = sorted(new_lines - old_lines)
    removed = sorted(old_lines - new_lines)

    if not old_lines:
        return {
            "status": "BASELINE",
            "added": added,
            "removed": [],
            "message": "No prior snapshot — this run establishes the baseline.",
        }

    status = "FAIL" if removed else ("WARN" if added else "PASS")
    return {
        "status": status,
        "added": added,
        "removed": removed,
        "message": (
            f"{len(added)} class(es) added, {len(removed)} class(es) removed. "
            + ("Build fails — classes were removed from the hierarchy." if removed else "")
        ),
    }


def find_unsatisfiable(ontology_path: str) -> List[Dict]:
    """Run the reasoner and collect unsatisfiable class findings.

    Returns a list of CRITICAL finding dicts (empty = clean).
    """
    robot = _robot_cmd()
    if not robot:
        return []

    reasoner = "elk"
    cmd = [
        robot, "reason",
        "--reasoner", reasoner,
        "--input", ontology_path,
        "--output", "/dev/null",
    ]
    result = _run(cmd)
    findings = []
    for line in (result.stderr + result.stdout).splitlines():
        if "unsatisfiable" in line.lower():
            # Try to extract the class name from the message
            match = re.search(r"<[^>]+>|:\w+", line)
            class_ref = match.group(0) if match else "unknown class"
            findings.append({
                "severity": "CRITICAL",
                "type": "UNSATISFIABLE_CLASS",
                "class": class_ref,
                "description": line.strip(),
                "remediation": (
                    "Review the constraints on this class — it has no possible instances. "
                    "Check for conflicting domain/range restrictions or disjointness axioms."
                ),
            })
    return findings


def run_and_report(ontology_path: str, output_dir: str,
                   profile: str = "OWL 2 EL") -> Dict:
    """Convenience wrapper: reason → snapshot → diff → report.

    Returns a combined result dict for use in toolkit.py and CI/CD.
    """
    classified_path = os.path.join(output_dir, "enterprise-classified.ttl")
    snapshot_new    = os.path.join(output_dir, "hierarchy-snapshot.tsv")
    snapshot_old    = os.path.join(output_dir, "hierarchy-snapshot-prev.tsv")

    # Roll previous snapshot if it exists
    if os.path.isfile(snapshot_new):
        import shutil as _shutil
        _shutil.copy2(snapshot_new, snapshot_old)

    reason_result    = run_reasoner(ontology_path, classified_path, profile)
    snapshot_result  = snapshot_hierarchy(classified_path, snapshot_new)
    diff_result      = diff_hierarchy(snapshot_old, snapshot_new)
    unsatisfiable    = find_unsatisfiable(ontology_path)

    overall_status = "PASS"
    if reason_result["status"] == "FAIL":
        overall_status = "FAIL"
    elif diff_result.get("status") == "FAIL":
        overall_status = "FAIL"
    elif unsatisfiable:
        overall_status = "FAIL"
    elif reason_result["status"] == "SKIPPED":
        overall_status = "SKIPPED"

    print(f"  {'✓' if overall_status == 'PASS' else ('~' if overall_status == 'SKIPPED' else '✗')} "
          f"Reasoner [{reason_result.get('reasoner', 'n/a')}]: {reason_result['status']}")
    if reason_result["status"] == "SKIPPED":
        print(f"    {reason_result['message']}")
    if unsatisfiable:
        for f in unsatisfiable:
            print(f"    CRITICAL: Unsatisfiable class: {f['class']}")
    if diff_result.get("removed"):
        for cls in diff_result["removed"]:
            print(f"    CRITICAL: Class removed from hierarchy: {cls}")
    if diff_result.get("added"):
        print(f"    INFO: {len(diff_result['added'])} new class(es) in hierarchy")

    return {
        "overall_status": overall_status,
        "reasoner":        reason_result,
        "snapshot":        snapshot_result,
        "hierarchy_diff":  diff_result,
        "unsatisfiable":   unsatisfiable,
    }
