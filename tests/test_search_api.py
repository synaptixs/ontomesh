"""Phase-3: /api/search route + /ask console (flag-gated). Offline, stubbed engine."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "wizard", ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytest.importorskip("flask")


@pytest.fixture()
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def enabled(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "ONTOFORGE_SEARCH", True)


def _fake_answer():
    from runtime.reasoning_search import Citation, ReasonedAnswer
    return ReasonedAnswer(
        answer="Acme is at risk.",
        results=[{"id": 1, "name": "Acme"}],
        citations=[Citation(iri="Customer/1", source_table="customer"),
                   Citation(iri="prov:Derived/impacts/1", inferred=True)],
        inferred=[{"fact": ["impacts", "1"], "rule": "impacts", "derived_from": []}],
        confidence=0.85, executed_query="SELECT name FROM customer LIMIT 200",
        trace=[{"stage": "execute", "rows": 1}, {"stage": "reason", "derived": 1}],
        provider="ollama", status="ok",
    )


# ── flag gating ──────────────────────────────────────────────────────────────
def test_search_disabled_by_default(client):
    assert client.post("/api/search", json={"question": "x", "flavor": "f"}).status_code == 404
    assert client.get("/ask").status_code == 404


# ── validation ───────────────────────────────────────────────────────────────
def test_search_requires_question_and_flavor(client, enabled):
    rv = client.post("/api/search", json={"question": ""})
    assert rv.status_code == 400
    assert "required" in rv.get_json()["error"]


# ── success contract ─────────────────────────────────────────────────────────
def test_search_returns_reasoned_answer(client, enabled, monkeypatch):
    import runtime.reasoning_search as rs
    monkeypatch.setattr(rs, "search", lambda question, **kw: _fake_answer())

    rv = client.post("/api/search", json={"question": "who is at risk?", "flavor": "network-ops"})
    assert rv.status_code == 200
    d = rv.get_json()
    assert d["answer"] == "Acme is at risk."
    assert d["status"] == "ok" and d["confidence"] == 0.85
    assert d["executed_query"].startswith("SELECT")
    assert any(c["inferred"] for c in d["citations"])
    assert d["inferred"][0]["rule"] == "impacts"


def test_search_handles_engine_error(client, enabled, monkeypatch):
    import runtime.reasoning_search as rs

    def boom(question, **kw):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(rs, "search", boom)
    rv = client.post("/api/search", json={"question": "q", "flavor": "f"})
    assert rv.status_code == 500 and "db unreachable" in rv.get_json()["error"]


# ── console ──────────────────────────────────────────────────────────────────
def test_ask_console_served_when_enabled(client, enabled):
    rv = client.get("/ask")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "ask-form" in body and "Reason" in body and 'id="answer"' in body


# ── SSE streaming ────────────────────────────────────────────────────────────
def test_search_stream_emits_stages_then_answer(client, enabled, monkeypatch):
    import runtime.reasoning_search as rs

    def streaming_search(question, **kw):
        cb = kw.get("on_event")
        if cb:
            cb({"stage": "plan", "classes": ["Customer"]})
            cb({"stage": "execute", "rows": 1})
        return _fake_answer()

    monkeypatch.setattr(rs, "search", streaming_search)
    rv = client.post("/api/search/stream", json={"question": "q", "flavor": "f"})
    assert rv.status_code == 200
    assert rv.mimetype == "text/event-stream"
    body = rv.get_data(as_text=True)
    assert "event: stage" in body and '"stage": "plan"' in body
    assert "event: answer" in body and "Acme is at risk." in body


def test_stream_disabled_by_default(client):
    assert client.post("/api/search/stream", json={"question": "x", "flavor": "f"}).status_code == 404


# ── memory adapter ───────────────────────────────────────────────────────────
def test_build_memory_adapter_shape():
    """The AgentMemory adapter exposes recall()->list (not the raw @graph dict)."""
    import app as app_module
    mem = app_module._build_memory()
    if mem is None:               # AgentMemory unavailable in this env — fine
        return
    assert hasattr(mem, "recall") and hasattr(mem, "remember")
    assert isinstance(mem.recall("anything", flavor="f"), list)
    assert mem.remember({"question": "x"}) is None


# ── in-wizard link ───────────────────────────────────────────────────────────
def test_wizard_hides_ask_link_by_default(client):
    assert 'href="/ask"' not in client.get("/wizard").get_data(as_text=True)


def test_wizard_shows_ask_link_when_enabled(client, enabled):
    assert 'href="/ask"' in client.get("/wizard").get_data(as_text=True)


def test_wizard_embeds_ask_step_when_enabled(client, enabled):
    body = client.get("/wizard").get_data(as_text=True)
    assert 'data-step="ask"' in body and 'id="step-ask"' in body and 'src="/ask"' in body


def test_wizard_no_ask_step_by_default(client):
    assert 'id="step-ask"' not in client.get("/wizard").get_data(as_text=True)


# ── caching ──────────────────────────────────────────────────────────────────
def test_search_caches_identical_requests(client, enabled, monkeypatch):
    import app as app_module
    app_module._SEARCH_CACHE.clear()
    monkeypatch.setattr(app_module, "SEARCH_CACHE_TTL", 60.0)

    calls = {"n": 0}

    def counting_search(question, **kw):
        calls["n"] += 1
        return _fake_answer()

    import runtime.reasoning_search as rs
    monkeypatch.setattr(rs, "search", counting_search)

    payload = {"question": "who is at risk?", "flavor": "network-ops"}
    r1 = client.post("/api/search", json=payload)
    r2 = client.post("/api/search", json=payload)            # served from cache
    r3 = client.post("/api/search", json={"question": "different?", "flavor": "network-ops"})

    assert r1.status_code == r2.status_code == 200
    assert calls["n"] == 2                                    # 1st + 3rd ran; 2nd cached
    assert r2.get_json().get("cached") is True
    assert "cached" not in r1.get_json()
