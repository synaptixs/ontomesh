"""F2 + suggestion #6 — single-rule preview.

Covers preview_rule() across all three rule kinds, the empty-result
"rule fired but produced no triples" path, and the API route wiring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wizard.rules import preview_rule  # noqa: E402


PREVIEW_ABOX = """\
@prefix : <https://test.example/preview#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
:partA :partOf :partB .
:partB :partOf :partC .
:t1 a :Trigger .
"""


# ── SPARQL preview ───────────────────────────────────────────────────────


def test_sparql_construct_produces_derived_triples():
    rule = {
        "id": "two-hop", "kind": "sparql", "label": "two-hop reach",
        "body": ("PREFIX : <https://test.example/preview#>\n"
                 "CONSTRUCT { ?x :reaches ?z }\n"
                 "WHERE     { ?x :partOf ?y . ?y :partOf ?z }"),
    }
    result = preview_rule(rule, abox_text=PREVIEW_ABOX)
    assert result.ok
    assert result.derived_count >= 1
    # Lineage must include the WHERE bindings.
    lin = result.lineage[0]
    assert {"x", "y", "z"}.issubset(lin["bindings"].keys())
    # Premises captured.
    assert any("partOf" in p[1] for p in lin["premises"])


def test_sparql_with_no_matches_returns_empty_with_warning():
    rule = {
        "id": "no-match", "kind": "sparql", "label": "no match",
        "body": ("PREFIX : <https://test.example/preview#>\n"
                 "CONSTRUCT { ?x :unrelated ?y }\n"
                 "WHERE     { ?x :nonexistentRel ?y }"),
    }
    result = preview_rule(rule, abox_text=PREVIEW_ABOX)
    assert result.ok                     # rule itself ran fine
    assert result.derived_count == 0     # but produced nothing
    assert result.warnings               # surfaced a soft warning


# ── SHACL preview ────────────────────────────────────────────────────────


def test_shacl_triple_rule_fires_against_synthetic_abox():
    rule = {
        "id": "trigger-flag", "kind": "shacl", "label": "trigger flag",
        "body": """
@prefix : <https://test.example/preview#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
:S a sh:NodeShape ; sh:targetClass :Trigger ;
   sh:rule [ a sh:TripleRule ;
             sh:subject sh:this ;
             sh:predicate :flag ;
             sh:object true ] .
""",
    }
    result = preview_rule(rule, abox_text=PREVIEW_ABOX)
    assert result.ok
    assert result.derived_count >= 1
    # Each derived triple should carry rule attribution.
    assert all(l["rule"].startswith("shacl:") for l in result.lineage)


# ── OWL preview (via OWL-RL closure) ─────────────────────────────────────


def test_owl_axiom_drives_owl_rl_closure():
    rule = {
        "id": "transitive-partof", "kind": "owl",
        "label": "partOf transitive",
        "body": """
@prefix : <https://test.example/preview#> .
:partOf a owl:ObjectProperty, owl:TransitiveProperty .
""",
    }
    result = preview_rule(rule, abox_text=PREVIEW_ABOX)
    assert result.ok
    # Closure must derive :partA :partOf :partC
    triples = {(s, p, o) for (s, p, o) in result.derived}
    assert ("https://test.example/preview#partA",
            "https://test.example/preview#partOf",
            "https://test.example/preview#partC") in triples


# ── Validation surfaces in the preview result ────────────────────────────


def test_invalid_rule_fails_fast_without_running_engine():
    rule = {"id": "bad", "kind": "sparql", "label": "bad",
            "body": "SELECT ?s WHERE { ?s ?p ?o }"}
    result = preview_rule(rule, abox_text=PREVIEW_ABOX)
    assert not result.ok
    assert result.engine_status == "FAIL"
    assert any("CONSTRUCT" in e for e in result.errors)


# ── Default ABox path ────────────────────────────────────────────────────


def test_default_preview_abox_is_shipped_and_loadable():
    """The shipped synthetic ABox lets the preview endpoint always have
    something to fire on, even before the user generates a real ABox."""
    rule = {
        "id": "default-abox", "kind": "sparql", "label": "x",
        "body": ("PREFIX : <https://ontology.example.com/enterprise/>\n"
                 "CONSTRUCT { ?x :reaches ?z }\n"
                 "WHERE     { ?x :partOf ?y . ?y :partOf ?z }"),
    }
    result = preview_rule(rule)
    assert result.abox_path  # default discovered
    assert result.derived_count >= 1


# ── API route registers ─────────────────────────────────────────────────


def test_preview_endpoint_registers():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    assert "/api/rules/preview" in rules
