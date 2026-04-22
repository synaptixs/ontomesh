"""
compliance.dashboard — Workstream 4, Component 5
=================================================
Compliance summary report helpers.

Generates two artefacts alongside the standard toolkit HTML report
whenever :func:`write_summary` is invoked:

  * ``output/reports/compliance_summary.csv`` — per-regulation coverage
  * ``output/reports/compliance_summary.html`` — human-readable rollup
                                                 with traffic-light
                                                 indicators per
                                                 requirement.

Consumed by ``src/reporter.py`` on every pipeline run and by the
browser wizard's Compliance Dashboard tab.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import assembler, mapping, registry

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


def _light(coverage: int) -> str:
    return "green" if coverage >= 80 else ("amber" if coverage >= 50 else "red")


def write_summary(
    *,
    out_path: str,
    db_path: str,
) -> Dict[str, Any]:
    reports = os.path.join(out_path, "reports")
    os.makedirs(reports, exist_ok=True)

    per_reg: List[Dict[str, Any]] = []
    for item in registry.list_regulations():
        try:
            ev = assembler.assemble_evidence(
                regulation_id=item["regulation_id"],
                decision_iri=None,
                db_path=db_path,
                out_path=out_path,
            )
        except (ValueError, OSError):
            continue
        per_reg.append({
            "regulation_id":  ev["regulation_id"],
            "name":           ev["name"],
            "jurisdiction":   ev["jurisdiction"],
            "effective_date": ev.get("effective_date"),
            "coverage":       ev["summary"]["coverage_percent"],
            "satisfied":      ev["summary"]["satisfied"],
            "total":          ev["summary"]["total_requirements"],
            "light":          _light(ev["summary"]["coverage_percent"]),
            "evidence":       ev["evidence"],
        })

    csv_path = os.path.join(reports, "compliance_summary.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["regulation_id", "name", "jurisdiction",
                    "effective_date", "coverage_percent",
                    "satisfied", "total", "traffic_light"])
        for r in per_reg:
            w.writerow([r["regulation_id"], r["name"], r["jurisdiction"],
                        r["effective_date"], r["coverage"],
                        r["satisfied"], r["total"], r["light"]])

    html_path = os.path.join(reports, "compliance_summary.html")
    with open(html_path, "w") as f:
        f.write(_render_html(per_reg))

    return {
        "ok":           True,
        "regulations":  len(per_reg),
        "csv_path":     csv_path,
        "html_path":    html_path,
    }


_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Compliance Evidence Summary</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 24px;
         color: #24292f; }}
  h1 {{ border-bottom: 2px solid #d0d7de; padding-bottom: 8px; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 32px; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: left;
            vertical-align: top; }}
  th {{ background: #f6f8fa; }}
  .light {{ display: inline-block; width: 14px; height: 14px;
            border-radius: 50%; vertical-align: middle; margin-right: 6px; }}
  .green {{ background: #3fb950; }}
  .amber {{ background: #d29922; }}
  .red   {{ background: #f85149; }}
  .status-SATISFIED     {{ color: #1a7f37; }}
  .status-INSUFFICIENT  {{ color: #a40e26; }}
  .status-NOT_APPLICABLE {{ color: #6e7781; }}
  .status-MISSING       {{ color: #a40e26; }}
  code {{ background: #f6f8fa; padding: 0 4px; border-radius: 3px; }}
  .meta {{ color: #6e7781; font-size: 13px; margin-bottom: 16px; }}
</style>
</head><body>
<h1>Regulatory Compliance Evidence Summary</h1>
<p class="meta">Generated {ts}. Part of the toolkit governance pipeline — see <code>output/reports/governance_scorecard.csv</code> for scorecard rows.</p>

<h2>Coverage overview</h2>
<table>
  <thead><tr>
    <th>Regulation</th><th>Jurisdiction</th><th>Effective</th>
    <th>Coverage</th><th>Satisfied</th><th>Light</th>
  </tr></thead>
  <tbody>{overview_rows}</tbody>
</table>

{per_regulation}
</body></html>
"""


def _render_html(per_reg: List[Dict[str, Any]]) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    if not per_reg:
        overview_rows = "<tr><td colspan=6><em>No regulations loaded.</em></td></tr>"
    else:
        overview_rows = "\n".join(
            f"<tr><td>{r['name']} <code>[{r['regulation_id']}]</code></td>"
            f"<td>{r['jurisdiction']}</td>"
            f"<td>{r.get('effective_date') or ''}</td>"
            f"<td>{r['coverage']}%</td>"
            f"<td>{r['satisfied']}/{r['total']}</td>"
            f"<td><span class='light {r['light']}'></span>{r['light']}</td>"
            "</tr>"
            for r in per_reg
        )
    blocks: List[str] = []
    for r in per_reg:
        rows = "\n".join(
            f"<tr><td><code>{e['req_id']}</code></td>"
            f"<td>{e['title']}</td>"
            f"<td class='status-{e['status']}'>{e['status']}</td>"
            f"<td><code>{e['artefact_type']}:{e['evidence_selector']}</code></td>"
            f"<td>{e.get('note', '')}</td></tr>"
            for e in r["evidence"]
        )
        blocks.append(
            f"<h2>{r['name']}</h2>"
            f"<p class='meta'>Coverage {r['coverage']}% — "
            f"{r['satisfied']}/{r['total']} requirements satisfied.</p>"
            "<table><thead><tr><th>Req</th><th>Title</th>"
            "<th>Status</th><th>Artefact</th><th>Note</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table>"
        )
    return _HTML_TEMPLATE.format(
        ts=ts,
        overview_rows=overview_rows,
        per_regulation="\n".join(blocks),
    )
