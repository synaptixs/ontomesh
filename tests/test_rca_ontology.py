"""L5 — RCA ontology generation."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# ── L5.1 — Causal taxonomy fragment ─────────────────────────────────────


def test_emit_taxonomy_contains_core_iris():
    from rca_taxonomy import emit_taxonomy
    ttl = emit_taxonomy()
    for needle in (":CausalEvent", ":hasCause", ":triggers",
                   ":precededBy", ":rootCause"):
        assert needle in ttl


def test_emit_taxonomy_is_valid_turtle():
    from rca_taxonomy import emit_taxonomy
    from rdflib import Graph
    # The fragment uses prefixes the ontology_generator emits — supply
    # them here so the parse succeeds standalone.
    prefixes = (
        "@prefix : <https://ontology.example.com/enterprise/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
    )
    Graph().parse(data=prefixes + emit_taxonomy(), format="turtle")


# ── L5.2 — Log-derived classes + time props + severity tiers ────────────


@pytest.fixture
def session_with_log_events():
    return {
        "events": [
            {"name": "heartbeat_timeout", "label": "Heartbeat Timeout",
             "description": "NF missed heartbeat", "severity": "ERROR",
             "source": "log-discovery"},
            {"name": "nf_deregister", "label": "NF Deregister",
             "description": "NRF removed NF", "severity": "INFO",
             "source": "log-discovery"},
        ],
    }


@pytest.fixture
def generated_ttl(session_with_log_events):
    """Generate against the bundled demo DB with a log-discovery
    session and return the resulting Turtle string."""
    from db_introspector import DBIntrospector
    from ontology_generator import generate_ontology
    demo_db = ROOT / "db" / "enterprise.db"
    if not demo_db.is_file():
        pytest.skip("demo enterprise.db not present")
    out = Path(tempfile.mkdtemp())
    intro = DBIntrospector(str(demo_db))
    try:
        generate_ontology(intro, str(out), session=session_with_log_events)
    finally:
        intro.close()
    return (out / "enterprise.ttl").read_text()


def test_log_derived_event_classes_emitted(generated_ttl):
    assert ":HeartbeatTimeout" in generated_ttl
    assert ":NfDeregister" in generated_ttl
    # Both must be rdfs:subClassOf :CausalEvent.
    assert "rdfs:subClassOf :CausalEvent" in generated_ttl


def test_time_interval_data_properties_emitted_once(generated_ttl):
    for prop in (":startedAt", ":endedAt", ":duration"):
        assert prop in generated_ttl


def test_severity_maps_to_sensitivity_tier(generated_ttl):
    # ERROR → Confidential
    block = generated_ttl.split(":HeartbeatTimeout", 1)[1].split(".", 1)[0]
    assert ":sensitivityTier :Confidential" in block
    # INFO → Public
    block = generated_ttl.split(":NfDeregister", 1)[1].split(".", 1)[0]
    assert ":sensitivityTier :Public" in block


def test_generated_ttl_parses_with_rdflib(generated_ttl):
    """Whatever we emit must be valid Turtle. Caught the
    multi-line-string concatenation bug during L5.1."""
    from rdflib import Graph
    Graph().parse(data=generated_ttl, format="turtle")


def test_no_taxonomy_when_session_has_no_log_discovery():
    """Generator must NOT inject the RCA taxonomy when the active
    session has no log-discovery output — keeps the demo path clean."""
    from db_introspector import DBIntrospector
    from ontology_generator import generate_ontology
    demo_db = ROOT / "db" / "enterprise.db"
    if not demo_db.is_file():
        pytest.skip("demo enterprise.db not present")
    out = Path(tempfile.mkdtemp())
    intro = DBIntrospector(str(demo_db))
    try:
        generate_ontology(intro, str(out), session={"events": []})
    finally:
        intro.close()
    ttl = (out / "enterprise.ttl").read_text()
    # No log-discovery events → no taxonomy fragment.
    assert ":CausalEvent" not in ttl
    assert ":hasCause" not in ttl


# ── L5.3 — compile_causal_rule ─────────────────────────────────────────


def test_compile_causal_rule_emits_construct_and_filter():
    from wizard.rules import compile_causal_rule
    edge = {
        "id": "hb-triggers-dereg",
        "cause_class": ":HeartbeatTimeout",
        "effect_class": ":NfDeregister",
        "window_seconds": 30,
    }
    body = compile_causal_rule(edge)
    assert "CONSTRUCT" in body
    assert ":hasCause" in body and ":triggers" in body
    assert ":HeartbeatTimeout" in body and ":NfDeregister" in body
    # Window value recorded as an audit comment (SPARQL itself can't
    # reliably do xsd:dateTime arithmetic in rdflib).
    assert "30 seconds" in body
    # Directional filter must be present so causes precede effects.
    assert "?et > ?ct" in body


def test_compile_causal_rule_falls_back_to_existing_body():
    """When the edge dict carries only a free-form Turtle stub (old
    session schema), the compiler must return it unchanged."""
    from wizard.rules import compile_causal_rule
    raw = {"body": "PREFIX : <x:> CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"}
    assert compile_causal_rule(raw) == raw["body"]


def test_compile_causal_rule_qname_normalisation():
    """Bare local names get prefixed with `:` so the SPARQL is valid
    even when the engineer drops the colon by mistake."""
    from wizard.rules import compile_causal_rule
    body = compile_causal_rule({
        "id": "x", "cause_class": "Foo", "effect_class": "Bar",
    })
    assert ":Foo" in body and ":Bar" in body


def test_export_causal_rules_writes_rq_file(tmp_path):
    from wizard.rules import export_causal_rules
    edges = [{
        "id": "rule-1", "cause_class": ":A", "effect_class": ":B",
        "window_seconds": 60,
    }]
    out = export_causal_rules(edges, str(tmp_path))
    assert out["written"]
    assert (tmp_path / "sparql_rules" / "causal-rule-1.rq").is_file()


def test_export_causal_rules_skips_empty_dicts(tmp_path):
    from wizard.rules import export_causal_rules
    out = export_causal_rules([{}, {"id": "broken"}], str(tmp_path))
    # Both entries lacked cause/effect → returned empty body → skipped.
    assert not out["written"]
    assert len(out["skipped"]) >= 1


# ── L5 — end-to-end Phase B materialisation of :hasCause ───────────────


def test_phase_b_materialises_hascause_from_compiled_rule(tmp_path):
    """Acceptance gate (dev plan §5.5): after running phases
    mine → review → 2 → reason, materialised.ttl contains a derived
    :hasCause triple with a prov:wasDerivedFrom block naming the rule.

    Here we skip mine/review and seed the workspace with a tiny ABox
    that has one cause and one effect instance, then run the
    materialiser directly with the compiled causal rule. The check
    is the same: a derived :hasCause must appear with lineage."""
    from wizard.rules import compile_causal_rule
    from materializer import materialize

    ontology = tmp_path / "enterprise.ttl"
    ontology.write_text("""\
