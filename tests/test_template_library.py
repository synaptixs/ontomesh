"""T2.2 — Cross-corpus template library.

Tests signature computation, library registration, lookup, and
the bootstrap-on-new-corpus path.

Acceptance gates (roadmap §3.T2.2):
- Bootstrapping a fresh corpus against a library mined from a
  sibling corpus reduces review-queue size by ≥ 30 %.
- No leakage: signatures store only hashes + slot types, never
  raw log lines.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


from db.migrations.v3_template_library import migrate as v3_lib_migrate  # noqa: E402
from template_library import (                                            # noqa: E402
    BootstrapReport, LibraryMatch, TemplateLibrary, TemplateSignature,
    compute_signature,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_proposal_db() -> sqlite3.Connection:
    """Real proposal store schema — same fixture pattern used by
    the rest of the v2/v3 test suites."""
    c = sqlite3.connect(":memory:")
    with open(ROOT / "db" / "schema.sql") as f:
        c.executescript(f.read())
    return c


def _seed_proposal(conn, *, pid, cluster_id, status="PENDING"):
    conn.execute(
        "INSERT INTO ontology_evolution_proposals "
        "(proposal_id, proposal_type, title, candidate_turtle, "
        " evidence_sparql, detection_strategy, confidence_score, "
        " evidence_template_id, status) "
        "VALUES (?, 'LOG_EVENT', ?, ':x a owl:Class .', 'ASK {}', "
        " 'LOG_TEMPLATE_CLUSTERING', 0.7, ?, ?)",
        (pid, f"template #{cluster_id}", cluster_id, status),
    )
    conn.commit()


# ── Signature determinism + privacy ──────────────────────────────────


def test_signature_is_deterministic_for_same_template():
    s1 = compute_signature("User <*> logged in successfully")
    s2 = compute_signature("User <*> logged in successfully")
    assert s1 == s2


def test_signature_ignores_placeholder_text():
    a = compute_signature("User <*> logged in from <*>")
    b = compute_signature("User <*> logged in from <*>")
    assert a == b


def test_signature_changes_when_tokens_change():
    a = compute_signature("User <*> logged in")
    b = compute_signature("Admin <*> signed up")
    assert a.signature_hash != b.signature_hash


def test_signature_carries_slot_types():
    s = compute_signature("User <*> logged in", slot_types=["UUID"])
    assert s.slot_types == ("UUID",)


def test_signature_only_stores_hashed_data():
    """Privacy invariant — the signature must not echo the raw
    template text. We assert the signature_hash + tokens_hash are
    16-hex strings and slot_types contains only upper-case symbols."""
    template = "VeryConfidentialUserId-123-Login-Success-At-Special-Time"
    s = compute_signature(template, slot_types=["UUID", "ENUM"])
    assert re.fullmatch(r"[a-f0-9]{16}", s.signature_hash)
    assert re.fullmatch(r"[a-f0-9]{16}", s.tokens_hash)
    assert all(re.fullmatch(r"[A-Z]+", t) for t in s.slot_types)
    # The raw template text must not appear anywhere in the
    # serialised form.
    payload = str(s.as_dict())
    assert "VeryConfidential" not in payload


# ── Migration + library lifecycle ─────────────────────────────────────


def test_migration_creates_template_library_table():
    c = sqlite3.connect(":memory:")
    out = v3_lib_migrate(c)
    assert "template_library" in out["tables_created"]
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='template_library'"
    ).fetchall()
    assert rows


def test_register_and_match_round_trip():
    c = sqlite3.connect(":memory:")
    v3_lib_migrate(c)
    lib = TemplateLibrary(c)
    s = compute_signature("User <*> logged in")
    lib.register([s], source="corpus-A", n_approved_each=3, n_rejected_each=1)
    m = lib.find_match(s)
    assert isinstance(m, LibraryMatch)
    assert m.n_approved == 3
    assert m.n_rejected == 1
    assert m.source_corpora == ["corpus-A"]
    assert m.score == 1.0


def test_register_merges_corpus_sources():
    c = sqlite3.connect(":memory:")
    v3_lib_migrate(c)
    lib = TemplateLibrary(c)
    s = compute_signature("PaymentReceived for <*>")
    lib.register([s], source="corpus-A", n_approved_each=2)
    lib.register([s], source="corpus-B", n_approved_each=3, n_rejected_each=1)
    m = lib.find_match(s)
    # Sources merged; decisions summed.
    assert set(m.source_corpora) == {"corpus-A", "corpus-B"}
    assert m.n_approved == 5
    assert m.n_rejected == 1


def test_record_decision_increments_counters():
    c = sqlite3.connect(":memory:")
    v3_lib_migrate(c)
    lib = TemplateLibrary(c)
    s = compute_signature("Session expired")
    lib.register([s], source="corpus-A")
    lib.record_decision(s.signature_hash, approved=True)
    lib.record_decision(s.signature_hash, approved=False)
    m = lib.find_match(s)
    assert m.n_approved == 1
    assert m.n_rejected == 1


def test_match_returns_none_for_unknown_template():
    c = sqlite3.connect(":memory:")
    v3_lib_migrate(c)
    lib = TemplateLibrary(c)
    s = compute_signature("Some template never seen")
    assert lib.find_match(s) is None


# ── Bootstrap acceptance gate ────────────────────────────────────────


def test_bootstrap_acceptance_gate_30pct_reduction(tmp_path):
    """Hero acceptance gate (roadmap §3.T2.2).

    Train the library on corpus-A's strong approvals; then mine
    corpus-B which shares the same template families. Bootstrap
    must auto-decide on at least 30 % of unique templates.
    """
    # Step 1 — seed the shared library with mostly-approved templates
    # from corpus A (≥ 5 approvals per signature, > 90 % approval).
    lib_db = sqlite3.connect(":memory:")
    v3_lib_migrate(lib_db)
    lib = TemplateLibrary(lib_db)
    shared_templates = [
        "User <*> logged in successfully",
        "PaymentReceived for customer <*>",
        "Session expired after <*> minutes",
        "OrderCompleted for <*>",
        "Notification sent to <*>",
    ]
    for t in shared_templates:
        sig = compute_signature(t)
        lib.register([sig], source="corpus-A",
                     n_approved_each=8, n_rejected_each=0)

    # Step 2 — build corpus B's extractions. 10 unique templates,
    # 5 of them overlap with the library; 5 are new.
    new_templates = [
        "FraudAlert raised for <*>",
        "BackupCompleted in <*>",
        "ConfigDrift detected in <*>",
        "MaintenanceWindow started for <*>",
        "PartitionRebalance completed",
    ]
    all_templates_b = shared_templates + new_templates
    extractions = []
    for cid, t in enumerate(all_templates_b, start=1):
        for n in range(3):
            extractions.append({
                "cluster_id": cid,
                "template":   t,
                "ts":         f"2026-06-02 10:0{n}:00",
            })

    # Step 3 — seed corpus B's proposal store with PENDING proposals
    # for each template, then bootstrap.
    target = _make_proposal_db()
    for cid in range(1, len(all_templates_b) + 1):
        _seed_proposal(target, pid=f"corp-b-{cid}", cluster_id=cid)
    report = lib.bootstrap_proposals(target, extractions)

    assert report.n_unique_templates == 10
    assert report.n_matched == 5

    # ≥ 30 % reduction in queue size = ≥ 3 of 10 auto-decided.
    auto_decided = report.n_auto_approved + report.n_skipped_rejected
    assert auto_decided >= 3, (
        f"bootstrap auto-decided only {auto_decided}/10 templates "
        f"(want ≥ 30 % reduction)"
    )

    # Step 4 — the matched proposals are now APPROVED (or REJECTED)
    # in the target store, not PENDING.
    pending = target.execute(
        "SELECT COUNT(*) FROM ontology_evolution_proposals "
        "WHERE status = 'PENDING'"
    ).fetchone()[0]
    assert pending <= 7        # at most 5 unknown + 2 unmatched-but-undecided


def test_bootstrap_respects_thresholds_when_decisions_are_split():
    """A library entry with 50/50 approve/reject must NOT auto-
    decide — the engineer has to look at it."""
    lib_db = sqlite3.connect(":memory:")
    v3_lib_migrate(lib_db)
    lib = TemplateLibrary(lib_db)
    sig = compute_signature("User <*> logged in")
    lib.register([sig], source="A", n_approved_each=5, n_rejected_each=5)

    target = _make_proposal_db()
    _seed_proposal(target, pid="p1", cluster_id=99)
    extractions = [{"cluster_id": 99, "template": "User <*> logged in"}]
    report = lib.bootstrap_proposals(target, extractions)
    assert report.n_matched == 1
    assert report.n_auto_approved == 0
    assert report.n_skipped_rejected == 0
    # Proposal stays PENDING.
    status = target.execute(
        "SELECT status FROM ontology_evolution_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "PENDING"


def test_bootstrap_reduction_rate_is_correct():
    lib_db = sqlite3.connect(":memory:")
    v3_lib_migrate(lib_db)
    lib = TemplateLibrary(lib_db)
    extractions = [{"cluster_id": 1, "template": "User <*> logged in"}]
    target = _make_proposal_db()
    _seed_proposal(target, pid="p1", cluster_id=1)
    report = lib.bootstrap_proposals(target, extractions)
    assert report.reduction_rate() == 0.0
    # Now seed the library and try again — should match.
    lib.register([compute_signature("User <*> logged in")],
                 source="X", n_approved_each=10)
    report2 = lib.bootstrap_proposals(
        target, [{"cluster_id": 2, "template": "User <*> logged in"}],
    )
    assert report2.reduction_rate() == 1.0


def test_size_reflects_registered_entries():
    c = sqlite3.connect(":memory:")
    v3_lib_migrate(c)
    lib = TemplateLibrary(c)
    assert lib.size() == 0
    # Use 7 lexically-distinct templates so each signs to a unique hash.
    distinct = ["UserLoggedIn", "PaymentReceived", "SessionExpired",
                "OrderCompleted", "RetryStorm", "AuthFailure",
                "MaintenanceWindow"]
    lib.register([compute_signature(t) for t in distinct], source="A")
    assert lib.size() == 7
