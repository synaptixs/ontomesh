"""
log_templates.py — Phase L1.2
─────────────────────────────
Template clustering for log mining (see docs/log-rca-roadmap.md §3 and
docs/log-rca-dev-plan.md §1.2).

Wraps the Drain3 algorithm (LogPAI benchmark winner) and persists the
discovered templates into a SQLite table the engineer-review step and
downstream phases (sequence learning, PMI graph, causality) all read.

Template lifecycle
─────────────────
1. **Mine.** :meth:`LogTemplateMiner.consume` feeds each log message into
   the underlying Drain tree. Drain produces a `cluster_id` and a
   wildcard template like ``"NFRegister received from <*> <*>"``.
2. **Persist.** Each cluster maps to a row in :sql:`log_templates`. Hits
   accumulate across calls; first/last-seen timestamps are tracked.
3. **EM refinement.** Once a cluster has ``hits >= hits_threshold`` and
   :meth:`refine` is called, near-duplicate templates within edit
   distance ``edit_threshold`` are merged. The surviving template keeps
   the lower id; the loser's hits are added to the survivor.

The miner is intentionally side-effect-light: nothing about
``ontology_metadata`` is touched here. Promotion of a template into a
domain event class happens in the engineer-review step (Phase L4).
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
    _DRAIN_OK = True
except ImportError:                                  # pragma: no cover
    _DRAIN_OK = False


# ── Schema ───────────────────────────────────────────────────────────────


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS log_templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id    INTEGER UNIQUE NOT NULL,           -- drain3 cluster id
    template      TEXT NOT NULL,
    regex         TEXT,                              -- compiled match regex
    sample_line   TEXT,
    hits          INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT,
    last_seen     TEXT,
    severity      TEXT,                              -- modal severity
    service       TEXT,                              -- modal service
    merged_into   INTEGER REFERENCES log_templates(id),
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_log_templates_cluster ON log_templates(cluster_id);
CREATE INDEX IF NOT EXISTS idx_log_templates_service ON log_templates(service);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the log_templates table if it doesn't exist. Idempotent."""
    conn.executescript(_CREATE_SQL)
    conn.commit()


# ── Data class ───────────────────────────────────────────────────────────


@dataclass
class Template:
    id: Optional[int]
    cluster_id: int
    template: str
    sample_line: str
    hits: int = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    severity: Optional[str] = None
    service: Optional[str] = None
    merged_into: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "cluster_id": self.cluster_id,
            "template": self.template, "sample_line": self.sample_line,
            "hits": self.hits, "first_seen": self.first_seen,
            "last_seen": self.last_seen, "severity": self.severity,
            "service": self.service, "merged_into": self.merged_into,
        }


# ── Miner ────────────────────────────────────────────────────────────────


