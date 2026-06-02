"""T3.4 — Continuous compliance with regulation diffs.

Acceptance gate (roadmap §3.T3.4):
- When HIPAA §164.312(a)(1) changes (text-hash differs), surface
  the ontology axioms linked to that clause as
  ``RevalidationFinding`` entries.
- Diff persistence + audit log round-trips cleanly.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


from compliance_feeds import (                                       # noqa: E402
    ChangedClause, RegulationClause, RegulationDiff,
    RegulationRegistry, RevalidationFinding, ensure_diff_schema,
    persist_diff, revalidate,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _hipaa_v1() -> RegulationRegistry:
    return RegulationRegistry(
        version="2024.01",
        clauses={
            "HIPAA-164.312(a)(1)": RegulationClause(
                id="HIPAA-164.312(a)(1)",
                title="Access Control",
                text="Implement technical policies and procedures.",
                ontology_axioms=[
                    "http://ex.com/hasAccessControl",
                    "http://ex.com/ProtectedHealthInformation",
                ],
                family="HIPAA",
            ),
            "HIPAA-164.312(b)": RegulationClause(
                id="HIPAA-164.312(b)",
                title="Audit Controls",
                text="Hardware, software, and procedural mechanisms.",
                ontology_axioms=["http://ex.com/hasAuditTrail"],
                family="HIPAA",
            ),
        },
    )


def _hipaa_v2_changed_clause() -> RegulationRegistry:
    """v2 of HIPAA: §164.312(a)(1) text changed (e.g. tightened);
    §164.312(b) unchanged; new clause §164.314 added."""
    r = _hipaa_v1()
    new_clauses = dict(r.clauses)
    new_clauses["HIPAA-164.312(a)(1)"] = RegulationClause(
        id="HIPAA-164.312(a)(1)",
        title="Access Control",
        text=("Implement technical policies and procedures. "
              "Effective 2026 — must include multi-factor auth."),
        ontology_axioms=[
            "http://ex.com/hasAccessControl",
            "http://ex.com/ProtectedHealthInformation",
            "http://ex.com/requiresMFA",     # new linked axiom
        ],
        family="HIPAA",
    )
    new_clauses["HIPAA-164.314"] = RegulationClause(
        id="HIPAA-164.314",
        title="Organizational Requirements",
        text="Business associate contracts.",
        ontology_axioms=["http://ex.com/hasBAA"],
        family="HIPAA",
    )
    return RegulationRegistry(version="2026.01", clauses=new_clauses)


def _consistent_ontology(tmp_path):
    body = """
@prefix : <http://ex.com/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

