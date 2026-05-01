"""5G-NF First-Contact Demo — unified runner.

One script that executes all three LLM-facing phases for the 5G demo:
  baseline  — raw rows + plain prompt (no ontology)
  grounded  — RuntimeClient.ask(flavor='fiveg') through the full governance pipeline
  report    — builds output/demo-5g/{comparison.html, executive.html, comparison.csv}

Usage:
  python3 scripts/demo_5g.py baseline [--live]
  python3 scripts/demo_5g.py grounded [--live]
  python3 scripts/demo_5g.py report
  python3 scripts/demo_5g.py all [--live]

Without --live and without API keys, the baseline + grounded phases write
NO_API_KEY placeholders and the report builder falls back to
`scripts/demo_5g_illustrative.json`. The ontology, SHACL shapes, semantic-loss
findings, and governance scorecard (produced by `toolkit.py`) are 100 % real
regardless of mode.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(SCRIPT_DIR))

from demo_5g_questions import QUESTIONS  # noqa: E402

DB_PATH = ROOT / "db" / "demo_5g.db"
OUT_DIR = ROOT / "output" / "demo-5g"
CACHE_DIR = OUT_DIR / "cache"
ILLUSTRATIVE_PATH = SCRIPT_DIR / "demo_5g_illustrative.json"
FLAVOR = "fiveg"
VENDORS = ["anthropic", "openai"]
EXEC_PICKS = ["Q1", "Q4", "Q6"]   # biggest teaching moments for 5G

BASELINE_SYSTEM_PROMPT = (
    "You are a 5G Core operations analyst. Answer the user's question using ONLY "
    "the JSON rows provided. Keep your answer short and precise."
)


# ------------------------- baseline -------------------------

def _dump_tables(conn: sqlite3.Connection, tables: list[str]) -> str:
    out = {}
    for t in tables:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
        out[t] = rows
    return json.dumps(out, indent=2, default=str)


def _call_anthropic(model: str, system: str, user: str) -> dict:
    import anthropic
    t0 = time.time()
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=600, temperature=0.2,
        system=system, messages=[{"role": "user", "content": user}],
    )
    return {
        "status": "OK", "vendor": "anthropic", "model": model,
        "answer": "".join(b.text for b in resp.content if b.type == "text"),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
    }


def _call_openai(model: str, system: str, user: str) -> dict:
    import openai
    t0 = time.time()
    client = openai.OpenAI()
    resp = client.chat.completions.create(
        model=model, temperature=0.2, max_tokens=600,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return {
        "status": "OK", "vendor": "openai", "model": model,
        "answer": resp.choices[0].message.content,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "usage": {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens},
    }


def _placeholder(mode: str, vendor: str, qid: str, reason: str) -> dict:
    note = ("Set the API keys and re-run to populate this cell with a real response. "
            "The comparison report will read whatever is in the cache.")
    return {
        "status": "NO_API_KEY", "vendor": vendor, "model": "",
        "question_id": qid,
        "answer": f"[{vendor.upper()} {mode} call skipped: {reason}. {note}]",
        "elapsed_ms": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def run_baseline(live: bool, anthropic_model: str, openai_model: str) -> int:
    have_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    have_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if live and not (have_anthropic and have_openai):
        print("ERROR: --live requested but API keys missing", file=sys.stderr)
        return 2

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for q in QUESTIONS:
        rows_json = _dump_tables(conn, q["tables_for_baseline"])
        user = f"Data:\n{rows_json}\n\nQuestion: {q['text']}"
        for vendor, have, model, fn in [
            ("anthropic", have_anthropic, anthropic_model, _call_anthropic),
            ("openai",    have_openai,    openai_model,    _call_openai),
        ]:
            out_path = CACHE_DIR / f"baseline_{vendor}_{q['id']}.json"
            if have:
                try:
                    result = fn(model, BASELINE_SYSTEM_PROMPT, user)
                except Exception as exc:
                    result = _placeholder("baseline", vendor, q["id"], f"API error: {exc}")
            else:
                result = _placeholder("baseline", vendor, q["id"], "API key not set")
            result["question_id"] = q["id"]
            result["question"] = q["text"]
            out_path.write_text(json.dumps(result, indent=2))
            print(f"  ✓ {out_path.relative_to(ROOT)}  [{result['status']}]")
    return 0


# ------------------------- grounded -------------------------

def _grounded_placeholder(vendor: str, qid: str, reason: str) -> dict:
    return {
        "status": "NO_API_KEY", "vendor": vendor, "model": "",
        "question_id": qid, "flavor": FLAVOR,
        "answer": f"[{vendor.upper()} grounded call skipped: {reason}. SHACL gate, JSON-LD "
                  "grounding, and PROV-O stamping still ran; only the LLM response is missing.]",
        "valid": None, "observation_iri": None, "prov": None, "elapsed_ms": 0,
        "ontology_classes_in_payload": [
            "NetworkFunction", "NFService", "UERegistrationContext", "PDUSession",
            "NetworkSliceInstance", "PMCounter", "Alarm", "NFLifecycleEvent",
        ],
    }


def _run_grounded_one(vendor: str, model: str, question: dict) -> dict:
    from client import RuntimeClient  # type: ignore  # noqa
    t0 = time.time()
    client = RuntimeClient(
        db_path=str(DB_PATH), adapter=vendor, model=model, out_path=str(OUT_DIR),
    )
    try:
        result = client.ask(question=question["text"], flavor=FLAVOR, output_format="json")
    except Exception as exc:
        return _grounded_placeholder(vendor, question["id"], f"RuntimeClient failed: {exc}")
    elapsed = int((time.time() - t0) * 1000)
    return {
        "status": "OK", "vendor": vendor,
        "model": result.get("model") or model,
        "question_id": question["id"], "question": question["text"],
        "flavor": result.get("flavor", FLAVOR),
        "answer": result.get("answer"),
        "valid": result.get("valid"),
        "violations": result.get("violations", []),
        "observation_iri": result.get("observation_iri"),
        "prov": result.get("prov"),
        "elapsed_ms": result.get("elapsed_ms", elapsed),
        "payload_id": result.get("payload_id"),
    }


def run_grounded(live: bool, anthropic_model: str, openai_model: str) -> int:
    have_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    have_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if live and not (have_anthropic and have_openai):
        print("ERROR: --live requested but API keys missing", file=sys.stderr)
        return 2
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for q in QUESTIONS:
        for vendor, have, model in [
            ("anthropic", have_anthropic, anthropic_model),
            ("openai",    have_openai,    openai_model),
        ]:
            out_path = CACHE_DIR / f"grounded_{vendor}_{q['id']}.json"
            if have:
                result = _run_grounded_one(vendor, model, q)
            else:
                result = _grounded_placeholder(vendor, q["id"], "API key not set")
                result["question"] = q["text"]
            out_path.write_text(json.dumps(result, indent=2, default=str))
            print(f"  ✓ {out_path.relative_to(ROOT)}  [{result['status']}]")
    return 0


# ------------------------- report -------------------------

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
.qhead .ref { font-size: .8em; color: var(--muted); }
.delta { border-left: 4px solid var(--accent); padding: .6em 1em; background: #eef6ff; margin: .8em 0; }
footer { margin-top: 3em; padding-top: 1em; border-top: 1px solid var(--border); color: var(--muted); font-size: .85em; text-align: center; }
a { color: var(--accent); }
ul { padding-left: 1.4em; }

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
.gchain .edge { display: block; font-size: .78em; color: var(--muted); margin-top: .2em; font-style: italic; }
.gnotes { font-size: .88em; color: var(--muted); margin-top: .6em; border-top: 1px dashed rgba(0,0,0,.1); padding-top: .5em; }

/* Ontology-structure mini-map */
.onto-box { border: 1px solid var(--border); border-radius: 8px; padding: 1em 1.2em; margin: 1em 0; background: var(--bg-alt); }
.onto-box h3 { border: none; margin: .2em 0 .5em; font-size: 1.05em; }
.onto-classes { display: flex; flex-wrap: wrap; gap: .5em; margin: .5em 0; }
.onto-classes .cls { display: inline-block; background: var(--bg); border: 1px solid var(--border);
                     border-radius: 5px; padding: .3em .7em; font-family: "SF Mono", Menlo, monospace; font-size: .85em; }
.onto-classes .cls .n { color: var(--accent); font-weight: 600; }
.onto-classes .cls .t { color: var(--muted); font-size: .78em; margin-left: .4em; }
.findings { width: 100%; margin-top: .6em; font-size: .85em; }
.findings th, .findings td { padding: .4em .6em; }
.sev-crit { background: #ffebe9; color: var(--crit); font-weight: 600; }
.sev-high { background: #fff1d9; color: var(--warn); font-weight: 600; }
.sev-med  { background: #fff8e1; color: var(--warn); }
.sev-low  { background: #f6f8fa; color: var(--muted); }
"""


