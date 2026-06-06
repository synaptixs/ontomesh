"""
reporter.py
────────────
Generates a self-contained HTML summary report of all toolkit outputs.
  output/reports/toolkit_report.html
"""

import os
import csv
import json
from datetime import datetime


def _read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _badge(text: str, color: str) -> str:
    return (f'<span style="background:{color};color:#fff;padding:2px 8px;'
            f'border-radius:4px;font-size:11px;font-weight:bold">{text}</span>')


def _status_badge(s: str) -> str:
    colors = {"PASS": "#16a34a", "FAIL": "#dc2626", "ERROR": "#d97706",
              "CRITICAL": "#dc2626", "HIGH": "#d97706", "MEDIUM": "#2563a8", "LOW": "#64748b",
              "ORPHAN": "#dc2626", "CONNECTED": "#16a34a",
              "ISOLATED_SOURCE": "#d97706", "ISOLATED_SINK": "#2563a8"}
    return _badge(s, colors.get(s, "#64748b"))


def _score_bar(score: int) -> str:
    colors = {0: "#dc2626", 1: "#ef4444", 2: "#f97316",
              3: "#eab308", 4: "#22c55e", 5: "#16a34a"}
    pct = score * 20
    color = colors.get(score, "#64748b")
    return (f'<div style="background:#e5e7eb;border-radius:4px;height:12px;width:100px;display:inline-block;vertical-align:middle">'
            f'<div style="background:{color};width:{pct}%;height:100%;border-radius:4px"></div></div> '
            f'<span style="font-weight:bold;color:{color}">{score}/5</span>')


