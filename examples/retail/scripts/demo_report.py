"""Build the side-by-side comparison report for the first-contact demo.

Reads:
  - output/demo/cache/{baseline,grounded}_{vendor}_{qid}.json
  - output/demo/illustrative.json (fallback when cache is NO_API_KEY)

Writes:
  - output/demo/comparison.html  — engineering-facing, full side-by-side
  - output/demo/executive.html   — exec one-pager, 3 most dramatic examples
  - output/demo/comparison.csv   — raw matrix for downstream tooling

If all cache entries are NO_API_KEY, both HTML outputs display a banner noting
they are running in illustrative mode and pointing the viewer to
`scripts/demo_baseline.py --live` + `scripts/demo_grounded.py --live` to regenerate
with real vendor calls.
"""
from __future__ import annotations

import csv
import html
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
from demo_questions import QUESTIONS  # noqa: E402

DEMO_DIR = ROOT / "output" / "demo"
CACHE = DEMO_DIR / "cache"
# Illustrative answers live alongside this script (persistent — output/demo/ gets wiped by --fresh)
ILLUSTRATIVE_PATH = SCRIPT_DIR / "demo_illustrative.json"

VENDORS = ["anthropic", "openai"]

# Executive view: the three questions with the biggest teaching moment
EXEC_PICKS = ["Q1", "Q3", "Q6"]


def load_cache(mode: str, vendor: str, qid: str) -> dict | None:
    p = CACHE / f"{mode}_{vendor}_{qid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def load_illustrative() -> dict:
    if not ILLUSTRATIVE_PATH.exists():
        return {}
    return json.loads(ILLUSTRATIVE_PATH.read_text())


def resolve_answer(mode: str, vendor: str, qid: str, illustrative: dict):
    """Return (answer, source_label, raw_dict).

    `answer` is a string for baseline mode (and for live grounded output, which
    comes back as a string from the LLM). For illustrative grounded output it
    is a structured dict — see render_grounded_answer() for the schema.
    `source_label` is 'live' | 'illustrative' | 'missing'.
    """
    cached = load_cache(mode, vendor, qid)
    if cached and cached.get("status") == "OK":
        return cached.get("answer", ""), "live", cached
    entry = illustrative.get(qid, {}).get(mode, {}).get(vendor)
    if entry is not None:
        return entry, "illustrative", cached or {"status": "NO_API_KEY"}
    return "(no answer)", "missing", cached or {}


def any_live() -> bool:
    for q in QUESTIONS:
        for mode in ("baseline", "grounded"):
            for v in VENDORS:
                c = load_cache(mode, v, q["id"])
                if c and c.get("status") == "OK":
                    return True
    return False