class LogTemplateMiner:
    """Stateful Drain wrapper backed by SQLite persistence.

    Args:
        conn: open SQLite connection. The table is created on construct.
        sim_threshold: Drain similarity threshold for grouping (0..1).
            Higher = stricter (fewer, larger clusters). Default 0.4
            matches the Drain3 library default.
        max_depth: Drain parse-tree depth. Default 4 is the library
            default and works well for short-to-medium log lines.
        hits_threshold: minimum hits before a template is eligible for
            EM merging. Stops single-occurrence noise from being merged.
        edit_threshold: max Levenshtein distance for EM merging.
    """

    def __init__(self, conn: sqlite3.Connection, *,
                 sim_threshold: float = 0.4,
                 max_depth: int = 4,
                 hits_threshold: int = 10,
                 edit_threshold: int = 2):
        if not _DRAIN_OK:
            raise ImportError(
                "drain3 is required for LogTemplateMiner. "
                "Install via `pip install drain3` or `pip install -e .[mining]`."
            )
        self.conn = conn
        ensure_schema(self.conn)
        self.hits_threshold = hits_threshold
        self.edit_threshold = edit_threshold

        config = TemplateMinerConfig()
        config.drain_sim_th = sim_threshold
        config.drain_max_depth = max_depth
        # Suppress drain3's default print on every config-load.
        self._tm = TemplateMiner(config=config)

        # Per-cluster accumulators we flush on commit/refine.
        self._pending_hits: Dict[int, int] = {}
        self._pending_first: Dict[int, str] = {}
        self._pending_last: Dict[int, str] = {}
        self._pending_severity: Dict[int, Dict[str, int]] = {}
        self._pending_service: Dict[int, Dict[str, int]] = {}
        self._pending_templates: Dict[int, Tuple[str, str]] = {}  # cid → (template, sample)

        # L1.3 / L1.4 / L1.5 — per-message extraction record. Each entry:
        # {cluster_id, template, slots, ts, trace_id, service}. Used by
        # downstream slot-typing and PMI graph computation. Kept in
        # memory; flush() does not persist these (they're transient).
        self.extractions: List[dict] = []

    # ── consume ────────────────────────────────────────────────────────

    def consume(self, message: str, *, timestamp: str = "",
                severity: Optional[str] = None,
                service: Optional[str] = None,
                trace_id: Optional[str] = None) -> int:
        """Feed one log message and return its cluster id."""
        result = self._tm.add_log_message(message)
        cid = result["cluster_id"]
        template = result["template_mined"]

        self._pending_hits[cid] = self._pending_hits.get(cid, 0) + 1
        if cid not in self._pending_first and timestamp:
            self._pending_first[cid] = timestamp
        if timestamp:
            self._pending_last[cid] = timestamp
        if severity:
            bucket = self._pending_severity.setdefault(cid, {})
            bucket[severity] = bucket.get(severity, 0) + 1
        if service:
            bucket = self._pending_service.setdefault(cid, {})
            bucket[service] = bucket.get(service, 0) + 1
        self._pending_templates[cid] = (template, message)

        # L1.3: capture the actual slot values that filled the <*>
        # placeholders. Drain3's extract_parameters runs the same
        # tokeniser used at clustering time so the slot ordering is
        # stable across runs.
        slots: List[str] = []
        try:
            params = self._tm.extract_parameters(template, message)
            if params:
                slots = [p.value for p in params]
        except Exception:  # noqa: BLE001 — never let extraction kill ingest
            pass
        self.extractions.append({
            "cluster_id": cid,
            "template":   template,
            "slots":      slots,
            "ts":         timestamp,
            "trace_id":   trace_id,
            "service":    service,
            "severity":   severity,
        })
        return cid

    # ── flush ──────────────────────────────────────────────────────────

    def flush(self) -> None:
        """Persist accumulated stats to the database. Call after a batch
        of `consume()` calls. Safe to call any number of times."""
        for cid, (template, sample) in self._pending_templates.items():
            hits = self._pending_hits.get(cid, 0)
            first = self._pending_first.get(cid)
            last = self._pending_last.get(cid)
            sev_modal = self._modal(self._pending_severity.get(cid, {}))
            svc_modal = self._modal(self._pending_service.get(cid, {}))
            self._upsert(cid, template, sample, hits, first, last,
                         sev_modal, svc_modal)
        self.conn.commit()
        # Reset accumulators so we don't double-count on next flush.
        self._pending_hits.clear()
        self._pending_first.clear()
        self._pending_last.clear()
        self._pending_severity.clear()
        self._pending_service.clear()
        self._pending_templates.clear()

    @staticmethod
    def _modal(counts: Dict[str, int]) -> Optional[str]:
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def _upsert(self, cid: int, template: str, sample: str, hits_delta: int,
                first: Optional[str], last: Optional[str],
                severity: Optional[str], service: Optional[str]) -> None:
        row = self.conn.execute(
            "SELECT id, hits, first_seen FROM log_templates WHERE cluster_id = ?",
            (cid,)
        ).fetchone()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if row is None:
            self.conn.execute(
                "INSERT INTO log_templates "
                "(cluster_id, template, sample_line, hits, first_seen, last_seen, severity, service, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, template, sample, hits_delta, first or now,
                 last or now, severity, service, now),
            )
        else:
            existing_first = row[2]
            new_first = existing_first if existing_first else first
            self.conn.execute(
                "UPDATE log_templates SET template = ?, sample_line = ?, "
                "hits = hits + ?, first_seen = COALESCE(first_seen, ?), "
                "last_seen = ?, severity = ?, service = ?, "
                "updated_at = ? "
                "WHERE cluster_id = ?",
                (template, sample, hits_delta, new_first,
                 last or now, severity, service, now, cid),
            )

    # ── refine (EM-style merge) ────────────────────────────────────────

    def refine(self) -> int:
        """Merge near-duplicate templates within ``edit_threshold`` edit
        distance once each has ``>= hits_threshold`` hits. Returns the
        number of merges performed.
        """
        rows = self.conn.execute(
            "SELECT id, cluster_id, template, hits FROM log_templates "
            "WHERE merged_into IS NULL AND hits >= ? "
            "ORDER BY hits DESC",
            (self.hits_threshold,)
        ).fetchall()
        merged_count = 0
        survived: List[Tuple[int, int, str, int]] = []
        for r in rows:
            row_id, _cid, template, hits = r
            absorbed_into = None
            for s_id, _s_cid, s_template, _s_hits in survived:
                if _levenshtein(template, s_template) <= self.edit_threshold:
                    absorbed_into = s_id
                    break
            if absorbed_into is None:
                survived.append(r)
            else:
                # Mark this one merged; add its hits to the survivor.
                self.conn.execute(
                    "UPDATE log_templates SET merged_into = ? WHERE id = ?",
                    (absorbed_into, row_id),
                )
                self.conn.execute(
                    "UPDATE log_templates SET hits = hits + ? WHERE id = ?",
                    (hits, absorbed_into),
                )
                merged_count += 1
        self.conn.commit()
        return merged_count

    # ── read ───────────────────────────────────────────────────────────

    def list_templates(self, *, include_merged: bool = False) -> List[Template]:
        sql = ("SELECT id, cluster_id, template, sample_line, hits, "
               "first_seen, last_seen, severity, service, merged_into "
               "FROM log_templates")
        if not include_merged:
            sql += " WHERE merged_into IS NULL"
        sql += " ORDER BY hits DESC, id ASC"
        out = []
        for r in self.conn.execute(sql):
            out.append(Template(
                id=r[0], cluster_id=r[1], template=r[2], sample_line=r[3],
                hits=r[4], first_seen=r[5], last_seen=r[6],
                severity=r[7], service=r[8], merged_into=r[9],
            ))
        return out


# ── Levenshtein (small, no dependency) ──────────────────────────────────


def _levenshtein(a: str, b: str) -> int:
    """Iterative two-row Levenshtein. O(len(a) * len(b)). Sufficient for
    template strings (typically ≤ 200 chars)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


__all__ = ["LogTemplateMiner", "Template", "ensure_schema"]