def generate_report(output_base: str):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    reports_dir = os.path.join(output_base, "reports")
    mapping_dir = os.path.join(output_base, "mapping")

    cq_results   = _read_csv(os.path.join(reports_dir, "cq_test_results.csv"))
    gov_scores   = _read_csv(os.path.join(reports_dir, "governance_scorecard.csv"))
    loss_report  = _read_csv(os.path.join(mapping_dir, "semantic_loss_report.csv"))
    orphan_rpt   = _read_csv(os.path.join(mapping_dir, "orphan_candidates.csv"))
    mapping_rows = _read_csv(os.path.join(mapping_dir, "logical_physical_map.csv"))

    # ── Compute summary stats ─────────────────────────────────────────
    cq_pass  = sum(1 for r in cq_results if r.get("status") == "PASS")
    cq_total = len(cq_results)
    crit_loss = sum(1 for r in loss_report if r.get("severity") == "CRITICAL")
    high_loss = sum(1 for r in loss_report if r.get("severity") == "HIGH")
    avg_score = (sum(int(s.get("score", 0)) for s in gov_scores) / max(len(gov_scores), 1))
    orphan_count = sum(1 for o in orphan_rpt if o.get("status") == "ORPHAN")
    map_count = len(mapping_rows)

    # ── HTML ──────────────────────────────────────────────────────────
    cq_rows = "".join(
        f"<tr>"
        f"<td><b>{r['cq_id']}</b></td>"
        f"<td>{_status_badge(r.get('priority',''))}</td>"
        f"<td>{_status_badge(r.get('status',''))}</td>"
        f"<td>{r.get('row_count',0)}</td>"
        f"<td style='font-size:12px'>{r.get('question','')[:80]}</td>"
        f"</tr>"
        for r in cq_results
    )

    gov_rows = "".join(
        f"<tr>"
        f"<td><b>{s.get('domain','')}</b></td>"
        f"<td style='font-size:12px'>{s.get('criterion','')}</td>"
        f"<td>{_score_bar(int(s.get('score',0)))}</td>"
        f"<td style='font-size:11px;color:#374151'>{s.get('rationale','')[:90]}</td>"
        f"</tr>"
        for s in gov_scores
    )

    loss_rows = "".join(
        f"<tr>"
        f"<td>{_status_badge(r.get('severity',''))}</td>"
        f"<td><code>{r.get('table','')}</code></td>"
        f"<td><code>{r.get('column','') or '—'}</code></td>"
        f"<td style='font-size:11px'><b>{r.get('loss_type','')}</b><br>{r.get('description','')[:100]}</td>"
        f"<td style='font-size:11px;color:#16a34a'>{r.get('remediation','')[:80]}</td>"
        f"</tr>"
        for r in loss_report
    )

    orphan_rows = "".join(
        f"<tr>"
        f"<td><b>{o.get('class_name','')}</b></td>"
        f"<td><code>{o.get('table_name','')}</code></td>"
        f"<td style='text-align:center'>{o.get('inbound_fks',0)}</td>"
        f"<td style='text-align:center'>{o.get('outbound_fks',0)}</td>"
        f"<td>{_status_badge(o.get('status',''))}</td>"
        f"</tr>"
        for o in orphan_rpt
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ontology Toolkit Report</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 0; background: #f7f9f8; color: #1f2937; }}
  .header {{ background: linear-gradient(135deg, #14284a, #1f3a5f); color: #fff; padding: 32px 40px; border-bottom: 4px solid #7dc242; }}
  .header h1 {{ margin: 0 0 6px; font-size: 28px; }}
  .header p  {{ margin: 0; opacity: .8; font-size: 14px; }}
  .content {{ padding: 32px 40px; max-width: 1200px; }}
  .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 32px; }}
  .stat {{ background: #fff; border-radius: 8px; padding: 20px; border: 1px solid #e5e7eb; text-align: center; }}
  .stat .num {{ font-size: 36px; font-weight: bold; color: #14284a; }}
  .stat .lbl {{ font-size: 12px; color: #6b7280; margin-top: 4px; }}
  .section {{ background: #fff; border-radius: 8px; border: 1px solid #e5e7eb; margin-bottom: 24px; overflow: hidden; }}
  .section-header {{ background: #14284a; color: #fff; padding: 12px 20px; font-weight: bold; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #eef2ef; padding: 8px 12px; text-align: left; font-size: 12px; border-bottom: 2px solid #e5e7eb; color: #374151; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
  tr:hover td {{ background: #f7f9f8; }}
  .files {{ padding: 16px 20px; }}
  .files ul {{ margin: 0; padding-left: 20px; }}
  .files li {{ font-size: 13px; margin-bottom: 4px; font-family: monospace; color: #1f3a5f; }}
  .footer {{ text-align: center; padding: 24px; color: #9ca3af; font-size: 12px; }}
</style>
</head>
<body>
<div class="header">
  <h1>&#127381; Ontology Toolkit — Run Report</h1>
  <p>Generated: {now} &nbsp;|&nbsp; Framework: Domain-Agnostic Ontology Engineering v1.1</p>
</div>
<div class="content">

<div class="stats">
  <div class="stat"><div class="num">{cq_pass}/{cq_total}</div><div class="lbl">CQ Tests Passed</div></div>
  <div class="stat"><div class="num">{avg_score:.1f}</div><div class="lbl">Avg Governance Score /5</div></div>
  <div class="stat"><div class="num">{len(loss_report)}</div><div class="lbl">Semantic Loss Issues<br><span style="color:#dc2626">{crit_loss} CRITICAL / {high_loss} HIGH</span></div></div>
  <div class="stat"><div class="num">{orphan_count}</div><div class="lbl">Orphan Classes</div></div>
  <div class="stat"><div class="num">{map_count}</div><div class="lbl">Mapping Rows</div></div>
</div>

<div class="section">
  <div class="section-header">&#9989; Competency Question Test Results</div>
  <table>
    <tr><th>CQ-ID</th><th>Priority</th><th>Status</th><th>Rows</th><th>Question</th></tr>
    {cq_rows}
  </table>
</div>

<div class="section">
  <div class="section-header">&#128203; Governance Scorecard (Auto-Scored Criteria)</div>
  <table>
    <tr><th>Domain</th><th>Criterion</th><th>Score</th><th>Rationale</th></tr>
    {gov_rows}
  </table>
</div>

<div class="section">
  <div class="section-header">&#9888;&#65039; Semantic Loss Report</div>
  <table>
    <tr><th>Severity</th><th>Table</th><th>Column</th><th>Finding</th><th>Remediation</th></tr>
    {loss_rows if loss_rows else '<tr><td colspan="5" style="text-align:center;color:#16a34a">No semantic loss issues detected.</td></tr>'}
  </table>
</div>

<div class="section">
  <div class="section-header">&#128279; Relationship Graph — Orphan Analysis</div>
  <table>
    <tr><th>Class</th><th>Table</th><th>Inbound FKs</th><th>Outbound FKs</th><th>Status</th></tr>
    {orphan_rows}
  </table>
</div>

<div class="section">
  <div class="section-header">&#128194; Generated Artifacts</div>
  <div class="files">
    <ul>
      <li>output/ontology/enterprise.ttl — Primary OWL 2 ontology</li>
      <li>output/ontology/events.ttl — Event subclass hierarchy</li>
      <li>output/ontology/provenance.ttl — PROV-O provenance patterns</li>
      <li>output/shapes/enterprise-shapes.ttl — SHACL NodeShapes (all classes)</li>
      <li>output/shapes/agent-gate.ttl — Agent acceptance gate</li>
      <li>output/vocab/enterprise-skos.ttl — SKOS terminology scheme</li>
      <li>output/jsonld/enterprise-context.json — JSON-LD context</li>
      <li>output/jsonld/sample-observation-payload.json — Sample agent payload</li>
      <li>output/jsonld/sample-event-payload.json — Sample event payload</li>
      <li>output/jsonld/mcp-tool-definitions.json — MCP tool definitions</li>
      <li>output/mapping/logical_physical_map.csv — Logical/physical mapping workbook</li>
      <li>output/mapping/semantic_loss_report.csv — Semantic loss findings</li>
      <li>output/mapping/orphan_candidates.csv — Orphan class analysis</li>
      <li>output/reports/cq_test_results.csv — CQ test results</li>
      <li>output/reports/governance_scorecard.csv — Governance checklist scores</li>
      <li>output/reports/toolkit_report.html — This report</li>
    </ul>
  </div>
</div>

</div>
<div class="footer">Ontology Toolkit v1.0 &nbsp;|&nbsp; Framework v1.1 &nbsp;|&nbsp; {now}</div>
</body>
</html>"""

    # TMF sections
    tmf_cq  = _read_csv(os.path.join(reports_dir, "tmf_cq_test_results.csv"))
    tmf_api = _read_csv(os.path.join(mapping_dir, "tmf_api_coverage.csv"))
    tmf_cq_pass = sum(1 for r in tmf_cq  if r.get("status") == "PASS")
    tmf_api_cov = sum(1 for r in tmf_api if r.get("covered_in_schema") == "YES")

    tmf_cq_rows = "".join(
        f"<tr><td><b>{r['cq_id']}</b></td><td>{_status_badge(r.get('priority',''))}</td>"
        f"<td>{_status_badge(r.get('status',''))}</td><td>{r.get('row_count',0)}</td>"
        f"<td style='font-size:12px'>{r.get('question','')[:80]}</td></tr>"
        for r in tmf_cq
    ) if tmf_cq else "<tr><td colspan='5' style='text-align:center;color:#6b7280'>No TMF CQ results yet — run: python3 toolkit.py --phase tmf</td></tr>"

    tmf_api_rows = "".join(
        f"<tr><td><b>{r.get('tmf_api_id','')}</b></td>"
        f"<td style='font-size:12px'>{r.get('api_name','')}</td>"
        f"<td>{r.get('version','')}</td><td>{r.get('sid_domain','')}</td>"
        f"<td>{r.get('sid_class','')}</td>"
        f"<td>{'&#9989;' if r.get('covered_in_schema')=='YES' else '&#10060;'}</td>"
        f"<td><code style='font-size:11px'>{r.get('schema_table','') or chr(8212)}</code></td></tr>"
        for r in tmf_api
    ) if tmf_api else "<tr><td colspan='7' style='text-align:center;color:#6b7280'>No TMF API coverage data yet</td></tr>"

    tmf_sections = (
        f'''<div class="section">'''
        f'''<div class="section-header">&#128225; TM Forum &#8212; {tmf_cq_pass}/{len(tmf_cq)} TMF CQ Tests Passed (SID + Open API aligned)</div>'''
        f'''<table><tr><th>CQ-ID</th><th>Priority</th><th>Status</th><th>Rows</th><th>Question</th></tr>{tmf_cq_rows}</table></div>'''
        f'''<div class="section">'''
        f'''<div class="section-header">&#128279; TMF Open API Coverage &#8212; {tmf_api_cov}/{len(tmf_api)} APIs Mapped (SID v23.0)</div>'''
        f'''<table><tr><th>API</th><th>Name</th><th>Version</th><th>SID Domain</th><th>SID Class</th><th>In Schema</th><th>Table</th></tr>{tmf_api_rows}</table></div>'''
    )
    html = html.replace('<div class="footer">', tmf_sections + '<div class="footer">')

    report_path = os.path.join(reports_dir, "toolkit_report.html")
    with open(report_path, "w") as f:
        f.write(html)
    print(f"  ✓ HTML report           → {report_path}")