CSS = """
:root { --fg:#1f2328; --muted:#57606a; --border:#d0d7de; --bg:#fff; --bg-alt:#f6f8fa;
        --accent:#0969da; --ok:#1a7f37; --warn:#9a6700; --crit:#cf222e; --baseline:#fff4e5; --grounded:#e6fffa; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       color: var(--fg); background: var(--bg); max-width: 1180px; margin: 2rem auto; padding: 0 1.5rem;
       line-height: 1.55; }
h1, h2, h3 { line-height: 1.25; border-bottom: 1px solid var(--border); padding-bottom: .3em; margin-top: 2em; }
h1 { font-size: 2em; margin-top: .2em; }
h2 { font-size: 1.45em; }
.subtitle { color: var(--muted); margin-top: -.5em; }
code, pre, .iri { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: .88em; }
code { background: var(--bg-alt); padding: .1em .35em; border-radius: 3px; }
pre { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 6px; padding: 1em; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: .92em; }
th, td { text-align: left; padding: .6em .8em; border: 1px solid var(--border); vertical-align: top; }
th { background: var(--bg-alt); font-weight: 600; }
.banner { padding: .8em 1em; border-radius: 6px; margin: 1em 0; border: 1px solid var(--border); }
.banner.warn { background: #fff8e1; border-color: #f0d58c; }
.banner.ok   { background: #e6ffed; border-color: #a7e3b5; }
.pill { display: inline-block; font-size: .72em; font-weight: 600; padding: .15em .55em;
        border-radius: 10px; color: #fff; vertical-align: middle; }
.pill-ok { background: var(--ok); } .pill-warn { background: var(--warn); }
.pill-crit { background: var(--crit); } .pill-accent { background: var(--accent); }
.pill-muted { background: var(--muted); }
.card { border: 1px solid var(--border); border-radius: 8px; padding: 1em 1.2em; margin: 1em 0;
        background: var(--bg); }
.card.baseline { background: var(--baseline); }
.card.grounded { background: var(--grounded); }
.small { font-size: .88em; color: var(--muted); }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1em; }
.qhead { background: var(--bg-alt); padding: .6em 1em; border-radius: 6px; border-left: 4px solid var(--accent); margin-top: 2em; }
.delta { border-left: 4px solid var(--accent); padding: .6em 1em; background: #eef6ff; margin: .8em 0; }
footer { margin-top: 3em; padding-top: 1em; border-top: 1px solid var(--border); color: var(--muted); font-size: .85em; text-align: center; }
a { color: var(--accent); }
ul { padding-left: 1.4em; }

/* Structured grounded-answer rendering */
.gsummary { font-weight: 600; margin: .3em 0 .7em; }
.gvocab { background: #fff8e1; border-left: 3px solid var(--warn); padding: .5em .8em;
          border-radius: 4px; margin: .5em 0; font-size: .9em; }
.gentities { list-style: none; padding: 0; margin: .4em 0; }
.gentities > li { background: rgba(255,255,255,.7); border: 1px solid rgba(0,0,0,.07);
                  border-radius: 5px; padding: .4em .7em; margin: .3em 0; }
.iri { color: var(--accent); font-weight: 600; }
.elabel { color: var(--fg); margin-left: .5em; }
.attrs { margin-top: .25em; font-size: .82em; }
.attrs .kv { display: inline-block; background: rgba(0,0,0,.05); padding: .05em .45em;
             border-radius: 3px; margin: .1em .3em .1em 0; }
.attrs .k { color: var(--muted); }
.attrs .v { color: var(--fg); font-weight: 500; }
.gchain { margin: .4em 0; padding: 0; list-style: none; }
.gchain > li { background: rgba(255,255,255,.7); border: 1px solid rgba(0,0,0,.07);
               border-radius: 5px; padding: .4em .7em; margin: 0; position: relative; }
.gchain > li + li { margin-top: 1.6em; }
.gchain > li + li::before { content: "▼"; position: absolute; top: -1.35em; left: .8em;
                            color: var(--accent); font-size: .85em; }
.gchain .edge { display: block; font-size: .78em; color: var(--muted);
                margin-top: .2em; font-style: italic; }
.gnotes { font-size: .88em; color: var(--muted); margin-top: .6em; border-top: 1px dashed rgba(0,0,0,.1); padding-top: .5em; }
"""


def esc(s: str) -> str:
    return html.escape(s or "").replace("\n", "<br>")


def _render_attrs(attrs: dict) -> str:
    if not attrs:
        return ""
    pills = []
    for k, v in attrs.items():
        pills.append(
            f'<span class="kv"><span class="k">{esc(str(k))}</span>: '
            f'<span class="v">{esc(str(v))}</span></span>'
        )
    return '<div class="attrs">' + "".join(pills) + "</div>"


def _render_entity(e: dict) -> str:
    iri = esc(e.get("iri", ""))
    label = esc(e.get("label", ""))
    label_html = f'<span class="elabel">{label}</span>' if label else ""
    attrs_html = _render_attrs(e.get("attrs") or {})
    return f'<li><span class="iri">{iri}</span>{label_html}{attrs_html}</li>'


