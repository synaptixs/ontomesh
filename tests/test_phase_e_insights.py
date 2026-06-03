"""Phase E — LLM Insights wiring.

Verifies:
    - provider_status reads runtime/llm_providers.json and reports each
      provider as configured/unconfigured based on env vars + SDK
      importability (probed but never called).
    - validate_iris correctly partitions response tokens against the
      ontology vocabulary (hallucination filter).
    - build_grounding stays small even for big ontologies.
    - Insights.ask end-to-end with an injected fake adapter — no
      network, no provider SDK required.
    - The materialisation toggle results in a residency warning when
      sending to a us-cloud provider.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from runtime.insights import (  # noqa: E402
    Insights, build_grounding, provider_status, validate_iris,
)


# ── provider_status ──────────────────────────────────────────────────────


def test_provider_status_lists_known_providers():
    statuses = provider_status()
    names = {p.name for p in statuses}
    # The catalogue must declare these MVP + extended providers.
    assert {"openai", "oci", "anthropic", "ollama"}.issubset(names)
    # Every entry has a residency hint and a model default.
    for p in statuses:
        assert p.residency
        assert p.model


def test_provider_status_marks_missing_keys_unconfigured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    statuses = {p.name: p for p in provider_status()}
    assert statuses["openai"].configured is False
    assert "OPENAI_API_KEY" in (statuses["openai"].reason or "")


# ── IRI validation ───────────────────────────────────────────────────────


def test_validate_iris_partitions_correctly():
    answer = ("The class :Asset has properties :hasOwner and "
              ":hallucinatedProp. See <https://known.example/A>.")
    known = {":Asset", ":hasOwner", "<https://known.example/A>"}
    grounded, unknown = validate_iris(answer, known)
    assert ":Asset" in grounded
    assert ":hasOwner" in grounded
    assert ":hallucinatedProp" in unknown


# ── grounding payload ────────────────────────────────────────────────────


def test_build_grounding_truncates_large_files(tmp_path):
    big = tmp_path / "ont.ttl"
    big.write_text("@prefix : <ex:> .\n" + "x" * 10_000)
    g = build_grounding(str(big), max_class_chars=500)
    assert g["asserted_chars"] == len(big.read_text())
    assert len(g["asserted_summary"]) <= 500


def test_build_grounding_includes_materialised_when_present(tmp_path):
    ont = tmp_path / "ont.ttl"
    ont.write_text("@prefix : <ex:> .\n:A a :Class .\n")
    mat = tmp_path / "mat.ttl"
    mat.write_text(":A :p :B .\n:B :p :C .\n")
    g = build_grounding(str(ont), str(mat))
    assert "materialised_summary" in g
    assert ":A" in g["asserted_iris"]


# ── Insights.ask with a fake adapter ─────────────────────────────────────


class _FakeAdapter:
    """Dummy adapter that echoes the prompt back so we can inspect the
    payload structure without touching the network."""
    def __init__(self, response: str = "The :Asset class is documented."):
        self.response = response
        self.last_payload = None

    def complete(self, payload):
        self.last_payload = payload
        return self.response


@pytest.fixture
def workspace(tmp_path):
    ont = tmp_path / "ent.ttl"
    ont.write_text("""\
@prefix : <https://test.example/e#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
:Asset a owl:Class .
:Owner a owl:Class .
""")
    mat = tmp_path / "mat.ttl"
    mat.write_text(":Asset :hasOwner :Owner .\n")
    return {"ontology": str(ont), "materialised": str(mat)}


def test_ask_with_fake_adapter_returns_answer(workspace):
    adapter = _FakeAdapter("The :Asset class is supported by :Owner.")
    insights = Insights(workspace["ontology"], workspace["materialised"])
    result = insights.ask("What is Asset?", provider="ollama",
                          adapter=adapter, include_materialised=False)
    assert result.answer == "The :Asset class is supported by :Owner."
    assert result.provider == "ollama"
    # Payload sent to adapter must include the asserted ontology.
    assert "Asset" in adapter.last_payload["user"]
    # Materialised must NOT appear in the prompt unless toggled on.
    assert "Materialised triples" not in adapter.last_payload["user"]


def test_ask_with_materialised_toggle_includes_triples(workspace):
    adapter = _FakeAdapter()
    insights = Insights(workspace["ontology"], workspace["materialised"])
    insights.ask("Q?", provider="ollama", adapter=adapter,
                 include_materialised=True)
    assert "Materialised triples" in adapter.last_payload["user"]


def test_ask_flags_unknown_iris(workspace):
    adapter = _FakeAdapter("The :HallucinatedClass is great.")
    insights = Insights(workspace["ontology"])
    result = insights.ask("Q?", provider="ollama", adapter=adapter)
    assert ":HallucinatedClass" in result.unknown_iris
    assert any("hallucinated" in w.lower() for w in result.warnings)


def test_ask_warns_when_sending_materialised_to_us_cloud(workspace):
    adapter = _FakeAdapter()
    insights = Insights(workspace["ontology"], workspace["materialised"])
    result = insights.ask("Q?", provider="openai", adapter=adapter,
                          include_materialised=True)
    assert any("residency" in w.lower() for w in result.warnings)
    assert any("us-cloud" in w for w in result.warnings)


def test_ask_unknown_provider_raises(workspace):
    adapter = _FakeAdapter()
    insights = Insights(workspace["ontology"])
    with pytest.raises(Exception):
        insights.ask("Q?", provider="nonexistent", adapter=None)
