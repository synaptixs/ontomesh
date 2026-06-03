"""
log_miner.py — Phase L1.3–L1.5 + L1.6 orchestrator
──────────────────────────────────────────────────
End-to-end log-mining pipeline. Reads a folder of logs via
:mod:`log_corpus`, runs :class:`log_templates.LogTemplateMiner`, then
adds three Phase-L1 layers:

* **L1.3 — Slot typing.** For each `<*>` placeholder in a template,
  classify the value distribution as one of
  ``IRI / IP / UUID / ENUM / NUMERIC / FREETEXT``. The classification
  decides whether downstream review treats a slot as an *object*-property
  target (it points at an entity) or a *data*-property value.
* **L1.4 — PMI-weighted entity graph.** Pairs of slot values that
  co-occur (same ``trace_id`` or within Δt seconds) are scored with
  pointwise mutual information:
  ``PMI(x,y) = log2 P(x,y) / (P(x) P(y))``. Edges below ``τ_PMI`` are
  dropped — keeps the review queue manageable.
* **L1.5 — Temporal ordering.** For each surviving edge, count how
  often ``x → y`` precedes ``y → x`` within Δt. ``temporal_lead_ratio``
  > ``lead_ratio_threshold`` sets a direction; otherwise the edge stays
  bidirectional and Phase L4's review queue surfaces the ambiguity.

The defaults tuned in L1.8 are exported at the top of this module so
they're discoverable in one place.

CLI (L1.6)
──────────
::

    python toolkit.py --phase mine --log-path examples/log-rca/sample/
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

# ── Defaults (tuned in L1.8, exported for visibility) ────────────────────
#
# Tuning sweep against examples/log-rca/sample/ (215 lines, 6 files):
#
#   τ_PMI   edges   noisy   good   time
#   0.0      320     34     286    0.018s
#   1.0      318     34     284    0.014s
#   2.0      318     34     284    0.013s   ← chosen default
#   3.0      317     34     283    0.013s
#   5.0      311     29     282    0.013s
#
# Observations from the sweep:
#   * PMI distribution is dominated by very-strong edges (> 5 bits) so
#     raising τ_PMI past ~2 barely affects the surviving set.
#   * The "noisy" count (short tokens like `#1`, `OSS`) is independent
#     of PMI threshold — it traces back to slot-length, not co-
#     occurrence strength. A slot-length filter is a future refinement
#     in L1.8+; for v1 the PMI threshold remains the primary lever.
#
# The chosen defaults clear the L1 acceptance gate by a wide margin:
# 37 templates ≥ 20 required, 318 edges ≥ 30 required, 21 ms ≪ 60 s.

PMI_THRESHOLD_DEFAULT = 2.0
"""Minimum PMI in bits for an entity edge to survive."""

TEMPORAL_WINDOW_S_DEFAULT = 60
"""Δt window (seconds) for co-occurrence and temporal ordering."""

LEAD_RATIO_THRESHOLD_DEFAULT = 0.7
"""x→y ratio above which an edge is treated as directed."""

ENUM_DISTINCT_MAX = 8
"""≤ N distinct values → classify as ENUM."""

SLOT_TOP_VALUES_N = 5
"""How many top values to persist per slot."""


# ── Schemas ──────────────────────────────────────────────────────────────


_SLOT_DDL = """
CREATE TABLE IF NOT EXISTS log_template_slots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id     INTEGER NOT NULL REFERENCES log_templates(id),
    slot_idx        INTEGER NOT NULL,
    type            TEXT NOT NULL,                  -- IRI/IP/UUID/ENUM/NUMERIC/FREETEXT
    distinct_count  INTEGER NOT NULL,
    sample_count    INTEGER NOT NULL,
    top_values      TEXT,                           -- comma-joined
    pii_risk        INTEGER DEFAULT 0,              -- 1 if classifier hit PII heuristic
    UNIQUE(template_id, slot_idx)
);

