"""T1.1 — LLM-assisted proposal naming.

Covers:
- Provider abstraction picks based on env var; missing key → None
  (no-op rather than crash).
- name_proposal is pure: same row + same provider → same output.
- All four kinds (LOG_EVENT / ENTITY / RELATIONSHIP / CAUSAL_EDGE)
  produce parseable names from the Mock provider.
- rename_pending_proposals is idempotent: re-running doesn't re-LLM
  rows that are already 'llm', and never touches 'human' rows.
- The v3 migration is idempotent and adds the name_source column.
- Engineer mark_human_edited is sticky against force=True reruns.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from db.migrations.v3_proposal_namer import migrate as v3_migrate    # noqa: E402
from wizard.proposal_namer import (                                  # noqa: E402
    AnthropicProvider, LLMProvider, MockProvider, OpenAIProvider,
    get_provider, mark_human_edited, name_proposal,
    rename_pending_proposals, _parse_completion,
)


# ── Migration ─────────────────────────────────────────────────────────


def _make_conn():
    c = sqlite3.connect(":memory:")
    with open(ROOT / "db" / "schema.sql") as f:
        c.executescript(f.read())
    return c


def _insert_proposal(conn, *, pid, kind="LOG_EVENT", title="x",
                     sample="sample line", status="PENDING"):
    conn.execute(
        "INSERT INTO ontology_evolution_proposals "
        "(proposal_id, proposal_type, title, candidate_turtle, "
        " evidence_sparql, detection_strategy, evidence_sample, status) "
        "VALUES (?, ?, ?, ':x a owl:Class .', 'ASK {}', "
        " 'LOG_TEMPLATE_CLUSTERING', ?, ?)",
        (pid, kind, title, sample, status),
    )
    conn.commit()


def test_migration_adds_name_source_and_timestamp_columns():
    conn = _make_conn()
    v3_migrate(conn)
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(ontology_evolution_proposals)"
    )}
    assert "name_source" in cols
    assert "name_generated_at" in cols


def test_migration_is_idempotent():
    conn = _make_conn()
    first = v3_migrate(conn)
    second = v3_migrate(conn)
    assert first["columns_added"]            # both columns the first time
    assert second["columns_added"] == []     # nothing the second time


# ── Provider selection ───────────────────────────────────────────────


def test_get_provider_defaults_to_none():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROPOSAL_NAMER_PROVIDER", None)
        assert get_provider() is None


def test_get_provider_picks_mock_when_env_set():
    with patch.dict(os.environ, {"PROPOSAL_NAMER_PROVIDER": "mock"}):
        p = get_provider()
        assert isinstance(p, MockProvider)


def test_get_provider_returns_none_when_anthropic_key_missing():
    with patch.dict(os.environ, {"PROPOSAL_NAMER_PROVIDER": "anthropic"}, clear=False):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # Missing key shouldn't crash — just degrade to no-op.
        assert get_provider() is None


def test_get_provider_picks_anthropic_when_key_present():
    with patch.dict(os.environ, {
        "PROPOSAL_NAMER_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "fake-key-not-used",
    }):
        p = get_provider()
        assert isinstance(p, AnthropicProvider)
        assert p.api_key == "fake-key-not-used"


# ── name_proposal core ───────────────────────────────────────────────


def test_name_proposal_returns_auto_when_no_provider():
    row = {"kind": "LOG_EVENT", "title": "Event template #42", "evidence_sample": "x"}
    result = name_proposal(row, provider=None)
    assert result["source"] == "auto"
    assert result["name"] == "Event template #42"


def test_name_proposal_returns_llm_with_mock():
    row = {
        "kind": "LOG_EVENT",
        "title": "Event template #1: UserLoggedIn from <*>",
        "evidence_sample": "UserLoggedIn from host-1",
    }
    result = name_proposal(row, provider=MockProvider())
    assert result["source"] == "llm"
    assert result["name"].startswith(":")
    assert "UserLoggedIn" in result["name"]
    assert result["description"]


def test_name_proposal_is_deterministic_with_mock():
    row = {
        "kind": "LOG_EVENT",
        "title": "Event template #1: PaymentFailed for <*>",
        "evidence_sample": "PaymentFailed for tx-99",
    }
    p = MockProvider()
    r1 = name_proposal(row, provider=p)
    r2 = name_proposal(row, provider=p)
    assert r1 == r2


def test_name_proposal_handles_provider_exception():
    """A provider that throws shouldn't crash the namer — degrade to
    auto so the pipeline never blocks on a flaky LLM call."""
    class FlakyProvider:
        name = "flaky"
        def complete(self, *a, **kw):
            raise RuntimeError("boom")
    row = {"kind": "LOG_EVENT", "title": "x", "evidence_sample": "y"}
    result = name_proposal(row, provider=FlakyProvider())
    assert result["source"] == "auto"


def test_name_proposal_each_kind_returns_parseable_name():
    p = MockProvider()
    for kind in ("LOG_EVENT", "LOG_ENTITY", "LOG_RELATIONSHIP", "LOG_CAUSAL_EDGE"):
        row = {"kind": kind, "title": f"{kind} candidate: AuthFail",
               "evidence_sample": "AuthFail occurred"}
        result = name_proposal(row, provider=p)
        assert result["source"] in ("llm", "auto")
        # If LLM succeeded, name must be a valid IRI-ish qname.
        if result["source"] == "llm":
            assert result["name"].startswith(":")


# ── Completion parsing ───────────────────────────────────────────────


def test_parse_completion_extracts_name_and_desc():
    raw = "NAME: :UserLoggedIn\nDESC: A successful authentication."
    parsed = _parse_completion(raw)
    assert parsed["name"] == ":UserLoggedIn"
    assert parsed["description"] == "A successful authentication."


def test_parse_completion_tolerates_preamble():
    raw = "Here you go!\n\nNAME: :MyEvent\nDESC: My description."
    parsed = _parse_completion(raw)
    assert parsed["name"] == ":MyEvent"
    assert parsed["description"] == "My description."


def test_parse_completion_adds_colon_prefix_if_missing():
    raw = "NAME: UnprefixedName\nDESC: ok."
    parsed = _parse_completion(raw)
    assert parsed["name"] == ":UnprefixedName"


def test_parse_completion_returns_empty_on_bad_input():
    assert _parse_completion("")["name"] == ""
    assert _parse_completion("just chatty text")["name"] == ""


# ── Bulk rename + idempotency ────────────────────────────────────────


def test_rename_no_op_when_no_provider():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p1", title="Event template #1: Foo")
    out = rename_pending_proposals(conn, provider=None)
    assert out["renamed"] == 0
    # name_source stayed at default 'auto'
    src = conn.execute("SELECT name_source FROM ontology_evolution_proposals"
                       " WHERE proposal_id='p1'").fetchone()[0]
    assert src == "auto"


def test_rename_marks_rows_as_llm():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p1",
                     title="Event template #1: PaymentReceived for <*>",
                     sample="PaymentReceived for tx-1")
    out = rename_pending_proposals(conn, provider=MockProvider())
    assert out["renamed"] == 1
    title, src = conn.execute(
        "SELECT title, name_source FROM ontology_evolution_proposals "
        "WHERE proposal_id='p1'"
    ).fetchone()
    assert src == "llm"
    assert ":" in title          # has the qname prefix
    assert "Payment" in title    # captured the semantic stem


def test_rename_is_idempotent_skips_llm_rows():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p1",
                     title="Event template #1: Foo for <*>",
                     sample="Foo for x")
    # First pass renames.
    rename_pending_proposals(conn, provider=MockProvider())
    title_after_first = conn.execute(
        "SELECT title FROM ontology_evolution_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    # Second pass should be a no-op (no rows with name_source='auto' left).
    out2 = rename_pending_proposals(conn, provider=MockProvider())
    assert out2["renamed"] == 0
    title_after_second = conn.execute(
        "SELECT title FROM ontology_evolution_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert title_after_first == title_after_second


def test_rename_with_force_reruns_llm_rows_but_never_human():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p_auto", title="Event template #1: AuthEvent for <*>",
                     sample="AuthEvent sample")
    _insert_proposal(conn, pid="p_human", title="Engineer custom title")
    # Mark p_human as human-edited.
    mark_human_edited(conn, "p_human")

    rename_pending_proposals(conn, provider=MockProvider())
    rename_pending_proposals(conn, provider=MockProvider(), force=True)

    human_title, human_src = conn.execute(
        "SELECT title, name_source FROM ontology_evolution_proposals "
        "WHERE proposal_id='p_human'"
    ).fetchone()
    assert human_src == "human"
    assert human_title == "Engineer custom title"


def test_rename_skips_approved_and_rejected_rows():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p_appr", title="Event template #1: X", status="APPROVED")
    _insert_proposal(conn, pid="p_rej",  title="Event template #2: Y", status="REJECTED")
    _insert_proposal(conn, pid="p_pend", title="Event template #3: ZebraSession",
                     sample="ZebraSession")
    out = rename_pending_proposals(conn, provider=MockProvider())
    # Only the pending row gets renamed; the others retain their auto name.
    assert out["renamed"] == 1


def test_rename_records_timestamp():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p1", title="Event template #1: Quux", sample="Quux line")
    rename_pending_proposals(conn, provider=MockProvider())
    ts = conn.execute(
        "SELECT name_generated_at FROM ontology_evolution_proposals "
        "WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert ts is not None
    assert ts.startswith("20")          # ISO year prefix


def test_rename_returns_stats_dict():
    conn = _make_conn(); v3_migrate(conn)
    _insert_proposal(conn, pid="p1", title="Event template #1: Alpha", sample="Alpha")
    out = rename_pending_proposals(conn, provider=MockProvider())
    assert set(out) >= {"renamed", "skipped", "errors", "provider", "duration_s"}
    assert out["provider"] == "mock"
    assert out["duration_s"] >= 0.0
