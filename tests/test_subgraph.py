"""Subgraph materialization + minimal live-SPARQL."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.reasoning_search import Subgraph, Triple, build_subgraph, sparql


def _graph():
    rows = [{"id": 1, "name": "Acme"}, {"id": 2, "name": "Beta"}]
    neighbors = [{"subject_key": "1", "from_col": "customer_id", "ref_table": "customer",
                  "ref_key": "7", "row": {"id": 7, "sla_tier": "Platinum"}}]
    inferred = [{"fact": ["vip", "1"], "rule": "vip", "derived_from": []}]
    return build_subgraph(rows, primary_class="Order", fk_neighbors=neighbors, inferred=inferred)


def test_build_subgraph_emits_typed_triples():
    g = _graph()
    trips = {(t.s, t.p, t.o, t.o_is_iri) for t in g.triples}
    assert ("Order/1", "rdf:type", "Order", True) in trips           # type
    assert ("Order/1", "name", "Acme", False) in trips               # literal attr
    assert ("Order/1", "customer_id", "customer/7", True) in trips    # FK edge -> IRI
    assert ("customer/7", "sla_tier", "Platinum", False) in trips     # neighbour attr
    assert ("Order/1", "rdf:type", "vip", True) in trips             # inferred unary -> type


def test_subgraph_turtle_and_view():
    g = _graph()
    ttl = g.to_turtle()
    assert "<urn:ontoforge:Order/1>" in ttl                   # full angle-bracket IRI
    assert 'rdf:type' in ttl and '"Acme"' in ttl
    view = g.to_view()
    ids = {n["id"] for n in view["nodes"]}
    assert "Order/1" in ids and "customer/7" in ids
    assert any(e["label"] == "customer_id" for e in view["edges"])


def test_sparql_select_basic_graph_pattern():
    g = _graph()
    res = sparql(g, "SELECT ?s ?n WHERE { ?s rdf:type Order . ?s name ?n }")
    assert set(res["vars"]) == {"?s", "?n"}
    pairs = {(r["?s"], r["?n"]) for r in res["rows"]}
    assert pairs == {("Order/1", "Acme"), ("Order/2", "Beta")}


def test_sparql_join_across_fk_edge():
    g = _graph()
    # Order -> customer -> sla_tier, filtered to the Platinum literal.
    res = sparql(g, 'SELECT ?o WHERE { ?o customer_id ?c . ?c sla_tier "Platinum" }')
    assert [r["?o"] for r in res["rows"]] == ["Order/1"]


def test_sparql_a_shorthand_and_select_star():
    g = _graph()
    res = sparql(g, "SELECT * WHERE { ?s a Order }")
    assert {r["?s"] for r in res["rows"]} == {"Order/1", "Order/2"}


def test_sparql_rejects_non_select():
    import pytest
    with pytest.raises(ValueError):
        sparql(_graph(), "ASK { ?s ?p ?o }")