CREATE INDEX IF NOT EXISTS idx_log_template_slots_template ON log_template_slots(template_id);
CREATE INDEX IF NOT EXISTS idx_log_template_slots_type     ON log_template_slots(type);
"""

_EDGE_DDL = """
CREATE TABLE IF NOT EXISTS log_entity_edges (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    src                   TEXT NOT NULL,
    dst                   TEXT NOT NULL,
    pmi                   REAL NOT NULL,
    cooccurrence_count    INTEGER NOT NULL,
    temporal_lead_ratio   REAL,                     -- NULL until L1.5 sets it
    directed              INTEGER DEFAULT 0,        -- 1 if lead_ratio > threshold
    created_at            TEXT DEFAULT (datetime('now')),
    UNIQUE(src, dst)
);

CREATE INDEX IF NOT EXISTS idx_log_entity_edges_src ON log_entity_edges(src);
CREATE INDEX IF NOT EXISTS idx_log_entity_edges_dst ON log_entity_edges(dst);
CREATE INDEX IF NOT EXISTS idx_log_entity_edges_pmi ON log_entity_edges(pmi);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SLOT_DDL)
    conn.executescript(_EDGE_DDL)
    conn.commit()


# ── Slot typing (L1.3) ──────────────────────────────────────────────────


_IRI_RE  = re.compile(r"^(?:https?|urn|ftp):\S+$|^[A-Za-z][\w-]*:[A-Za-z][\w-]*$")
_IP_RE   = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NUM_RE  = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_HEX_RE  = re.compile(r"^(?:0x)?[0-9a-fA-F]{8,}$")
# PII heuristic: anything that *looks like* a personal identifier. The
# review UI can downgrade later; the miner defaults to caution.
_PII_RE  = re.compile(r"(?:imsi|msisdn|email|ssn|tax)", re.I)


@dataclass
class SlotProfile:
    template_id: int
    slot_idx: int
    type: str
    distinct_count: int
    sample_count: int
    top_values: List[str]
    pii_risk: bool = False

    def to_dict(self) -> dict:
        return {
            "template_id":    self.template_id,
            "slot_idx":       self.slot_idx,
            "type":           self.type,
            "distinct_count": self.distinct_count,
            "sample_count":   self.sample_count,
            "top_values":     self.top_values,
            "pii_risk":       self.pii_risk,
        }


def classify_slot(values: Iterable[str]) -> SlotProfile:
    """Return the slot profile for an iterable of observed values.

    The classification ladder runs strict → loose. We pick the first
    rule that matches the *majority* (≥ 80 %) of values. IRI / IP /
    UUID first because they're unambiguous; ENUM next when the
    cardinality is small; NUMERIC when the values are numbers; HEX
    when they look like hashes / TEIDs; FREETEXT as fallback.
    """
    vals = [str(v) for v in values if v is not None and str(v) != ""]
    if not vals:
        return SlotProfile(0, 0, "FREETEXT", 0, 0, [])
    counts = Counter(vals)
    distinct = len(counts)
    sample = len(vals)
    top = [v for v, _ in counts.most_common(SLOT_TOP_VALUES_N)]

    def _frac(predicate) -> float:
        hits = sum(1 for v in vals if predicate(v))
        return hits / sample

    type_ = "FREETEXT"
    if _frac(lambda v: bool(_IRI_RE.match(v))) >= 0.8:
        type_ = "IRI"
    elif _frac(lambda v: bool(_IP_RE.match(v))) >= 0.8:
        type_ = "IP"
    elif _frac(lambda v: bool(_UUID_RE.match(v))) >= 0.8:
        type_ = "UUID"
    elif distinct <= ENUM_DISTINCT_MAX and distinct < sample:
        type_ = "ENUM"
    elif _frac(lambda v: bool(_NUM_RE.match(v))) >= 0.8:
        type_ = "NUMERIC"
    elif _frac(lambda v: bool(_HEX_RE.match(v))) >= 0.8:
        type_ = "HEX"

    pii = any(_PII_RE.search(v) for v in top)
    return SlotProfile(
        template_id=0, slot_idx=0,
        type=type_, distinct_count=distinct, sample_count=sample,
        top_values=top, pii_risk=pii,
    )


