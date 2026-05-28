"""L6 — RCA starter rule library + Insights presets."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# ── L6.1 — Library shape ───────────────────────────────────────────────


def test_rca_yaml_loads_and_every_rule_validates():
    from wizard.rules import load_starter_library, validate_rule
    rules = load_starter_library(str(ROOT / "templates" / "rules"), "rca")
    assert len(rules) >= 5
    for r in rules:
        res = validate_rule(r)
        assert res.ok, f"{r['id']} broken: {res.errors}"


def test_rca_library_covers_three_rule_families():
    from wizard.rules import load_starter_library
    rules = load_starter_library(str(ROOT / "templates" / "rules"), "rca")
    ids = {r["id"] for r in rules}
    # Cause-chain closure (one + two hop).
    assert any("rootcause" in i for i in ids)
    # Concurrent-cause marker.
    assert any("multiple-causes" in i for i in ids)
    # Heartbeat / derivation differentiation.
    assert any("derivation" in i for i in ids)


# ── L6.2 — Insights presets ────────────────────────────────────────────


def test_list_rca_presets_returns_named_templates():
    from runtime.insights import list_rca_presets
    presets = list_rca_presets()
    assert "root-cause" in presets
    assert "similar-incidents" in presets
    assert "{event}" in presets["root-cause"]


def test_expand_rca_preset_substitutes_event_iri():
    from runtime.insights import expand_rca_preset
    text = expand_rca_preset("root-cause",
                             event_iri="https://x/y/event-42")
    assert "{event}" not in text
    assert "event-42" in text


def test_expand_rca_preset_unknown_raises():
    from runtime.insights import expand_rca_preset
    with pytest.raises(KeyError):
        expand_rca_preset("nonexistent-preset", event_iri="x")


def test_rca_endpoints_register():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    assert "/api/insights/rca-presets" in rules
    assert "/api/insights/rca" in rules


# ── End-to-end: cause-chain closure materialises :rootCause ────────────


def test_cause_chain_closure_materialises_rootcause(tmp_path):
    """Build a 3-event chain (A → B → C) with explicit :hasCause edges,
    run --phase reason with the RCA starter library, confirm a
    :rootCause edge from C → A is materialised."""
    from materializer import materialize
    from wizard.rules import export_rules, load_starter_library

    ontology = tmp_path / "enterprise.ttl"
    ontology.write_text("""\
@prefix : <https://ontology.example.com/enterprise/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:CausalEvent a owl:Class .
:hasCause   a owl:ObjectProperty ; rdfs:domain :CausalEvent ; rdfs:range :CausalEvent .
:rootCause  a owl:ObjectProperty ; rdfs:subPropertyOf :hasCause .

:A a :CausalEvent .
:B a :CausalEvent ; :hasCause :A .
:C a :CausalEvent ; :hasCause :B .
""")
    # Load the RCA library and export the rootcause rules to disk so
    # the materialiser picks them up.
    rules = load_starter_library(str(ROOT / "templates" / "rules"), "rca")
    rootcause_rules = [r for r in rules if "rootcause" in r["id"]]
    export_rules(rootcause_rules, str(tmp_path))

    result = materialize(
        str(ontology), str(tmp_path / "out"),
        sparql_rules_dir=str(tmp_path / "sparql_rules"),
    )
    sparql = next(e for e in result.engines if e.name == "sparql")
    assert sparql.status == "PASS"
    # Spot-check: at least one :rootCause edge to :A.
    from rdflib import Graph, URIRef
    g = Graph()
    g.parse(sparql.output_path, format="turtle")
    NS = "https://ontology.example.com/enterprise/"
    has_rootcause_a = (URIRef(NS + "C"),
                       URIRef(NS + "rootCause"),
                       URIRef(NS + "A")) in g
    assert has_rootcause_a, "C :rootCause :A must be derived"


def test_concurrent_cause_marker_fires(tmp_path):
    """When an effect has more than one cause, the concurrent-cause
    rule must materialise :multipleCandidateCauses true on the effect."""
    from materializer import materialize
    from wizard.rules import export_rules, load_starter_library

    ontology = tmp_path / "enterprise.ttl"
    ontology.write_text("""\
@prefix : <https://ontology.example.com/enterprise/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:CausalEvent a owl:Class .
:hasCause   a owl:ObjectProperty .
:multipleCandidateCauses a owl:DatatypeProperty .

:A a :CausalEvent .
:B a :CausalEvent .
:C a :CausalEvent ; :hasCause :A , :B .
""")
    rules = load_starter_library(str(ROOT / "templates" / "rules"), "rca")
    multi_rules = [r for r in rules if "multiple-causes" in r["id"]]
    export_rules(multi_rules, str(tmp_path))

    result = materialize(
        str(ontology), str(tmp_path / "out"),
        sparql_rules_dir=str(tmp_path / "sparql_rules"),
    )
    sparql = next(e for e in result.engines if e.name == "sparql")
    assert sparql.derived_triples >= 1, \
        "expected the concurrent-cause marker to fire on :C"
