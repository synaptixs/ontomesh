"""End-to-end smoke test for runtime/drift/ (feature/monitordrift).

Exercises P2 → P5 with synthetic data. Self-contained — does not require
the toolkit pipeline to have run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

# rdflib + drift_monitor must be importable; fail clearly if not.
pytest.importorskip("drift_monitor")
pytest.importorskip("rdflib")

from runtime.drift import (  # noqa: E402
    DriftEnricher,
    OntologyDriftMonitor,
    OWLPropagator,
    SHACLGate,
    iri_to_entity_key,
)


NS = "https://test.example/retail#"


@pytest.fixture
def tmp_ontology(tmp_path: Path) -> Path:
    """Tiny OWL graph with two sibling classes and four individuals.

        Order ─┐
                ├─subClassOf─ Transaction
        Invoice┘

        Order/1, Order/2, Invoice/1, Invoice/2 are NamedIndividuals.
    """
    ttl = f"""\
@prefix : <{NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Transaction a owl:Class .
:Order      a owl:Class ; rdfs:subClassOf :Transaction .
:Invoice    a owl:Class ; rdfs:subClassOf :Transaction .

<{NS}Order/1>   a :Order, owl:NamedIndividual .
<{NS}Order/2>   a :Order, owl:NamedIndividual .
<{NS}Invoice/1> a :Invoice, owl:NamedIndividual .
<{NS}Invoice/2> a :Invoice, owl:NamedIndividual .
"""
    p = tmp_path / "demo.ttl"
    p.write_text(ttl)
    return p


@pytest.fixture
def baseline_features() -> dict[str, pd.DataFrame]:
    # PSIMonitor wants ≥ n_bins=10 samples per feature.
    df = pd.DataFrame({
        "amount":   [10.0, 20.0, 15.0, 12.0, 18.0,
                     11.0, 19.0, 14.0, 13.0, 17.0,
                     16.0, 21.0],
        "category": ["A", "B", "A", "B", "A",
                     "B", "A", "B", "A", "B",
                     "A", "B"],
    })
    return {
        "Order::1":   df.copy(),
        "Order::2":   df.copy(),
        "Invoice::1": df.copy(),
        "Invoice::2": df.copy(),
    }


# ── P2 ────────────────────────────────────────────────────────────────────
def test_iri_to_entity_key_retail_form():
    assert iri_to_entity_key(f"{NS}Customer/42", NS) == "Customer::42"


def test_iri_to_entity_key_underscore_form():
    assert iri_to_entity_key("https://e.org/x#AMF_RegionA_N11",
                             "https://e.org/x#") == "AMF::RegionA::N11"


def test_monitor_discovers_individuals(tmp_ontology):
    mon = OntologyDriftMonitor(ontology_path=tmp_ontology, namespace=NS)
    keys = mon.discover_individuals()
    assert set(keys) == {"Order::1", "Order::2", "Invoice::1", "Invoice::2"}


def test_monitor_register_all(tmp_ontology, baseline_features):
    mon = OntologyDriftMonitor(ontology_path=tmp_ontology, namespace=NS)
    registered = mon.register_all(
        baseline_features=baseline_features,
        numeric_features=["amount"],
        categorical_features=["category"],
    )
    assert sorted(registered) == ["Invoice::1", "Invoice::2", "Order::1", "Order::2"]


def test_monitor_run_appends_to_buffer(tmp_ontology, baseline_features):
    mon = OntologyDriftMonitor(ontology_path=tmp_ontology, namespace=NS)
    mon.register_all(baseline_features=baseline_features,
                     numeric_features=["amount"],
                     categorical_features=["category"])
    # Heavily-shifted production data → expect drift
    prod = pd.DataFrame({
        "amount":   [200.0, 300.0, 250.0, 220.0, 280.0,
                     210.0, 290.0, 260.0, 230.0, 270.0,
                     240.0, 295.0],
        "category": ["C"] * 12,
    })
    alerts = mon.run("Order::1", prod_df=prod, window_id="W1")
    assert isinstance(alerts, list)
    # Some metrics should fire on this much shift
    assert mon.recent_alerts(n=10) == alerts[-10:]


# ── P3 ────────────────────────────────────────────────────────────────────
def test_shacl_gate_noop_when_shapes_missing(tmp_path):
    gate = SHACLGate(shapes_path=tmp_path / "missing.ttl", namespace=NS)
    assert not gate.is_active()
    df = pd.DataFrame({"x": [1, 2, 3]})
    out = gate.validate(df, "Order::1")
    pd.testing.assert_frame_equal(out, df)


def test_shacl_gate_passes_well_formed_input(tmp_path):
    """A minimal NodeShape that allows any property."""
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text(f"""\
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix ns:  <{NS}> .
ns:OrderShape a sh:NodeShape ; sh:targetClass ns:Order ; sh:closed false .
""")
    gate = SHACLGate(shapes_path=shapes, namespace=NS)
    assert gate.is_active()
    df = pd.DataFrame({"amount": [1.0, 2.0]})
    out = gate.validate(df, "Order::1")
    pd.testing.assert_frame_equal(out, df)


# ── P4 ────────────────────────────────────────────────────────────────────
def test_enricher_round_trip(tmp_path):
    obs_db = tmp_path / "obs.jsonl"
    enr = DriftEnricher(
        context_path=tmp_path / "absent.json",  # triggers fallback context
        obs_db_path=obs_db,
        entity_namespace=NS,
    )
    raw = {
        "entity_key": "Order::1",
        "psi_score":  0.42,
        "drift_level": "warning",
    }
    rec = enr.enrich_and_store(raw, baseline_id="2024W01", window_id="W1")
    assert rec["@id"].endswith("Order_1")
    assert rec["@type"] == f"{NS}Order"
    assert rec["drift:psiScore"] == 0.42
    assert rec["drift:driftLevel"] == "warning"
    assert "prov:atTime" in rec
    # File written and parseable as JSONL
    line = obs_db.read_text().strip().splitlines()[-1]
    assert json.loads(line)["@id"] == rec["@id"]


# ── P5 ────────────────────────────────────────────────────────────────────
def test_propagator_finds_siblings(tmp_ontology):
    prop = OWLPropagator(ontology_path=tmp_ontology, namespace=NS)
    # Order/1 has sibling class Invoice → Invoice::1 is a dependent.
    deps = prop.dependents("Order::1")
    assert "Invoice::1" in deps


def test_propagator_records_escalations(tmp_ontology):
    prop = OWLPropagator(ontology_path=tmp_ontology, namespace=NS)

    class FakeAlert:
        entity_key  = "Order::1"
        severity    = "warning"
        metric_type = "psi"
        message     = "PSI 0.42 > 0.10"
        timestamp   = "2026-04-30T12:00:00Z"

    deps = prop.propagate(FakeAlert())
    assert "Invoice::1" in deps
    esc = prop.escalations_for("Invoice::1")
    assert esc and esc[0]["from_entity"] == "Order::1"


def test_propagator_handles_dict_alert(tmp_ontology):
    prop = OWLPropagator(ontology_path=tmp_ontology, namespace=NS)
    deps = prop.propagate({"entity_key": "Order::2", "severity": "critical"})
    assert "Invoice::2" in deps


def test_alert_to_jsonld_helper():
    """The static helper used by RuntimeClient must accept dataclass + dict."""
    from runtime.client import RuntimeClient
    node = RuntimeClient._alert_to_jsonld(
        {"entity_key": "Order::1", "severity": "critical",
         "metric_type": "psi", "message": "shifted", "timestamp": "T"})
    assert node["@type"] == "drift:DriftAlert"
    assert node["drift:entityKey"] == "Order::1"
    assert node["drift:severity"] == "critical"