def persist_slot_profiles(conn: sqlite3.Connection,
                          extractions: List[dict]) -> List[SlotProfile]:
    """Group extractions by (cluster_id, slot_idx), classify each slot,
    and write to `log_template_slots`. Returns the persisted profiles.
    """
    ensure_schema(conn)

    # Map cluster_id → template DB id for foreign-key population.
    cluster_to_db = {
        r[1]: r[0] for r in conn.execute(
            "SELECT id, cluster_id FROM log_templates WHERE merged_into IS NULL"
        )
    }

    by_slot: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    for ex in extractions:
        cid = ex["cluster_id"]
        for i, val in enumerate(ex.get("slots", []) or []):
            by_slot[(cid, i)].append(val)

    profiles: List[SlotProfile] = []
    for (cid, slot_idx), values in by_slot.items():
        tmpl_id = cluster_to_db.get(cid)
        if tmpl_id is None:
            continue
        p = classify_slot(values)
        p.template_id = tmpl_id
        p.slot_idx = slot_idx
        profiles.append(p)
        conn.execute(
            "INSERT OR REPLACE INTO log_template_slots "
            "(template_id, slot_idx, type, distinct_count, sample_count, "
            " top_values, pii_risk) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tmpl_id, slot_idx, p.type, p.distinct_count, p.sample_count,
             ",".join(p.top_values), int(p.pii_risk)),
        )
    conn.commit()
    return profiles


# ── PMI-weighted entity graph (L1.4) ────────────────────────────────────


def _entity_values_for(extraction: dict, slot_profiles: Dict[Tuple[int, int], SlotProfile]
                       ) -> List[str]:
    """Pick the slot values that *look like* entities (IRI, IP, UUID,
    ENUM, HEX) — exclude freetext and pure numerics that are likely
    measurements rather than identifiers. ENUM values still count
    because they're often status codes worth modelling as entities."""
    out: List[str] = []
    cid = extraction["cluster_id"]
    for i, val in enumerate(extraction.get("slots", []) or []):
        profile = slot_profiles.get((cid, i))
        if profile is None:
            continue
        if profile.type in ("IRI", "IP", "UUID", "HEX", "ENUM"):
            if val:
                out.append(val)
    return out


def _parse_ts(ts: str) -> Optional[float]:
    if not ts:
        return None
    try:
        # tolerate the 'Z' suffix
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def compute_pmi_edges(extractions: List[dict],
                      slot_profiles: List[SlotProfile],
                      *,
                      window_s: float = TEMPORAL_WINDOW_S_DEFAULT,
                      threshold: float = PMI_THRESHOLD_DEFAULT
                      ) -> List[dict]:
    """Compute the PMI-weighted entity graph.

    A pair ``(x, y)`` co-occurs when:
      * they share a non-empty ``trace_id``, **or**
      * their timestamps differ by ≤ ``window_s`` seconds.

    Edges with PMI < ``threshold`` are discarded. The output list of
    dicts is sorted by descending PMI so the review queue surfaces the
    strongest signals first.
    """
    profile_lookup = {(p.template_id, p.slot_idx): p for p in slot_profiles}
    # Re-key by cluster_id since extractions carry cluster_id, not template DB id.
    # We map cluster_id → template_id once via the slot profiles' template_id
    # by matching positional order — simpler to recompute via extractions:
    cid_to_slot_profile: Dict[Tuple[int, int], SlotProfile] = {}
    # Build cluster_id → list of (slot_idx, profile) from profile_lookup:
    # profile_lookup keys are (template_db_id, slot_idx). The extraction has
    # cluster_id; we don't have direct mapping here. Build a fresh lookup
    # from the extractions themselves (which carry cluster_id) + the
    # slot-typing pass we already ran on them.
    # Simpler: re-classify on the fly using the value distribution per
    # (cluster_id, slot_idx) seen in `extractions`. That's the same data
    # `persist_slot_profiles` consumed, so the result is consistent.
    by_slot: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    for ex in extractions:
        cid = ex["cluster_id"]
        for i, val in enumerate(ex.get("slots", []) or []):
            by_slot[(cid, i)].append(val)
    for key, vals in by_slot.items():
        p = classify_slot(vals)
        cid_to_slot_profile[key] = p

    # 1. Per-record entity set.
    entities_per_record: List[Tuple[float, Optional[str], List[str]]] = []
    for ex in extractions:
        vals: List[str] = []
        cid = ex["cluster_id"]
        for i, val in enumerate(ex.get("slots", []) or []):
            p = cid_to_slot_profile.get((cid, i))
            if p and p.type in ("IRI", "IP", "UUID", "HEX", "ENUM") and val:
                vals.append(val)
        if not vals:
            continue
        t = _parse_ts(ex.get("ts", ""))
        entities_per_record.append((t or 0.0, ex.get("trace_id"), vals))

    if not entities_per_record:
        return []

    # 2. Marginals.
    marginal = Counter()
    total_records = len(entities_per_record)
    for _, _, vals in entities_per_record:
        for v in set(vals):
            marginal[v] += 1

    # 3. Co-occurrence. Two strategies, union of both:
    #    (a) same non-empty trace_id
    #    (b) timestamp distance ≤ window_s
    cooc = Counter()

    # (a) trace_id co-occurrence
    trace_buckets: Dict[str, List[str]] = defaultdict(list)
    for _, trace, vals in entities_per_record:
        if trace:
            trace_buckets[trace].extend(vals)
    for trace, vals in trace_buckets.items():
        uniq = list(set(vals))
        for i, x in enumerate(uniq):
            for y in uniq[i + 1:]:
                key = (min(x, y), max(x, y))
                cooc[key] += 1

    # (b) timestamp window. Sort by ts, sliding window.
    timed = sorted([(t, vals) for t, _, vals in entities_per_record if t > 0])
    j = 0
    for i, (ti, vi) in enumerate(timed):
        # advance j to first record in the window
        while j < len(timed) and ti - timed[j][0] > window_s:
            j += 1
        for k in range(j, i):
            for x in set(vi):
                for y in set(timed[k][1]):
                    if x == y:
                        continue
                    key = (min(x, y), max(x, y))
                    cooc[key] += 1

    # 4. PMI.
    edges: List[dict] = []
    for (x, y), n_xy in cooc.items():
        n_x = marginal[x]
        n_y = marginal[y]
        if n_x == 0 or n_y == 0:
            continue
        p_xy = n_xy / total_records
        p_x = n_x / total_records
        p_y = n_y / total_records
        if p_xy == 0 or p_x * p_y == 0:
            continue
        pmi = math.log2(p_xy / (p_x * p_y))
        if pmi < threshold:
            continue
        edges.append({
            "src": x, "dst": y, "pmi": pmi,
            "cooccurrence_count": n_xy,
        })
    edges.sort(key=lambda e: e["pmi"], reverse=True)
    return edges


