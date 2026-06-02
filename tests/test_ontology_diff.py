"""T2.4 — Semantic ontology diff + change-impact analysis.

Tests the three layers (structural / semantic / impact) and the
top-level :func:`diff_ontologies` wrapper.

Acceptance gates (roadmap §3.T2.4):
- On a before/after pair where one disjointness axiom is removed,
  the diff lists the resulting *new entailments* correctly.
- Change-impact analysis identifies downstream code that
  references a renamed class.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("rdflib")
pytest.importorskip("owlrl")

from ontology_diff import (                                          # noqa: E402
    AffectedFile, ImpactReport, OntologyDiffReport, SemanticDiff,
    StructuralDiff, diff_ontologies, impact_analysis,
    render_diff_html, semantic_diff, structural_diff,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _write(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(dedent(body).strip() + "\n")
    return str(p)


def _consistent_v1(tmp_path: Path) -> str:
    return _write(tmp_path, "v1.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Vehicle  a owl:Class .
        :Car      a owl:Class ;
                  rdfs:subClassOf :Vehicle .
        :Truck    a owl:Class ;
                  rdfs:subClassOf :Vehicle ;
                  owl:disjointWith :Car .
        :hasOwner a owl:ObjectProperty .
    """)


def _consistent_v2_added_class(tmp_path: Path) -> str:
    """v2 of the above, but adds Motorbike subclass of Vehicle."""
    return _write(tmp_path, "v2.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Vehicle   a owl:Class .
        :Car       a owl:Class ;
                   rdfs:subClassOf :Vehicle .
        :Truck     a owl:Class ;
                   rdfs:subClassOf :Vehicle ;
                   owl:disjointWith :Car .
        :Motorbike a owl:Class ;
                   rdfs:subClassOf :Vehicle .
        :hasOwner  a owl:ObjectProperty .
    """)


def _chain_before(tmp_path: Path) -> str:
    """v1: Dog ⊑ Mammal ⊑ Animal. Closure entails Dog ⊑ Animal."""
    return _write(tmp_path, "before.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Animal a owl:Class .
        :Mammal a owl:Class ;
                rdfs:subClassOf :Animal .
        :Dog    a owl:Class ;
                rdfs:subClassOf :Mammal .
    """)


def _chain_after_link_removed(tmp_path: Path) -> str:
    """v2: same classes; Mammal ⊑ Animal link removed. Closure no
    longer entails Dog ⊑ Animal — that's the semantic regression
    a reviewer needs to see."""
    return _write(tmp_path, "after.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Animal a owl:Class .
        :Mammal a owl:Class .
        :Dog    a owl:Class ;
                rdfs:subClassOf :Mammal .
    """)


def _renamed_class_old(tmp_path: Path) -> str:
    return _write(tmp_path, "old.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Vehicle a owl:Class .
        :Wagon   a owl:Class ;
                 rdfs:label "Wagon" ;
                 rdfs:subClassOf :Vehicle .
    """)


def _renamed_class_new(tmp_path: Path) -> str:
    return _write(tmp_path, "new.ttl", """
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Vehicle a owl:Class .
        :Cart    a owl:Class ;
                 rdfs:label "Wagon" ;
                 rdfs:subClassOf :Vehicle .
    """)


# ── Structural diff ──────────────────────────────────────────────────


def test_structural_diff_detects_added_class(tmp_path):
    a = _consistent_v1(tmp_path)
    b = _consistent_v2_added_class(tmp_path)
    diff = structural_diff(a, b)
    assert "http://ex.com/Motorbike" in diff.added_classes
    assert diff.removed_classes == []


def test_structural_diff_no_changes_returns_empty(tmp_path):
    a = _consistent_v1(tmp_path)
    diff = structural_diff(a, a)
    assert diff.is_empty()


def test_structural_diff_detects_rename(tmp_path):
    a = _renamed_class_old(tmp_path)
    b = _renamed_class_new(tmp_path)
    diff = structural_diff(a, b)
    # Wagon → Cart with identical label/superclass signature.
    assert ("http://ex.com/Wagon", "http://ex.com/Cart") in diff.renamed_classes


# ── Semantic diff ─────────────────────────────────────────────────────


def test_semantic_diff_no_changes_for_identical_ontologies(tmp_path):
    a = _consistent_v1(tmp_path)
    sd = semantic_diff(a, a, reasoner="owlrl")
    assert sd.is_empty()


