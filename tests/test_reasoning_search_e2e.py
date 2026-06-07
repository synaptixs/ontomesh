"""North-star acceptance test for ontology-grounded reasoning search.

Written **failing-first** (TDD): marked ``xfail`` until the Phase-0 engine lands,
at which point the ``search()`` stop raising and the assertions below become the
bar to clear — then remove the xfail mark.

Target: the telecom "blast-radius" example returns a cited, query-backed answer
on the demo database (see REASONING_SEARCH_DESIGN.local.md §4A / §11).
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEMO_DB = os.path.join(ROOT, "db", "demo.db")

TELECOM_Q = "Which customers are at risk from the degraded core router crt-07, and why?"


@pytest.mark.xfail(
    reason="reasoning_search engine not implemented until Phase 0 (see §11)",
    strict=False,
)
def test_reasoning_search_telecom_blast_radius():
    """End-to-end: NL question -> cited, query-backed ReasonedAnswer."""
    from runtime.reasoning_search import ReasonedAnswer, search

    ans = search(
        TELECOM_Q,
        flavor="network-ops",
        db_path=DEMO_DB,
        providers="ollama",
    )

    assert isinstance(ans, ReasonedAnswer)
    assert ans.answer.strip(), "expected a non-empty synthesized answer"
    assert len(ans.citations) >= 1, "every answer must cite at least one source"
    assert ans.executed_query.strip(), "the executed (read-only) query must be surfaced"
    assert 0.0 <= ans.confidence <= 1.0, "confidence must be normalised to 0..1"


def test_contract_is_importable_and_typed():
    """The response contract exists and is usable now (guards the scaffold).

    This passes today — it locks the public shape (`ReasonedAnswer` / `Citation`)
    that the SDK, CLI, API and console all depend on.
    """
    from runtime.reasoning_search import Citation, ReasonedAnswer

    ans = ReasonedAnswer(answer="ok")
    ans.citations.append(Citation(iri="tmf:Customer/acme", label="Acme", source_table="customer"))
    assert ans.answer == "ok"
    assert ans.citations[0].iri == "tmf:Customer/acme"
    assert ans.confidence == 0.0 and ans.executed_query == ""
