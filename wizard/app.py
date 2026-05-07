"""
wizard/app.py — Phase 3 · Sprint S15–S17
────────────────────────────────────────
Browser-based onboarding wizard — web equivalent of onboard.py.

Provides a drag-and-drop entity/relationship builder that generates
a session.json compatible with the CLI pipeline.

Features:
  • Step 1 — Domain identity (name, description, base IRI)
  • Step 2 — Entity builder (add/remove entities + properties)
  • Step 3 — Event builder
  • Step 4 — Relationship editor
  • Step 5 — Competency questions
  • Step 6 — Review + generate (triggers toolkit pipeline)

Routes:
  GET  /             — Wizard UI (single-page app)
  GET  /health       — Health check
  POST /api/session  — Save/update session JSON
  GET  /api/session  — Load current session
  POST /api/generate — Run toolkit pipeline from session
  GET  /api/templates — List available industry templates
  GET  /api/template/<name> — Load a template as session
  GET  /api/output/<path>   — Serve a generated artifact

Usage:
  python3 wizard/app.py                         # dev server on localhost:5000
  python3 wizard/app.py --host 0.0.0.0 --port 5000
"""

from __future__ import annotations

import os
import re
import sys
import json
import subprocess
import threading
import argparse
from datetime import datetime, timezone
from pathlib import Path

HERE    = os.path.dirname(os.path.abspath(__file__))
ROOT    = os.path.dirname(HERE)
SRC_DIR = os.path.join(ROOT, "src")
sys.path.insert(0, SRC_DIR)
sys.path.insert(0, ROOT)

SESSION_FILE = os.path.join(ROOT, ".wizard_session.json")
TEMPLATES_DIR = os.path.join(ROOT, "templates")
ONTOLOGIES_DB = os.path.join(ROOT, "db", "ontologies.db")
OUTPUT_DIR = os.path.join(ROOT, "output")

from wizard import ontologies_store as _store
_store.init_db(ONTOLOGIES_DB)

# Built-in starter templates live in onboard.py's INDUSTRY_TEMPLATES dict
# (telecom, healthcare, finance, manufacturing, retail). Import them so the
# Ontology Studio and the CLI wizard share the same source of truth.
try:
    from onboard import INDUSTRY_TEMPLATES as _ONBOARD_TEMPLATES  # type: ignore
except Exception:
    _ONBOARD_TEMPLATES = {}

try:
    from flask import Flask, request, jsonify, send_file, send_from_directory
    from flask_cors import CORS
    _flask_ok = True
except ImportError:
    _flask_ok = False
    print("Flask not installed — run: pip install flask flask-cors")
    sys.exit(1)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

_pipeline_lock = threading.Lock()
_pipeline_running = False
_pipeline_log: list[str] = []


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_session() -> dict:
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "domain": {},
        "entities": [],
        "events": [],
        "relationships": [],
        "competency_questions": [],
        "rules": [],
        "created_at": _now(),
        "updated_at": _now(),
    }


