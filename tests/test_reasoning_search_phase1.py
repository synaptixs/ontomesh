"""Phase-1 engine behaviour: tier gating, graceful states, SDK, CLI, eval."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ScriptedAdapter:
    model_id = "fake"

    def __init__(self, plan_json: str, answer: str = "ok"):
        self._plan, self._answer = plan_json, answer

    def complete(self, payload: dict) -> str:
        return self._answer if "synth" in payload.get("payload_id", "") else self._plan


@pytest.fixture()
def fx(tmp_path):
    db = tmp_path / "demo.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT, ssn TEXT, sla_tier TEXT);"
        "INSERT INTO customer (name, ssn, sla_tier) VALUES "
        "('Acme','111','Platinum'),('Beta','222','Gold');"
    )
    con.commit(); con.close()

    flavors = tmp_path / "flavors"; flavors.mkdir()
    (flavors / "f.json").write_text(
        '{"name":"f","owl_classes":["Customer","Secret"],'
        '"context_terms":{"Customer":"x","name":"x","ssn":"x","slaTier":"x","Secret":"x"},'
        '"db_tables":["customer","secret"]}'
    )
    mapping = tmp_path / "map.csv"
    mapping.write_text(
        "ontology_class,ontology_property,property_type,logical_element,physical_table,"
        "physical_column,xsd_type,required,sensitivity_tier,semantic_notes,cq_coverage\n"
        "Customer,(class),OWL Class,customer,customer,(table),,Y,Internal,,\n"
        "Customer,name,Data Property,customer.name,customer,name,xsd:string,N,Internal,,\n"
        "Customer,ssn,Data Property,customer.ssn,customer,ssn,xsd:string,N,Restricted,,\n"
        "Customer,slaTier,Data Property,customer.sla_tier,customer,sla_tier,xsd:string,N,Internal,,\n"
        "Secret,(class),OWL Class,secret,secret,(table),,Y,Restricted,,\n"
    )
    return {"db": str(db), "flavors": str(flavors), "mapping": str(mapping)}


def _search(fx, plan_json, **kw):
    from runtime.reasoning_search import search
    return search("q", flavor="f", db_path=fx["db"],
                  adapter=ScriptedAdapter(plan_json), flavors_dir=fx["flavors"],
                  mapping_path=fx["mapping"], **kw)


def test_tier_excludes_restricted_column(fx):
    ans = _search(fx, '{"intent":"i","classes":["Customer"],"filters":[]}')  # max_tier=Internal
    assert ans.status == "ok"
    assert "name" in ans.executed_query and "sla_tier" in ans.executed_query
    assert "ssn" not in ans.executed_query        # Restricted column withheld


def test_tier_blocks_restricted_class(fx):
    ans = _search(fx, '{"intent":"i","classes":["Secret"],"filters":[]}')
    assert ans.status == "blocked"
    assert ans.confidence == 0.0
    assert "Secret" in ans.answer


def test_ungrounded_unknown_class_is_graceful(fx):
    ans = _search(fx, '{"intent":"i","classes":["Nope"],"filters":[]}')
    assert ans.status == "ungrounded"
    assert "couldn't ground" in ans.answer.lower()


def test_empty_results_state(fx):
    ans = _search(fx, '{"intent":"i","classes":["Customer"],'
                      '"filters":[{"prop":"name","op":"=","value":"ZZZ"}]}')
    assert ans.status == "empty"
    assert ans.results == [] and ans.confidence < 0.5


def test_filter_on_restricted_column_is_ungrounded(fx):
    # planner allows it (ssn is in vocab) but the compiler refuses → graceful
    ans = _search(fx, '{"intent":"i","classes":["Customer"],'
                      '"filters":[{"prop":"ssn","op":"=","value":"111"}]}')
    assert ans.status == "ungrounded"


def test_sdk_delegation(monkeypatch):
    """RuntimeClient.search reuses the client's adapter + db_path."""
    import runtime.reasoning_search as rs
    from runtime.client import RuntimeClient

    captured = {}

    def fake_search(question, **kw):
        captured.update(question=question, **kw)
        return "SENTINEL"

    monkeypatch.setattr(rs, "search", fake_search)

    client = RuntimeClient.__new__(RuntimeClient)   # skip heavy __init__
    client._db_path = "/tmp/x.db"
    client._adapter_instance = object()
    out = client.search("hello", "network-ops", max_tier="Internal")

    assert out == "SENTINEL"
    assert captured["db_path"] == "/tmp/x.db"
    assert captured["adapter"] is client._adapter_instance
    assert captured["flavor"] == "network-ops"


def test_cli_prints_answer(monkeypatch, capsys):
    import runtime.reasoning_search as rs
    from runtime.reasoning_search import ReasonedAnswer
    from runtime.reasoning_search.cli import run

    def fake_search(question, **kw):
        return ReasonedAnswer(answer="Two Platinum customers.", executed_query="SELECT 1",
                              confidence=0.85, provider="fake", status="ok")

    monkeypatch.setattr(rs, "search", fake_search)
    code = run(["q", "--flavor", "f", "--db", "x"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Two Platinum customers." in out and "confidence: 85%" in out


def test_eval_harness_summarizes():
    from runtime.reasoning_search.eval import evaluate, summarize
    from runtime.reasoning_search import ReasonedAnswer

    def run(q):
        return ReasonedAnswer(answer="a", citations=[], confidence=0.8, status="ok")

    summary = summarize(evaluate(["q1", "q2"], run=run))
    assert summary["n"] == 2 and summary["exec_rate"] == 1.0 and summary["grounded_rate"] == 1.0