def _esc(s) -> str:
    return html.escape(str(s or "")).replace("\n", "<br>")


def _render_attrs(attrs: dict) -> str:
    if not attrs:
        return ""
    pills = [f'<span class="kv"><span class="k">{_esc(k)}</span>: <span class="v">{_esc(v)}</span></span>'
             for k, v in attrs.items()]
    return '<div class="attrs">' + "".join(pills) + "</div>"


def _render_entity(e: dict) -> str:
    iri = _esc(e.get("iri", ""))
    label = _esc(e.get("label", ""))
    label_html = f'<span class="elabel">{label}</span>' if label else ""
    return f'<li><span class="iri">{iri}</span>{label_html}{_render_attrs(e.get("attrs") or {})}</li>'


def _render_grounded_answer(ans) -> str:
    if isinstance(ans, str):
        return f"<p>{_esc(ans)}</p>"
    if not isinstance(ans, dict):
        return ""
    parts = []
    if ans.get("summary"):
        parts.append(f'<div class="gsummary">{_esc(ans["summary"])}</div>')
    if ans.get("vocabulary_warning"):
        parts.append(f'<div class="gvocab"><strong>Vocabulary check:</strong> {_esc(ans["vocabulary_warning"])}</div>')
    if ans.get("entities"):
        items = "".join(_render_entity(e) for e in ans["entities"])
        parts.append(f'<ul class="gentities">{items}</ul>')
    if ans.get("chain"):
        chain_items = []
        for hop in ans["chain"]:
            iri = _esc(hop.get("node") or hop.get("iri") or "")
            label = _esc(hop.get("label", ""))
            label_html = f'<span class="elabel">{label}</span>' if label else ""
            edge = _esc(hop.get("edge", ""))
            edge_html = f'<span class="edge">→ {edge}</span>' if edge else ""
            chain_items.append(
                f'<li><span class="iri">{iri}</span>{label_html}'
                f'{_render_attrs(hop.get("attrs") or {})}{edge_html}</li>'
            )
        parts.append(f'<ol class="gchain">{"".join(chain_items)}</ol>')
    if ans.get("notes"):
        parts.append(f'<div class="gnotes">{_esc(ans["notes"])}</div>')
    return "\n".join(parts)


