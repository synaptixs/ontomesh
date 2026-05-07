"""Suggestion #2 — NL summary round-trip.

Verifies that:
    - normalise_rule defaults nl_summary to '' so reading a session
      that pre-dates this feature still works.
    - summarise_rule strips fences/quotes and forces a single line.
    - The /api/rules/summarise endpoint persists the result back into
      the wizard session so it survives a reload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from runtime.insights import summarise_rule  # noqa: E402
from wizard.rules import normalise_rule  # noqa: E402


class _FakeAdapter:
    def __init__(self, response: str):
        self.response = response
        self.last_payload = None

    def complete(self, payload):
        self.last_payload = payload
        return self.response


# ── normalise_rule ───────────────────────────────────────────────────────


def test_normalise_defaults_nl_summary_to_empty_string():
    out = normalise_rule({"kind": "sparql", "label": "x",
                          "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"})
    assert out["nl_summary"] == ""


def test_normalise_preserves_existing_nl_summary():
    out = normalise_rule({"kind": "sparql", "label": "x", "nl_summary": "Already known.",
                          "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"})
    assert out["nl_summary"] == "Already known."


# ── summarise_rule ───────────────────────────────────────────────────────


def test_summarise_strips_fences_and_quotes():
    adapter = _FakeAdapter('"```\nFlags impacted sites in outage.\n```"')
    summary = summarise_rule({"kind": "shacl", "label": "x",
                              "body": "@prefix : <ex:> .\n:S a sh:NodeShape ."},
                             provider="ollama", adapter=adapter)
    # Quotes stripped, fences stripped, whitespace collapsed.
    assert "```" not in summary
    assert summary.startswith("Flags") or "Flags impacted" in summary


def test_summarise_collapses_whitespace_to_one_line():
    adapter = _FakeAdapter("Marks   sites\n   in outage   as impacted.")
    summary = summarise_rule({"kind": "shacl", "label": "x",
                              "body": ":S a sh:NodeShape ."},
                             provider="ollama", adapter=adapter)
    assert "\n" not in summary
    assert "  " not in summary  # no double-spaces


def test_summarise_includes_kind_and_body_in_prompt():
    adapter = _FakeAdapter("ok.")
    summarise_rule({"kind": "sparql", "label": "two-hop",
                    "body": "CONSTRUCT { ?x :reaches ?z } WHERE { ?x :partOf ?y }"},
                   provider="ollama", adapter=adapter)
    user = adapter.last_payload["user"]
    assert "sparql" in user
    assert "two-hop" in user
    assert "CONSTRUCT" in user


# ── Endpoint persistence ─────────────────────────────────────────────────


def test_summarise_endpoint_persists_to_session(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))

    # Redirect SESSION_FILE to a tmp path so the test doesn't disturb
    # the user's wizard session.
    import importlib
    app_mod = importlib.import_module("wizard.app")
    session_path = tmp_path / "wizard_session.json"
    monkeypatch.setattr(app_mod, "SESSION_FILE", str(session_path))

    # Seed a rule into the session.
    session_path.write_text(json.dumps({
        "rules": [{
            "id": "demo", "kind": "sparql", "label": "demo",
            "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
            "nl_summary": "",
        }]
    }))

    # Stub summarise_rule so the route doesn't try to load an LLM.
    from runtime import insights as _ins_mod
    monkeypatch.setattr(_ins_mod, "summarise_rule",
                        lambda rule, **kw: "Echoes any triple back.")

    client = app_mod.app.test_client()
    res = client.post("/api/rules/summarise", json={"rule": {
        "id": "demo", "kind": "sparql", "label": "demo",
        "body": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
    }})
    assert res.status_code == 200
    out = res.get_json()
    assert out["nl_summary"] == "Echoes any triple back."

    # Persistence: reload the session and confirm the summary is on the rule.
    saved = json.loads(session_path.read_text())
    assert saved["rules"][0]["nl_summary"] == "Echoes any triple back."


def test_summarise_endpoint_rejects_empty_body():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    client = app_mod.app.test_client()
    res = client.post("/api/rules/summarise", json={"rule": {
        "id": "x", "kind": "sparql", "label": "x", "body": "",
    }})
    assert res.status_code == 400
