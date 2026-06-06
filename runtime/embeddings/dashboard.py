"""
runtime.embeddings.dashboard — Workstream 5 reporting helpers
==============================================================
Writes an HTML + CSV summary of the embedding indexes and the latest
benchmark run so the toolkit HTML report and the browser wizard
"Retrieval" tab share a single rendering path.
"""

from __future__ import annotations

import csv
import html
import os
from typing import Any, Dict, List, Optional

from .pipeline  import list_indexes
from .benchmark import read_latest_benchmark


def _cell(v: Any) -> str:
    return html.escape(str(v)) if v is not None else ""


def write_summary(
    *,
    out_path: str,
    db_path: str,
) -> Dict[str, str]:
    """Emit ``retrieval_summary.html`` + ``retrieval_indexes.csv``."""
    reports_dir = os.path.join(out_path, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    html_path = os.path.join(reports_dir, "retrieval_summary.html")
    csv_path  = os.path.join(reports_dir, "retrieval_indexes.csv")

    indexes = list_indexes(db_path)
    bench   = read_latest_benchmark(db_path)

    # CSV — per-index snapshot
    if indexes:
        with open(csv_path, "w", newline="") as f:
            fieldnames = [
                "index_name", "flavor", "vector_store", "model_id",
                "dimensions", "record_count", "max_sensitivity",
                "last_indexed_at",
            ]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for i in indexes:
                w.writerow({k: i.get(k) for k in fieldnames})

    # HTML
    body_parts: List[str] = []
    body_parts.append("<h2>Embedding Indexes</h2>")
    if not indexes:
        body_parts.append("<p><em>No indexes registered. "
                          "Run <code>python3 toolkit.py --phase embed</code>.</em></p>")
    else:
        body_parts.append(
            "<table><thead><tr>"
            "<th>Index</th><th>Flavor</th><th>Store</th><th>Model</th>"
            "<th>Dims</th><th>Records</th><th>Tier</th>"
            "<th>Last indexed</th>"
            "</tr></thead><tbody>"
        )
        for i in indexes:
            body_parts.append(
                f"<tr><td>{_cell(i['index_name'])}</td>"
                f"<td>{_cell(i['flavor'])}</td>"
                f"<td>{_cell(i['vector_store'])}</td>"
                f"<td>{_cell(i['model_id'])}</td>"
                f"<td>{_cell(i['dimensions'])}</td>"
                f"<td>{_cell(i['record_count'])}</td>"
                f"<td>{_cell(i['max_sensitivity'])}</td>"
                f"<td>{_cell(i['last_indexed_at'])}</td></tr>"
            )
        body_parts.append("</tbody></table>")

    body_parts.append("<h2>Latest Retrieval Benchmark</h2>")
    if not bench:
        body_parts.append("<p><em>No benchmark results yet. "
                          "Run <code>python3 toolkit.py --phase retrieve --benchmark</code>.</em></p>")
    else:
        body_parts.append(
            "<table><thead><tr>"
            "<th>Strategy</th><th>Domain</th><th>Queries</th>"
            "<th>Precision@5</th><th>MRR</th>"
            "<th>Latency p50 ms</th><th>Latency p95 ms</th>"
            "<th>Δ vs baseline</th><th>Wrong-class blocked</th>"
            "<th>Run at</th></tr></thead><tbody>"
        )
        for b in bench:
            body_parts.append(
                f"<tr><td>{_cell(b['strategy'])}</td>"
                f"<td>{_cell(b['domain'])}</td>"
                f"<td>{_cell(b['queries'])}</td>"
                f"<td>{_cell(b['precision_at_5'])}</td>"
                f"<td>{_cell(b['mean_reciprocal_rank'])}</td>"
                f"<td>{_cell(b['latency_p50_ms'])}</td>"
                f"<td>{_cell(b['latency_p95_ms'])}</td>"
                f"<td>{_cell(b['improvement_over_baseline'])}</td>"
                f"<td>{_cell(b['wrong_class_blocked'])}</td>"
                f"<td>{_cell(b['executed_at'])}</td></tr>"
            )
        body_parts.append("</tbody></table>")

    with open(html_path, "w") as f:
        f.write("<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Ontology-Bounded Vector Retrieval</title>"
                "<style>body{font-family:system-ui,sans-serif;margin:2em;max-width:1024px;color:#1f2937;background:#f7f9f8}"
                "h1{background:linear-gradient(135deg,#14284a,#1f3a5f);color:#fff;"
                "margin:-2em -2em 1em;padding:1em 2em;border-bottom:4px solid #7dc242}"
                "table{border-collapse:collapse;width:100%;margin:1em 0;background:#fff}"
                "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left;font-size:.9em}"
                "th{background:#eef2ef}h2{margin-top:2em;color:#14284a}</style></head><body>")
        f.write("<h1>Workstream 5 — Ontology-Bounded Vector Retrieval</h1>")
        f.write("\n".join(body_parts))
        f.write("</body></html>")

    return {"html_path": html_path, "csv_path": csv_path}
