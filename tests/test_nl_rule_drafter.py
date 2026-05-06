"""Suggestion #1 — NL → rule drafting via the LLM adapter.

We never touch the network: a `_FakeAdapter` returns canned responses
so we can assert prompt shape, fence stripping, IRI grounding stats,
and validation pass-through without provider credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from runtime.insights import draft_rule  # noqa: E402


# ── Test fixtures ────────────────────────────────────────────────────────


VOCAB = {
    "base_iri": "https://test.example/nl#",
    "classes": [
        {"qname": ":Site",  "label": "Site"},
        {"qname": ":Asset", "label": "Asset"},
    ],
    "properties": [
        {"qname": ":hasIncident", "kind": "object",   "label": "has incident"},
        {"qname": ":status",      "kind": "data",     "label": "status"},
    ],
}


class _FakeAdapter:
    def __init__(self, response: str):
        self.response = response
        self.last_payload = None

    def complete(self, payload):
        self.last_payload = payload
        return self.response


# ── Prompt shape ─────────────────────────────────────────────────────────


def test_prompt_includes_vocabulary_and_user_description():
    adapter = _FakeAdapter("# any-body\n:Site a owl:Class .")
    draft_rule(nl="When a Site is in OUTAGE, mark it impacted.",
               kind="shacl", vocabulary=VOCAB,
               provider="ollama", adapter=adapter)
    user = adapter.last_payload["user"]
    # Vocabulary must reach the prompt verbatim so the model can use it.
    assert ":Site" in user
    assert ":hasIncident" in user
    assert "When a Site is in OUTAGE" in user
    # System prompt forces "no prose / no fences" instructions.
    assert "Output" in adapter.last_payload["system"]


def test_prompt_kind_changes_system_role():
    adapter = _FakeAdapter("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    draft_rule(nl="ignore", kind="sparql", vocabulary=VOCAB,
               provider="ollama", adapter=adapter)
    assert "SPARQL" in adapter.last_payload["system"]


# ── Markdown fence stripping ─────────────────────────────────────────────


def test_markdown_fences_are_stripped():
    body = (":S a sh:NodeShape ; sh:targetClass :Site ;\n"
            "   sh:rule [ a sh:TripleRule ; sh:subject sh:this ;\n"
            "             sh:predicate :hasIncident ; sh:object true ] .")
    fenced = "```turtle\n" + body + "\n```"
    adapter = _FakeAdapter(fenced)
    draft = draft_rule(nl="x", kind="shacl", vocabulary=VOCAB,
                       provider="ollama", adapter=adapter)
    assert draft.body.strip() == body
    assert "```" not in draft.body


def test_response_without_fences_passes_through():
    adapter = _FakeAdapter(":partOf a owl:ObjectProperty .")
    draft = draft_rule(nl="x", kind="owl", vocabulary=VOCAB,
                       provider="ollama", adapter=adapter)
    assert ":partOf a owl:ObjectProperty" in draft.body


# ── Validation pass-through ──────────────────────────────────────────────


def test_invalid_draft_returns_valid_false_with_errors():
    adapter = _FakeAdapter("SELECT ?s WHERE { ?s ?p ?o }")  # not CONSTRUCT
    draft = draft_rule(nl="x", kind="sparql", vocabulary=VOCAB,
                       provider="ollama", adapter=adapter)
    assert draft.valid is False
    assert any("CONSTRUCT" in e for e in draft.validation_errors)


def test_valid_draft_returns_valid_true():
    adapter = _FakeAdapter(
        "PREFIX : <https://test.example/nl#>\n"
        "CONSTRUCT { ?s :hasIncident true } WHERE { ?s a :Site }"
    )
    draft = draft_rule(nl="x", kind="sparql", vocabulary=VOCAB,
                       provider="ollama", adapter=adapter)
    assert draft.valid


# ── IRI hallucination / grounding ────────────────────────────────────────


def test_known_iris_classified_as_grounded():
    body = (":S a sh:NodeShape ; sh:targetClass :Site ;\n"
            "   sh:rule [ a sh:TripleRule ; sh:subject sh:this ;\n"
            "             sh:predicate :hasIncident ; sh:object true ] .")
    draft = draft_rule(nl="x", kind="shacl", vocabulary=VOCAB,
                       provider="ollama", adapter=_FakeAdapter(body))
    assert ":Site" in draft.grounded_iris
    assert ":hasIncident" in draft.grounded_iris


def test_unknown_user_iris_flagged_but_standard_vocab_ignored():
    body = (":S a sh:NodeShape ; sh:targetClass :HallucinatedClass ;\n"
            "   sh:rule [ a sh:TripleRule ; sh:subject sh:this ;\n"
            "             sh:predicate :madeUpProp ; sh:object true ] .")
    draft = draft_rule(nl="x", kind="shacl", vocabulary=VOCAB,
                       provider="ollama", adapter=_FakeAdapter(body))
    assert ":HallucinatedClass" in draft.unknown_iris
    assert ":madeUpProp" in draft.unknown_iris
    # Standard SHACL vocabulary must NOT be reported as hallucinated.
    assert not any(t.startswith(("sh:", "owl:", "rdf:", "rdfs:", "xsd:"))
                   for t in draft.unknown_iris)


# ── Misc edge cases ──────────────────────────────────────────────────────


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="kind"):
        draft_rule(nl="x", kind="swrl", vocabulary=VOCAB,
                   provider="ollama", adapter=_FakeAdapter(""))


def test_route_registers():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    assert "/api/rules/nl" in rules
