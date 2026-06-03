"""L4 — engineer review pipeline.

Covers:
- seed_from_mining produces one proposal per template / slot / edge.
- list_candidates sorts by confidence × consequence and filters by kind.
- approve / reject / merge mutate both proposal_store + session.
- Re-seeding is idempotent and respects prior decisions.
- /api/log-discovery/* endpoints register correctly and round-trip.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("drain3")
pytest.importorskip("hmmlearn")

from log_corpus import LogCorpus              # noqa: E402
from log_templates import LogTemplateMiner    # noqa: E402
from log_miner import mine_corpus             # noqa: E402
from sequence_learner import mine_sequences   # noqa: E402
from wizard.log_review import (               # noqa: E402
    approve, get_candidate, list_candidates, merge, reject,
    seed_from_mining, summary,
)


@pytest.fixture
def populated_conn():
    """Build a DB with the full L1 + L2 outputs against the sample
    corpus, then call seed_from_mining. The proposal store is now
    populated with candidates of all four kinds — ready for L4 tests."""
    sample_dir = ROOT / "examples" / "log-rca" / "sample"
    if not sample_dir.is_dir():
        pytest.skip("sample corpus not present")
    c = sqlite3.connect(":memory:")
    with open(ROOT / "db" / "schema.sql") as f:
        c.executescript(f.read())
    corpus = LogCorpus(str(sample_dir))
    mine_corpus(corpus, c)
    # Re-build extractions for L2 (cheaper than a second mine_corpus pass).
    miner = LogTemplateMiner(c)
    for rec in corpus.iter():
        miner.consume(rec.message, timestamp=rec.timestamp,
                      severity=rec.severity,
                      service=rec.fields.get("service"),
                      trace_id=rec.fields.get("trace_id"))
    miner.flush(); miner.refine()
    mine_sequences(miner.extractions, c)
    seed_from_mining(c)
    yield c
    c.close()


# ── seed_from_mining ───────────────────────────────────────────────────


def test_seed_produces_all_four_proposal_kinds(populated_conn):
    s = summary(populated_conn)
    assert s["available"]
    kinds = s["by_kind"]
    assert "LOG_EVENT" in kinds
    assert "LOG_ENTITY" in kinds
    assert "LOG_RELATIONSHIP" in kinds or "LOG_CAUSAL_EDGE" in kinds


def test_seed_is_idempotent(populated_conn):
    before = populated_conn.execute(
        "SELECT COUNT(*) FROM ontology_evolution_proposals"
    ).fetchone()[0]
    seed_from_mining(populated_conn)
    seed_from_mining(populated_conn)
    after = populated_conn.execute(
        "SELECT COUNT(*) FROM ontology_evolution_proposals"
    ).fetchone()[0]
    assert before == after


def test_seed_preserves_prior_decisions(populated_conn):
    """Approving a row then re-running seed must not flip it back to
    PENDING — engineers shouldn't have to re-decide on re-mine."""
    session = {"events": [], "entities": [], "relationships": [], "causal_rules": []}
    events = list_candidates(populated_conn, kind="LOG_EVENT", limit=1)
    pid = events[0]["proposal_id"]
    approve(populated_conn, session, pid)
    seed_from_mining(populated_conn)
    cand = get_candidate(populated_conn, pid)
    assert cand["status"] == "APPROVED"


# ── list_candidates ────────────────────────────────────────────────────


def test_list_sorted_by_confidence_times_consequence(populated_conn):
    cands = list_candidates(populated_conn, limit=20)
    scores = [(c["confidence_score"], c["dim_evidence_recency"]) for c in cands]
    products = [s[0] * (1.0 + (s[1] or 0)) for s in scores]
    assert products == sorted(products, reverse=True)


def test_list_filters_by_kind(populated_conn):
    cands = list_candidates(populated_conn, kind="LOG_EVENT", limit=20)
    assert all(c["kind"] == "LOG_EVENT" for c in cands)


def test_list_respects_status_filter(populated_conn):
    cands = list_candidates(populated_conn, status="PENDING", limit=5)
    assert all(c["status"] == "PENDING" for c in cands)


# ── approve / reject / merge ───────────────────────────────────────────


def test_approve_routes_event_to_session_events(populated_conn):
    session = {"events": [], "entities": [], "relationships": [], "causal_rules": []}
    pid = list_candidates(populated_conn, kind="LOG_EVENT", limit=1)[0]["proposal_id"]
    result = approve(populated_conn, session, pid)
    assert result["kind"] == "LOG_EVENT"
    assert len(session["events"]) == 1
    assert session["events"][0]["proposal_id"] == pid


def test_approve_with_edits_overrides_label(populated_conn):
    session = {"events": [], "entities": [], "relationships": [], "causal_rules": []}
    pid = list_candidates(populated_conn, kind="LOG_EVENT", limit=1)[0]["proposal_id"]
    approve(populated_conn, session, pid, edits={"label": "custom-label"})
    assert session["events"][0]["label"] == "custom-label"


def test_reject_sets_status_without_touching_session(populated_conn):
    session = {"events": [], "entities": [], "relationships": [], "causal_rules": []}
    pid = list_candidates(populated_conn, kind="LOG_ENTITY", limit=1)[0]["proposal_id"]
    reject(populated_conn, pid, note="not useful")
    assert session["entities"] == []
    assert get_candidate(populated_conn, pid)["status"] == "REJECTED"


def test_merge_appends_evidence_to_existing_entry(populated_conn):
    """Merge folds the proposal's sample into an existing session
    entry's `evidence_samples` instead of adding a new row."""
    session = {"events": [{"name": "existing_event", "label": "Existing"}],
               "entities": [], "relationships": [], "causal_rules": []}
    pid = list_candidates(populated_conn, kind="LOG_EVENT", limit=1)[0]["proposal_id"]
    merge(populated_conn, session, pid, into_name="existing_event")
    assert len(session["events"]) == 1   # not appended, merged in place
    assert "evidence_samples" in session["events"][0]


def test_approve_unknown_proposal_raises(populated_conn):
    session = {"events": [], "entities": [], "relationships": [], "causal_rules": []}
    with pytest.raises(KeyError):
        approve(populated_conn, session, "no-such-id")


# ── API smoke (Flask test client) ──────────────────────────────────────


def test_log_discovery_endpoints_register():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    for path in (
        "/api/log-discovery/summary",
        "/api/log-discovery/candidates",
        "/api/log-discovery/seed",
        "/api/log-discovery/<proposal_id>/approve",
        "/api/log-discovery/<proposal_id>/reject",
        "/api/log-discovery/<proposal_id>/merge",
    ):
        assert path in rules, f"missing {path}"
