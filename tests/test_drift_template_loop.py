"""L7 — drift hook for unknown log templates."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("drain3")


def _write_jsonl(path: Path, lines):
    with path.open("w") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def _seed_existing_templates(conn, samples):
    """Lay down a small log_templates table with the given sample
    lines so the drift detector starts from a populated catalogue."""
    from log_templates import ensure_schema
    with open(ROOT / "db" / "schema.sql") as f:
        conn.executescript(f.read())
    ensure_schema(conn)
    for i, sample in enumerate(samples, start=1):
        conn.execute(
            "INSERT INTO log_templates (cluster_id, template, sample_line, hits) "
            "VALUES (?, ?, ?, ?)",
            (i, sample, sample, 5),
        )
    conn.commit()


# ── Tests ───────────────────────────────────────────────────────────────


def test_known_lines_produce_no_drift_proposals(tmp_path):
    from log_corpus import LogCorpus
    from runtime.drift.log_template_drift import detect_template_drift

    conn = sqlite3.connect(":memory:")
    _seed_existing_templates(conn, [
        "User alice logged in from 10.0.0.1",
        "PDUSession established sessionId=pdu-0001 sessionStatus=ACTIVE",
    ])
    # Corpus only contains lines that match the seeded templates.
    log_file = tmp_path / "known.jsonl"
    _write_jsonl(log_file, [
        {"ts": "2026-05-07T09:00:00Z", "severity": "INFO", "service": "AMF",
         "message": "User bob logged in from 10.0.0.2"},
        {"ts": "2026-05-07T09:00:01Z", "severity": "INFO", "service": "SMF",
         "message": "PDUSession established sessionId=pdu-0009 sessionStatus=ACTIVE"},
    ])
    report = detect_template_drift(LogCorpus(str(log_file)), conn)
    assert report.lines_seen == 2
    assert report.new_proposals == 0
    conn.close()


def test_unknown_template_with_enough_hits_creates_proposal(tmp_path):
    from log_corpus import LogCorpus
    from runtime.drift.log_template_drift import detect_template_drift

    conn = sqlite3.connect(":memory:")
    _seed_existing_templates(conn, [
        "User alice logged in from 10.0.0.1",
    ])
    # 4 occurrences of a brand-new template — passes the hit floor.
    log_file = tmp_path / "drift.jsonl"
    _write_jsonl(log_file, [
        {"ts": f"2026-05-07T09:00:0{i}Z", "severity": "ERROR",
         "service": "OAM",
         "message": f"Tachyon flux destabilised reactor=R-{i:02d}"}
        for i in range(4)
    ])
    report = detect_template_drift(LogCorpus(str(log_file)), conn,
                                   min_hits_to_propose=3)
    assert report.lines_seen == 4
    assert report.new_templates >= 1
    assert report.new_proposals >= 1
    row = conn.execute(
        "SELECT detection_strategy, proposal_type FROM ontology_evolution_proposals"
    ).fetchone()
    assert row is not None
    assert row[0] == "DRIFT_ON_NEW_TEMPLATE"
    assert row[1] == "LOG_EVENT"
    conn.close()


def test_one_off_unknown_line_does_not_create_proposal(tmp_path):
    """Single-occurrence noise must not spam the review queue —
    that's what min_hits_to_propose guards against."""
    from log_corpus import LogCorpus
    from runtime.drift.log_template_drift import detect_template_drift

    conn = sqlite3.connect(":memory:")
    _seed_existing_templates(conn, ["Heartbeat received from nfId=AMF-01"])
    log_file = tmp_path / "noise.jsonl"
    _write_jsonl(log_file, [{
        "ts": "2026-05-07T09:00:00Z", "severity": "INFO", "service": "OAM",
        "message": "A unique line that never repeats again",
    }])
    report = detect_template_drift(LogCorpus(str(log_file)), conn,
                                   min_hits_to_propose=3)
    assert report.new_proposals == 0
    conn.close()


def test_drift_pass_is_idempotent(tmp_path):
    """Running the drift detector twice over the same corpus must not
    create duplicate proposals — the uuid5-keyed upsert handles it."""
    from log_corpus import LogCorpus
    from runtime.drift.log_template_drift import detect_template_drift

    conn = sqlite3.connect(":memory:")
    _seed_existing_templates(conn, ["something familiar"])
    log_file = tmp_path / "drift.jsonl"
    _write_jsonl(log_file, [
        {"ts": f"2026-05-07T09:00:0{i}Z", "severity": "WARN",
         "service": "OAM",
         "message": f"NeverSeenBefore widget gid={i:03d}"}
        for i in range(5)
    ])
    detect_template_drift(LogCorpus(str(log_file)), conn,
                          min_hits_to_propose=3)
    first = conn.execute(
        "SELECT COUNT(*) FROM ontology_evolution_proposals"
    ).fetchone()[0]
    detect_template_drift(LogCorpus(str(log_file)), conn,
                          min_hits_to_propose=3)
    second = conn.execute(
        "SELECT COUNT(*) FROM ontology_evolution_proposals"
    ).fetchone()[0]
    assert first == second
    conn.close()


def test_drift_safe_when_log_templates_absent(tmp_path):
    """Calling drift detection on a fresh DB (no L1 mining has run)
    must not raise. Returns an empty report."""
    from log_corpus import LogCorpus
    from runtime.drift.log_template_drift import detect_template_drift

    conn = sqlite3.connect(":memory:")
    log_file = tmp_path / "any.jsonl"
    _write_jsonl(log_file, [{
        "ts": "2026-05-07T09:00:00Z", "severity": "INFO",
        "service": "X", "message": "anything"
    }])
    report = detect_template_drift(LogCorpus(str(log_file)), conn)
    assert report.new_proposals == 0
    conn.close()
