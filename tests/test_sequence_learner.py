"""L2 — sequence learning + anomaly proposals."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("hmmlearn")

from sequence_learner import (  # noqa: E402
    Trajectory, build_trajectories, fit_hmms, mine_sequences,
    score_anomalies, persist_anomaly_proposals,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    # Ship the proposal-store schema + the mining-side tables that
    # persist paths reference (log_templates, log_template_slots, edges).
    with open(ROOT / "db" / "schema.sql") as f:
        c.executescript(f.read())
    from log_templates import ensure_schema as _ensure_templates
    from log_miner import ensure_schema as _ensure_miner
    _ensure_templates(c)
    _ensure_miner(c)
    yield c
    c.close()


# ── L2.1 — trajectory grouping ──────────────────────────────────────────


def test_build_trajectories_groups_by_service_then_orders_by_ts():
    extractions = [
        # AMF — out-of-order ts; expect sorted [4,2,1,3] after sort
        {"cluster_id": 1, "service": "AMF", "trace_id": "t-1",
         "ts": "2026-05-07T09:00:02Z", "slots": []},
        {"cluster_id": 2, "service": "AMF", "trace_id": "t-1",
         "ts": "2026-05-07T09:00:01Z", "slots": []},
        {"cluster_id": 3, "service": "AMF", "trace_id": "t-1",
         "ts": "2026-05-07T09:00:03Z", "slots": []},
        {"cluster_id": 4, "service": "AMF", "trace_id": "t-1",
         "ts": "2026-05-07T09:00:00Z", "slots": []},
        {"cluster_id": 1, "service": "SMF", "trace_id": "s-1",
         "ts": "2026-05-07T09:00:00Z", "slots": []},
        {"cluster_id": 2, "service": "SMF", "trace_id": "s-1",
         "ts": "2026-05-07T09:00:01Z", "slots": []},
        {"cluster_id": 3, "service": "SMF", "trace_id": "s-1",
         "ts": "2026-05-07T09:00:02Z", "slots": []},
        {"cluster_id": 4, "service": "SMF", "trace_id": "s-1",
         "ts": "2026-05-07T09:00:03Z", "slots": []},
    ]
    trajectories = build_trajectories(extractions)
    by_service = {t.service: t for t in trajectories}
    assert by_service["AMF"].cluster_ids == [4, 2, 1, 3]
    assert by_service["SMF"].cluster_ids == [1, 2, 3, 4]


def test_build_trajectories_dedupes_consecutive_identical_ids():
    # Build [1,1,2,2,3,3,4,4] — 8 entries, dedupes to [1,2,3,4] (≥ MIN_SEQ_LEN).
    pattern = [1, 1, 2, 2, 3, 3, 4, 4]
    extractions = [
        {"cluster_id": cid, "service": "X", "trace_id": "a",
         "ts": f"2026-05-07T09:00:0{i}Z", "slots": []}
        for i, cid in enumerate(pattern)
    ]
    trajectories = build_trajectories(extractions)
    assert len(trajectories) == 1
    assert trajectories[0].cluster_ids == [1, 2, 3, 4]


def test_build_trajectories_dedupe_can_be_disabled():
    pattern = [1, 1, 2, 2]
    extractions = [
        {"cluster_id": cid, "service": "X", "trace_id": "a",
         "ts": f"2026-05-07T09:00:0{i}Z", "slots": []}
        for i, cid in enumerate(pattern)
    ]
    trajectories = build_trajectories(extractions, dedupe_consecutive=False)
    assert trajectories[0].cluster_ids == [1, 1, 2, 2]


def test_trajectories_below_min_length_skipped():
    # 3 extractions → length 3 < MIN_SEQ_LEN (4) → dropped.
    extractions = [
        {"cluster_id": i, "service": "X", "trace_id": "a",
         "ts": f"2026-05-07T09:00:0{i}Z", "slots": []}
        for i in range(3)
    ]
    assert build_trajectories(extractions) == []


# ── L2.2 — HMM fitter ───────────────────────────────────────────────────


def test_fit_hmms_returns_one_model_per_eligible_service():
    # Two services, each with 4 stable trajectories.
    trajectories = []
    for svc in ("A", "B"):
        for i in range(4):
            trajectories.append(Trajectory(
                service=svc, host=f"host-{i}",
                cluster_ids=[1, 2, 3, 1, 2, 3, 1, 2],
                timestamps=[f"2026-05-07T09:00:0{j}Z" for j in range(8)],
            ))
    fitted = fit_hmms(trajectories)
    assert set(fitted.keys()) == {"A", "B"}
    for fh in fitted.values():
        assert 2 <= fh.n_states
        assert fh.bic > 0 or fh.bic < 0
        assert fh.alphabet_size == 3
        assert fh.encoding   # populated for downstream scoring


def test_fit_skips_services_below_min_hits():
    trajectories = [Trajectory(
        service="tiny", host="h", cluster_ids=[1, 2, 3, 4],
        timestamps=["2026-05-07T09:00:00Z"] * 4)]
    assert fit_hmms(trajectories) == {}


# ── L2.3 — Anomaly scoring ──────────────────────────────────────────────


def test_injected_outlier_is_flagged_with_confidence_ge_06():
    """The dev plan acceptance gate: on a synthetic corpus with one
    injected outlier, ≥ 1 LOG_EVENT candidate with confidence ≥ 0.6.
    We use a structural anomaly (extra cluster id never seen elsewhere)
    so the bag-novelty signal carries the confidence floor."""
    normal = [1, 2, 3, 1, 2, 3, 1, 2]
    trajectories = []
    for i in range(10):
        trajectories.append(Trajectory(
            service="svc", host=f"h-{i}", cluster_ids=list(normal),
            timestamps=[f"2026-05-07T09:00:0{j}Z" for j in range(8)],
        ))
    # Outlier visits cluster 99 which no other trajectory uses.
    trajectories.append(Trajectory(
        service="svc", host="bad", cluster_ids=[1, 2, 99, 1, 2, 3],
        timestamps=[f"2026-05-07T10:00:0{j}Z" for j in range(6)],
    ))
    fitted = fit_hmms(trajectories, percentile=15.0)
    hits = score_anomalies(trajectories, fitted, percentile=15.0)
    assert hits, "expected at least one anomaly"
    bad = [h for h in hits if h.host == "bad"]
    assert bad and bad[0].confidence >= 0.6
    # Change-point cluster id should be the novel 99.
    assert bad[0].change_point_cluster_id == 99


def test_persist_anomaly_proposals_writes_to_evolution_table(conn):
    # Seed a couple of log_templates rows so persist can resolve the
    # change-point template id and sample line.
    conn.execute(
        "INSERT INTO log_templates "
        "(cluster_id, template, sample_line, hits) "
        "VALUES (1, 'tmpl-1', 'sample line 1', 5)"
    )
    conn.commit()

    from sequence_learner import AnomalyHit
    hits = [AnomalyHit(
        service="svc", host="bad", trajectory_length=6,
        per_step_logL=-2.5, threshold=-0.8,
        change_point_idx=2, change_point_cluster_id=1,
        confidence=0.7,
    )]
    n = persist_anomaly_proposals(conn, hits)
    assert n == 1
    row = conn.execute(
        "SELECT proposal_type, detection_strategy, confidence_score, "
        " evidence_template_id, evidence_sample "
        "FROM ontology_evolution_proposals"
    ).fetchone()
    assert row[0] == "LOG_EVENT"
    assert row[1] == "HMM_SEQUENCE_ANOMALY"
    assert row[2] == 0.7
    assert row[4] == "sample line 1"


def test_anomaly_proposal_is_idempotent_on_rerun(conn):
    conn.execute(
        "INSERT INTO log_templates "
        "(cluster_id, template, sample_line, hits) "
        "VALUES (1, 'tmpl', 'sample', 5)"
    )
    conn.commit()
    from sequence_learner import AnomalyHit
    hit = AnomalyHit(service="svc", host=None, trajectory_length=6,
                     per_step_logL=-2.0, threshold=-0.8,
                     change_point_idx=0, change_point_cluster_id=1,
                     confidence=0.65)
    persist_anomaly_proposals(conn, [hit])
    persist_anomaly_proposals(conn, [hit])   # idempotent re-write
    count = conn.execute(
        "SELECT COUNT(*) FROM ontology_evolution_proposals"
    ).fetchone()[0]
    assert count == 1


# ── L2 end-to-end via mine_sequences ────────────────────────────────────


def test_mine_sequences_pipeline_on_sample_corpus(conn):
    """End-to-end: mine the sample corpus, then run sequence learning.
    Expect at least one anomaly proposal."""
    from log_corpus import LogCorpus
    from log_templates import LogTemplateMiner
    sample_dir = ROOT / "examples" / "log-rca" / "sample"
    if not sample_dir.is_dir():
        pytest.skip("sample corpus not present")

    miner = LogTemplateMiner(conn)
    for rec in LogCorpus(str(sample_dir)).iter():
        miner.consume(rec.message, timestamp=rec.timestamp,
                      severity=rec.severity,
                      service=rec.fields.get("service"),
                      trace_id=rec.fields.get("trace_id"))
    miner.flush()
    miner.refine()
    report = mine_sequences(miner.extractions, conn, percentile=20.0)
    r = report.as_dict()
    assert r["trajectories"] > 0
    assert r["services_fit"] >= 1
    # The corpus seeds a heartbeat-timeout chain — should surface as
    # at least one anomaly.
    assert r["anomalies"] >= 1
    assert r["proposals_persisted"] >= 1
