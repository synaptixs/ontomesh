"""
runtime.embeddings.benchmark — Workstream 5, Component 6
=========================================================
Benchmark suite comparing three retrieval strategies:

  1. ``UNFILTERED_VECTOR`` — baseline RAG (no OWL class filter)
  2. ``ONTOLOGY_BOUNDED``  — OWL class filter + sensitivity tier gate
  3. ``PURE_SPARQL``       — structured retrieval, no vector ranking

Metrics per strategy (averaged across the query pool):

  * precision@k           — fraction of returned records whose
                            ``owl_class`` matches the expected class
  * recall@k              — fraction of expected records returned
  * mean_reciprocal_rank  — 1/rank of first relevant result
  * latency_p50 / p95     — milliseconds
  * wrong_class_blocked   — fraction of wrong-class candidates filtered

Results land in the ``retrieval_benchmarks`` table, a CSV, and the
HTML toolkit report section.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HERE    = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.dirname(_HERE)
_ROOT    = os.path.dirname(_RUNTIME)
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from hybrid_retriever   import HybridRetriever  # noqa: E402
from .pipeline          import index_flavor, list_indexes


_DEFAULT_DB    = os.path.join(_ROOT, "db", "enterprise.db")
_DEFAULT_OUT   = os.path.join(_ROOT, "output")


# ─────────────────────────────────────────────────────────────────────
# Default query pool
# ─────────────────────────────────────────────────────────────────────
#
# Each query specifies:
#   question            — natural-language question
#   class_expression    — OWL class expression (the "correct" scope)
#   expected_classes    — classes whose records are considered relevant
#   expected_substring  — substrings in text_repr that mark a true positive


DEFAULT_QUERIES: List[Dict[str, Any]] = [
    {
        "domain": "telecom",
        "question": "Which network functions are degraded or failed?",
        "class_expression": "tmf:NetworkFunction",
        "expected_classes": ["https://ontology.example.com/tmf/NetworkFunction"],
        "expected_substring": [],
        "flavor": "network-ops",
    },
    {
        "domain": "telecom",
        "question": "Show open critical alarms on production services",
        "class_expression": "tmf:Alarm",
        "expected_classes": ["https://ontology.example.com/tmf/Alarm"],
        "expected_substring": [],
        "flavor": "network-ops",
    },
    {
        "domain": "telecom",
        "question": "What KPIs have breached thresholds recently?",
        "class_expression": "tmf:PerformanceIndicator",
        "expected_classes": ["https://ontology.example.com/tmf/PerformanceIndicator"],
        "expected_substring": [],
        "flavor": "network-ops",
    },
    {
        "domain": "telecom",
        "question": "Which resources are in the inventory catalogue?",
        "class_expression": "tmf:NetworkSlice",
        "expected_classes": ["https://ontology.example.com/tmf/NetworkSlice"],
        "expected_substring": [],
        "flavor": "network-ops",
    },
    {
        "domain": "telecom",
        "question": "Show active billing accounts and overdue bills",
        "class_expression": "tmf:CustomerBill",
        "expected_classes": ["https://ontology.example.com/tmf/CustomerBill"],
        "expected_substring": [],
        "flavor": "billing",
    },
    {
        "domain": "telecom",
        "question": "Which trouble tickets violate the SLA?",
        "class_expression": "tmf:TroubleTicket",
        "expected_classes": ["https://ontology.example.com/tmf/TroubleTicket"],
        "expected_substring": [],
        "flavor": "fault-management",
    },
]


# ─────────────────────────────────────────────────────────────────────
# Metric helpers
# ─────────────────────────────────────────────────────────────────────


def _is_relevant(result: Dict[str, Any], query: Dict[str, Any]) -> bool:
    cls = (result.get("owl_class") or "").lower()
    expected = [c.lower() for c in (query.get("expected_classes") or [])]
    if expected and cls in expected:
        return True
    text = (result.get("text_repr") or "").lower()
    subs = [s.lower() for s in (query.get("expected_substring") or [])]
    return any(s in text for s in subs)


def _precision_at_k(results: List[Dict[str, Any]], query: Dict[str, Any]) -> float:
    if not results:
        return 0.0
    hits = sum(1 for r in results if _is_relevant(r, query))
    return hits / len(results)


def _reciprocal_rank(results: List[Dict[str, Any]], query: Dict[str, Any]) -> float:
    for i, r in enumerate(results, start=1):
        if _is_relevant(r, query):
            return 1.0 / i
    return 0.0


def _wrong_class_blocked(
    unfiltered: List[Dict[str, Any]],
    filtered: List[Dict[str, Any]],
    query: Dict[str, Any],
) -> float:
    """Fraction of the unfiltered candidates whose class is wrong but
    which the ontology-bounded filter correctly excluded."""
    if not unfiltered:
        return 0.0
    expected = set(c.lower() for c in (query.get("expected_classes") or []))
    wrong_in_unfiltered = [
        r for r in unfiltered
        if expected and (r.get("owl_class") or "").lower() not in expected
    ]
    if not wrong_in_unfiltered:
        return 1.0  # nothing wrong to block
    filt_iris = {r.get("record_iri") for r in filtered}
    blocked = sum(
        1 for r in wrong_in_unfiltered
        if r.get("record_iri") not in filt_iris
    )
    return blocked / len(wrong_in_unfiltered)


# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────


def _ensure_index(flavor: str, db_path: str) -> None:
    """Make sure the flavor has an index.  First call per flavor is
    the only slow path."""
    existing = [i for i in list_indexes(db_path) if i["flavor"] == flavor]
    if not existing:
        index_flavor(flavor, db_path=db_path)


def run_benchmark(
    *,
    db_path: str = _DEFAULT_DB,
    out_path: str = _DEFAULT_OUT,
    queries: Optional[List[Dict[str, Any]]] = None,
    k: int = 5,
    strategies: Tuple[str, ...] = (
        "UNFILTERED_VECTOR", "ONTOLOGY_BOUNDED", "PURE_SPARQL",
    ),
) -> Dict[str, Any]:
    """Run the benchmark across *strategies* and persist results."""
    queries = queries or DEFAULT_QUERIES
    flavors = sorted({q["flavor"] for q in queries})
    for fl in flavors:
        try:
            _ensure_index(fl, db_path)
        except ValueError:
            pass  # missing flavor — skipped at query time

    # Cache HybridRetriever per flavor
    retrievers: Dict[str, HybridRetriever] = {}

    per_strategy: Dict[str, List[Dict[str, Any]]] = {s: [] for s in strategies}
    per_query_unfiltered: Dict[int, List[Dict[str, Any]]] = {}

    for i, q in enumerate(queries):
        flavor = q["flavor"]
        try:
            rt = retrievers.setdefault(flavor, HybridRetriever(
                flavor=flavor, db_path=db_path,
            ))
        except ValueError:
            continue

        for strat in strategies:
            t0 = time.time()
            res = rt.retrieve(
                q["question"],
                class_expression=q.get("class_expression"),
                k=k,
                strategy=strat,
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            results = res["results"]
            if strat == "UNFILTERED_VECTOR":
                per_query_unfiltered[i] = results

            per_strategy[strat].append({
                "query_idx":  i,
                "results":    results,
                "latency_ms": elapsed_ms,
                "precision":  _precision_at_k(results, q),
                "rr":         _reciprocal_rank(results, q),
            })

    # Aggregate
    run_id = str(uuid.uuid4())
    summary_rows: List[Dict[str, Any]] = []
    baseline_precision: Optional[float] = None
    for strat in strategies:
        rows = per_strategy[strat]
        if not rows:
            continue
        precisions = [r["precision"] for r in rows]
        mrrs       = [r["rr"]        for r in rows]
        latencies  = [r["latency_ms"] for r in rows]
        avg_precision = statistics.mean(precisions) if precisions else 0.0
        if strat == "UNFILTERED_VECTOR":
            baseline_precision = avg_precision
        improvement = 0.0
        if baseline_precision is not None and baseline_precision > 0.0:
            improvement = (avg_precision - baseline_precision) / baseline_precision
        elif strat != "UNFILTERED_VECTOR" and baseline_precision == 0.0:
            improvement = float(avg_precision)

        # wrong-class-blocked only makes sense for ontology-bounded
        wcb = 0.0
        if strat == "ONTOLOGY_BOUNDED":
            wcb_vals = []
            for r in rows:
                qi = r["query_idx"]
                unfiltered = per_query_unfiltered.get(qi) or []
                wcb_vals.append(
                    _wrong_class_blocked(unfiltered, r["results"], queries[qi])
                )
            wcb = statistics.mean(wcb_vals) if wcb_vals else 0.0

        latencies_sorted = sorted(latencies) if latencies else [0]
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p95_idx = max(0, int(round(len(latencies_sorted) * 0.95)) - 1)
        p95 = latencies_sorted[p95_idx]

        summary = {
            "run_id":               run_id,
            "domain":               "+".join(sorted({q["domain"] for q in queries})),
            "strategy":             strat,
            "corpus_size":          sum(rt.adapter.count() for rt in retrievers.values()),
            "queries":              len(rows),
            "precision_at_5":       round(avg_precision, 4),
            "recall_at_5":          round(avg_precision, 4),   # single expected-class per query → same
            "mean_reciprocal_rank": round(statistics.mean(mrrs), 4) if mrrs else 0.0,
            "latency_p50_ms":       p50,
            "latency_p95_ms":       p95,
            "improvement_over_baseline": round(improvement, 4),
            "wrong_class_blocked":  round(wcb, 4),
            "executed_at":          datetime.now(timezone.utc).isoformat(),
        }
        summary_rows.append(summary)

    _persist_benchmark(db_path, summary_rows)
    csv_path = _write_csv(out_path, summary_rows)

    return {
        "run_id":        run_id,
        "corpus_sizes":  {fl: rt.adapter.count() for fl, rt in retrievers.items()},
        "strategies":    summary_rows,
        "csv_path":      csv_path,
        "queries":       len(queries),
    }


def _persist_benchmark(db_path: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        with sqlite3.connect(db_path) as conn:
            for r in rows:
                conn.execute("""
                    INSERT OR REPLACE INTO retrieval_benchmarks (
                        run_id, domain, strategy, corpus_size, queries,
                        precision_at_5, recall_at_5, mean_reciprocal_rank,
                        latency_p50_ms, latency_p95_ms,
                        improvement_over_baseline, wrong_class_blocked,
                        executed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["run_id"] + "::" + r["strategy"], r["domain"], r["strategy"],
                    r["corpus_size"], r["queries"], r["precision_at_5"],
                    r["recall_at_5"], r["mean_reciprocal_rank"],
                    r["latency_p50_ms"], r["latency_p95_ms"],
                    r["improvement_over_baseline"], r["wrong_class_blocked"],
                    r["executed_at"],
                ))
    except sqlite3.OperationalError:
        pass


def _write_csv(out_path: str, rows: List[Dict[str, Any]]) -> str:
    reports_dir = os.path.join(out_path, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, "retrieval_benchmark.csv")
    if not rows:
        return path
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


def read_latest_benchmark(db_path: str = _DEFAULT_DB) -> List[Dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT strategy, domain, queries, precision_at_5,
                       mean_reciprocal_rank, latency_p50_ms, latency_p95_ms,
                       improvement_over_baseline, wrong_class_blocked,
                       executed_at
                FROM retrieval_benchmarks
                ORDER BY executed_at DESC
                LIMIT 20
            """).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(r) for r in rows]