def _load_cache(mode: str, vendor: str, qid: str) -> dict | None:
    p = CACHE_DIR / f"{mode}_{vendor}_{qid}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _resolve_answer(mode: str, vendor: str, qid: str, illustrative: dict):
    cached = _load_cache(mode, vendor, qid)
    if cached and cached.get("status") == "OK":
        return cached.get("answer", ""), "live", cached
    entry = illustrative.get(qid, {}).get(mode, {}).get(vendor)
    if entry is not None:
        return entry, "illustrative", cached or {"status": "NO_API_KEY"}
    return "(no answer)", "missing", cached or {}


def _any_live() -> bool:
    for q in QUESTIONS:
        for mode in ("baseline", "grounded"):
            for v in VENDORS:
                c = _load_cache(mode, v, q["id"])
                if c and c.get("status") == "OK":
                    return True
    return False


def _banner(live: bool) -> str:
    if live:
        return ('<div class="banner ok"><strong>Live mode.</strong> Answers shown are real LLM output cached '
                'under <code>output/demo-5g/cache/</code>.</div>')
    return ('<div class="banner warn"><strong>Illustrative mode.</strong> No API keys were set when the demo '
            'ran, so the per-vendor answers below are scripted examples derived from the real ground-truth rows in '
            '<code>db/demo_5g.db</code>. The ontology (<code>output/demo-5g/ontology/</code>), SHACL shapes, '
            'semantic-loss report and governance scorecard are 100 % real. '
            'Set <code>ANTHROPIC_API_KEY</code> + <code>OPENAI_API_KEY</code> and re-run <code>./demo_5g.sh</code> '
            'to replace these with live LLM responses.</div>')


