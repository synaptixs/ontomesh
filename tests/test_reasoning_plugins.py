"""T2.1 — Logical reasoning plug-in.

Tests the Reasoner plug-in framework + the three high-level call
sites (classify / check_consistency / detect_redundant_shacl).

Acceptance gates (roadmap §3.T2.1):
- Inconsistency detected within 10 s + unsat axiom set surfaced
  on a test ontology where ``Customer ⊓ Robot`` is asserted
  ``owl:disjointWith`` and an instance is typed as both.
- A SHACL constraint redundant given OWL entailment gets flagged.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from textwrap import dedent

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("rdflib")
pytest.importorskip("owlrl")

from reasoners import (                                              # noqa: E402
    AVAILABLE_REASONERS, Inconsistency, MockReasoner, OwlrlReasoner,
    RobotElkReasoner, RobotHermitReasoner,
    default_reasoner_for_profile, get_reasoner,
)
from reasoners.base import RedundancyFinding                         # noqa: E402
from reasoning import (                                              # noqa: E402
    check_consistency, classify, detect_redundant_shacl,
)


# ── Fixture ontologies ────────────────────────────────────────────────


def _write_file(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(dedent(body).strip() + "\n")
    return str(p)


# A clean consistent ontology with a class hierarchy that lets us
# verify subsumption inference.
def _consistent_ontology(tmp_path: Path) -> str:
    return _write_file(tmp_path, "consistent.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Animal a owl:Class .
        :Mammal a owl:Class ;
                rdfs:subClassOf :Animal .
        :Dog a owl:Class ;
             rdfs:subClassOf :Mammal .

        :rex a :Dog .
    """)


# Hero corpus for the consistency-check gate.
# Customer and Robot are disjoint; an instance is typed as both.
def _inconsistent_ontology(tmp_path: Path) -> str:
    return _write_file(tmp_path, "inconsistent.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Customer a owl:Class .
        :Robot    a owl:Class ;
                  owl:disjointWith :Customer .

        :acme a :Customer , :Robot .
    """)


# Ontology with rdfs:range — used by the SHACL redundancy test.
def _ontology_with_range(tmp_path: Path) -> str:
    return _write_file(tmp_path, "range.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Customer    a owl:Class .
        :EmailAddr   a owl:Class .
        :hasEmail    a owl:ObjectProperty ;
                     rdfs:domain :Customer ;
                     rdfs:range  :EmailAddr .
    """)


def _redundant_shapes(tmp_path: Path) -> str:
    return _write_file(tmp_path, "redundant-shapes.ttl", """
        @prefix : <http://ex.com/> .
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

        :CustomerShape a sh:NodeShape ;
            sh:targetClass :Customer ;
            sh:property [
                sh:path :hasEmail ;
                sh:class :EmailAddr ;
            ] .
    """)


# ── Registry / selection ─────────────────────────────────────────────


def test_available_reasoners_lists_all_three_real_plus_mock():
    assert {"owlrl", "robot-elk", "robot-hermit", "mock"} <= set(AVAILABLE_REASONERS)


def test_default_reasoner_for_profile_picks_elk_for_el():
    assert default_reasoner_for_profile("OWL 2 EL") == "robot-elk"
    assert default_reasoner_for_profile("OWL 2 DL") == "robot-hermit"
    assert default_reasoner_for_profile("OWL 2 RL") == "owlrl"
    assert default_reasoner_for_profile(None) == "owlrl"


def test_get_reasoner_falls_back_to_owlrl_when_robot_missing():
    """When ROBOT isn't on PATH (the typical CI case) the registry
    must transparently slide down to owlrl so the build never
    fails on a missing optional runtime."""
    r = get_reasoner("robot-elk", fallback=True)
    # Either ROBOT IS available (rare; we accept that case) or we
    # got owlrl (the fallback). Anything else is a bug.
    assert r.name in ("robot-elk", "owlrl")


def test_get_reasoner_no_fallback_returns_named_adapter():
    r = get_reasoner("robot-elk", fallback=False)
    assert r.name == "robot-elk"


def test_get_reasoner_unknown_name_with_fallback_returns_owlrl():
    r = get_reasoner("nonexistent", fallback=True)
    assert r.name == "owlrl"


def test_get_reasoner_unknown_name_without_fallback_raises():
    with pytest.raises(KeyError):
        get_reasoner("nonexistent", fallback=False)


# ── owlrl adapter — classify ─────────────────────────────────────────


def test_owlrl_classify_returns_ok_on_consistent_ontology(tmp_path):
    path = _consistent_ontology(tmp_path)
    res = OwlrlReasoner().classify(path)
    assert res.status == "OK"
    assert res.duration_s >= 0.0


def test_owlrl_classify_finds_transitive_subclass(tmp_path):
    path = _consistent_ontology(tmp_path)
    res = OwlrlReasoner().classify(path)
    # rdfs:subClassOf is transitive — Dog ⊑ Mammal ⊑ Animal entails Dog ⊑ Animal.
    derived_pairs = set(res.derived_subclass)
    assert ("http://ex.com/Dog", "http://ex.com/Animal") in derived_pairs


def test_owlrl_classify_writes_closure_when_output_path_given(tmp_path):
    path = _consistent_ontology(tmp_path)
    out = str(tmp_path / "closure.ttl")
    res = OwlrlReasoner().classify(path, output_path=out)
    assert res.status == "OK"
    assert res.derived_axioms_path == out
    assert Path(out).is_file()


# ── owlrl adapter — consistency ──────────────────────────────────────


def test_owlrl_consistency_passes_on_consistent_ontology(tmp_path):
    path = _consistent_ontology(tmp_path)
    inc = OwlrlReasoner().check_consistency(path)
    assert not inc.has_findings()