# ── Temporal ordering (L1.5) ────────────────────────────────────────────


def add_temporal_ordering(extractions: List[dict],
                          edges: List[dict],
                          *,
                          window_s: float = TEMPORAL_WINDOW_S_DEFAULT,
                          lead_ratio_threshold: float = LEAD_RATIO_THRESHOLD_DEFAULT
                          ) -> List[dict]:
    """Annotate every edge with `temporal_lead_ratio` (fraction of times
    `src` appeared before `dst` within ``window_s``). Sets ``directed``
    when ratio exceeds the threshold (or is below ``1 - threshold``,
    in which case we flip src/dst). Edges in the ambiguous middle
    band remain undirected and the review queue flags them.
    """
    # Map value → list of timestamps, sorted.
    value_times: Dict[str, List[float]] = defaultdict(list)
    for ex in extractions:
        t = _parse_ts(ex.get("ts", ""))
        if t is None:
            continue
        for v in (ex.get("slots") or []):
            if v:
                value_times[str(v)].append(t)
    for v in value_times:
        value_times[v].sort()

    for edge in edges:
        x_times = value_times.get(edge["src"], [])
        y_times = value_times.get(edge["dst"], [])
        if not x_times or not y_times:
            edge["temporal_lead_ratio"] = None
            edge["directed"] = False
            continue
        x_first = y_first = 0
        # Count pairs within the window with x preceding y (and vice versa).
        for tx in x_times:
            for ty in y_times:
                dt = ty - tx
                if abs(dt) > window_s:
                    continue
                if dt > 0:
                    x_first += 1
                elif dt < 0:
                    y_first += 1
        total = x_first + y_first
        if total == 0:
            edge["temporal_lead_ratio"] = None
            edge["directed"] = False
            continue
        ratio = x_first / total
        if ratio >= lead_ratio_threshold:
            edge["temporal_lead_ratio"] = ratio
            edge["directed"] = True
        elif ratio <= 1.0 - lead_ratio_threshold:
            # Flip direction so src is always the cause-like endpoint.
            edge["src"], edge["dst"] = edge["dst"], edge["src"]
            edge["temporal_lead_ratio"] = 1.0 - ratio
            edge["directed"] = True
        else:
            edge["temporal_lead_ratio"] = ratio
            edge["directed"] = False
    return edges