def _save_session(data: dict) -> None:
    data["updated_at"] = _now()
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(os.path.join(HERE, "templates"), "index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "timestamp": _now()})


@app.route("/api/session", methods=["GET"])
def get_session():
    return jsonify(_load_session())


@app.route("/api/session", methods=["POST"])
def save_session():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    existing = _load_session()
    existing.update(data)
    _save_session(existing)
    return jsonify({"ok": True, "updated_at": existing["updated_at"]})


def _to_snake(s: str) -> str:
    return "_".join(s.lower().replace("-", " ").replace("/", " ").split())


def _builtin_to_session(name: str, t: dict) -> dict:
    """Translate an onboard.py INDUSTRY_TEMPLATES entry into the wizard's
    session shape. The CLI dict stores entities/events as plain strings
    and relationships as 3-tuples; the wizard expects structured records.
    """
    entities = [
        {"name": _to_snake(label), "label": label, "description": "",
         "sensitivity": "Internal", "is_event": False, "properties": []}
        for label in t.get("entities", [])
    ]
    events = [
        {"name": _to_snake(label), "label": label, "description": ""}
        for label in t.get("events", [])
    ]
    relationships = [
        {"from_entity": frm, "label": lbl, "to_entity": to}
        for (frm, lbl, to) in t.get("relationships", [])
    ]
    cqs = [
        {"id": f"CQ-{i+1:02d}", "question": q, "priority": "Medium"}
        for i, q in enumerate(t.get("cqs", []))
    ]
    return {
        "domain": {
            "name": t.get("domain_name", name.title()),
            "description": t.get("domain_description", ""),
            "base_iri": f"https://ontology.example.com/{name}/",
            "industry": name,
        },
        "entities": entities,
        "events": events,
        "relationships": relationships,
        "competency_questions": cqs,
        "created_at": _now(),
        "updated_at": _now(),
    }


def _parse_relationship_sentence(text: str, labels: list) -> dict | None:
    """Best-effort split of a free-form English relationship sentence into
    {from_entity, label, to_entity} using the loaded entity labels.

    Supports two label-spelling conventions in the same sentence by
    matching both the label as written ("Power Asset") and its
    space-stripped form ("PowerAsset") — the YAML templates routinely
    mix these. Returns None when the sentence can't be split confidently.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip().rstrip(".")
    # Build aliases for every label: as-written, space-stripped, hyphen→space.
    # Also add the LAST WORD of any multi-word label as a suffix-alias when
    # it's unique across the label set — YAML authors routinely write the
    # short form ("Policy" instead of "Insurance Policy") in sentences.
    aliases = {}
    suffix_counts = {}
    for lbl in labels:
        if not lbl:
            continue
        for alias in {lbl, lbl.replace(" ", ""), lbl.replace("-", " ")}:
            aliases[alias] = lbl
        parts = [p for p in lbl.split() if p]
        if len(parts) > 1:
            suffix_counts[parts[-1]] = suffix_counts.get(parts[-1], 0) + 1
    for lbl in labels:
        parts = [p for p in (lbl or "").split() if p]
        if len(parts) > 1 and suffix_counts.get(parts[-1], 0) == 1:
            aliases.setdefault(parts[-1], lbl)

    # Find first and last alias hits in the sentence. Earliest start vs.
    # latest end win — and we now allow first == last (self-references).
    def _scan(haystack):
        first = last = None
        for alias, target in aliases.items():
            i = haystack.find(alias)
            if i == -1:
                continue
            if first is None or i < first[1]:
                first = (target, i, i + len(alias))
            j = haystack.rfind(alias)
            jend = j + len(alias)
            if last is None or jend > last[2]:
                last = (target, j, jend)
        return first, last
    first, last = _scan(s)
    # Retry case-insensitively if either side is missing (not on disagreement).
    if not first or not last:
        first, last = _scan(s.lower())
        if not first or not last:
            return None
    # Self-references are legitimate (parent→child trees) — accept them.
    if first[1] >= last[1]:
        # Single occurrence of one alias only; treat as a self-reference if
        # the entity itself was found, otherwise un-parseable.
        if first[0] == last[0]:
            verb = (s.split(first[0], 1)[1].strip().lstrip(",;:")
                    if first[0] in s else "related to")
            verb = re.sub(r"^(?:is|are|may\s+be|can\s+be)\s+", "", verb).rstrip(",;:.").strip()
            verb = re.split(r"\s+(?:to|with)?\s*another\s+", verb)[0].strip() or "related to"
            return {"from_entity": first[0], "label": verb or "related to", "to_entity": first[0]}
        return None
    verb = s[first[2]:last[1]].strip().lstrip(",;:").rstrip(",;:").strip() or "related to"
    # Strip leading articles ("is", "are", "may be") that read awkwardly as
    # an OWL property label — e.g. "is submitted by" → "submitted by".
    verb = re.sub(r"^(?:is|are|may\s+be|can\s+be)\s+", "", verb)
    return {"from_entity": first[0], "label": verb, "to_entity": last[0]}


def _structure_yaml_relationships(raw: list, entities_yaml: list) -> list:
    """Normalise YAML 'relationships' (often free-form strings) into the
    structured {from_entity, label, to_entity} dicts the graph view and
    downstream tooling expect. Falls back to the original entry when a
    sentence can't be parsed — keeps human content visible."""
    labels = [(e.get("label") or e.get("name", "")).strip() for e in (entities_yaml or [])]
    out = []
    for r in (raw or []):
        if isinstance(r, dict) and r.get("from_entity") and r.get("to_entity"):
            out.append({"from_entity": r["from_entity"],
                        "label":       r.get("label", "related to"),
                        "to_entity":   r["to_entity"]})
            continue
        if isinstance(r, (list, tuple)) and len(r) == 3:
            out.append({"from_entity": r[0], "label": r[1], "to_entity": r[2]})
            continue
        if isinstance(r, str):
            parsed = _parse_relationship_sentence(r, labels)
            if parsed:
                out.append(parsed)
            else:
                # Keep the sentence so the user still sees it on the List
                # tab; graph view will skip un-parseable entries.
                out.append({"from_entity": "", "label": r, "to_entity": ""})
    return out


def _yaml_to_session(name: str, tmpl: dict) -> dict:
    """Translate a templates/*.yaml file into the wizard's session shape."""
    return {
        "domain": {
            "name": tmpl.get("label", name),
            "description": tmpl.get("description", "").strip(),
            "base_iri": tmpl.get("base_iri", f"https://ontology.example.com/{name}/"),
            "industry": name,
        },
        "entities": [
            {
                "name": e["name"],
                "label": e.get("label", e["name"]),
                "description": e.get("description", ""),
                "sensitivity": e.get("sensitivity", "Internal"),
                "is_event": e.get("is_event", False),
                "properties": [
                    {"name": pn,
                     "type": (pv.get("type", "string") if isinstance(pv, dict) else "string"),
                     "required": (pv.get("required", False) if isinstance(pv, dict) else False)}
                    for item in (e.get("properties") or [])
                    for pn, pv in (item.items() if isinstance(item, dict) else [])
                ],
            }
            for e in tmpl.get("entities", [])
        ],
        "events": [
            {"name": ev["name"], "label": ev.get("label", ev["name"]),
             "description": ev.get("description", "")}
            for ev in tmpl.get("events", [])
        ],
        "relationships": _structure_yaml_relationships(
            tmpl.get("relationships", []),
            tmpl.get("entities", []),
        ),
        "competency_questions": [
            {"id": cq.get("id", ""), "question": cq.get("question", ""),
             "priority": cq.get("priority", "Medium")}
            for cq in tmpl.get("competency_questions", [])
        ],
        "created_at": _now(),
        "updated_at": _now(),
    }


@app.route("/api/templates", methods=["GET"])
def list_templates():
    yaml_names: list[str] = []
    if os.path.isdir(TEMPLATES_DIR):
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if fname.endswith((".yaml", ".yml")):
                yaml_names.append(fname.rsplit(".", 1)[0])
    builtin = list(_ONBOARD_TEMPLATES.keys())   # telecom, healthcare, finance, manufacturing, retail
    # Preserve order, drop duplicates if a YAML happens to share a name with a builtin.
    seen: set[str] = set()
    out: list[str] = []
    for n in builtin + yaml_names:
        if n not in seen:
            out.append(n)
            seen.add(n)
    # Apply user's landing-page visibility filter.
    prefs = _store.get_preferences(ONTOLOGIES_DB)
    hidden = set(prefs.get("landing.hidden_domains") or [])
    visible = [n for n in out if n not in hidden]
    return jsonify({"templates": visible, "hidden": sorted(hidden), "all": out})


@app.route("/api/template/<name>", methods=["GET"])
def load_template(name: str):
    # 1. Built-in starter templates from onboard.py
    if name in _ONBOARD_TEMPLATES:
        session = _builtin_to_session(name, _ONBOARD_TEMPLATES[name])
        _save_session(session)
        return jsonify(session)

    # 2. YAML templates under templates/
    try:
        import yaml
    except ImportError:
        return jsonify({"error": "PyYAML not installed — run: pip install pyyaml"}), 500

    for ext in (".yaml", ".yml"):
        path = os.path.join(TEMPLATES_DIR, name + ext)
        if os.path.exists(path):
            with open(path) as f:
                tmpl = yaml.safe_load(f) or {}
            session = _yaml_to_session(name, tmpl)
            _save_session(session)
            return jsonify(session)

    return jsonify({"error": f"Template '{name}' not found"}), 404


# ── /api/import — file-import (issue #16) ──────────────────────────────────
#
# Two ways to call:
#   multipart/form-data: file=<bytes> [+ format=auto|json|sql]
#   application/json:    {content: "<raw text>", format: "auto", filename?, dialect?}
#
# Returns the parse + validate result without persisting. The browser
# wizard's review modal then lets the user Accept (→ /api/import/commit)
# or Reject. Persistence is deferred so a malformed import can never
# stomp the in-progress session.
@app.route("/api/import", methods=["POST"])
def import_file():
    try:
        from . import importer as _imp
    except ImportError:
        # Allow flat-import fallback if /wizard isn't a package context.
        sys.path.insert(0, HERE)
        import importer as _imp                  # type: ignore[no-redef]

    raw: bytes = b""
    fmt = "auto"; dialect = "auto"; filename = None
    if request.files and "file" in request.files:
        f = request.files["file"]
        raw = f.read()
        filename = f.filename
        fmt = (request.form.get("format") or "auto").lower()
        dialect = (request.form.get("dialect") or "auto").lower()
    else:
        body = request.get_json(silent=True) or {}
        text = body.get("content")
        if isinstance(text, str):
            raw = text.encode("utf-8")
        elif isinstance(body, dict) and body:
            # Treat the entire posted JSON object as the file content.
            raw = json.dumps(body).encode("utf-8")
        fmt = (body.get("format") or "auto").lower()
        dialect = (body.get("dialect") or "auto").lower()
        filename = body.get("filename")

    if not raw:
        return jsonify({"error": "No file or content supplied (POST a multipart 'file' or a JSON body with 'content')."}), 400

    existing = _load_session()
    result = _imp.parse_and_validate(
        raw, fmt=fmt, dialect=dialect,
        existing_session=existing, filename=filename,
    )
    return jsonify(result.to_dict()), (200 if result.ok or result.session else 200)


@app.route("/api/import/commit", methods=["POST"])
def import_commit():
    """Persist a previously-parsed import as the current wizard session.

    Body: the `session` object returned by /api/import. The route does a
    final-guard re-validate; if errors surface again it refuses to write.
    """
    try:
        from . import importer as _imp
    except ImportError:
        sys.path.insert(0, HERE)
        import importer as _imp                  # type: ignore[no-redef]

    body = request.get_json(force=True) or {}
    session = body.get("session")
    if not isinstance(session, dict):
        return jsonify({"error": "Body must be {session: {...}}"}), 400

    # Final guard — same validators that ran at parse time.
    raw = json.dumps(session).encode("utf-8")
    result = _imp.parse_and_validate(raw, fmt="json", existing_session=_load_session())
    if not result.ok:
        return jsonify({
            "error": "Validation failed at commit time",
            "errors": [i.to_dict() for i in result.errors],
        }), 400

    _save_session(result.session)
    return jsonify({"ok": True, "session": result.session,
                    "warnings": [i.to_dict() for i in result.warnings],
                    "stats": result.stats})


@app.route("/api/generate", methods=["POST"])
def generate():
    global _pipeline_running, _pipeline_log
    if _pipeline_running:
        return jsonify({"error": "Pipeline already running"}), 409

    body = request.get_json(force=True) or {}
    phases = body.get("phases", ["all"])

    def _run():
        global _pipeline_running, _pipeline_log
        _pipeline_running = True
        _pipeline_log = []
        try:
            cmd = [sys.executable, os.path.join(ROOT, "toolkit.py")]
            for ph in phases:
                cmd += ["--phase", ph]
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
            _pipeline_log = (result.stdout + result.stderr).splitlines()
        except subprocess.TimeoutExpired:
            _pipeline_log = ["ERROR: pipeline timed out after 300s"]
        except Exception as e:
            _pipeline_log = [f"ERROR: {e}"]
        finally:
            _pipeline_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Pipeline started", "phases": phases})


# ── Phase C — Rules step ─────────────────────────────────────────────────

from wizard import rules as _rules_mod  # noqa: E402

_RULES_LIBRARY_DIR = os.path.join(ROOT, "templates", "rules")


@app.route("/api/rules", methods=["GET"])
def get_rules():
    return jsonify({"rules": _load_session().get("rules", [])})


@app.route("/api/rules", methods=["POST"])
def save_rules():
    body = request.get_json(force=True) or {}
    rules = body.get("rules", [])
    if not isinstance(rules, list):
        return jsonify({"error": "rules must be a list"}), 400
    results = _rules_mod.validate_rules(rules)
    bad = {rid: r.to_dict() for rid, r in results.items() if not r.ok}
    if bad:
        return jsonify({"error": "validation_failed", "results": bad}), 400
    session = _load_session()
    session["rules"] = [_rules_mod.normalise_rule(r) for r in rules]
    _save_session(session)
    return jsonify({"ok": True, "count": len(session["rules"])})


@app.route("/api/rules/validate", methods=["POST"])
def validate_rule():
    body = request.get_json(force=True) or {}
    if "rules" in body and isinstance(body["rules"], list):
        results = _rules_mod.validate_rules(body["rules"])
        return jsonify({"results": {rid: r.to_dict() for rid, r in results.items()}})
    result = _rules_mod.validate_rule(body)
    return jsonify(result.to_dict())


@app.route("/api/rules/summarise", methods=["POST"])
def summarise_rule_route():
    """Generate a one-sentence English summary of a rule. Best-effort:
    400 only when the input is malformed; provider failures bubble up
    as 502 so the UI can decide whether to retry or skip silently.

    Body:
        { "rule": {...}, "provider": "ollama" (optional) }

    On success the summary is also written back to ``session.rules`` so
    the round-trip persists across reloads.
    """
    body = request.get_json(force=True) or {}
    rule = body.get("rule") or body
    if not rule.get("body"):
        return jsonify({"error": "rule body is empty"}), 400
    from runtime.insights import summarise_rule
    try:
        summary = summarise_rule(rule, provider=body.get("provider"),
                                 model=body.get("model"))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502

    # Persist back into the session so the next reload renders the
    # English label without a fresh LLM call.
    if rule.get("id"):
        session = _load_session()
        for stored in session.get("rules") or []:
            if stored.get("id") == rule["id"]:
                stored["nl_summary"] = summary
                break
        _save_session(session)

    return jsonify({"id": rule.get("id"), "nl_summary": summary})


@app.route("/api/rules/nl", methods=["POST"])
def draft_rule_route():
    """Draft a rule body from a plain-English description. Body:

        { "nl": "When a Site is in OUTAGE, mark it impacted",
          "kind": "shacl" | "sparql" | "owl",
          "provider": "ollama" (optional),
          "model":    "..."   (optional) }

    The response carries the drafted body, IRI grounding stats, and
    whether the draft passes Phase C validation. Authors review and
    accept (or reject) the draft on the client.
    """
    body = request.get_json(force=True) or {}
    nl   = (body.get("nl") or "").strip()
    kind = (body.get("kind") or "shacl").strip().lower()
    if not nl:
        return jsonify({"error": "nl is required"}), 400

    # Vocabulary feed — same source the slot-fill builder uses.
    from vocabulary import get_vocabulary
    ontology_path = os.path.join(OUTPUT_DIR, "ontology", "enterprise.ttl")
    vocab = get_vocabulary(ontology_path).to_dict()
    if not (vocab.get("classes") or vocab.get("properties")):
        return jsonify({"error": "No ontology vocabulary available — "
                                "run --phase 2 first."}), 400

    from runtime.insights import draft_rule
    try:
        draft = draft_rule(
            nl=nl, kind=kind, vocabulary=vocab,
            provider=body.get("provider"), model=body.get("model"),
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502
    return jsonify(draft.to_dict())


@app.route("/api/rules/preview", methods=["POST"])
def preview_rule_route():
    """Test-fire a single rule against a small synthetic ABox and return
    the derived triples + lineage. The UI uses this to give authors
    instant feedback on whether their rule actually matches anything.

    Body:
        { "rule": {...}, "abox_text": "..." (optional) }

    The default ABox is `templates/preview_abox.ttl`.
    """
    body = request.get_json(force=True) or {}
    rule = body.get("rule") or body
    abox_text = body.get("abox_text")
    ontology_path = os.path.join(OUTPUT_DIR, "ontology", "enterprise.ttl")
    if not os.path.isfile(ontology_path):
        ontology_path = None  # let preview_rule fall back
    result = _rules_mod.preview_rule(
        rule,
        ontology_path=ontology_path,
        abox_text=abox_text,
    )
    return jsonify(result.to_dict())


@app.route("/api/rules/compile", methods=["POST"])
def compile_rule():
    """Compile a slot-fill rule to its Turtle body without persisting.
    Used by the slot-fill UI to render a live "show source" preview.
    """
    body = request.get_json(force=True) or {}
    rule = _rules_mod.normalise_rule(body)
    return jsonify({
        "id": rule["id"], "kind": rule["kind"],
        "body": rule["body"], "meta": rule.get("meta") or {},
    })


@app.route("/api/rules/coverage", methods=["GET"])
def rules_coverage():
    """Per-class rule-impact map. Drives the Relationships graph's heat
    overlay (#7) and any other visual surfaces that need to know which
    rules touch a class.
    """
    from vocabulary import get_vocabulary
    ontology_path = os.path.join(OUTPUT_DIR, "ontology", "enterprise.ttl")
    vocab = get_vocabulary(ontology_path).to_dict()
    rules = _load_session().get("rules") or []
    coverage = _rules_mod.compute_coverage(rules, vocab)
    # Convenience aggregates for the UI.
    counts = [c["count"] for c in coverage.values()]
    summary = {
        "max":   max(counts) if counts else 0,
        "total": sum(counts),
        "covered_classes": sum(1 for n in counts if n > 0),
        "all_classes":     len(counts),
    }
    return jsonify({"coverage": coverage, "summary": summary})


@app.route("/api/rules/library", methods=["GET"])
def list_rule_library():
    industries = []
    if os.path.isdir(_RULES_LIBRARY_DIR):
        for p in sorted(Path(_RULES_LIBRARY_DIR).glob("*.yaml")):
            industries.append(p.stem)
    return jsonify({"industries": industries})


@app.route("/api/rules/library/<industry>", methods=["GET"])
def get_rule_library(industry: str):
    starter = _rules_mod.load_starter_library(_RULES_LIBRARY_DIR, industry)
    return jsonify({"industry": industry, "rules": starter})


# ── Phase D — Explain / why-trace ────────────────────────────────────────


@app.route("/api/explain", methods=["GET"])
def explain_triple_route():
    """Return the lineage records for a single derived triple. Required
    query params: subject, predicate, object. Each may be either a full
    IRI or a quoted literal `"value"`.
    """
    subject = request.args.get("subject", "").strip()
    predicate = request.args.get("predicate", "").strip()
    obj = request.args.get("object", "").strip()
    if not (subject and predicate and obj):
        return jsonify({"error": "subject, predicate, object are required"}), 400
    lineage_path = os.path.join(OUTPUT_DIR, "ontology", "materialised-lineage.ttl")
    from materializer import explain_triple
    derivations = explain_triple(lineage_path, subject, predicate, obj)
    return jsonify({
        "triple": {"subject": subject, "predicate": predicate, "object": obj},
        "derivations": derivations,
        "asserted": len(derivations) == 0,
    })


@app.route("/api/materialised/triples", methods=["GET"])
def list_materialised_triples():
    """Return derived triples with their rule attribution. Powers the
    Viewer's Materialised tab.

    Query params: limit (default 200), engine, rule.
    """
    lineage_path = os.path.join(OUTPUT_DIR, "ontology", "materialised-lineage.ttl")
    if not os.path.isfile(lineage_path):
        return jsonify({"triples": [], "available": False})
    try:
        limit = max(1, min(2000, int(request.args.get("limit", "200"))))
    except ValueError:
        limit = 200
    engine_filter = request.args.get("engine", "").strip().lower()
    rule_filter = request.args.get("rule", "").strip()

    from rdflib import Graph as _G, URIRef as _U
    from rdflib.namespace import RDF as _RDF, PROV as _PROV
    TOOLKIT_RULE = _U("https://ontology.example.com/toolkit/materializer/rule")
    TOOLKIT_ENGINE = _U("https://ontology.example.com/toolkit/materializer/engine")

    g = _G()
    try:
        g.parse(lineage_path, format="turtle")
    except Exception as exc:  # noqa: BLE001
        return jsonify({"triples": [], "available": True, "error": str(exc)})

    out = []
    for stmt in g.subjects(_RDF.type, _RDF.Statement):
        s = next(g.objects(stmt, _RDF.subject), None)
        p = next(g.objects(stmt, _RDF.predicate), None)
        o = next(g.objects(stmt, _RDF.object), None)
        if not (s and p and o):
            continue
        deriv = next(g.objects(stmt, _PROV.wasDerivedFrom), None)
        rule = engine = None
        if deriv:
            r = next(g.objects(deriv, TOOLKIT_RULE), None)
            e = next(g.objects(deriv, TOOLKIT_ENGINE), None)
            rule = str(r) if r else None
            engine = str(e) if e else None
        if engine_filter and (engine or "").lower() != engine_filter:
            continue
        if rule_filter and rule_filter not in (rule or ""):
            continue
        out.append({
            "subject": str(s), "predicate": str(p), "object": str(o),
            "rule": rule, "engine": engine,
        })
        if len(out) >= limit:
            break
    return jsonify({"triples": out, "available": True})


# ── F1 — Ontology vocabulary catalogue ───────────────────────────────────


@app.route("/api/ontology/vocabulary", methods=["GET"])
def ontology_vocabulary():
    """Return classes + properties parsed from `enterprise.ttl`. Drives
    the slot-fill rule builder, NL-rule prompts, and rule-impact overlay.
    Cached by mtime — repeat calls reuse the parse on unchanged files.
    """
    from vocabulary import get_vocabulary
    ontology_path = os.path.join(OUTPUT_DIR, "ontology", "enterprise.ttl")
    vocab = get_vocabulary(ontology_path)
    return jsonify(vocab.to_dict())


# ── Phase E — Insights / LLM grounding ───────────────────────────────────


@app.route("/api/insights/providers", methods=["GET"])
def insights_providers():
    """List declared providers + per-provider configuration status. Used
    to populate the Settings → Providers panel.
    """
    from runtime.insights import provider_status
    return jsonify({"providers": [p.to_dict() for p in provider_status()]})


@app.route("/api/insights/ask", methods=["POST"])
def insights_ask():
    """Answer a question grounded in the active ontology. Body:
        {
          "question": "...",
          "provider": "openai" | "ollama" | ... (optional),
          "model": "gpt-4o" (optional),
          "include_materialised": false
        }
    """
    body = request.get_json(force=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    ontology_path = os.path.join(OUTPUT_DIR, "ontology", "enterprise.ttl")
    materialised_path = os.path.join(OUTPUT_DIR, "ontology", "materialised.ttl")
    if not os.path.isfile(ontology_path):
        return jsonify({"error": "no ontology — run --phase 2 first"}), 400

    from runtime.insights import Insights
    insights = Insights(
        ontology_path,
        materialised_path if os.path.isfile(materialised_path) else None,
    )
    try:
        result = insights.ask(
            question,
            provider=body.get("provider"),
            model=body.get("model"),
            include_materialised=bool(body.get("include_materialised")),
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502
    return jsonify(result.to_dict())


@app.route("/api/pipeline/status", methods=["GET"])
def pipeline_status():
    return jsonify({
        "running": _pipeline_running,
        "log_lines": len(_pipeline_log),
        "last_lines": _pipeline_log[-50:] if _pipeline_log else [],
    })


# ── Saved Ontologies (Library + Viewer) ───────────────────────────────────

@app.route("/api/ontologies", methods=["GET"])
def list_saved_ontologies():
    return jsonify({"ontologies": _store.list_ontologies(ONTOLOGIES_DB)})


@app.route("/api/ontologies", methods=["POST"])
def save_saved_ontology():
    body = request.get_json(force=True) or {}
    domain  = (body.get("domain")  or "").strip()
    product = (body.get("product") or "").strip()
    label   = (body.get("label")   or "").strip()
    if not (domain and product and label):
        return jsonify({"error": "domain, product, and label are required"}), 400

    session_payload = body.get("session")
    if session_payload is None:
        session_payload = _load_session()

    generated = body.get("generated")
    if generated is None:
        generated = _store.harvest_generated(OUTPUT_DIR)

    overwrite = bool(body.get("overwrite", False))
    try:
        result = _store.save_ontology(
            ONTOLOGIES_DB,
            domain=domain, product=product, label=label,
            session=session_payload, generated=generated,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        return jsonify({"error": "exists", "slug": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/api/ontologies/<slug>", methods=["GET"])
def get_saved_ontology(slug: str):
    row = _store.get_ontology(ONTOLOGIES_DB, slug)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/api/ontologies/<slug>", methods=["DELETE"])
def delete_saved_ontology(slug: str):
    ok = _store.delete_ontology(ONTOLOGIES_DB, slug)
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/ontologies/<slug>/reharvest", methods=["POST"])
def reharvest_saved_ontology(slug: str):
    """Re-read output/ and refresh the saved generated artifacts for slug."""
    result = _store.reharvest_ontology(ONTOLOGIES_DB, slug, OUTPUT_DIR)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@app.route("/api/ontologies/<slug>/load", methods=["POST"])
def load_saved_ontology(slug: str):
    """Copy a saved ontology's session into the active wizard session."""
    row = _store.get_ontology(ONTOLOGIES_DB, slug)
    if not row:
        return jsonify({"error": "not found"}), 404
    _save_session(row["session"])
    return jsonify(row["session"])


# ── Preferences (domain visibility, etc.) ─────────────────────────────────

@app.route("/api/preferences", methods=["GET"])
def get_preferences():
    return jsonify(_store.get_preferences(ONTOLOGIES_DB))


@app.route("/api/preferences", methods=["PUT"])
def put_preferences():
    body = request.get_json(force=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "body must be an object"}), 400
    return jsonify(_store.set_preferences(ONTOLOGIES_DB, body))


@app.route("/api/output", methods=["GET"])
def list_output():
    out_dir = os.path.join(ROOT, "output")
    result: dict[str, list[str]] = {}
    for sub in ("ontology", "shapes", "vocab", "jsonld", "mapping", "reports", "security"):
        d = os.path.join(out_dir, sub)
        if os.path.isdir(d):
            result[sub] = sorted(os.listdir(d))
    return jsonify(result)


# ── Workstream 2 — Autonomous Ontology Evolution ──────────────────────────
# Evolution Review tab — surfaces PENDING proposals, lets reviewers inspect,
# approve, reject, or defer, and triggers CI/CD auto-versioning on APPROVAL.

_DB_PATH = os.path.join(ROOT, "db", "enterprise.db")
_OUT_DIR = os.path.join(ROOT, "output")


@app.route("/api/evolve/proposals", methods=["GET"])
def evolve_list_proposals():
    try:
        from evolution_reviewer import list_pending
    except ImportError as exc:
        return jsonify({"error": f"evolution module unavailable: {exc}"}), 500
    band = request.args.get("band")
    limit = int(request.args.get("limit", "100"))
    return jsonify({"proposals": list_pending(_DB_PATH, band=band, limit=limit)})


@app.route("/api/evolve/proposals/<proposal_id>", methods=["GET"])
def evolve_get_proposal(proposal_id: str):
    from evolution_reviewer import get_proposal
    p = get_proposal(_DB_PATH, proposal_id)
    if not p:
        return jsonify({"error": "not found"}), 404
    return jsonify(p)


@app.route("/api/evolve/proposals/<proposal_id>/decision", methods=["POST"])
def evolve_record_decision(proposal_id: str):
    from evolution_reviewer import record_decision
    body = request.get_json(force=True) or {}
    action = body.get("action", "").upper()
    if action not in ("APPROVE", "REJECT", "DEFER"):
        return jsonify({"error": "action must be APPROVE|REJECT|DEFER"}), 400
    result = record_decision(
        db_path=_DB_PATH,
        proposal_id=proposal_id,
        action=action,
        reviewer_id=body.get("reviewer_id", "wizard:reviewer"),
        note=body.get("note", ""),
        version_target=body.get("version_target"),
        defer_until=body.get("defer_until"),
    )
    return jsonify(result)


@app.route("/api/evolve/proposals/<proposal_id>/apply", methods=["POST"])
def evolve_apply(proposal_id: str):
    from evolution_reviewer import apply_approved
    body = request.get_json(silent=True) or {}
    result = apply_approved(
        db_path=_DB_PATH,
        out_path=_OUT_DIR,
        proposal_id=proposal_id,
        open_pr=bool(body.get("open_pr", False)),
        dry_run=bool(body.get("dry_run", False)),
    )
    return jsonify(result)


@app.route("/api/evolve/run", methods=["POST"])
def evolve_run_monitor():
    """Kick the monitor + scorer.  Non-blocking for large runs is not
    required yet — the monitor is quick against local SQLite."""
    from evolution_monitor import run_evolution_monitor
    from evolution_scorer  import score_pending
    body = request.get_json(silent=True) or {}
    _ = run_evolution_monitor(
        db_path=_DB_PATH,
        out_path=_OUT_DIR,
        min_evidence=int(body.get("min_evidence", 3)),
        strategy=body.get("strategy"),
    )
    summary = score_pending(db_path=_DB_PATH, out_path=_OUT_DIR)
    return jsonify(summary)


# ── Workstream 4 — Regulatory AI Compliance Evidence Engine ────────────────

@app.route("/api/comply/regulations", methods=["GET"])
def comply_list_regulations():
    try:
        sys.path.insert(0, ROOT)
        from compliance import registry as reg_mod
    except ImportError as exc:
        return jsonify({"error": f"compliance module unavailable: {exc}"}), 500
    return jsonify({"regulations": reg_mod.list_regulations()})


@app.route("/api/comply/regulations/<regulation_id>", methods=["GET"])
def comply_get_regulation(regulation_id: str):
    """Return the full raw regulation JSON for the viewer link."""
    sys.path.insert(0, ROOT)
    from compliance import registry as reg_mod
    try:
        return jsonify(reg_mod.load_regulation(regulation_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.route("/api/comply/coverage", methods=["GET"])
def comply_coverage():
    sys.path.insert(0, ROOT)
    from compliance import mapping as map_mod
    return jsonify(map_mod.coverage_score(
        out_path=_OUT_DIR,
        db_path=_DB_PATH,
    ))


@app.route("/api/comply/gap", methods=["GET"])
def comply_gap():
    sys.path.insert(0, ROOT)
    from compliance import mapping as map_mod
    return jsonify(map_mod.gap_analysis(out_path=_OUT_DIR))


@app.route("/api/comply/bundles", methods=["GET"])
def comply_bundles():
    sys.path.insert(0, ROOT)
    from compliance import bundle as bun_mod
    return jsonify({"bundles": bun_mod.list_bundles(_DB_PATH)})


@app.route("/api/comply/assemble", methods=["POST"])
def comply_assemble():
    sys.path.insert(0, ROOT)
    from compliance import assembler as asm_mod, bundle as bun_mod
    body = request.get_json(force=True) or {}
    regulation_id = body.get("regulation_id")
    if not regulation_id:
        return jsonify({"error": "regulation_id is required"}), 400
    decision_iri = body.get("decision_iri") or None
    try:
        ev = asm_mod.assemble_evidence(
            regulation_id=regulation_id,
            decision_iri=decision_iri,
            db_path=_DB_PATH,
            out_path=_OUT_DIR,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    bundle = bun_mod.export_bundle(
        ev,
        publish_to_graph=True,
        db_path=_DB_PATH,
    )
    return jsonify({"evidence": ev, "bundle": bundle})


@app.route("/api/comply/verify", methods=["POST"])
def comply_verify():
    sys.path.insert(0, ROOT)
    from compliance import bundle as bun_mod
    body = request.get_json(force=True) or {}
    path = body.get("bundle_path")
    if not path:
        return jsonify({"error": "bundle_path is required"}), 400
    return jsonify(bun_mod.verify_bundle(path))


# ── Workstream 5 — Ontology-Bounded Vector Retrieval ──────────────────────

@app.route("/api/retrieve/indexes", methods=["GET"])
def retrieve_list_indexes():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "runtime"))
    from runtime.embeddings import pipeline as pipe_mod
    return jsonify({"indexes": pipe_mod.list_indexes(_DB_PATH)})


@app.route("/api/retrieve/index/<flavor>", methods=["POST"])
def retrieve_index_flavor(flavor: str):
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "runtime"))
    from runtime.embeddings import pipeline as pipe_mod
    body = request.get_json(silent=True) or {}
    return jsonify(pipe_mod.index_flavor(
        flavor,
        db_path=_DB_PATH,
        connection_string=body.get("vector_store"),
        model_id=body.get("model"),
        force=bool(body.get("force", False)),
    ))


@app.route("/api/retrieve/query", methods=["POST"])
def retrieve_query():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "runtime"))
    from runtime.hybrid_retriever import HybridRetriever
    body = request.get_json(force=True) or {}
    flavor = body.get("flavor")
    question = body.get("question")
    if not (flavor and question):
        return jsonify({"error": "flavor and question are required"}), 400
    retriever = HybridRetriever(flavor=flavor, db_path=_DB_PATH)
    return jsonify(retriever.retrieve(
        question,
        class_expression=body.get("class_expression"),
        k=int(body.get("k", 5)),
        strategy=body.get("strategy", "ONTOLOGY_BOUNDED"),
    ))


@app.route("/api/retrieve/benchmark", methods=["POST"])
def retrieve_benchmark():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "runtime"))
    from runtime.embeddings import benchmark as bench_mod
    return jsonify(bench_mod.run_benchmark(db_path=_DB_PATH, out_path=_OUT_DIR))


@app.route("/api/retrieve/benchmark", methods=["GET"])
def retrieve_benchmark_latest():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "runtime"))
    from runtime.embeddings import benchmark as bench_mod
    return jsonify({"strategies": bench_mod.read_latest_benchmark(_DB_PATH)})


@app.route("/api/output/<subdir>/<filename>")
def serve_output(subdir: str, filename: str):
    out_dir = os.path.join(ROOT, "output", subdir)
    safe_filename = Path(filename).name
    full_path = os.path.join(out_dir, safe_filename)
    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404
    return send_file(full_path, as_attachment=False)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ontology Toolkit — Ontology Studio (v3.0)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  Ontology Toolkit — Ontology Studio (v3.0)")
    print(f"  ────────────────────────────────────────────")
    print(f"  URL: http://{args.host}:{args.port}")
    print(f"  Session file: {SESSION_FILE}")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