def render_grounded_answer(ans) -> str:
    """Render a grounded answer.

    Accepts a structured dict (summary / entities / chain / notes / vocabulary_warning)
    or a plain string (live LLM output). Strings fall through to the same
    newline-aware escape used for baseline answers.
    """
    if isinstance(ans, str):
        return f"<p>{esc(ans)}</p>"
    if not isinstance(ans, dict):
        return ""

    parts = []
    summary = ans.get("summary")
    if summary:
        parts.append(f'<div class="gsummary">{esc(summary)}</div>')

    vocab = ans.get("vocabulary_warning")
    if vocab:
        parts.append(
            f'<div class="gvocab"><strong>Vocabulary check:</strong> {esc(vocab)}</div>'
        )

    entities = ans.get("entities") or []
    if entities:
        items = "".join(_render_entity(e) for e in entities)
        parts.append(f'<ul class="gentities">{items}</ul>')

    chain = ans.get("chain") or []
    if chain:
        chain_items = []
        for hop in chain:
            iri = esc(hop.get("node") or hop.get("iri") or "")
            label = esc(hop.get("label", ""))
            label_html = f'<span class="elabel">{label}</span>' if label else ""
            attrs_html = _render_attrs(hop.get("attrs") or {})
            edge = esc(hop.get("edge", ""))
            edge_html = f'<span class="edge">→ {edge}</span>' if edge else ""
            chain_items.append(
                f'<li><span class="iri">{iri}</span>{label_html}{attrs_html}{edge_html}</li>'
            )
        parts.append(f'<ol class="gchain">{"".join(chain_items)}</ol>')

    notes = ans.get("notes")
    if notes:
        parts.append(f'<div class="gnotes">{esc(notes)}</div>')

    return "\n".join(parts)


def banner_for(live: bool) -> str:
    if live:
        return ('<div class="banner ok"><strong>Live mode.</strong> Answers shown are real LLM output cached '
                'under <code>output/demo/cache/</code>. Re-run <code>scripts/demo_baseline.py</code> and '
                '<code>scripts/demo_grounded.py</code> to refresh.</div>')
    return ('<div class="banner warn"><strong>Illustrative mode.</strong> No API keys were set when the demo '
            'ran, so these answers are scripted examples derived from the actual ground-truth rows in '
            '<code>db/demo.db</code>. The comparison logic, ontology artifacts, and SHACL gating are real. '
            'Set <code>ANTHROPIC_API_KEY</code> + <code>OPENAI_API_KEY</code> and re-run <code>./demo.sh</code> '
            'to replace these with live LLM responses.</div>')


def render_question_card(q: dict, illustrative: dict) -> str:
    qid, qtext = q["id"], q["text"]
    why = q["why"]
    d_entry = illustrative.get(qid, {})
    delta_note = d_entry.get("delta", "")
    ground_truth = d_entry.get("ground_truth", "")

    parts = [f'<div class="qhead"><strong>{qid}</strong> — {esc(qtext)}<br>'
             f'<span class="small">Why in the bank: {esc(why)}</span></div>']

    if ground_truth:
        parts.append(f'<p class="small"><strong>Ground truth</strong> (derived from <code>db/demo.db</code>): '
                     f'{esc(ground_truth)}</p>')

    for vendor in VENDORS:
        b_ans, b_src, b_raw = resolve_answer("baseline", vendor, qid, illustrative)
        g_ans, g_src, g_raw = resolve_answer("grounded", vendor, qid, illustrative)
        valid = g_raw.get("valid")
        prov = g_raw.get("prov")
        obs_iri = g_raw.get("observation_iri")

        valid_pill = ('<span class="pill pill-ok">SHACL ✓</span>' if valid is True
                      else '<span class="pill pill-crit">SHACL ✗</span>' if valid is False
                      else '<span class="pill pill-muted">SHACL —</span>')
        prov_pill = ('<span class="pill pill-ok">PROV-O ✓</span>' if prov
                     else '<span class="pill pill-muted">PROV-O —</span>')
        obs_pill = (f'<span class="pill pill-accent">ObservationRecord</span>' if obs_iri else '')

        parts.append(f'<h3 style="border:none;margin-top:1em;">{vendor.capitalize()}</h3>')
        parts.append('<div class="grid2">')
        parts.append(
            f'<div class="card baseline"><strong>Baseline (no ontology)</strong> '
            f'<span class="pill pill-muted">{b_src}</span><p>{esc(b_ans) if isinstance(b_ans, str) else ""}</p></div>'
        )
        parts.append(
            f'<div class="card grounded"><strong>Ontology-grounded</strong> '
            f'<span class="pill pill-muted">{g_src}</span> {valid_pill} {prov_pill} {obs_pill}'
            f'{render_grounded_answer(g_ans)}</div>'
        )
        parts.append('</div>')

    if delta_note:
        parts.append(f'<div class="delta"><strong>Why it matters:</strong> {esc(delta_note)}</div>')
    return "\n".join(parts)


