"""Phase-2 engine integration: derived facts (reasoning) + agentic re-plan."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SeqAdapter:
    """Returns plan responses in sequence (per planner call), one answer for synth."""

    model_id = "fake"

    def __init__(self, plans: list[str], answer: str = "ok"):
        self._plans = list(plans)
        self._answer = answer
        self.plan_calls = 0

    def complete(self, payload: dict) -> str:
        if "synth" in payload.get("payload_id", ""):
            return self._answer
        self.plan_calls += 1
        # repeat the last plan if we run out
        return self._plans[min(self.plan_calls - 1, len(self._plans) - 1)]


@pytest.fixture()
def fx(tmp_path):
    db = tmp_path / "demo.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT, sla_tier TEXT);"
        "INSERT INTO customer (name, sla_tier) VALUES ('Acme','Platinum'),('Beta','Gold');"
    )
    con.commit(); con.close()

    flavors = tmp_path / "flavors"; flavors.mkdir()
    (flavors / "f.json").write_text(
        '{"name":"f","owl_classes":["Customer"],'
        '"context_terms":{"Customer":"x","name":"x","slaTier":"x"},'
        '"db_tables":["customer"]}'
    )
    mapping = tmp_path / "map.csv"
    mapping.write_text(
        "ontology_class,ontology_property,property_type,logical_element,physical_table,"
        "physical_column,xsd_type,required,sensitivity_tier,semantic_notes,cq_coverage\n"
        "Customer,(class),OWL Class,customer,customer,(table),,Y,Internal,,\n"
        "Customer,name,Data Property,customer.name,customer,name,xsd:string,N,Internal,,\n"
        "Customer,slaTier,Data Property,customer.sla_tier,customer,sla_tier,xsd:string,N,Internal,,\n"
    )
    return {"db": str(db), "flavors": str(flavors), "mapping": str(mapping)}


def test_engine_derives_inferred_facts(fx):
    """Rules + relationship facts -> derived 'impacts' in ReasonedAnswer.inferred."""
    from runtime.reasoning_search import search

    adapter = SeqAdapter(['{"intent":"i","classes":["Customer"],"filters":[]}'],
                         answer="Acme is impacted.")
    # customer rows have id 1 (Acme) and 2 (Beta). Supply the relationship graph.
    extra = [("consumes", "1", "svc1"), ("hosts", "crt07", "svc1"), ("degraded", "crt07")]
    rules = ["impacts(?c) :- consumes(?c,?s), hosts(?r,?s), degraded(?r)"]

    ans = search("who is impacted?", flavor="f", db_path=fx["db"], adapter=adapter,
                 flavors_dir=fx["flavors"], mapping_path=fx["mapping"],
                 rules=rules, extra_facts=extra)

    assert ans.status == "ok"
    facts = [tuple(i["fact"]) for i in ans.inferred]
    assert ("impacts", "1") in facts                       # Acme (id 1) derived
    assert ("impacts", "2") not in facts                   # Beta not impacted
    # provenance + an inferred citation are attached
    rec = next(i for i in ans.inferred if i["fact"] == ["impacts", "1"])
    assert rec["rule"] == "impacts" and rec["derived_from"]
    assert any(c.inferred and "impacts" in c.iri for c in ans.citations)
    assert any(t["stage"] == "reason" for t in ans.trace)


def test_agentic_replan_on_empty(fx):
    """First plan filters to nothing; engine re-plans and the second plan returns rows."""
    from runtime.reasoning_search import search

    plans = [
        '{"intent":"too narrow","classes":["Customer"],'
        '"filters":[{"prop":"name","op":"=","value":"ZZZ"}]}',   # 0 rows
        '{"intent":"broadened","classes":["Customer"],"filters":[]}',  # rows
    ]
    adapter = SeqAdapter(plans, answer="Two customers.")
    ans = search("list customers", flavor="f", db_path=fx["db"], adapter=adapter,
                 flavors_dir=fx["flavors"], mapping_path=fx["mapping"], max_replans=1)

    assert adapter.plan_calls == 2                          # it re-planned once
    assert ans.status == "ok" and len(ans.results) == 2
    assert any(t["stage"] == "replan" for t in ans.trace)


def test_no_rules_means_no_inferred(fx):
    from runtime.reasoning_search import search

    adapter = SeqAdapter(['{"intent":"i","classes":["Customer"],"filters":[]}'])
    ans = search("list", flavor="f", db_path=fx["db"], adapter=adapter,
                 flavors_dir=fx["flavors"], mapping_path=fx["mapping"])
    assert ans.inferred == []


class FakeMemory:
    def __init__(self, recalls): self._recalls = recalls; self.remembered = []
    def recall(self, question, flavor=None): return self._recalls
    def remember(self, rec): self.remembered.append(rec)


def test_memory_recall_before_and_remember_after(fx):
    """Engine consults memory.recall up front and memory.remember on completion."""
    from runtime.reasoning_search import search

    mem = FakeMemory([{"prior": "earlier question"}])
    adapter = SeqAdapter(['{"intent":"i","classes":["Customer"],"filters":[]}'])
    ans = search("list customers", flavor="f", db_path=fx["db"], adapter=adapter,
                 flavors_dir=fx["flavors"], mapping_path=fx["mapping"], memory=mem)

    assert any(t["stage"] == "recall" and t["count"] == 1 for t in ans.trace)
    assert mem.remembered and mem.remembered[0]["question"] == "list customers"
    assert mem.remembered[0]["status"] == "ok"


def test_on_event_streams_each_stage(fx):
    """on_event fires for every trace entry (drives SSE)."""
    from runtime.reasoning_search import search

    seen = []
    adapter = SeqAdapter(['{"intent":"i","classes":["Customer"],"filters":[]}'])
    search("list", flavor="f", db_path=fx["db"], adapter=adapter,
           flavors_dir=fx["flavors"], mapping_path=fx["mapping"],
           on_event=lambda e: seen.append(e["stage"]))
    assert "plan" in seen and "execute" in seen and "synthesize" in seen
