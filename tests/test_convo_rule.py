"""Suggestion #8 — conversational rule construction.

The drawer composes #1 (NL draft) + #6 (test-fire) + #7 (highlight).
The backend pieces are already individually covered; here we focus
on the new contract that the drawer relies on:

    - draft_rule returns a `class_iris` array containing only the
      vocabulary classes the drafted body actually references.
    - That list survives JSON round-trip through `RuleDraft.to_dict()`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from runtime.insights import draft_rule  # noqa: E402


VOCAB = {
    "base_iri": "https://test.example/c8#",
    "classes": [
        {"qname": ":Site",     "label": "Site"},
        {"qname": ":Asset",    "label": "Asset"},
        {"qname": ":Customer", "label": "Customer"},
    ],
    "properties": [
        {"qname": ":hasIncident", "kind": "object", "label": "has incident"},
        {"qname": ":status",      "kind": "data",   "label": "status"},
    ],
}


class _FakeAdapter:
    def __init__(self, response: str):
        self.response = response
        self.last_payload = None

    def complete(self, payload):
        self.last_payload = payload
        return self.response


def test_class_iris_is_subset_of_grounded_with_only_classes():
    body = (
        ":S a sh:NodeShape ; sh:targetClass :Site ;\n"
        "   sh:rule [ a sh:TripleRule ; sh:subject sh:this ;\n"
        "             sh:predicate :hasIncident ; sh:object true ] .\n"
    )
    draft = draft_rule(nl="x", kind="shacl", vocabulary=VOCAB,
                       provider="ollama", adapter=_FakeAdapter(body))
    assert ":Site" in draft.class_iris
    # Only classes — :hasIncident is a property, must NOT be in class_iris.
    assert ":hasIncident" not in draft.class_iris


def test_class_iris_excludes_unknown_iris():
    body = (":S a sh:NodeShape ; sh:targetClass :NotAClass ; "
            "sh:rule [ a sh:TripleRule ] .")
    draft = draft_rule(nl="x", kind="shacl", vocabulary=VOCAB,
                       provider="ollama", adapter=_FakeAdapter(body))
    assert ":NotAClass" not in draft.class_iris
    assert ":NotAClass" in draft.unknown_iris


def test_multiple_class_references_all_listed():
    body = (
        "PREFIX : <https://test.example/c8#>\n"
        "CONSTRUCT { ?s :hasIncident ?c }\n"
        "WHERE { ?s a :Site . ?c a :Customer . ?a a :Asset . ?s :hosts ?a }"
    )
    draft = draft_rule(nl="x", kind="sparql", vocabulary=VOCAB,
                       provider="ollama", adapter=_FakeAdapter(body))
    assert set(draft.class_iris) >= {":Site", ":Customer", ":Asset"}


def test_class_iris_round_trips_via_to_dict():
    body = ":S a sh:NodeShape ; sh:targetClass :Site ; sh:rule [ a sh:TripleRule ] ."
    draft = draft_rule(nl="x", kind="shacl", vocabulary=VOCAB,
                       provider="ollama", adapter=_FakeAdapter(body))
    payload = draft.to_dict()
    assert "class_iris" in payload
    assert payload["class_iris"] == draft.class_iris


def test_empty_vocabulary_yields_empty_class_iris():
    body = ":S a sh:NodeShape ; sh:targetClass :Site ."
    draft = draft_rule(nl="x", kind="shacl",
                       vocabulary={"classes": [], "properties": []},
                       provider="ollama", adapter=_FakeAdapter(body))
    assert draft.class_iris == []
