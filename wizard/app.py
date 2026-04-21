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


@app.route("/api/templates", methods=["GET"])
def list_templates():
    names = []
    if os.path.isdir(TEMPLATES_DIR):
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if fname.endswith((".yaml", ".yml")):
                names.append(fname.rsplit(".", 1)[0])
    builtin = ["telecom", "healthcare", "finance"]
    return jsonify({"templates": builtin + names})


@app.route("/api/template/<name>", methods=["GET"])
def load_template(name: str):
    try:
        import yaml
        for ext in (".yaml", ".yml"):
            path = os.path.join(TEMPLATES_DIR, name + ext)
            if os.path.exists(path):
                with open(path) as f:
                    tmpl = yaml.safe_load(f)
                session = {
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
                                {"name": pn, "type": (pv.get("type", "string") if isinstance(pv, dict) else "string"),
                                 "required": (pv.get("required", False) if isinstance(pv, dict) else False)}
                                for item in (e.get("properties") or [])
                                for pn, pv in (item.items() if isinstance(item, dict) else [])
                            ]
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
                _save_session(session)
                return jsonify(session)
    except ImportError:
        return jsonify({"error": "PyYAML not installed — run: pip install pyyaml"}), 500
    return jsonify({"error": f"Template '{name}' not found"}), 404


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
