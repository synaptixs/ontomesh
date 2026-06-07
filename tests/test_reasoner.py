"""Unit tests for the forward-chaining reasoner (§11 #20)."""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.reasoning_search.reasoner import parse_rule, reason  # noqa: E402


def test_parse_rule():
    r = parse_rule("impacts(?c) :- consumes(?c,?s), hosts(?r,?s), degraded(?r)")
    assert r.head == ("impacts", "?c")
    assert r.body[0] == ("consumes", "?c", "?s")
    assert len(r.body) == 3
    assert r.name == "impacts"


def test_telecom_impact_derivation_with_provenance():
    facts = [
        ("consumes", "acme", "svc1"),
        ("hosts", "crt07", "svc1"),
        ("degraded", "crt07"),
        ("consumes", "beta", "svc2"),   # beta unaffected (svc2 not degraded)
    ]
    rule = parse_rule("impacts(?c) :- consumes(?c,?s), hosts(?r,?s), degraded(?r)")
    res = reason(facts, [rule])

    assert ("impacts", "acme") in res.derived
    assert ("impacts", "beta") not in res.derived          # no spurious inference
    rule_name, support = res.provenance[("impacts", "acme")]
    assert rule_name == "impacts"
    assert ("degraded", "crt07") in support and ("hosts", "crt07", "svc1") in support


def test_multi_hop_transitive_fixpoint():
    facts = [("parent", "a", "b"), ("parent", "b", "c")]
    rules = [
        parse_rule("ancestor(?x,?y) :- parent(?x,?y)"),
        parse_rule("ancestor(?x,?z) :- parent(?x,?y), ancestor(?y,?z)"),
    ]
    res = reason(facts, rules)
    assert ("ancestor", "a", "c") in res.facts             # derived across 2 hops
    assert ("ancestor", "a", "b") in res.derived


def test_clinical_ineligibility_derivation():
    facts = [
        ("enrolledIn", "s1", "study1"),
        ("hasCriterion", "study1", "ec7"),
        ("latestLab", "s1", "labA"),
        ("violates", "labA", "ec7"),
        ("enrolledIn", "s2", "study1"),       # s2 has no violating lab
        ("latestLab", "s2", "labB"),
    ]
    rule = parse_rule(
        "ineligible(?s) :- enrolledIn(?s,?st), hasCriterion(?st,?c), "
        "latestLab(?s,?l), violates(?l,?c)")
    res = reason(facts, [rule])
    assert ("ineligible", "s1") in res.derived
    assert ("ineligible", "s2") not in res.derived


def test_bad_rule_raises():
    with pytest.raises(ValueError):
        parse_rule("not a rule")
