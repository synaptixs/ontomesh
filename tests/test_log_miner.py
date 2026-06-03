"""L1.3 + L1.4 + L1.5 + L1.6 — end-to-end miner.

Each block has unit-level coverage plus one integration test against
the bundled sample corpus.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("drain3")

from log_corpus import LogCorpus  # noqa: E402
from log_miner import (  # noqa: E402
    PMI_THRESHOLD_DEFAULT,
    add_temporal_ordering,
    classify_slot,
    compute_pmi_edges,
    ensure_schema,
    mine_corpus,
    persist_edges,
    persist_slot_profiles,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


# ── L1.3 slot typing ────────────────────────────────────────────────────


def test_classify_uuid_slot():
    vals = [
        "550e8400-e29b-41d4-a716-446655440000",
        "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    ]
    p = classify_slot(vals)
    assert p.type == "UUID"


def test_classify_ip_slot():
    vals = ["10.0.0.1", "10.0.0.2", "192.168.1.1"]
    p = classify_slot(vals)
    assert p.type == "IP"


def test_classify_enum_slot_when_distinct_le_eight():
    vals = ["ACTIVE"] * 10 + ["RELEASED"] * 5 + ["PENDING"] * 2
    p = classify_slot(vals)
    assert p.type == "ENUM"
    assert p.distinct_count == 3
    assert "ACTIVE" in p.top_values


def test_classify_numeric_slot():
    vals = ["42", "3.14", "-7", "1e5"]
    p = classify_slot(vals)
    assert p.type == "NUMERIC"


def test_classify_freetext_fallback():
    vals = ["the quick brown fox", "lazy dog jumps", "completely arbitrary"]
    p = classify_slot(vals)
    assert p.type == "FREETEXT"


def test_classify_flags_pii_for_imsi_top_values():
    vals = ["imsi-001010000000001", "imsi-001010000000002",
            "imsi-001010000000003", "imsi-001010000000004"]
    p = classify_slot(vals)
    # 4 distinct values out of 4 samples → FREETEXT (not ENUM by our cap),
    # but PII flag must still fire because the values match the PII regex.
    assert p.pii_risk is True


def test_empty_slot_returns_freetext_with_zero_counts():
    p = classify_slot([])
    assert p.type == "FREETEXT"
    assert p.sample_count == 0


# ── persist_slot_profiles writes rows ───────────────────────────────────


def test_persist_slot_profiles_writes_rows(conn):
    ensure_schema(conn)
    # Insert a template row so the FK lookup finds something.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS log_templates "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, cluster_id INTEGER UNIQUE, "
        " template TEXT, sample_line TEXT, hits INT, first_seen TEXT, "
        " last_seen TEXT, severity TEXT, service TEXT, merged_into INTEGER, "
        " regex TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute("INSERT INTO log_templates (cluster_id, template, sample_line, hits) "
                 "VALUES (?, ?, ?, ?)", (1, "User <*> logged in", "User alice", 2))
    conn.commit()
    extractions = [
        {"cluster_id": 1, "slots": ["alice"], "ts": "", "trace_id": None,
         "service": None, "severity": None, "template": "..."},
        {"cluster_id": 1, "slots": ["bob"],   "ts": "", "trace_id": None,
         "service": None, "severity": None, "template": "..."},
    ]
    profiles = persist_slot_profiles(conn, extractions)
    assert len(profiles) == 1
    row = conn.execute(
        "SELECT type, distinct_count, sample_count FROM log_template_slots"
    ).fetchone()
    # 2 distinct values out of 2 samples → freetext (ENUM requires distinct<sample)
    assert row[1] == 2 and row[2] == 2


# ── L1.4 PMI graph ──────────────────────────────────────────────────────


def test_pmi_edges_from_trace_co_occurrence():
    """Two slot values that always appear in the same trace should be
    one of the top PMI edges."""
    extractions = []
    for i in range(10):
        extractions.append({
            "cluster_id": 1, "slots": ["NF=AMF-01", "STATUS=REG"],
            "ts": f"2026-05-07T09:00:{i:02d}Z", "trace_id": f"t-{i}",
        })
    # Add some noise unrelated to the pair
    for i in range(5):
        extractions.append({
            "cluster_id": 2, "slots": ["OTHER=X"],
            "ts": f"2026-05-07T10:00:{i:02d}Z", "trace_id": f"noise-{i}",
        })
    profiles = [
        # both slot positions classified as ENUM
        type("P", (), {"template_id": 1, "slot_idx": 0, "type": "ENUM"})(),
        type("P", (), {"template_id": 1, "slot_idx": 1, "type": "ENUM"})(),
    ]
    edges = compute_pmi_edges(extractions, profiles, threshold=0.0)
    pair = {"NF=AMF-01", "STATUS=REG"}
    assert any(set([e["src"], e["dst"]]) == pair for e in edges)


def test_pmi_threshold_filters_low_signal_edges():
    extractions = []
    # Random co-occurrences that should yield low PMI
    for i in range(20):
        extractions.append({
            "cluster_id": 1, "slots": [f"x-{i % 5}", f"y-{i % 4}"],
            "ts": f"2026-05-07T09:00:{i:02d}Z", "trace_id": None,
        })
    profiles = []  # not used in compute_pmi_edges anymore
    high = compute_pmi_edges(extractions, profiles, threshold=10.0)
    low  = compute_pmi_edges(extractions, profiles, threshold=0.0)
    # A high threshold must produce strictly fewer (or equal) edges.
    assert len(high) <= len(low)


# ── L1.5 temporal ordering ──────────────────────────────────────────────


def test_temporal_ordering_sets_directed_when_lead_clear():
    # cause always at 09:00:00, effect always at 09:00:10
    extractions = []
    for i in range(8):
        extractions.append({
            "cluster_id": 1, "slots": ["cause"],
            "ts": f"2026-05-07T09:00:0{i % 6}Z", "trace_id": None,
        })
        extractions.append({
            "cluster_id": 2, "slots": ["effect"],
            "ts": f"2026-05-07T09:00:1{i % 6}Z", "trace_id": None,
        })
    edges = [{"src": "cause", "dst": "effect",
              "pmi": 5.0, "cooccurrence_count": 8}]
    out = add_temporal_ordering(extractions, edges, window_s=60,
                                lead_ratio_threshold=0.7)
    assert out[0]["directed"] is True
    assert out[0]["temporal_lead_ratio"] >= 0.7


def test_temporal_ordering_leaves_ambiguous_edges_undirected():
    extractions = []
    for i in range(5):
        # interleaved — neither always first
        extractions.append({"cluster_id": 1, "slots": ["a"],
                            "ts": f"2026-05-07T09:00:0{i}Z", "trace_id": None})
        extractions.append({"cluster_id": 2, "slots": ["b"],
                            "ts": f"2026-05-07T09:00:0{i}Z", "trace_id": None})
    edges = [{"src": "a", "dst": "b", "pmi": 5.0, "cooccurrence_count": 5}]
    out = add_temporal_ordering(extractions, edges, window_s=60,
                                lead_ratio_threshold=0.7)
    assert out[0]["directed"] is False


def test_persist_edges_idempotent(conn):
    ensure_schema(conn)
    edges = [
        {"src": "a", "dst": "b", "pmi": 3.0, "cooccurrence_count": 5,
         "temporal_lead_ratio": 0.8, "directed": True},
    ]
    assert persist_edges(conn, edges) == 1
    assert persist_edges(conn, edges) == 1   # second run overwrites, doesn't duplicate
    rows = conn.execute("SELECT COUNT(*) FROM log_entity_edges").fetchone()
    assert rows[0] == 1


# ── L1.6 CLI smoke ──────────────────────────────────────────────────────


def test_phase_mine_cli_writes_summary(tmp_path):
    """End-to-end CLI: invoke toolkit.py and confirm the headline JSON
    summary lands in <out>/reports/log_mining_summary.json."""
    sample_dir = ROOT / "examples" / "log-rca" / "sample"
    if not sample_dir.is_dir():
        pytest.skip("sample corpus not present")
    db = tmp_path / "mining.db"
    out = tmp_path
    res = subprocess.run(
        [sys.executable, str(ROOT / "toolkit.py"),
         "--phase", "mine",
         "--log-path", str(sample_dir),
         "--db", str(db), "--out", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    summary_path = out / "reports" / "log_mining_summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text())
    assert summary["records_ingested"] == 215
    # L1 acceptance gate from dev plan §1: ≥ 20 templates, ≥ 30 edges.
    assert summary["templates"] >= 20
    assert summary["edges_persisted"] >= 30
    # L1 acceptance gate: runtime under 60 s on the demo corpus.
    assert summary["duration_s"] < 60.0


# ── full sample-corpus integration ──────────────────────────────────────


def test_mine_corpus_against_sample_meets_acceptance_gate(conn):
    sample_dir = ROOT / "examples" / "log-rca" / "sample"
    if not sample_dir.is_dir():
        pytest.skip("sample corpus not present")
    corpus = LogCorpus(str(sample_dir))
    report = mine_corpus(conn=conn, corpus=corpus)
    r = report.as_dict()
    # L1 acceptance gate (dev plan §1 acceptance gate):
    # ≥ 20 templates, ≥ 30 entity edges in < 60 s.
    assert r["records_ingested"] == 215
    assert r["templates"] >= 20
    assert r["edges_persisted"] >= 30
    assert r["duration_s"] < 60.0