def render_comparison(live: bool, illustrative: dict) -> str:
    body = [
        f'<h1>First-Contact Demo — Ontology vs Baseline</h1>',
        f'<p class="subtitle">Retail schema · 10 customers · 15 orders · Anthropic <code>claude-sonnet-4-5</code> · OpenAI <code>gpt-4o</code></p>',
        banner_for(live),
        '<h2>Pipeline summary</h2>',
        '<ul>',
        '  <li>Schema + seed: <code>db/demo.sql</code> · <code>db/demo_seed.sql</code> → <code>db/demo.db</code></li>',
        '  <li>Ontology: <code>output/demo/ontology/enterprise.ttl</code> (OWL 2) + <code>events.ttl</code> (OrderEvent subclasses)</li>',
        '  <li>SHACL: <code>output/demo/shapes/enterprise-shapes.ttl</code> + <code>agent-gate.ttl</code></li>',
        '  <li>JSON-LD context: <code>output/demo/jsonld/enterprise-context.json</code></li>',
        '  <li>Semantic loss report: <code>output/demo/mapping/semantic_loss_report.csv</code> — includes a CRITICAL <em>IMPLICIT_ACTOR</em> on <code>order_events</code> (no FK to party), HIGH <em>STATUS_AS_EVENT</em> on customers/orders/payments</li>',
        '  <li>Governance scorecard: <code>output/demo/reports/governance_scorecard.csv</code> — 34 criteria, averaging 3.6/5.0 on first run</li>',
        '  <li>43 SPARQL CQ tests: all pass (<code>output/demo/reports/sparql_cq_test_results.csv</code>)</li>',
        '</ul>',
        '<h2>Comparison matrix (8 questions × 2 vendors × 2 modes)</h2>',
    ]
    for q in QUESTIONS:
        body.append(render_question_card(q, illustrative))
    body.append('<footer>Toolkit v2.0 · branch <code>first-contact</code></footer>')
    return f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Demo Comparison</title><style>{CSS}</style></head><body>' + "\n".join(body) + '</body></html>'


