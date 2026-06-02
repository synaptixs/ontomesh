"""T3.3 — CQ → SPARQL auto-translation.

Tests translation, validation, idempotency, mock-provider fallback,
zero-hit detection, and coverage analysis.

Acceptance gates (roadmap §3.T3.3):
- Every CQ must yield ≥ 1 answer on the test corpus, OR be flagged
  ZERO_HITS for the engineer to review.
- A CQ with zero hits surfaces as either a wrong question or a
  missing concept.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from textwrap import dedent

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


pytest.importorskip("rdflib")


from db.migrations.v3_cq_translations import migrate as v3_cq_migrate  # noqa: E402
from wizard.cq_translator import (                                      # noqa: E402
    CqRunReport, CqTranslationResult,
    _extract_sparql, _mock_sparql_for, analyse_coverage,
    extract_ontology_context, translate_all_competency_questions,
    translate_one, validate_translation,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _consistent_ontology(tmp_path: Path) -> str:
    """A small ontology with both classes and instances. Some CQs
    will hit (return rows); others will be ZERO_HITS."""
    body = dedent("""
        @prefix : <http://ex.com/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        :Customer a owl:Class .
        :Order    a owl:Class .
        :Robot    a owl:Class .                   # no instances → zero hits
        :hasOrder a owl:ObjectProperty ;
                  rdfs:domain :Customer ;
                  rdfs:range  :Order .

        :alice a :Customer .
        :bob   a :Customer .
        :order-1 a :Order .
        :alice :hasOrder :order-1 .
    """).strip()
    p = tmp_path / "ontology.ttl"
    p.write_text(body + "\n")
    return str(p)


def _conn():
    c = sqlite3.connect(":memory:")
    v3_cq_migrate(c)
    return c


# ── Migration ─────────────────────────────────────────────────────────


def test_migration_creates_cq_translations_table():
    c = sqlite3.connect(":memory:")
    out = v3_cq_migrate(c)
    assert "cq_translations" in out["tables_created"]
    cols = {r[1] for r in c.execute(
        "PRAGMA table_info(cq_translations)"
    )}
    assert {"cq_id", "cq_text", "sparql_query", "source",
             "validation_status", "n_hits", "generated_at"} <= cols


def test_migration_is_idempotent():
    c = sqlite3.connect(":memory:")
    v3_cq_migrate(c)
    v3_cq_migrate(c)            # re-run: no error


# ── Ontology context extraction (privacy invariant) ───────────────────


def test_extract_context_returns_classes_and_properties(tmp_path):
    path = _consistent_ontology(tmp_path)
    ctx = extract_ontology_context(path)
    assert any(c.endswith("Customer") for c in ctx["classes"])
    assert any(c.endswith("Order") for c in ctx["classes"])
    assert any(p.endswith("hasOrder") for p in ctx["properties"])


def test_extract_context_no_instance_data_leaks(tmp_path):
    """Privacy invariant — the context handed to the LLM must NOT
    include any individual instance names (alice / bob / order-1)."""
    path = _consistent_ontology(tmp_path)
    ctx = extract_ontology_context(path)
    serialized = str(ctx)
    assert "alice" not in serialized
    assert "bob"   not in serialized
    assert "order-1" not in serialized


# ── SPARQL extraction from LLM output ─────────────────────────────────


def test_extract_sparql_strips_code_fence():
    raw = "Here you go:\n```sparql\nSELECT ?x WHERE { ?x a :C }\n```\nThanks!"
    out = _extract_sparql(raw)
    assert out.startswith("SELECT")
    assert "```" not in out


def test_extract_sparql_tolerates_preamble():
    raw = "Translation:\n\nPREFIX : <http://ex.com/>\nSELECT ?x WHERE { ?x a :C }"
    out = _extract_sparql(raw)
    assert "SELECT" in out


def test_extract_sparql_returns_raw_when_no_select_found():
    out = _extract_sparql("totally unstructured text")
    assert out == "totally unstructured text"


# ── Mock template fallback ────────────────────────────────────────────


def test_mock_sparql_anchors_on_class_when_named_in_cq(tmp_path):
    path = _consistent_ontology(tmp_path)
    ctx = extract_ontology_context(path)
    out = _mock_sparql_for("Which customers are active?", ctx)
    assert "Customer" in out
    assert "SELECT" in out


def test_mock_sparql_falls_back_to_first_class_when_cq_unambiguous(tmp_path):
    path = _consistent_ontology(tmp_path)
    ctx = extract_ontology_context(path)
    out = _mock_sparql_for("Show everything.", ctx)
    assert "SELECT" in out


# ── Translation + validation ─────────────────────────────────────────


def test_translate_one_with_no_provider_uses_mock_and_validates(tmp_path):
    path = _consistent_ontology(tmp_path)
    r = translate_one("Which customers are there?", path,
                      cq_id="CQ-01")
    # Mock template will anchor on :Customer and find rows.
    assert r.source == "mock"
    assert r.sparql_query.startswith("SELECT")
    assert r.validation_status == "OK"
    assert r.n_hits >= 2          # alice + bob


def test_translate_one_zero_hits_when_class_has_no_instances(tmp_path):
    path = _consistent_ontology(tmp_path)
    r = translate_one("What robots are deployed?", path, cq_id="CQ-02")
    # No :Robot instances → mock SPARQL returns zero rows.
    assert r.validation_status == "ZERO_HITS"
    assert r.n_hits == 0


def test_translate_one_with_flaky_provider_falls_to_syntax_error(tmp_path):
    """If the LLM provider throws, we don't crash — we record the
    failure as a SYNTAX_ERROR with the exception text."""
    class FlakyProvider:
        name = "flaky"
        def complete(self, *a, **kw):
            raise RuntimeError("boom")
    path = _consistent_ontology(tmp_path)
    r = translate_one("Q?", path, cq_id="CQ-X",
                      provider=FlakyProvider())
    assert r.validation_status == "SYNTAX_ERROR"
    assert "boom" in r.error_message


def test_translate_one_uses_provider_when_supplied(tmp_path):
    """A mock provider that returns a fixed SPARQL is used in lieu
    of the template fallback."""
    class CannedProvider:
        name = "canned"
        def complete(self, prompt, **kw):
            return ("PREFIX : <http://ex.com/>\n"
                    "SELECT ?x WHERE { ?x a :Customer . }")
    path = _consistent_ontology(tmp_path)
    r = translate_one("Q?", path, cq_id="CQ-03",
                      provider=CannedProvider())
    assert r.source == "canned"
    assert r.validation_status == "OK"
    assert r.n_hits >= 2


def test_validate_translation_syntax_error_for_invalid_sparql(tmp_path):
    path = _consistent_ontology(tmp_path)
    r = validate_translation(
        cq_id="CQ-bad", cq_text="?", sparql="THIS IS NOT SPARQL",
        source="manual", ontology_path=path,
    )
    assert r.validation_status == "SYNTAX_ERROR"


def test_validate_translation_empty_sparql_is_syntax_error(tmp_path):
    path = _consistent_ontology(tmp_path)
    r = validate_translation(
        cq_id="CQ-empty", cq_text="?", sparql="",
        source="mock", ontology_path=path,
    )
    assert r.validation_status == "SYNTAX_ERROR"


# ── Bulk translation + idempotency ───────────────────────────────────


def test_translate_all_persists_and_caches(tmp_path):
    path = _consistent_ontology(tmp_path)
    conn = _conn()
    cqs = [
        {"id": "CQ-01", "question": "Which customers exist?"},
        {"id": "CQ-02", "question": "What robots are deployed?"},
    ]
    rep = translate_all_competency_questions(
        conn, path, cqs, ontology_version="1.0.0",
    )
    assert rep.translated >= 1
    assert rep.zero_hits == 1   # CQ-02 should be ZERO_HITS

    # Second run with same ontology_version → fully cached.
    rep2 = translate_all_competency_questions(
        conn, path, cqs, ontology_version="1.0.0",
    )
    assert rep2.cached == len(cqs)
    assert rep2.translated == 0


def test_translate_all_force_re_runs_even_when_cached(tmp_path):
    path = _consistent_ontology(tmp_path)
    conn = _conn()
    cqs = [{"id": "CQ-01", "question": "Which customers exist?"}]
    translate_all_competency_questions(conn, path, cqs,
                                       ontology_version="1.0.0")
    rep2 = translate_all_competency_questions(
        conn, path, cqs, ontology_version="1.0.0", force=True,
    )
    assert rep2.cached == 0


def test_translate_all_separate_ontology_versions_are_independent(tmp_path):
    path = _consistent_ontology(tmp_path)
    conn = _conn()
    cqs = [{"id": "CQ-01", "question": "Which customers exist?"}]
    translate_all_competency_questions(conn, path, cqs,
                                       ontology_version="1.0.0")
    # Different version → not cached.
    rep = translate_all_competency_questions(
        conn, path, cqs, ontology_version="2.0.0",
    )
    assert rep.cached == 0
    assert rep.translated == 1


def test_translate_all_skips_rows_missing_id_or_text(tmp_path):
    path = _consistent_ontology(tmp_path)
    conn = _conn()
    cqs = [
        {"id": "", "question": "skipped no id"},
        {"id": "CQ-01", "question": ""},
        {"id": "CQ-02", "question": "Which customers exist?"},
    ]
    rep = translate_all_competency_questions(conn, path, cqs)
    assert len(rep.results) == 1
    assert rep.results[0].cq_id == "CQ-02"


# ── Coverage analysis ────────────────────────────────────────────────


def test_analyse_coverage_lists_used_classes_per_cq(tmp_path):
    path = _consistent_ontology(tmp_path)
    results = [
        CqTranslationResult(
            cq_id="CQ-01", cq_text="x",
            sparql_query="SELECT ?x WHERE { ?x a :Customer . }",
            validation_status="OK",
        ),
        CqTranslationResult(
            cq_id="CQ-02", cq_text="x",
            sparql_query="SELECT ?x WHERE { ?x a :Order . }",
            validation_status="OK",
        ),
    ]
    rep = analyse_coverage(results, path)
    assert rep.n_cqs == 2
    assert any("Customer" in c for c in rep.coverage["CQ-01"])
    assert any("Order"    in c for c in rep.coverage["CQ-02"])


def test_analyse_coverage_flags_unused_classes(tmp_path):
    """The acceptance-gate companion: a class that no CQ
    references is dead vocabulary the reviewer can drop."""
    path = _consistent_ontology(tmp_path)
    # Only CQ-01 references Customer; Robot + Order untouched.
    results = [CqTranslationResult(
        cq_id="CQ-01", cq_text="x",
        sparql_query="SELECT ?x WHERE { ?x a :Customer . }",
        validation_status="OK",
    )]
    rep = analyse_coverage(results, path)
    unused = set(rep.unused_classes)
    assert any("Robot" in c for c in unused)
    assert any("Order" in c for c in unused)


# ── Acceptance gate: zero-hit ⇒ missing concept surfaced ─────────────


def test_zero_hits_visible_in_report_acceptance_gate(tmp_path):
    """Roadmap §3.T3.3 hero: a CQ with zero hits MUST surface so the
    engineer can edit the question or promote a missing concept."""
    path = _consistent_ontology(tmp_path)
    conn = _conn()
    cqs = [
        {"id": "CQ-01", "question": "Which customers exist?"},
        {"id": "CQ-02", "question": "What robots are deployed?"},
        {"id": "CQ-03", "question": "What orders were placed?"},
    ]
    rep = translate_all_competency_questions(
        conn, path, cqs, ontology_version="1.0.0",
    )
    # At least one ZERO_HITS surfaced. (Robot has no instances.)
    zero = [r for r in rep.results
            if r.validation_status == "ZERO_HITS"]
    assert zero, (
        "zero-hit CQ not surfaced — the gate's whole purpose is "
        "to make these visible"
    )
    # The status is persistently visible in subsequent runs (cached).
    rep2 = translate_all_competency_questions(
        conn, path, cqs, ontology_version="1.0.0",
    )
    assert rep2.cached == len(cqs)
    cached_zero = [r for r in rep2.results
                   if r.validation_status == "ZERO_HITS"]
    assert cached_zero
