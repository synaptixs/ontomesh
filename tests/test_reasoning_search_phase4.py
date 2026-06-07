"""Phase 4: SearchMemory round-trip + auto multi-hop (FK neighbour loading)."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ── SearchMemory write-path ──────────────────────────────────────────────────
def test_search_memory_round_trip(tmp_path):
    from runtime.reasoning_search.memory import SearchMemory

    mem = SearchMemory(str(tmp_path / "m.db"))
    mem.remember({"question": "which customers are platinum?", "flavor": "f",
                  "answer": "Acme and Gamma.", "status": "ok"})
    mem.remember({"question": "list orders", "flavor": "other", "answer": "...", "status": "ok"})

    got = mem.recall("customers platinum", flavor="f")
    assert len(got) == 1 and got[0]["answer"] == "Acme and Gamma."
    # flavor filter excludes the other-flavor turn
    assert mem.recall("orders", flavor="f") == []


class SeqAdapter:
    model_id = "fake"
    def __init__(self, plans, answer="ok"):
        self._plans = list(plans); self._answer = answer; self.plan_calls = 0
    def complete(self, payload):
        if "synth" in payload.get("payload_id", ""):
            return self._answer
        self.plan_calls += 1
        return self._plans[min(self.plan_calls - 1, len(self._plans) - 1)]


@pytest.fixture()
def fk_fx(tmp_path):
    """orders.customer_id -> customer.id; one customer is Platinum."""
    db = tmp_path / "demo.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT, sla_tier TEXT);"
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL,"
        " FOREIGN KEY(customer_id) REFERENCES customer(id));"
        "INSERT INTO customer (name, sla_tier) VALUES ('Acme','Platinum'),('Beta','Gold');"
        "INSERT INTO orders (customer_id, amount) VALUES (1, 99.0),(2, 10.0);"
    )
    con.commit(); con.close()

    flavors = tmp_path / "flavors"; flavors.mkdir()
    (flavors / "f.json").write_text(
        '{"name":"f","owl_classes":["Order"],'
        '"context_terms":{"Order":"x","id":"x","customer_id":"x","amount":"x"},'
        '"db_tables":["orders","customer"]}'
    )
    mapping = tmp_path / "map.csv"
    mapping.write_text(
        "ontology_class,ontology_property,property_type,logical_element,physical_table,"
        "physical_column,xsd_type,required,sensitivity_tier,semantic_notes,cq_coverage\n"
        "Order,(class),OWL Class,orders,orders,(table),,Y,Internal,,\n"
        "Order,id,Data Property,orders.id,orders,id,xsd:integer,N,Internal,,\n"
        "Order,customer_id,Data Property,orders.customer_id,orders,customer_id,xsd:integer,N,Internal,,\n"
        "Order,amount,Data Property,orders.amount,orders,amount,xsd:decimal,N,Internal,,\n"
    )
    return {"db": str(db), "flavors": str(flavors), "mapping": str(mapping)}


def test_auto_relations_enables_cross_table_reasoning(fk_fx):
    """With auto_relations, a rule chains orders -> customer (via FK) to derive vip."""
    from runtime.reasoning_search import search

    adapter = SeqAdapter(['{"intent":"i","classes":["Order"],"filters":[]}'])
    rules = ['vip(?o) :- customer_id(?o,?c), sla_tier(?c,"Platinum")']

    ans = search("orders by vip customers", flavor="f", db_path=fk_fx["db"], adapter=adapter,
                 flavors_dir=fk_fx["flavors"], mapping_path=fk_fx["mapping"],
                 rules=rules, auto_relations=True)

    facts = [tuple(i["fact"]) for i in ans.inferred]
    assert ("vip", "1") in facts          # order 1 (Acme, Platinum) is vip
    assert ("vip", "2") not in facts      # order 2 (Beta, Gold) is not
    assert any(t["stage"] == "relations" for t in ans.trace)


def test_auto_relations_off_means_no_cross_table(fk_fx):
    from runtime.reasoning_search import search

    adapter = SeqAdapter(['{"intent":"i","classes":["Order"],"filters":[]}'])
    rules = ['vip(?o) :- customer_id(?o,?c), sla_tier(?c,"Platinum")']
    ans = search("orders", flavor="f", db_path=fk_fx["db"], adapter=adapter,
                 flavors_dir=fk_fx["flavors"], mapping_path=fk_fx["mapping"],
                 rules=rules, auto_relations=False)
    assert ans.inferred == []             # no neighbour facts -> rule can't fire
