"""
runtime/drift/log_template_drift.py — Phase L7
──────────────────────────────────────────────
Closed-loop drift hook for log mining.

After an ontology has been generated via the Phase L1 / L2 / L4 / L5
flow, this module watches **new** log lines for templates the engineer
has never approved. Each unmatched line becomes a candidate
``LOG_EVENT`` proposal with
``detection_strategy='DRIFT_ON_NEW_TEMPLATE'`` — it lands in the same
review queue the bootstrap candidates do, so engineers see steady-state
drift and the initial onboarding in one place.

Why this lives under ``runtime/drift/`` and not ``src/``:
    The existing :mod:`runtime.drift.monitor` watches OWL / SHACL
    hierarchy drift. Adding template-drift here keeps all drift signals
    in one package without bloating the OWL-focused monitor.

Implementation
──────────────

1. Load the existing :sql:`log_templates` catalogue into a Drain3
   instance via ``add_log_message`` so the matcher recognises every
   approved-or-pending template. Drain3's ``match()`` returns the
   cluster id for a new line *only* when it falls into an existing
   cluster; otherwise it returns None or creates a new cluster.
2. For each new line in the supplied corpus, attempt a match. Lines
   without a match — i.e. genuinely new templates — feed a small
   per-template aggregator. Once a new template clears
   ``min_hits_to_propose`` (default 3, so single-line noise doesn't
   spam the queue), a ``LOG_EVENT`` proposal is upserted.
3. Idempotent: the proposal id is a uuid5 of the template string, so
   re-running the drift pass on the same corpus updates the existing
   proposal in place (hit count, last-seen) instead of creating a new
   one.

CLI
───
The drift pass is wired into a new toolkit phase::

    python toolkit.py --phase drift-templates --log-path /path/to/new-logs/
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

try:
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
    _DRAIN_OK = True
except ImportError:                                  # pragma: no cover
    _DRAIN_OK = False


# Stricter than the default 0.4. The drift detector needs to bias toward
# *more* clusters (less merging) so genuinely new patterns don't get
# pulled into the closest existing one by accident.
_DRIFT_SIM_TH = 0.7


# ── Schema (LOG_EVENT proposals already exist; no new tables) ───────────


@dataclass
class DriftReport:
    new_templates: int = 0
    new_proposals: int = 0
    lines_seen: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "new_templates":  self.new_templates,
            "new_proposals":  self.new_proposals,
            "lines_seen":     self.lines_seen,
            "duration_s":     round(self.duration_s, 3),
        }


def _stable_id(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


# ── Public API ───────────────────────────────────────────────────────────


def detect_template_drift(corpus, conn: sqlite3.Connection,
                          *, min_hits_to_propose: int = 3) -> DriftReport:
    """Walk ``corpus`` (a :class:`log_corpus.LogCorpus`) and surface
    LOG_EVENT proposals for templates the existing catalogue doesn't
    cover.

    The catalogue is rebuilt in-memory from the SQLite ``log_templates``
    table so Drain's similarity tree starts where the engineer left off.
    Lines that map to a known cluster are silently consumed. Lines that
    create *new* Drain clusters are tallied; once a new cluster's hit
    count reaches ``min_hits_to_propose`` it lands in the proposal
    store with detection_strategy='DRIFT_ON_NEW_TEMPLATE'.

    Args:
        corpus: an iterable of LogRecord (or anything with `.message`,
            `.timestamp`, `.severity`, `.fields`).
        conn: open SQLite connection to the project DB.
        min_hits_to_propose: minimum repeats before a new template
            graduates from "single noisy line" to "real candidate".
    """
    if not _DRAIN_OK:
        raise ImportError(
            "drain3 is required. Install via `pip install -e .[mining]`."
        )

    started = time.perf_counter()
    report = DriftReport()

    if not _table_exists(conn, "log_templates"):
        # Nothing to drift from — caller hasn't run --phase mine yet.
        report.duration_s = time.perf_counter() - started
        return report

    # Seed an in-memory Drain instance with every existing template's
    # representative sample line. Drain learns the parse-tree from these
    # samples so subsequent matches recognise them. We use a stricter
    # similarity threshold than the L1 miner so the drift detector
    # biases toward "this is new" rather than "this is close enough" —
    # false positives (drift on noise) are cheaper to dismiss than
    # false negatives (real drift hidden behind a permissive merge).
    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = _DRIFT_SIM_TH
    tm = TemplateMiner(config=cfg)
    # NOTE: drain3 assigns its own cluster_ids on add_log_message; the
    # DB's cluster_id column is unrelated to drain's internal counter
    # after a fresh re-seed. We track drain's *returned* ids so the
    # "is this a new cluster?" check stays correct.
    known_ids: set = set()
    for _db_cid, sample in conn.execute(
        "SELECT cluster_id, sample_line FROM log_templates "
        "WHERE merged_into IS NULL"
    ):
        if not sample:
            continue
        result = tm.add_log_message(sample)
        known_ids.add(int(result["cluster_id"]))
    known_count_before = len(tm.drain.clusters)

    # Track unseen templates by their drain cluster_id. The template
    # *string* evolves as Drain generalises (first occurrence is
    # literal; subsequent occurrences carry `<*>` placeholders), so
    # keying on cluster_id keeps hits aggregated correctly.
    new_template_hits: Dict[int, int] = {}
    new_template_meta: Dict[int, dict] = {}

    for rec in corpus.iter() if hasattr(corpus, "iter") else corpus:
        report.lines_seen += 1
        result = tm.add_log_message(rec.message)
        cid = result["cluster_id"]
        template_str = result["template_mined"]
        if cid in known_ids:
            continue
        new_template_hits[cid] = new_template_hits.get(cid, 0) + 1
        # Keep the most recent template string + first-seen sample so
        # the proposal carries Drain's stabilised generalisation, not
        # the literal first line.
        meta = new_template_meta.setdefault(cid, {})
        meta["template_str"] = template_str
        meta.setdefault("sample", rec.message)
        meta["ts"] = rec.timestamp
        meta["severity"] = rec.severity
        meta["service"] = (rec.fields.get("service") if rec.fields else None)

    report.new_templates = len(new_template_hits)

    # Persist any templates that cleared the hit floor.
    persisted = 0
    if _table_exists(conn, "ontology_evolution_proposals"):
        for cid, hits in new_template_hits.items():
            if hits < min_hits_to_propose:
                continue
            meta = new_template_meta.get(cid, {})
            template_str = meta.get("template_str", "")
            pid = _stable_id("drift:" + template_str)
            title = f"Drift template (new): {template_str[:60]}"
            confidence = min(1.0, 0.3 + 0.05 * hits)
            candidate_turtle = (
                f"# Drift candidate — new template not in approved set\n"
                f":DriftEvent_{abs(hash(template_str)) % 10**6} a owl:Class ;\n"
                f"  rdfs:subClassOf :CausalEvent ;\n"
                f'  rdfs:label "{template_str[:80]}" .\n'
            )
            evidence_sparql = (
                "PREFIX : <https://ontology.example.com/enterprise/>\n"
                "ASK { ?e a :CausalEvent }\n"
            )
            conn.execute(
                "INSERT INTO ontology_evolution_proposals "
                "(proposal_id, proposal_type, title, candidate_turtle, "
                " evidence_sparql, detection_strategy, confidence_score, "
                " dim_evidence_volume, dim_evidence_recency, "
                " evidence_sample, source_log_path) "
                "VALUES (?, 'LOG_EVENT', ?, ?, ?, 'DRIFT_ON_NEW_TEMPLATE', ?, ?, ?, ?, ?) "
                "ON CONFLICT(proposal_id) DO UPDATE SET "
                "  title = excluded.title, "
                "  candidate_turtle = excluded.candidate_turtle, "
                "  confidence_score = excluded.confidence_score, "
                "  dim_evidence_volume = excluded.dim_evidence_volume, "
                "  evidence_sample = excluded.evidence_sample, "
                "  updated_at = datetime('now')",
                (pid, title, candidate_turtle, evidence_sparql,
                 confidence,
                 min(1.0, hits / 30.0),
                 0.5,
                 meta.get("sample", "")[:200],
                 ""),
            )
            persisted += 1
        conn.commit()
    report.new_proposals = persisted
    report.duration_s = time.perf_counter() - started
    return report


__all__ = ["DriftReport", "detect_template_drift"]