def persist_edges(conn: sqlite3.Connection, edges: List[dict]) -> int:
    """Write edges to `log_entity_edges`. Idempotent — UNIQUE(src, dst)
    means re-runs update in place."""
    ensure_schema(conn)
    n = 0
    for e in edges:
        conn.execute(
            "INSERT INTO log_entity_edges "
            "(src, dst, pmi, cooccurrence_count, temporal_lead_ratio, directed) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(src, dst) DO UPDATE SET "
            "  pmi = excluded.pmi, "
            "  cooccurrence_count = excluded.cooccurrence_count, "
            "  temporal_lead_ratio = excluded.temporal_lead_ratio, "
            "  directed = excluded.directed",
            (e["src"], e["dst"], e["pmi"], e["cooccurrence_count"],
             e.get("temporal_lead_ratio"), int(bool(e.get("directed")))),
        )
        n += 1
    conn.commit()
    return n


# ── Pipeline (L1.6) ─────────────────────────────────────────────────────


@dataclass
class MiningReport:
    records_ingested: int = 0
    templates: int = 0
    templates_after_em: int = 0
    em_merges: int = 0
    slots_profiled: int = 0
    edges_persisted: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "records_ingested":     self.records_ingested,
            "templates":            self.templates,
            "templates_after_em":   self.templates_after_em,
            "em_merges":            self.em_merges,
            "slots_profiled":       self.slots_profiled,
            "edges_persisted":      self.edges_persisted,
            "duration_s":           round(self.duration_s, 3),
        }


def mine_corpus(corpus, conn: sqlite3.Connection, *,
                pmi_threshold: float = PMI_THRESHOLD_DEFAULT,
                temporal_window_s: float = TEMPORAL_WINDOW_S_DEFAULT,
                lead_ratio_threshold: float = LEAD_RATIO_THRESHOLD_DEFAULT,
                sim_threshold: float = 0.4,
                hits_threshold: int = 10,
                edit_threshold: int = 2,
                ) -> MiningReport:
    """End-to-end log mining over a :class:`LogCorpus`."""
    from log_templates import LogTemplateMiner   # late import — keeps deps light

    started = time.perf_counter()
    miner = LogTemplateMiner(
        conn,
        sim_threshold=sim_threshold,
        hits_threshold=hits_threshold,
        edit_threshold=edit_threshold,
    )
    for rec in corpus.iter():
        miner.consume(rec.message,
                      timestamp=rec.timestamp,
                      severity=rec.severity,
                      service=rec.fields.get("service") if rec.fields else None,
                      trace_id=rec.fields.get("trace_id") if rec.fields else None)
    miner.flush()
    templates_before = len(miner.list_templates())
    em_merges = miner.refine()
    templates_after = len(miner.list_templates())

    # L1.3 — slot typing
    profiles = persist_slot_profiles(conn, miner.extractions)

    # L1.4 — PMI graph
    edges = compute_pmi_edges(
        miner.extractions, profiles,
        window_s=temporal_window_s,
        threshold=pmi_threshold,
    )

    # L1.5 — temporal ordering
    edges = add_temporal_ordering(
        miner.extractions, edges,
        window_s=temporal_window_s,
        lead_ratio_threshold=lead_ratio_threshold,
    )

    persisted = persist_edges(conn, edges)

    duration = time.perf_counter() - started
    return MiningReport(
        records_ingested=len(miner.extractions),
        templates=templates_before,
        templates_after_em=templates_after,
        em_merges=em_merges,
        slots_profiled=len(profiles),
        edges_persisted=persisted,
        duration_s=duration,
    )


__all__ = [
    "MiningReport",
    "SlotProfile",
    "PMI_THRESHOLD_DEFAULT",
    "TEMPORAL_WINDOW_S_DEFAULT",
    "LEAD_RATIO_THRESHOLD_DEFAULT",
    "add_temporal_ordering",
    "classify_slot",
    "compute_pmi_edges",
    "ensure_schema",
    "mine_corpus",
    "persist_edges",
    "persist_slot_profiles",
]