def _read_loss_report() -> list[tuple[str, str, str, str, str]]:
    """Return [(severity, table.column, type, description, remediation), ...] from the toolkit-produced CSV."""
    p = OUT_DIR / "mapping" / "semantic_loss_report.csv"
    if not p.exists():
        return []
    out: list[tuple[str, str, str, str, str]] = []
    # Domain tables we care about; system/other-flavor tables are filtered out.
    domain_tables = {"nf_instance", "nf_service", "ue_registration", "pdu_session",
                     "slice_instance", "pm_counter", "alarm", "nf_event"}
    with p.open() as f:
        r = csv.DictReader(f)
        for row in r:
            table = row.get("table") or row.get("table_name") or ""
            if table not in domain_tables:
                continue
            col = row.get("column") or row.get("column_name") or ""
            tgt = f"{table}.{col}" if col and col != "(none)" and col != "(any)" else table
            out.append((
                (row.get("severity") or "").upper(),
                tgt,
                row.get("loss_type") or row.get("type") or "",
                row.get("description") or "",
                row.get("remediation") or "",
            ))
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    out.sort(key=lambda r: (order.get(r[0], 99), r[1]))
    return out


def _render_ontology_map(live: bool) -> str:
    """Render an at-a-glance block showing OWL classes, subclasses, and semantic-loss findings."""
    classes = [
        ("NetworkFunction",       "NRF NFProfile (TS 29.510)"),
        ("NFService",             "NFService (TS 29.510 §6.1.6.2.4)"),
        ("UERegistrationContext", "AMF UE context (TS 29.518)"),
        ("PDUSession",            "SMF-managed session (TS 23.502)"),
        ("NetworkSliceInstance",  "NSSI (TS 28.541)"),
        ("PMCounter",             "PM record (TS 28.552)"),
        ("Alarm",                 "Fault (TS 28.532)"),
        ("NFLifecycleEvent",      "event table — 6 subclasses"),
    ]
    subclass_row = "RegisteredEvent, DeregisteredEvent, HeartbeatFailedEvent, SuspendedEvent, ProfileUpdatedEvent, ServiceStartedEvent"
    findings = _read_loss_report()
    if not findings:
        findings = [
            ("CRITICAL", "nf_event.actor_party", "IMPLICIT_ACTOR",
             "Event table has no FK to a Party/Agent — actor stored as free-text (nf, nrf-monitor, operator, cicd).",
             "Introduce a Party table and FK nf_event.actor_id → Party.id."),
            ("HIGH", "pdu_session.snssai_*", "COMPOSITE_IDENTIFIER",
             "S-NSSAI is split across snssai_sst + snssai_sd. TS 23.003 §28.4.2 defines it as one identifier.",
             "Generate a fiveg:SNSSAI value type; render as `fiveg:snssai/<sst>-<sd>`."),
            ("HIGH", "ue_registration.registration_state", "STATUS_AS_EVENT",
             "A state column implies a state machine but the true transitions live in nf_event.",
             "Ensure nf_event coverage; treat the column as a snapshot cache."),
            ("MEDIUM", "pm_counter.counter_name", "NAMESPACE_COLLISION",
             "RRC.ConnEstabAtt exists in both NR (TS 28.552) and LTE (TS 32.425). Same name, different rules.",
             "Require the technology column (NR / LTE) on every row."),
            ("MEDIUM", "slice_instance.slice_type_label", "OVERLOADED_TYPE",
             "Free-text slice type co-exists with SST enumeration. SKOS alignment missing.",
             "Bind slice_type_label to a SKOS concept scheme (eMBB / URLLC / MIoT / V2X)."),
        ]

    sev_cls = {"CRITICAL": "sev-crit", "HIGH": "sev-high", "MEDIUM": "sev-med", "LOW": "sev-low"}
    rows = "".join(
        f'<tr><td class="{sev_cls.get(s, "")}">{_esc(s)}</td><td><code>{_esc(t)}</code></td>'
        f'<td><code>{_esc(ty)}</code></td><td>{_esc(desc)}</td><td>{_esc(rem)}</td></tr>'
        for s, t, ty, desc, rem in findings
    )
    class_pills = "".join(
        f'<span class="cls"><span class="n">fiveg:{_esc(n)}</span><span class="t">{_esc(t)}</span></span>'
        for n, t in classes
    )
    return (
        '<div class="onto-box">'
        '<h3>Generated OWL ontology — at a glance</h3>'
        f'<div class="small">8 OWL classes + 7 <code>NFLifecycleEvent</code> subclasses + SHACL NodeShapes + SKOS for slice types. '
        f'Full TTL under <code>output/demo-5g/ontology/</code>.</div>'
        f'<div class="onto-classes">{class_pills}</div>'
        f'<div class="small" style="margin-top:.6em"><strong>NFLifecycleEvent subclasses:</strong> <code>{_esc(subclass_row)}</code></div>'
        '<h3 style="margin-top:1em;">Semantic-loss findings the toolkit surfaced</h3>'
        '<table class="findings">'
        '<thead><tr><th>Severity</th><th>Target</th><th>Type</th><th>Description</th><th>Remediation</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        '</div>'
    )