@prefix : <https://ontology.example.com/enterprise/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:CausalEvent a owl:Class .
:HeartbeatTimeout a owl:Class ; rdfs:subClassOf :CausalEvent .
:NfDeregister     a owl:Class ; rdfs:subClassOf :CausalEvent .
:hasCause a owl:ObjectProperty ; rdfs:domain :CausalEvent ; rdfs:range :CausalEvent .
:triggers a owl:ObjectProperty ; owl:inverseOf :hasCause .
:startedAt a owl:DatatypeProperty ; rdfs:range xsd:dateTime .

:hb_001 a :HeartbeatTimeout ; :startedAt "2026-05-07T09:00:00Z"^^xsd:dateTime .
:dr_001 a :NfDeregister     ; :startedAt "2026-05-07T09:00:10Z"^^xsd:dateTime .
""")
    rules_dir = tmp_path / "sparql_rules"
    rules_dir.mkdir()
    (rules_dir / "hb-triggers-dereg.rq").write_text(compile_causal_rule({
        "id": "hb-triggers-dereg",
        "cause_class": ":HeartbeatTimeout",
        "effect_class": ":NfDeregister",
        "window_seconds": 30,
    }))

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = materialize(str(ontology), str(out_dir),
                         sparql_rules_dir=str(rules_dir))
    sparql = next(e for e in result.engines if e.name == "sparql")
    assert sparql.status == "PASS"
    assert sparql.derived_triples >= 2     # :hasCause + :triggers

    # Lineage check (Phase D) — the derived triple has a prov:wasDerivedFrom.
    from materializer import explain_triple
    deriv = explain_triple(
        result.lineage_path,
        subject="https://ontology.example.com/enterprise/dr_001",
        predicate="https://ontology.example.com/enterprise/hasCause",
        obj="https://ontology.example.com/enterprise/hb_001",
    )
    assert deriv
    assert "hb-triggers-dereg" in (deriv[0]["rule"] or "")
