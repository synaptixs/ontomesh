"""Full-pipeline integration test for reasoning search (offline, deterministic).

Exercises the *real* engine wiring — planner → query_compiler → read-only
execution → synthesis — against a temp SQLite DB with fixture flavor + mapping,
using a fake adapter (no live LLM). This is the CI-green counterpart to the
live-LLM north-star test (which stays xfail until Ollama/OpenAI is available).
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ScriptedAdapter:
    """Returns a plan for planner calls and an answer for synthesis calls."""

    model_id = "fake"

    def __init__(self, plan_json: str, answer: str):
        self._plan, self._answer = plan_json, answer

    def complete(self, payload: dict) -> str:
        if "synth" in payload.get("payload_id", ""):
            return self._answer
        return self._plan


@pytest.fixture()
def fixtures(tmp_path):
    # DB
    db = tmp_path / "demo.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT, sla_tier TEXT);"
        "INSERT INTO customer (name, sla_tier) VALUES "
        "('Acme','Platinum'),('Beta','Gold'),('Gamma','Platinum');"
    )
    con.commit()
    con.close()

    # Flavor
    flavors = tmp_path / "flavors"
    flavors.mkdir()
    (flavors / "network-ops.json").write_text(
        '{"name":"network-ops","owl_classes":["Customer"],'
        '"context_terms":{"Customer":"ex:Customer","name":"ex:name","slaTier":"ex:slaTier"},'
        '"db_tables":["customer"]}'
    )

    # Mapping
    mapping = tmp_path / "map.csv"
    mapping.write_text(
        "ontology_class,ontology_property,property_type,logical_element,physical_table,"
        "physical_column,xsd_type,required,sensitivity_tier,semantic_notes,cq_coverage\n"
        "Customer,(class),OWL Class,customer,customer,(table),,Y,Internal,,\n"
        "Customer,name,Data Property,customer.name,customer,name,xsd:string,N,Internal,,\n"
        "Customer,slaTier,Data Property,customer.sla_tier,customer,sla_tier,xsd:string,N,Internal,,\n"
    )
    return {"db": str(db), "flavors": str(flavors), "mapping": str(mapping)}


def test_pipeline_returns_cited_answer(fixtures):
    from runtime.reasoning_search import ReasonedAnswer, search

    adapter = ScriptedAdapter(
        plan_json='{"intent":"list at-risk customers","classes":["Customer"],"filters":[]}',
        answer="Acme, Beta and Gamma are customers; Acme and Gamma are Platinum.",
    )
    ans = search(
        "Which customers do we have and their SLA tier?",
        flavor="network-ops",
        db_path=fixtures["db"],
        adapter=adapter,
        flavors_dir=fixtures["flavors"],
        mapping_path=fixtures["mapping"],
    )
    assert isinstance(ans, ReasonedAnswer)
    assert ans.answer.strip()
    assert ans.executed_query.startswith("SELECT") and "FROM customer" in ans.executed_query
    assert len(ans.results) == 3
    assert len(ans.citations) >= 1
    assert ans.plan["classes"] == ["Customer"]
    assert any(t["stage"] == "execute" for t in ans.trace)
    assert ans.confidence > 0.5


def test_pipeline_applies_parameterized_filter(fixtures):
    from runtime.reasoning_search import search

    adapter = ScriptedAdapter(
        plan_json='{"intent":"platinum only","classes":["Customer"],'
                  '"filters":[{"prop":"slaTier","op":"=","value":"Platinum"}]}',
        answer="Two Platinum customers: Acme and Gamma.",
    )
    ans = search(
        "Which customers are Platinum?",
        flavor="network-ops",
        db_path=fixtures["db"],
        adapter=adapter,
        flavors_dir=fixtures["flavors"],
        mapping_path=fixtures["mapping"],
    )
    assert "WHERE sla_tier = ?" in ans.executed_query
    assert len(ans.results) == 2  # Acme, Gamma
    assert {r["sla_tier"] for r in ans.results} == {"Platinum"}


def test_safe_execute_refuses_writes(fixtures):
    from runtime.reasoning_search.safety import SafetyError, safe_execute

    with pytest.raises(SafetyError):
        safe_execute(fixtures["db"], "DELETE FROM customer", [])
