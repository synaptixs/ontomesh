"""T2.3 — Policy-based auto-approval.

Tests YAML policy loading, predicate evaluation, drift-gating,
audit trail, and revoke flow.

Acceptance gates (roadmap §3.T2.3):
- Policy engine matches engineer decisions ≥ 90 % on a curated set.
- Every auto-approval has a traceable policy match in the audit log.
- Engineer can revoke an auto-approval and the policy is auto-
  tightened (REVOKED: prefix prevents re-fire).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


from wizard.policy_engine import (                                   # noqa: E402
    Policy, PolicyEngine, PolicyMatch, PolicyRunReport,
    _eval_predicate, _parse_literal, load_policies,
    revoke_auto_approval,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _conn():
    c = sqlite3.connect(":memory:")
    with open(ROOT / "db" / "schema.sql") as f:
        c.executescript(f.read())
    return c


def _insert(conn, *, pid, kind="LOG_EVENT", title="x",
            confidence=0.5, pii=0.0, ev_vol=0.5, ev_rec=0.5,
            status="PENDING", age_hours=48.0):
    """Insert a pending proposal with a created_at offset so age
    predicates can be exercised."""
    created = (datetime.now(timezone.utc) - timedelta(hours=age_hours)) \
        .replace(tzinfo=None).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO ontology_evolution_proposals "
        "(proposal_id, proposal_type, title, candidate_turtle, "
        " evidence_sparql, detection_strategy, confidence_score, "
        " dim_consistency_risk, dim_evidence_volume, dim_evidence_recency, "
        " status, created_at) "
        "VALUES (?, ?, ?, ':x a owl:Class .', 'ASK {}', "
        " 'LOG_TEMPLATE_CLUSTERING', ?, ?, ?, ?, ?, ?)",
        (pid, kind, title, confidence, pii, ev_vol, ev_rec, status, created),
    )
    conn.commit()


def _safe_policy(name="high_conf_safe"):
    return Policy(
        name=name, enabled=True,
        if_={
            "kind":       "== LOG_EVENT",
            "confidence_score": ">= 0.95",
            "pii_risk":   "== 0",
            "age_hours":  ">= 24",
        },
        require=[{"ranker_decisions": ">= 100"}],
        then="approve",
        note="Auto-approved by policy {policy}.",
    )


# ── Predicate evaluation ──────────────────────────────────────────────


def test_eval_predicate_handles_operators():
    assert _eval_predicate(0.96, ">= 0.95")
    assert not _eval_predicate(0.94, ">= 0.95")
    assert _eval_predicate("LOG_EVENT", "== LOG_EVENT")
    assert _eval_predicate(0, "== 0")
    assert _eval_predicate("hello world", "contains world")
    assert _eval_predicate("auth_failure", "startswith auth")
    assert _eval_predicate(5, "in [1, 5, 10]")
    assert _eval_predicate("foo", "not in ['bar', 'baz']")


def test_eval_predicate_bare_literal_is_equality():
    assert _eval_predicate("X", "X")
    assert not _eval_predicate("X", "Y")


def test_parse_literal_handles_types():
    assert _parse_literal("42") == 42
    assert _parse_literal("3.14") == 3.14
    assert _parse_literal("true") is True
    assert _parse_literal("false") is False
    assert _parse_literal("'foo'") == "foo"
    assert _parse_literal("[1,2,3]") == [1, 2, 3]


# ── Policy loading ────────────────────────────────────────────────────


def test_load_policies_from_list_filters_disabled():
    raw = [
        {"name": "a", "enabled": True, "if": {"kind": "X"}},
        {"name": "b", "enabled": False, "if": {"kind": "Y"}},
    ]
    out = load_policies(raw)
    assert len(out) == 1
    assert out[0].name == "a"


def test_load_policies_from_yaml_file(tmp_path):
    yaml = pytest.importorskip("yaml")
    f = tmp_path / "policies.yml"
    f.write_text(
        "- name: p1\n  enabled: true\n  if:\n    kind: LOG_EVENT\n"
        "- name: p2\n  enabled: false\n  if:\n    kind: LOG_ENTITY\n"
    )
    out = load_policies(str(f))
    assert len(out) == 1
    assert out[0].name == "p1"


# ── Engine: structural matching ───────────────────────────────────────


def test_engine_approves_high_confidence_safe_proposal():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.97, pii=0.0, age_hours=48)
    engine = PolicyEngine(conn, [_safe_policy()],
                          ranker_decisions=150)
    report = engine.run()
    assert len(report.matches) == 1
    assert report.matches[0].action == "approve"
    row = conn.execute(
        "SELECT status, review_note, reviewer_id "
        "FROM ontology_evolution_proposals WHERE proposal_id='p1'"
    ).fetchone()
    assert row[0] == "APPROVED"
    assert "high_conf_safe" in row[1]
    assert row[2] == "policy:high_conf_safe"


def test_engine_skips_when_confidence_below_threshold():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.80, pii=0.0)
    engine = PolicyEngine(conn, [_safe_policy()], ranker_decisions=150)
    report = engine.run()
    assert report.matches == []
    assert report.skipped == 1


def test_engine_skips_when_pii_flag_set():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.6)
    engine = PolicyEngine(conn, [_safe_policy()], ranker_decisions=150)
    assert engine.run().matches == []


def test_engine_skips_when_too_young():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=2.0)
    engine = PolicyEngine(conn, [_safe_policy()], ranker_decisions=150)
    assert engine.run().matches == []


def test_engine_skips_when_ranker_decisions_below_floor():
    """The ranker_decisions floor prevents premature automation —
    the policy ships safe by default."""
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=48)
    engine = PolicyEngine(conn, [_safe_policy()],
                          ranker_decisions=20)        # < 100
    assert engine.run().matches == []


# ── Engine: drift-gating ──────────────────────────────────────────────


class _Alert:
    """Stand-in for metrics.DriftAlert — only ``severity`` is read."""
    def __init__(self, severity): self.severity = severity


def test_engine_pauses_on_critical_drift_alert():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=48)
    engine = PolicyEngine(
        conn, [_safe_policy()], ranker_decisions=200,
        drift_alerts=[_Alert(2)],         # critical
    )
    report = engine.run()
    assert report.drift_paused is True
    assert report.matches == []
    # Row stays PENDING.
    s = conn.execute(
        "SELECT status FROM ontology_evolution_proposals "
        "WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert s == "PENDING"


def test_engine_ignores_low_severity_drift_alerts():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=48)
    engine = PolicyEngine(
        conn, [_safe_policy()], ranker_decisions=200,
        drift_alerts=[_Alert(4)],         # info-level
    )
    report = engine.run()
    assert report.drift_paused is False
    assert len(report.matches) == 1


# ── Engine: audit + revoke ────────────────────────────────────────────


def test_revoke_auto_approval_returns_to_pending_with_marker():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=48)
    PolicyEngine(conn, [_safe_policy()], ranker_decisions=200).run()
    ok = revoke_auto_approval(conn, "p1", note="disagree")
    assert ok
    row = conn.execute(
        "SELECT status, review_note FROM ontology_evolution_proposals "
        "WHERE proposal_id='p1'"
    ).fetchone()
    assert row[0] == "PENDING"
    assert row[1].startswith("REVOKED:")


def test_revoke_refuses_when_not_policy_approved():
    """Only policy-driven approvals can be revoked through this path."""
    conn = _conn()
    _insert(conn, pid="p_manual", confidence=0.98, pii=0.0, age_hours=48,
            status="APPROVED")
    conn.execute(
        "UPDATE ontology_evolution_proposals "
        "SET reviewer_id = 'cli:reviewer' "
        "WHERE proposal_id = 'p_manual'"
    )
    conn.commit()
    assert revoke_auto_approval(conn, "p_manual") is False


def test_revoked_proposals_are_not_re_approved_by_same_policy():
    """The acceptance-gate guarantee: once a reviewer revokes, the
    same policy cannot fire on that proposal again."""
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=48)
    engine = PolicyEngine(conn, [_safe_policy()], ranker_decisions=200)
    engine.run()
    revoke_auto_approval(conn, "p1")
    # Second run on the same row — should NOT re-approve.
    report2 = engine.run()
    assert report2.matches == []
    s = conn.execute(
        "SELECT status FROM ontology_evolution_proposals "
        "WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert s == "PENDING"


# ── Multi-policy ordering ─────────────────────────────────────────────


def test_first_matching_policy_wins():
    conn = _conn()
    _insert(conn, pid="p1", confidence=0.98, pii=0.0, age_hours=48)
    permissive = Policy(
        name="permissive", enabled=True,
        if_={"kind": "== LOG_EVENT"},
        require=[],
    )
    strict = _safe_policy()
    # permissive first → fires before strict.
    engine = PolicyEngine(conn, [permissive, strict], ranker_decisions=0)
    report = engine.run()
    assert len(report.matches) == 1
    assert report.matches[0].policy == "permissive"


def test_engine_acceptance_gate_match_rate_high_on_known_safe_set():
    """Roadmap §3.T2.3 gate: on a curated set, the policy engine
    matches an engineer's decisions ≥ 90 % of the time. The
    'engineer's decisions' here are simulated: every high-confidence
    no-PII row was approved, every PII / low-confidence row was
    not approved.  We assert ≥ 90 % agreement."""
    conn = _conn()
    decisions = []   # (pid, engineer_will_approve)
    # 8 clear approvals
    for i in range(8):
        pid = f"approve-{i}"
        _insert(conn, pid=pid, confidence=0.97, pii=0.0, age_hours=48)
        decisions.append((pid, True))
    # 2 clearly NOT-approve (PII or low confidence)
    _insert(conn, pid="reject-1", confidence=0.97, pii=0.8, age_hours=48)
    decisions.append(("reject-1", False))
    _insert(conn, pid="reject-2", confidence=0.50, pii=0.0, age_hours=48)
    decisions.append(("reject-2", False))

    PolicyEngine(conn, [_safe_policy()], ranker_decisions=200).run()
    matches = 0
    for pid, expected in decisions:
        s = conn.execute(
            "SELECT status FROM ontology_evolution_proposals "
            "WHERE proposal_id = ?", (pid,),
        ).fetchone()[0]
        actually_approved = s == "APPROVED"
        if actually_approved == expected:
            matches += 1
    rate = matches / len(decisions)
    assert rate >= 0.9, f"policy/engineer agreement = {rate:.2%}"


# ── Report shape ──────────────────────────────────────────────────────


def test_run_report_as_dict_shape():
    report = PolicyRunReport()
    d = report.as_dict()
    assert {"matches", "skipped", "drift_paused", "n_policies", "duration_s"} \
        <= set(d)