:ProtectedHealthInformation a owl:Class .
:hasAccessControl a owl:ObjectProperty .
:hasAuditTrail    a owl:DatatypeProperty .
"""
    p = tmp_path / "ont.ttl"
    p.write_text(body)
    return str(p)


# ── RegulationClause + Registry shape ─────────────────────────────────


def test_clause_hashes_text_automatically():
    c = RegulationClause(id="X", title="t", text="hello world")
    assert c.text_hash
    assert len(c.text_hash) == 16


def test_clause_text_change_changes_hash():
    a = RegulationClause(id="X", title="t", text="a")
    b = RegulationClause(id="X", title="t", text="b")
    assert a.text_hash != b.text_hash


def test_registry_from_dict_round_trip():
    raw = {
        "version": "1.0",
        "regulations": [{
            "id": "X", "title": "t", "text": "hello",
            "ontology_axioms": ["http://x/y"],
        }],
    }
    r = RegulationRegistry.from_dict(raw)
    assert r.version == "1.0"
    assert "X" in r.clauses
    assert r.clauses["X"].text == "hello"


def test_registry_save_load_round_trip(tmp_path):
    r = _hipaa_v1()
    path = str(tmp_path / "reg.json")
    r.save(path)
    loaded = RegulationRegistry.load(path)
    assert loaded.version == r.version
    assert set(loaded.clauses.keys()) == set(r.clauses.keys())


def test_registry_skips_entries_without_id():
    raw = {"version": "1.0",
           "regulations": [{"text": "no id here"}]}
    r = RegulationRegistry.from_dict(raw)
    assert r.clauses == {}


# ── Diff ──────────────────────────────────────────────────────────────


def test_diff_between_identical_registries_is_empty():
    a = _hipaa_v1()
    diff = RegulationDiff.between(a, a)
    assert diff.is_empty()


def test_diff_detects_added_clause():
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    assert "HIPAA-164.314" in diff.added


def test_diff_detects_changed_clause():
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    changed_ids = [c.clause_id for c in diff.changed]
    assert "HIPAA-164.312(a)(1)" in changed_ids


def test_diff_unchanged_clause_not_flagged():
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    changed_ids = [c.clause_id for c in diff.changed]
    assert "HIPAA-164.312(b)" not in changed_ids


def test_diff_detects_removed_clause():
    a = _hipaa_v1()
    b = RegulationRegistry(version="2.0", clauses={"HIPAA-164.312(b)": a.clauses["HIPAA-164.312(b)"]})
    diff = RegulationDiff.between(a, b)
    assert "HIPAA-164.312(a)(1)" in diff.removed


def test_diff_all_affected_axioms_includes_union():
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    affected = set(diff.all_affected_axioms())
    # Both old and new axioms for the changed clause appear.
    assert "http://ex.com/hasAccessControl" in affected
    assert "http://ex.com/requiresMFA" in affected
    # Unchanged clauses' axioms NOT included.
    assert "http://ex.com/hasAuditTrail" not in affected


# ── Revalidation hook — HERO ACCEPTANCE GATE ─────────────────────────


def test_revalidate_surfaces_findings_for_changed_clauses(tmp_path):
    """Hero gate (roadmap §3.T3.4): when §164.312(a)(1) changes,
    every ontology axiom linked to that clause must surface as
    a RevalidationFinding."""
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    ontology = _consistent_ontology(tmp_path)
    findings = revalidate(diff, ontology,
                          new_registry=_hipaa_v2_changed_clause(),
                          old_registry=_hipaa_v1())
    iris = {f.axiom_iri for f in findings}
    # The changed clause's axioms appear, with CHANGED status.
    assert "http://ex.com/hasAccessControl" in iris
    by_iri = {f.axiom_iri: f for f in findings}
    ac = by_iri["http://ex.com/hasAccessControl"]
    assert ac.regulation_status == "CHANGED"
    assert "HIPAA-164.312(a)(1)" in ac.regulation_clauses


def test_revalidate_flags_missing_axiom_when_not_in_ontology(tmp_path):
    """If the regulation references an axiom IRI that's missing
    from the ontology, the finding's ontology_status is MISSING —
    the most serious finding kind."""
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    ontology = _consistent_ontology(tmp_path)
    findings = revalidate(diff, ontology,
                          new_registry=_hipaa_v2_changed_clause(),
                          old_registry=_hipaa_v1())
    by_iri = {f.axiom_iri: f for f in findings}
    # :requiresMFA is in the new clause's linked axioms but NOT in
    # the synthesised ontology.
    mfa = by_iri["http://ex.com/requiresMFA"]
    assert mfa.ontology_status == "MISSING"
    assert "missing from the ontology" in mfa.note


def test_revalidate_distinguishes_added_changed_removed():
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    findings = revalidate(diff, ontology_path=None,
                          new_registry=_hipaa_v2_changed_clause(),
                          old_registry=_hipaa_v1())
    statuses = {f.axiom_iri: f.regulation_status for f in findings}
    # CHANGED axioms are present.
    assert statuses["http://ex.com/hasAccessControl"] == "CHANGED"
    # ADDED axioms are present.
    assert statuses["http://ex.com/hasBAA"] == "ADDED"


def test_revalidate_ambiguous_status_when_no_ontology_path():
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    findings = revalidate(diff, ontology_path=None,
                          new_registry=_hipaa_v2_changed_clause())
    for f in findings:
        assert f.ontology_status == "AMBIGUOUS"


def test_revalidate_empty_diff_returns_no_findings(tmp_path):
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v1())
    ontology = _consistent_ontology(tmp_path)
    findings = revalidate(diff, ontology)
    assert findings == []


# ── Audit-log persistence ────────────────────────────────────────────


def test_ensure_diff_schema_creates_table():
    c = sqlite3.connect(":memory:")
    ensure_diff_schema(c)
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='regulation_diffs'"
    ).fetchall()
    assert rows


def test_persist_diff_writes_audit_row():
    c = sqlite3.connect(":memory:")
    ensure_diff_schema(c)
    diff = RegulationDiff.between(_hipaa_v1(), _hipaa_v2_changed_clause())
    row_id = persist_diff(c, diff)
    assert row_id >= 1
    out = c.execute(
        "SELECT old_version, new_version, diff_json "
        "FROM regulation_diffs WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert out[0] == "2024.01"
    assert out[1] == "2026.01"
    parsed = json.loads(out[2])
    assert parsed["new_version"] == "2026.01"
    assert "HIPAA-164.312(a)(1)" in [c["clause_id"] for c in parsed["changed"]]