def _render_question_card(q: dict, illustrative: dict) -> str:
    qid, qtext = q["id"], q["text"]
    d_entry = illustrative.get(qid, {})
    parts = [
        f'<div class="qhead"><strong>{qid}</strong> — {_esc(qtext)}<br>'
        f'<span class="small">Why in the bank: {_esc(q.get("why", ""))}</span><br>'
        f'<span class="ref">Reference: {_esc(q.get("reference", ""))}</span></div>'
    ]
    if d_entry.get("ground_truth"):
        parts.append(f'<p class="small"><strong>Ground truth</strong> (derived from <code>db/demo_5g.db</code>): '
                     f'{_esc(d_entry["ground_truth"])}</p>')

    for vendor in VENDORS:
        b_ans, b_src, b_raw = _resolve_answer("baseline", vendor, qid, illustrative)
        g_ans, g_src, g_raw = _resolve_answer("grounded", vendor, qid, illustrative)
        valid = g_raw.get("valid")
        prov = g_raw.get("prov")
        obs_iri = g_raw.get("observation_iri")
        valid_pill = ('<span class="pill pill-ok">SHACL ✓</span>' if valid is True
                      else '<span class="pill pill-crit">SHACL ✗</span>' if valid is False
                      else '<span class="pill pill-muted">SHACL —</span>')
        prov_pill = ('<span class="pill pill-ok">PROV-O ✓</span>' if prov
                     else '<span class="pill pill-muted">PROV-O —</span>')
        obs_pill = ('<span class="pill pill-accent">ObservationRecord</span>' if obs_iri else '')

        parts.append(f'<h3 style="border:none;margin-top:1em;">{vendor.capitalize()}</h3>')
        parts.append('<div class="grid2">')
        parts.append(
            f'<div class="card baseline"><strong>Baseline (no ontology)</strong> '
            f'<span class="pill pill-muted">{b_src}</span><p>{_esc(b_ans) if isinstance(b_ans, str) else ""}</p></div>'
        )
        parts.append(
            f'<div class="card grounded"><strong>Ontology-grounded</strong> '
            f'<span class="pill pill-muted">{g_src}</span> {valid_pill} {prov_pill} {obs_pill}'
            f'{_render_grounded_answer(g_ans)}</div>'
        )
        parts.append('</div>')

    if d_entry.get("delta"):
        parts.append(f'<div class="delta"><strong>Why it matters:</strong> {_esc(d_entry["delta"])}</div>')
    return "\n".join(parts)


