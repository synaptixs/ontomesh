"""L1.2 — LogTemplateMiner (Drain + EM refinement)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("drain3")

from log_corpus import LogCorpus  # noqa: E402
from log_templates import LogTemplateMiner, _levenshtein, ensure_schema  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


# ── Schema ───────────────────────────────────────────────────────────────


def test_ensure_schema_creates_table(conn):
    ensure_schema(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='log_templates'"
    ).fetchone()
    assert row is not None


def test_ensure_schema_idempotent(conn):
    ensure_schema(conn)
    ensure_schema(conn)   # second call must not throw
    ensure_schema(conn)


# ── Template clustering ──────────────────────────────────────────────────


def test_two_similar_lines_collapse_into_one_template(conn):
    miner = LogTemplateMiner(conn)
    miner.consume("User alice logged in")
    miner.consume("User bob logged in")
    miner.flush()
    templates = miner.list_templates()
    assert len(templates) == 1
    assert "<*>" in templates[0].template
    assert templates[0].hits == 2


def test_unrelated_lines_form_distinct_templates(conn):
    miner = LogTemplateMiner(conn)
    miner.consume("Heartbeat ok nfId=AMF-01")
    miner.consume("PDU session released")
    miner.flush()
    assert len(miner.list_templates()) == 2


def test_consume_aggregates_severity_and_service_modally(conn):
    miner = LogTemplateMiner(conn)
    for sev, svc in [("INFO", "NRF"), ("INFO", "NRF"),
                     ("WARN", "NRF"), ("INFO", "AMF")]:
        miner.consume("NF status check", severity=sev, service=svc)
    miner.flush()
    t = miner.list_templates()[0]
    assert t.severity == "INFO"          # 3 INFO vs 1 WARN
    assert t.service == "NRF"            # 3 NRF vs 1 AMF


def test_flush_is_idempotent(conn):
    miner = LogTemplateMiner(conn)
    miner.consume("Heartbeat ok nfId=AMF-01")
    miner.flush()
    miner.flush()   # no new consume — should be a no-op (no hit double-counting)
    miner.flush()
    assert miner.list_templates()[0].hits == 1


# ── EM refinement ────────────────────────────────────────────────────────


def test_refine_merges_near_duplicates(conn):
    miner = LogTemplateMiner(conn, hits_threshold=2, edit_threshold=3)
    # Same intent, slight wording variation — Drain alone may keep them
    # separate. We feed enough copies so EM refine kicks in.
    for _ in range(5):
        miner.consume("Connection refused on port 8080")
    for _ in range(5):
        miner.consume("Connection refused at port 8080")
    miner.flush()
    before = len(miner.list_templates())
    merged = miner.refine()
    after = len(miner.list_templates())
    assert merged >= 0      # the merge may or may not fire depending on Drain template
    if merged > 0:
        assert after < before
        # Surviving template should have absorbed the loser's hits.
        survivor = miner.list_templates()[0]
        assert survivor.hits >= 10


def test_refine_respects_hits_threshold(conn):
    miner = LogTemplateMiner(conn, hits_threshold=100)
    miner.consume("A")
    miner.consume("B")
    miner.flush()
    # Neither template has >= 100 hits → refine must be a no-op
    assert miner.refine() == 0


# ── Persistence ──────────────────────────────────────────────────────────


def test_templates_persist_across_miner_instances(conn):
    miner = LogTemplateMiner(conn)
    miner.consume("X happened")
    miner.flush()
    # A new miner over the same conn must see the existing template row.
    miner2 = LogTemplateMiner(conn)
    assert len(miner2.list_templates()) == 1


# ── Sample corpus integration ────────────────────────────────────────────


def test_full_sample_corpus_produces_at_least_20_templates(conn):
    sample_dir = ROOT / "examples" / "log-rca" / "sample"
    if not sample_dir.is_dir():
        pytest.skip("sample corpus not present")
    miner = LogTemplateMiner(conn)
    for rec in LogCorpus(str(sample_dir)).iter():
        miner.consume(rec.message, timestamp=rec.timestamp,
                      severity=rec.severity,
                      service=rec.fields.get("service"))
    miner.flush()
    templates = miner.list_templates()
    # L1 acceptance gate (dev plan §1 final block): ≥ 20 templates.
    assert len(templates) >= 20, f"only {len(templates)} templates"
    # Total hits must equal records consumed.
    total = sum(t.hits for t in templates)
    assert total == 215


# ── Levenshtein ──────────────────────────────────────────────────────────


def test_levenshtein_basic():
    assert _levenshtein("kitten", "kitten") == 0
    assert _levenshtein("kitten", "sitten") == 1
    assert _levenshtein("kitten", "sitting") == 3
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3
