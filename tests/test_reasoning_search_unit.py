"""Unit tests for reasoning-search modules (offline, fake adapter)."""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FakeAdapter:
    """Returns a fixed string for any payload (duck-types BaseAdapter)."""

    model_id = "fake"

    def __init__(self, response: str):
        self._r = response

    def complete(self, payload: dict) -> str:  # noqa: D401
        return self._r


# ── structured_output ───────────────────────────────────────────────────────
def test_structured_output_parses_fenced_json():
    from runtime.reasoning_search.structured_output import complete_json

    obj = complete_json(FakeAdapter('```json\n{"a": 1, "b": 2}\n```'),
                        system="s", user="u", required_keys=("a", "b"))
    assert obj == {"a": 1, "b": 2}


def test_structured_output_missing_key_raises():
    from runtime.reasoning_search.structured_output import StructuredOutputError, complete_json

    with pytest.raises(StructuredOutputError):
        complete_json(FakeAdapter('{"a": 1}'), system="s", user="u",
                      required_keys=("a", "b"), max_retries=0)


# ── planner ─────────────────────────────────────────────────────────────────
VOCAB = {"Customer", "name", "slaTier"}


def test_planner_valid_plan():
    from runtime.reasoning_search.planner import plan

    p = plan("list customers", vocab=VOCAB,
             adapter=FakeAdapter('{"intent":"list","classes":["Customer"],"filters":[]}'))
    assert p.primary_class == "Customer"
    assert p.intent == "list"


def test_planner_rejects_unknown_class():
    from runtime.reasoning_search.planner import PlanValidationError, plan

    with pytest.raises(PlanValidationError):
        plan("x", vocab=VOCAB,
             adapter=FakeAdapter('{"intent":"i","classes":["Hospital"]}'))


def test_planner_rejects_unknown_filter_prop():
    from runtime.reasoning_search.planner import PlanValidationError, plan

    with pytest.raises(PlanValidationError):
        plan("x", vocab=VOCAB, adapter=FakeAdapter(
            '{"intent":"i","classes":["Customer"],'
            '"filters":[{"prop":"ssn","op":"=","value":"1"}]}'))


# ── query_compiler ──────────────────────────────────────────────────────────
def _mapping():
    from runtime.reasoning_search._loaders import Mapping

    m = Mapping()
    m.class_table["Customer"] = "customer"
    m.prop_col[("Customer", "name")] = ("customer", "name")
    m.prop_col[("Customer", "slaTier")] = ("customer", "sla_tier")
    return m


def test_compiler_basic_select():
    from runtime.reasoning_search.planner import Plan
    from runtime.reasoning_search.query_compiler import compile_sql

    sql, params = compile_sql(Plan(intent="list", classes=["Customer"]),
                              mapping=_mapping(), allowed_tables={"customer"})
    assert sql.startswith("SELECT") and "FROM customer" in sql and "LIMIT" in sql
    assert params == []


def test_compiler_filter_is_parameterized():
    from runtime.reasoning_search.planner import Filter, Plan
    from runtime.reasoning_search.query_compiler import compile_sql

    sql, params = compile_sql(
        Plan(intent="f", classes=["Customer"],
             filters=[Filter(prop="slaTier", op="=", value="Platinum")]),
        mapping=_mapping(), allowed_tables={"customer"})
    assert "WHERE sla_tier = ?" in sql and params == ["Platinum"]


def test_compiler_blocks_non_allowlisted_table():
    from runtime.reasoning_search.planner import Plan
    from runtime.reasoning_search.query_compiler import CompileError, compile_sql

    with pytest.raises(CompileError):
        compile_sql(Plan(intent="x", classes=["Customer"]),
                    mapping=_mapping(), allowed_tables={"orders"})
