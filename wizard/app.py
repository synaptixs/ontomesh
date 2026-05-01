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

# Built-in starter templates live in onboard.py's INDUSTRY_TEMPLATES dict
# (telecom, healthcare, finance, manufacturing, retail). Import them so the
# browser wizard and the CLI wizard share the same source of truth.
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
        "relationships": tmpl.get("relationships", []),
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
    return jsonify({"templates": out})


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


@app.route("/api/pipeline/status", methods=["GET"])
def pipeline_status():
    return jsonify({
        "running": _pipeline_running,
        "log_lines": len(_pipeline_log),
        "last_lines": _pipeline_log[-50:] if _pipeline_log else [],
    })


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
    parser = argparse.ArgumentParser(description="Ontology Toolkit Browser Wizard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  Ontology Toolkit Browser Wizard")
    print(f"  ─────────────────────────────────")
    print(f"  URL: http://{args.host}:{args.port}")
    print(f"  Session file: {SESSION_FILE}")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