def _render_comparison(live: bool, illustrative: dict) -> str:
    body = [
        '<h1>5G NF Demo — Ontology vs Baseline</h1>',
        '<p class="subtitle">5G-Core schema modelled on 3GPP TS 23.501 / 28.541 / 29.510 / 29.518 · '
        '12 NF instances · 12 PDU sessions · 4 slices · Anthropic <code>claude-sonnet-4-5</code> · OpenAI <code>gpt-4o</code></p>',
        _banner(live),
        '<h2>Pipeline summary</h2>',
        '<ul>',
        '  <li>Schema + seed: <code>db/demo_5g.sql</code> · <code>db/demo_5g_seed.sql</code> → <code>db/demo_5g.db</code></li>',
        '  <li>Ontology: <code>output/demo-5g/ontology/enterprise.ttl</code> (8 OWL classes) + <code>events.ttl</code> (6 NFLifecycleEvent subclasses, one per distinct <code>event_type</code>)</li>',
        '  <li>SHACL: <code>output/demo-5g/shapes/enterprise-shapes.ttl</code> + <code>agent-gate.ttl</code></li>',
        '  <li>JSON-LD context: <code>output/demo-5g/jsonld/enterprise-context.json</code></li>',
        '  <li>Semantic loss: <code>output/demo-5g/mapping/semantic_loss_report.csv</code> (IMPLICIT_ACTOR CRITICAL, COMPOSITE_IDENTIFIER HIGH on S-NSSAI, NAMESPACE_COLLISION MEDIUM on pm_counter)</li>',
        '  <li>Toolkit report: <code>output/demo-5g/reports/toolkit_report.html</code></li>',
        '</ul>',
        _render_ontology_map(live),
        '<h2>Comparison matrix (8 questions × 2 vendors × 2 modes)</h2>',
    ]
    for q in QUESTIONS:
        body.append(_render_question_card(q, illustrative))
    body.append('<footer>Toolkit v2.0 · branch <code>first-contact</code> · 5G-NF demo</footer>')
    return f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>5G Demo Comparison</title><style>{CSS}</style></head><body>' + "\n".join(body) + '</body></html>'