def test_semantic_diff_acceptance_gate_lost_entailment(tmp_path):
    """Hero acceptance gate (roadmap §3.T2.4).

    Removing the ``Mammal ⊑ Animal`` axiom from a transitive chain
    causes the closure to *lose* the entailment ``Dog ⊑ Animal``.
    The semantic diff must surface that lost entailment — this is
    exactly the kind of "looks like a small edit, hides a big
    consequence" change that motivates T2.4 in the first place.
    """
    a = _chain_before(tmp_path)
    b = _chain_after_link_removed(tmp_path)

    sd = semantic_diff(a, b, reasoner="owlrl")
    s  = structural_diff(a, b)

    # Structural diff captures the removed subclass axiom.
    removed_predicates = {p for _, p, _ in s.removed_axioms}
    assert any("subClassOf" in p for p in removed_predicates), (
        f"expected removed subClassOf axiom; got {removed_predicates}"
    )

    # Semantic diff captures the lost Dog ⊑ Animal entailment.
    lost = set(sd.lost_subclass)
    assert ("http://ex.com/Dog", "http://ex.com/Animal") in lost, (
        f"expected lost Dog ⊑ Animal entailment; got {sd.lost_subclass}"
    )


# ── Impact analysis ──────────────────────────────────────────────────


def test_impact_analysis_finds_sparql_query_using_changed_iri(tmp_path):
    a = _consistent_v1(tmp_path)
    b = _consistent_v2_added_class(tmp_path)
    sparql_dir = tmp_path / "queries"
    sparql_dir.mkdir()
    (sparql_dir / "motorbikes.rq").write_text(
        "PREFIX : <http://ex.com/>\n"
        "SELECT ?m WHERE { ?m a :Motorbike }\n"
    )
    diff = structural_diff(a, b)
    impact = impact_analysis(diff, scan_dirs=[str(tmp_path)])
    assert impact.affected_files
    paths = {f.path for f in impact.affected_files}
    assert any("motorbikes.rq" in p for p in paths)


def test_impact_analysis_acceptance_gate_finds_renamed_class_references(tmp_path):
    """Renaming :Wagon → :Cart: the impact analysis must flag any
    downstream file still referring to the old name."""
    old = _renamed_class_old(tmp_path)
    new = _renamed_class_new(tmp_path)
    diff = structural_diff(old, new)
    # Place a SHACL file that still uses Wagon.
    shapes = tmp_path / "shapes"
    shapes.mkdir()
    (shapes / "wagon-shape.ttl").write_text(
        "@prefix : <http://ex.com/> .\n"
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        ":WagonShape a sh:NodeShape ; sh:targetClass :Wagon .\n"
    )
    impact = impact_analysis(diff, scan_dirs=[str(tmp_path)])
    # Found at least the shapes file.
    assert any("wagon-shape.ttl" in f.path for f in impact.affected_files)
    aff = next(f for f in impact.affected_files
               if "wagon-shape.ttl" in f.path)
    # The reference list captures the changed class IRI or its local name.
    assert any("Wagon" in r for r in aff.references)


def test_impact_analysis_empty_when_no_references(tmp_path):
    a = _consistent_v1(tmp_path)
    b = _consistent_v2_added_class(tmp_path)
    diff = structural_diff(a, b)
    # scan_dirs that doesn't contain references to Motorbike.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    (empty_dir / "unrelated.rq").write_text("SELECT * WHERE { ?s ?p ?o }")
    out = impact_analysis(diff, scan_dirs=[str(empty_dir)])
    assert out.is_empty()


# ── Top-level wrapper ────────────────────────────────────────────────


def test_diff_ontologies_composes_all_three_sections(tmp_path):
    a = _consistent_v1(tmp_path)
    b = _consistent_v2_added_class(tmp_path)
    rep = diff_ontologies(a, b, reasoner="owlrl",
                          scan_dirs=[str(tmp_path)])
    assert isinstance(rep, OntologyDiffReport)
    assert isinstance(rep.structural, StructuralDiff)
    assert isinstance(rep.semantic, SemanticDiff)
    assert isinstance(rep.impact, ImpactReport)
    d = rep.as_dict()
    assert {"structural", "semantic", "impact", "old_path", "new_path"} \
        == set(d.keys())


def test_diff_ontologies_is_pure_and_idempotent(tmp_path):
    a = _consistent_v1(tmp_path)
    b = _consistent_v2_added_class(tmp_path)
    r1 = diff_ontologies(a, b, reasoner="owlrl").as_dict()
    r2 = diff_ontologies(a, b, reasoner="owlrl").as_dict()
    assert r1 == r2


# ── HTML rendering ───────────────────────────────────────────────────


def test_render_diff_html_includes_section_headers(tmp_path):
    a = _consistent_v1(tmp_path)
    b = _consistent_v2_added_class(tmp_path)
    rep = diff_ontologies(a, b, reasoner="owlrl",
                          scan_dirs=[str(tmp_path)])
    html = render_diff_html(rep)
    assert "<h1>Ontology diff" in html
    assert "Structural" in html
    assert "Semantic (entailment delta)" in html
    assert "Downstream impact" in html
    # Includes the new class.
    assert "Motorbike" in html


def test_render_diff_html_shows_empty_states_for_no_changes(tmp_path):
    a = _consistent_v1(tmp_path)
    rep = diff_ontologies(a, a, reasoner="owlrl")
    html = render_diff_html(rep)
    assert "No structural changes." in html
    assert "No entailment changes" in html
