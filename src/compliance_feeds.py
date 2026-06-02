"""
src/compliance_feeds.py — T3.4
──────────────────────────────
Continuous compliance — track regulatory feeds, diff between
versions, surface the ontology axioms a change invalidates.

Why this exists
───────────────
Compliance evidence bundles in v3.2 (S4 territory) are *static
snapshots*. A regulation change six months from now invalidates
the snapshot silently — no signal reaches the team that wrote
the ontology against the old text.

T3.4 makes the compliance contract continuous:

  1. **Registry.** A versioned record of every regulation clause
     and the ontology axioms it constrains. JSON-shaped so a
     real production deployment can swap the file path for an
     HTTP feed (Thomson Reuters, the Federal Register, internal
     legal team's policy DB, …) without changing this module.
  2. **Diff.** Two registry versions → ``RegulationDiff`` with
     added / removed / changed clauses. Text hashing detects the
     "changed" set without semantic understanding.
  3. **Re-validation hook.** For every changed clause, the linked
     ontology axioms surface as ``RevalidationFinding`` entries.
     The wizard runs SHACL / reasoner against just those axioms;
     the build either continues or fails with a regulation-
     change error message.

Privacy / safety contract
─────────────────────────
- We *never* fetch from a live feed inside this module — the
  caller injects a snapshot. Tests + offline mode get the same
  code path that production uses with a real fetcher.
- Axiom IRIs are stored verbatim; no PII risk at this layer.

Public API
──────────
    reg     = RegulationRegistry.load(path)
    diff    = RegulationDiff.between(reg_old, reg_new)
    findings = revalidate(diff, ontology_path)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


# ── Schema for a regulation entry ───────────────────────────────────────


@dataclass
class RegulationClause:
    """One §clause from a regulation. ``text_hash`` is computed
    automatically from ``text`` when None — gives us cheap change
    detection without storing the body twice."""
    id:                 str            # "HIPAA-164.312(a)(1)"
    title:              str            # "Access Control"
    text:               str
    ontology_axioms:    List[str] = field(default_factory=list)
    text_hash:          Optional[str] = None
    family:             str = ""       # "HIPAA" / "GDPR" / "SOX" / ...

    def __post_init__(self) -> None:
        if not self.text_hash:
            self.text_hash = _hash16(self.text)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id":              self.id,
            "title":           self.title,
            "text":            self.text,
            "ontology_axioms": list(self.ontology_axioms),
            "text_hash":       self.text_hash,
            "family":          self.family,
        }


@dataclass
class RegulationRegistry:
    """A registry version. ``version`` is a free-text label (we
    don't enforce semver — regulatory feeds use their own
    versioning conventions)."""
    version:  str
    clauses:  Dict[str, RegulationClause] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "RegulationRegistry":
        version = str(raw.get("version") or "")
        clauses = {}
        for entry in raw.get("regulations") or []:
            c = RegulationClause(
                id=str(entry.get("id") or ""),
                title=str(entry.get("title") or ""),
                text=str(entry.get("text") or ""),
                ontology_axioms=list(entry.get("ontology_axioms") or []),
                text_hash=entry.get("text_hash") or None,
                family=str(entry.get("family") or ""),
            )
            if c.id:
                clauses[c.id] = c
        return cls(version=version, clauses=clauses)

    @classmethod
    def load(cls, path: str) -> "RegulationRegistry":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls.from_dict(raw)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "version": self.version,
                "regulations": [c.as_dict() for c in self.clauses.values()],
            }, f, indent=2)


# ── Diff between two registries ─────────────────────────────────────────


@dataclass
class ChangedClause:
    clause_id:       str
    old_hash:        str
    new_hash:        str
    affected_axioms: List[str]


@dataclass
class RegulationDiff:
    old_version: str
    new_version: str
    added:       List[str] = field(default_factory=list)
    removed:     List[str] = field(default_factory=list)
    changed:     List[ChangedClause] = field(default_factory=list)

    @classmethod
    def between(cls, old: RegulationRegistry,
                new: RegulationRegistry) -> "RegulationDiff":
        old_ids = set(old.clauses.keys())
        new_ids = set(new.clauses.keys())
        added = sorted(new_ids - old_ids)
        removed = sorted(old_ids - new_ids)
        changed: List[ChangedClause] = []
        for cid in sorted(old_ids & new_ids):
            o = old.clauses[cid]
            n = new.clauses[cid]
            if o.text_hash != n.text_hash:
                # Union of axioms across both versions — a clause
                # change can invalidate either old constraints or
                # new ones, so the re-validation needs to inspect
                # both sets.
                affected = sorted(set(o.ontology_axioms)
                                   | set(n.ontology_axioms))
                changed.append(ChangedClause(
                    clause_id=cid, old_hash=o.text_hash or "",
                    new_hash=n.text_hash or "",
                    affected_axioms=affected,
                ))
        return cls(
            old_version=old.version, new_version=new.version,
            added=added, removed=removed, changed=changed,
        )

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def all_affected_axioms(self) -> List[str]:
        out: Set[str] = set()
        for c in self.changed:
            out.update(c.affected_axioms)
        # Added / removed clauses too — their axioms also need
        # the re-validation pass.
        return sorted(out)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "old_version": self.old_version,
            "new_version": self.new_version,
            "added":       list(self.added),
            "removed":     list(self.removed),
            "changed":     [c.__dict__ for c in self.changed],
            "all_affected_axioms": self.all_affected_axioms(),
        }


# ── Re-validation hook ──────────────────────────────────────────────────


@dataclass
class RevalidationFinding:
    """One ontology axiom flagged by a regulation diff.

    ``ontology_status`` is one of ``"PRESENT"``, ``"MISSING"``, or
    ``"AMBIGUOUS"`` — whether the axiom IRI appears at all in the
    ontology text. ``regulation_status`` is one of ``"ADDED"``,
    ``"REMOVED"``, ``"CHANGED"``.
    """
    axiom_iri:          str
    regulation_status:  str
    regulation_clauses: List[str] = field(default_factory=list)
    ontology_status:    str = "PRESENT"
    note:               str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "axiom_iri":          self.axiom_iri,
            "regulation_status":  self.regulation_status,
            "regulation_clauses": list(self.regulation_clauses),
            "ontology_status":    self.ontology_status,
            "note":               self.note,
        }


def revalidate(diff: RegulationDiff,
               ontology_path: Optional[str] = None,
               *, new_registry: Optional[RegulationRegistry] = None,
               old_registry: Optional[RegulationRegistry] = None,
               ) -> List[RevalidationFinding]:
    """Surface one :class:`RevalidationFinding` per axiom touched
    by the diff. Each finding lists which regulation clauses
    refer to it and what the regulation status of those clauses
    is (added / removed / changed).

    When ``ontology_path`` is given, the function checks whether
    each axiom IRI actually appears in the ontology text. A
    flagged axiom that's *missing* from the ontology is the most
    serious finding — the regulation references something the
    toolkit never modelled.
    """
    findings: List[RevalidationFinding] = []
    # axiom → (status, [clause_ids])
    axiom_to_clauses: Dict[str, Tuple[str, List[str]]] = {}

    def _record(axiom: str, status: str, clause_id: str) -> None:
        existing = axiom_to_clauses.get(axiom)
        if existing is None:
            axiom_to_clauses[axiom] = (status, [clause_id])
            return
        prev_status, clauses = existing
        # CHANGED beats ADDED beats REMOVED in severity.
        rank = {"CHANGED": 3, "ADDED": 2, "REMOVED": 1}
        if rank.get(status, 0) > rank.get(prev_status, 0):
            prev_status = status
        if clause_id not in clauses:
            clauses.append(clause_id)
        axiom_to_clauses[axiom] = (prev_status, clauses)

    for changed in diff.changed:
        for axiom in changed.affected_axioms:
            _record(axiom, "CHANGED", changed.clause_id)
    if new_registry is not None:
        for cid in diff.added:
            clause = new_registry.clauses.get(cid)
            if clause is None:
                continue
            for axiom in clause.ontology_axioms:
                _record(axiom, "ADDED", cid)
    if old_registry is not None:
        for cid in diff.removed:
            clause = old_registry.clauses.get(cid)
            if clause is None:
                continue
            for axiom in clause.ontology_axioms:
                _record(axiom, "REMOVED", cid)

    ontology_text = ""
    if ontology_path:
        try:
            ontology_text = Path(ontology_path).read_text(errors="replace")
        except Exception:                                          # noqa: BLE001
            ontology_text = ""

    for axiom, (status, clauses) in axiom_to_clauses.items():
        if ontology_text:
            ont_status = "PRESENT" if axiom in ontology_text else "MISSING"
            note = ("axiom referenced by the regulation is missing "
                    "from the ontology") if ont_status == "MISSING" else ""
        else:
            ont_status = "AMBIGUOUS"
            note = "ontology not provided; status unknown"
        findings.append(RevalidationFinding(
            axiom_iri=axiom, regulation_status=status,
            regulation_clauses=sorted(clauses),
            ontology_status=ont_status, note=note,
        ))
    findings.sort(key=lambda f: (f.regulation_status, f.axiom_iri))
    return findings


# ── Audit-log persistence ──────────────────────────────────────────────


_DDL = """
CREATE TABLE IF NOT EXISTS regulation_diffs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    old_version     TEXT,
    new_version     TEXT,
    diff_json       TEXT NOT NULL,
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def ensure_diff_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()


def persist_diff(conn: sqlite3.Connection, diff: RegulationDiff) -> int:
    """Append the diff to the audit log. Returns the row id."""
    ensure_diff_schema(conn)
    cur = conn.execute(
        "INSERT INTO regulation_diffs "
        "(old_version, new_version, diff_json) "
        "VALUES (?, ?, ?)",
        (diff.old_version, diff.new_version,
         json.dumps(diff.as_dict())),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


# ── Helpers ─────────────────────────────────────────────────────────────


def _hash16(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


__all__ = [
    "RegulationClause", "RegulationRegistry",
    "ChangedClause", "RegulationDiff",
    "RevalidationFinding", "revalidate",
    "ensure_diff_schema", "persist_diff",
]
