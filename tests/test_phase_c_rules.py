"""Phase C — rules step.

Covers:
    - validate_rule: SHACL / SPARQL / OWL kinds, success and failure paths.
    - export_rules: writes shapes/rules.ttl + sparql_rules/<id>.rq.
    - load_starter_library: parses the three industry YAMLs.
    - End-to-end: rules → export → materializer.materialize picks them up.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wizard.rules import (  # noqa: E402
    export_rules, load_starter_library,
    normalise_rule, validate_rule, validate_rules,
)
from materializer import materialize  # noqa: E402


# ── validate_rule ─────────────────────────────────────────────────────────


def test_valid_sparql_construct():
    r = {"kind": "sparql", "label": "echo",
         "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"}
    assert validate_rule(r).ok


def test_sparql_select_rejected():
    r = {"kind": "sparql", "label": "x",
         "body": "SELECT ?s WHERE { ?s ?p ?o }"}
    res = validate_rule(r)
    assert not res.ok
    assert any("CONSTRUCT" in e for e in res.errors)


def test_sparql_syntax_error_caught():
    r = {"kind": "sparql", "label": "x", "body": "CONSTRUCT { broken"}
    assert not validate_rule(r).ok


def test_valid_shacl_rule():
    r = {"kind": "shacl", "label": "trigger flag", "body": """\
@prefix : <https://test.example/c#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
:S a sh:NodeShape ; sh:targetClass :Trigger ;
   sh:rule [ a sh:TripleRule ;
             sh:subject sh:this ; sh:predicate :flag ; sh:object true ] .
"""}
    res = validate_rule(r)
    assert res.ok, res.errors


def test_shacl_garbage_rejected():
    r = {"kind": "shacl", "label": "x", "body": "this is not turtle"}
    assert not validate_rule(r).ok


def test_owl_axiom_accepted():
    r = {"kind": "owl", "label": "transitive partOf", "body": """\
@prefix : <https://test.example/c#> .
:partOf a owl:ObjectProperty, owl:TransitiveProperty .
"""}
    assert validate_rule(r).ok


def test_unknown_kind_rejected():
    assert not validate_rule({"kind": "swrl", "label": "x", "body": "..."}).ok


def test_empty_body_rejected():
    assert not validate_rule({"kind": "sparql", "label": "x", "body": "  "}).ok


def test_validate_rules_detects_duplicates():
    rules = [
        {"id": "r1", "kind": "sparql", "label": "a",
         "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"},
        {"id": "r1", "kind": "sparql", "label": "b",
         "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"},
    ]
    out = validate_rules(rules)
    assert "__duplicate_ids__" in out
    assert not out["__duplicate_ids__"].ok


# ── export_rules ──────────────────────────────────────────────────────────


def test_export_writes_files(tmp_path):
    rules = [
        {"id": "echo", "kind": "sparql", "label": "echo",
         "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"},
        {"id": "shacl-flag", "kind": "shacl", "label": "flag", "body": """\
@prefix : <https://test.example/c#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
:S a sh:NodeShape ; sh:targetClass :T ;
   sh:rule [ a sh:TripleRule ;
             sh:subject sh:this ; sh:predicate :flag ; sh:object true ] .
"""},
        {"id": "axiom-1", "kind": "owl", "label": "transitive", "body": """\
@prefix : <https://test.example/c#> .
:partOf a owl:ObjectProperty, owl:TransitiveProperty .
"""},
    ]
    export = export_rules(rules, str(tmp_path))
    assert export["counts"] == {"shacl": 1, "sparql": 1, "owl": 1, "skipped": 0}
    assert (tmp_path / "shapes" / "rules.ttl").is_file()
    assert (tmp_path / "sparql_rules" / "echo.rq").is_file()
    assert (tmp_path / "owl_axioms.ttl").is_file()


def test_export_skips_disabled(tmp_path):
    rules = [
        {"id": "off", "kind": "sparql", "label": "x", "enabled": False,
         "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"},
    ]
    export = export_rules(rules, str(tmp_path))
    assert export["counts"]["sparql"] == 0


def test_export_skips_invalid_with_reason(tmp_path):
    rules = [
        {"id": "bad", "kind": "sparql", "label": "x",
         "body": "SELECT ?s WHERE { ?s ?p ?o }"},
    ]
    export = export_rules(rules, str(tmp_path))
    assert export["counts"]["skipped"] == 1
    assert export["skipped"][0][0] == "bad"


# ── starter library ──────────────────────────────────────────────────────


def test_starter_library_loads_each_industry():
    lib = ROOT / "templates" / "rules"
    for industry in ("telecom", "healthcare", "finance"):
        rules = load_starter_library(str(lib), industry)
        assert rules, f"no rules loaded for {industry}"
        # Every starter rule must validate cleanly.
        for r in rules:
            res = validate_rule(r)
            assert res.ok, f"{industry}/{r['id']} broken: {res.errors}"


def test_starter_library_missing_industry_returns_empty(tmp_path):
    assert load_starter_library(str(tmp_path), "nonexistent") == []


# ── End-to-end: rules → export → materialize ─────────────────────────────


def test_end_to_end_rules_drive_materialisation(tmp_path):
    """Saved rules go through export_rules and then drive Phase B."""
    ontology = tmp_path / "enterprise.ttl"
    ontology.write_text("""\
@prefix : <https://test.example/e2e#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
:partOf a owl:ObjectProperty .
:A :partOf :B .
:B :partOf :C .
""")
    rules = [
        {"id": "transitive-via-construct", "kind": "sparql",
         "label": "Two-hop reachability",
         "body": "PREFIX : <https://test.example/e2e#>\n"
                 "CONSTRUCT { ?x :reaches ?z } "
                 "WHERE { ?x :partOf ?y . ?y :partOf ?z }"},
    ]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    export = export_rules(rules, str(out_dir))
    assert (out_dir / "sparql_rules" / "transitive-via-construct.rq").is_file()

    result = materialize(
        str(ontology), str(out_dir / "ontology"),
        sparql_rules_dir=str(out_dir / "sparql_rules"),
    )
    sparql = next(e for e in result.engines if e.name == "sparql")
    assert sparql.status == "PASS"
    from rdflib import Graph, URIRef
    g = Graph()
    g.parse(sparql.output_path, format="turtle")
    NS = "https://test.example/e2e#"
    assert (URIRef(NS + "A"), URIRef(NS + "reaches"), URIRef(NS + "C")) in g


# ── Wizard API smoke (only runs if Flask is importable) ──────────────────


def test_wizard_api_routes_register():
    flask = pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    # Importing wizard.app registers the new /api/rules* routes.
    import importlib

    # The wizard module reads SESSION_FILE / ONTOLOGIES_DB at import; redirect
    # them to a tmp scratch path to avoid mutating the real files.
    sys.path.insert(0, str(ROOT))
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    assert "/api/rules" in rules
    assert "/api/rules/validate" in rules
    assert "/api/rules/library" in rules
    assert "/api/rules/library/<industry>" in rules