def test_owlrl_consistency_flags_disjoint_violation(tmp_path):
    """Hero gate (roadmap §3.T2.1): inject Customer ⊓ Robot disjoint
    + instance of both; reasoner must detect."""
    path = _inconsistent_ontology(tmp_path)
    inc = OwlrlReasoner().check_consistency(path)
    assert inc.has_findings()
    assert "http://ex.com/acme" in inc.individuals
    # The minimal-axiom-set on the owlrl adapter surfaces the
    # disjointWith + the two type assertions.
    assert any("disjointWith" in a for a in inc.conflicting_axioms)


def test_owlrl_consistency_detects_within_10s_acceptance_budget(tmp_path):
    """Acceptance gate timing: ≤ 10 s on the inconsistent corpus."""
    path = _inconsistent_ontology(tmp_path)
    t0 = time.perf_counter()
    inc = OwlrlReasoner().check_consistency(path)
    elapsed = time.perf_counter() - t0
    assert inc.has_findings()
    assert elapsed < 10.0, f"consistency check took {elapsed:.2f}s; budget 10s"


# ── owlrl adapter — SHACL redundancy ─────────────────────────────────


def test_owlrl_detects_redundant_shacl_class_constraint(tmp_path):
    """Acceptance gate: a SHACL sh:class constraint already entailed
    by rdfs:range gets flagged."""
    ontology = _ontology_with_range(tmp_path)
    shapes   = _redundant_shapes(tmp_path)
    findings = OwlrlReasoner().detect_redundant_shacl(ontology, shapes)
    assert len(findings) >= 1
    finding = findings[0]
    assert isinstance(finding, RedundancyFinding)
    assert "hasEmail" in finding.constraint
    assert "rdfs:range" in finding.reason


# ── ROBOT adapters — graceful when binary absent ─────────────────────


def test_robot_elk_reports_skipped_when_binary_unavailable(tmp_path):
    """In a typical CI env without ROBOT, the adapter must report
    SKIPPED not crash."""
    path = _consistent_ontology(tmp_path)
    adapter = RobotElkReasoner()
    if adapter.available():
        pytest.skip("ROBOT present; this test covers absent-binary path")
    res = adapter.classify(path)
    assert res.status == "SKIPPED"


def test_robot_hermit_reports_skipped_when_binary_unavailable(tmp_path):
    path = _consistent_ontology(tmp_path)
    adapter = RobotHermitReasoner()
    if adapter.available():
        pytest.skip("ROBOT present; this test covers absent-binary path")
    res = adapter.classify(path)
    assert res.status == "SKIPPED"


# ── Mock adapter ─────────────────────────────────────────────────────


def test_mock_reasoner_returns_canned_derived_pairs(tmp_path):
    path = _consistent_ontology(tmp_path)
    m = MockReasoner(canned_derived=[("a", "b"), ("c", "d")])
    res = m.classify(path)
    assert res.status == "OK"
    assert list(res.derived_subclass) == [("a", "b"), ("c", "d")]


def test_mock_reasoner_returns_canned_inconsistency(tmp_path):
    path = _consistent_ontology(tmp_path)
    m = MockReasoner(canned_inconsistency=Inconsistency(
        unsat_classes=["X"], individuals=["i"], message="bad",
    ))
    inc = m.check_consistency(path)
    assert inc.has_findings()
    assert "X" in inc.unsat_classes


# ── High-level v3 API ────────────────────────────────────────────────


def test_high_level_classify_returns_classification_report(tmp_path):
    path = _consistent_ontology(tmp_path)
    rep = classify(path, reasoner="owlrl")
    assert rep.status == "OK"
    assert rep.reasoner == "owlrl"
    assert rep.derived_subclass


def test_high_level_classify_separates_expected_from_accidental(tmp_path):
    path = _consistent_ontology(tmp_path)
    # Mark Dog ⊑ Mammal as expected; Dog ⊑ Animal becomes "accidental"
    # in the sense that the engineer did not assert it directly.
    expected = [("http://ex.com/Dog", "http://ex.com/Mammal")]
    rep = classify(path, reasoner="owlrl", expected_subclass=expected)
    accidental = set(rep.accidental_subclass)
    assert ("http://ex.com/Dog", "http://ex.com/Animal") in accidental
    # ...but not the one we explicitly expected.
    assert ("http://ex.com/Dog", "http://ex.com/Mammal") not in accidental


def test_high_level_check_consistency_returns_inconsistency(tmp_path):
    path = _inconsistent_ontology(tmp_path)
    inc = check_consistency(path, reasoner="owlrl")
    assert inc.has_findings()


def test_high_level_detect_redundant_shacl_returns_findings(tmp_path):
    ontology = _ontology_with_range(tmp_path)
    shapes   = _redundant_shapes(tmp_path)
    out = detect_redundant_shacl(ontology, shapes, reasoner="owlrl")
    assert len(out) >= 1


# ── Round-trip / smoke ───────────────────────────────────────────────


def test_classify_then_consistency_chain_works(tmp_path):
    """Sequence the two main call sites; both must work on the same
    file without leaking state."""
    path = _consistent_ontology(tmp_path)
    rep = classify(path, reasoner="owlrl")
    inc = check_consistency(path, reasoner="owlrl")
    assert rep.status == "OK"
    assert not inc.has_findings()


def test_high_level_api_uses_named_reasoner_when_specified(tmp_path):
    """The optional ``reasoner`` argument must dominate over profile-
    based selection. With name='owlrl' the report should bear that
    reasoner regardless of profile."""
    path = _consistent_ontology(tmp_path)
    rep = classify(path, reasoner="owlrl", profile="OWL 2 EL")
    assert rep.reasoner == "owlrl"