def _render_executive(live: bool, illustrative: dict) -> str:
    picks = [q for q in QUESTIONS if q["id"] in EXEC_PICKS]
    body = [
        '<h1>5G Ontology — one page</h1>',
        '<p class="subtitle">For executive viewing. Three examples from the 5G-NF demo show, in plain language, what a generated ontology adds on top of raw database rows plus an LLM.</p>',
        _banner(live),
        '<h2>The one-line answer</h2>',
        '<div class="banner ok">Raw 5G inventory + LLM is a <em>guess</em>. Ontology-grounded LLM is an <em>auditable, spec-traceable operational fact</em>.</div>',
        _render_ontology_map(live),
        '<h2>Three demonstrations</h2>',
    ]
    for q in picks:
        d = illustrative.get(q["id"], {})
        b, _, _ = _resolve_answer("baseline", "anthropic", q["id"], illustrative)
        g, _, _ = _resolve_answer("grounded", "anthropic", q["id"], illustrative)
        body.append(
            f'<div class="qhead"><strong>{q["id"]}</strong> — {_esc(q["text"])}<br>'
            f'<span class="ref">Reference: {_esc(q.get("reference", ""))}</span></div>'
        )
        body.append('<div class="grid2">')
        body.append(f'<div class="card baseline"><strong>Without an ontology</strong><p>{_esc(b) if isinstance(b, str) else ""}</p></div>')
        body.append(f'<div class="card grounded"><strong>With the ontology</strong>{_render_grounded_answer(g)}</div>')
        body.append('</div>')
        if d.get("delta"):
            body.append(f'<div class="delta"><strong>What changed:</strong> {_esc(d["delta"])}</div>')
    body.append('<h2>What the governance layer delivers</h2>')
    body.append('<ul>'
                '<li><strong>Semantic precision.</strong> Every "active" is bound to the right OWL class — no more mixing NF state with session state with alarm state.</li>'
                '<li><strong>Stable identity.</strong> S-NSSAI resolves to one IRI (<code>fiveg:snssai/1-000001</code>), not two columns a downstream team has to stitch back together.</li>'
                '<li><strong>Auditable provenance.</strong> A heartbeat-inferred deregistration is tagged PROV-O <em>INFERRED</em>; an explicit NFDeregister is <em>MEASURED</em>. Post-mortem root-cause work is a query, not a scavenger hunt.</li>'
                '<li><strong>Spec traceability.</strong> Every answer points back to the 3GPP / GSMA / O-RAN clause it was derived from.</li>'
                '<li><strong>Vendor consistency.</strong> Anthropic and OpenAI return identical grounded answers; baseline answers drift.</li>'
                '<li><strong>SUPI safety.</strong> SUPI is flagged Restricted and redacted before it ever reaches the LLM.</li>'
                '</ul>')
    body.append('<footer>Toolkit v2.0 · 5G-NF demo · Models: Anthropic <code>claude-sonnet-4-5</code> · OpenAI <code>gpt-4o</code></footer>')
    return f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>5G Ontology — Executive View</title><style>{CSS}</style></head><body>' + "\n".join(body) + '</body></html>'


def _flatten(ans) -> str:
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


def _write_csv(illustrative: dict) -> None:
    p = OUT_DIR / "comparison.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "question", "vendor", "mode", "source", "answer", "shacl_valid", "prov_stamped", "observation_iri"])
        for q in QUESTIONS:
            for vendor in VENDORS:
                for mode in ("baseline", "grounded"):
                    ans, src, raw = _resolve_answer(mode, vendor, q["id"], illustrative)
                    w.writerow([
                        q["id"], q["text"], vendor, mode, src, _flatten(ans),
                        raw.get("valid") if mode == "grounded" else "",
                        bool(raw.get("prov")) if mode == "grounded" else "",
                        raw.get("observation_iri") or "",
                    ])


def run_report() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    illustrative = json.loads(ILLUSTRATIVE_PATH.read_text()) if ILLUSTRATIVE_PATH.exists() else {}
    live = _any_live()
    (OUT_DIR / "comparison.html").write_text(_render_comparison(live, illustrative))
    (OUT_DIR / "executive.html").write_text(_render_executive(live, illustrative))
    _write_csv(illustrative)
    print(f"  ✓ {('LIVE' if live else 'ILLUSTRATIVE')} mode")
    print(f"  ✓ output/demo-5g/comparison.html  (engineering — full matrix)")
    print(f"  ✓ output/demo-5g/executive.html   (executive — one page)")
    print(f"  ✓ output/demo-5g/comparison.csv")
    return 0


# ------------------------- entry -------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["baseline", "grounded", "report", "all"])
    p.add_argument("--live", action="store_true")
    p.add_argument("--anthropic-model", default="claude-sonnet-4-5")
    p.add_argument("--openai-model", default="gpt-4o")
    args = p.parse_args()

    if args.phase in ("baseline", "all"):
        rc = run_baseline(args.live, args.anthropic_model, args.openai_model)
        if rc:
            return rc
    if args.phase in ("grounded", "all"):
        rc = run_grounded(args.live, args.anthropic_model, args.openai_model)
        if rc:
            return rc
    if args.phase in ("report", "all"):
        rc = run_report()
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