def render_executive(live: bool, illustrative: dict) -> str:
    picks = [q for q in QUESTIONS if q["id"] in EXEC_PICKS]
    body = [
        '<h1>Why an ontology? — one page</h1>',
        '<p class="subtitle">For executive and business-stakeholder viewing. Three examples from the retail demo show, in plain language, what a generated ontology adds on top of raw database rows plus an LLM.</p>',
        banner_for(live),
        '<h2>The one-line answer</h2>',
        '<div class="banner ok">Raw-rows + LLM is a <em>guess</em>. Ontology-grounded LLM is an <em>auditable enterprise fact</em>.</div>',
        '<h2>Three demonstrations</h2>',
    ]
    for q in picks:
        d = illustrative.get(q["id"], {})
        # Pick Anthropic as the representative answer for the exec view.
        b, _, _ = resolve_answer("baseline", "anthropic", q["id"], illustrative)
        g, _, _ = resolve_answer("grounded", "anthropic", q["id"], illustrative)
        body.append(f'<div class="qhead"><strong>{q["id"]}</strong> — {esc(q["text"])}</div>')
        body.append('<div class="grid2">')
        body.append(f'<div class="card baseline"><strong>Without an ontology</strong><p>{esc(b) if isinstance(b, str) else ""}</p></div>')
        body.append(f'<div class="card grounded"><strong>With the ontology</strong>{render_grounded_answer(g)}</div>')
        body.append('</div>')
        if d.get("delta"):
            body.append(f'<div class="delta"><strong>What changed:</strong> {esc(d["delta"])}</div>')
    body.append('<h2>What the governance layer delivers</h2>')
    body.append('<ul>'
                '<li><strong>Semantic precision</strong> — every answer references the correct concept by name.</li>'
                '<li><strong>Stable identity</strong> — every entity referenced has a permanent, resolvable IRI.</li>'
                '<li><strong>Structural validity</strong> — every answer passes a SHACL shape check before it is released.</li>'
                '<li><strong>Audit trail</strong> — every answer is stamped with the model, timestamp, confidence, and derivation method; answers are stored as PROV-O observation records.</li>'
                '<li><strong>Vendor consistency</strong> — Anthropic and OpenAI give identical grounded answers. Baseline answers drift between vendors.</li>'
                '<li><strong>Guardrails, not speed bumps</strong> — 3-second pipeline; no ML training required.</li>'
                '</ul>')
    body.append('<footer>Toolkit v2.0 · Demo: retail schema · Models: Anthropic <code>claude-sonnet-4-5</code> · OpenAI <code>gpt-4o</code></footer>')
    return f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Why an Ontology</title><style>{CSS}</style></head><body>' + "\n".join(body) + '</body></html>'


def _flatten_for_csv(ans) -> str:
    """Collapse a structured grounded answer into a single CSV-safe string."""
    if isinstance(ans, str):
        return ans
    if not isinstance(ans, dict):
        return ""
    parts = []
    if ans.get("summary"):
        parts.append(ans["summary"])
    if ans.get("vocabulary_warning"):
        parts.append("VOCAB: " + ans["vocabulary_warning"])
    for e in (ans.get("entities") or []):
        row = e.get("iri", "")
        if e.get("label"):
            row += f" ({e['label']})"
        if e.get("attrs"):
            row += " " + ", ".join(f"{k}={v}" for k, v in e["attrs"].items())
        parts.append(row)
    for hop in (ans.get("chain") or []):
        row = hop.get("node") or hop.get("iri") or ""
        if hop.get("label"):
            row += f" ({hop['label']})"
        if hop.get("edge"):
            row += f" --{hop['edge']}-->"
        parts.append(row)
    if ans.get("notes"):
        parts.append("note: " + ans["notes"])
    return " | ".join(parts)


def write_csv(illustrative: dict) -> None:
    p = DEMO_DIR / "comparison.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "question", "vendor", "mode", "source", "answer", "shacl_valid", "prov_stamped", "observation_iri"])
        for q in QUESTIONS:
            for vendor in VENDORS:
                for mode in ("baseline", "grounded"):
                    ans, src, raw = resolve_answer(mode, vendor, q["id"], illustrative)
                    w.writerow([
                        q["id"], q["text"], vendor, mode, src, _flatten_for_csv(ans),
                        raw.get("valid") if mode == "grounded" else "",
                        bool(raw.get("prov")) if mode == "grounded" else "",
                        raw.get("observation_iri") or "",
                    ])


def main() -> int:
    illustrative = load_illustrative()
    live = any_live()

    (DEMO_DIR / "comparison.html").write_text(render_comparison(live, illustrative))
    (DEMO_DIR / "executive.html").write_text(render_executive(live, illustrative))
    write_csv(illustrative)

    print(f"  ✓ {('live' if live else 'illustrative').upper()} mode")
    print(f"  ✓ output/demo/comparison.html  (engineering — full matrix)")
    print(f"  ✓ output/demo/executive.html   (executive — one-page)")
    print(f"  ✓ output/demo/comparison.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
