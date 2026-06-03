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
# P2.3 — Database URL.  Defaults to local SQLite for back-compat;
# set ONTOMESH_DB_URL=postgresql://user:pass@host/db to use Postgres
# (requires ``pip install ontomesh[postgres]``).
ONTOLOGIES_DB = os.environ.get(
    "ONTOMESH_DB_URL",
    os.path.join(ROOT, "db", "ontologies.db"),
)
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

# P3.4 — JSON access logging + X-Request-Id correlation.  Installed
# AFTER `app` exists so every Flask request goes through the
# before/after-request hooks.
try:
    from wizard.structured_logging import install as _install_logging
    _install_logging(app)
except Exception as _exc:                                              # noqa: BLE001
    # Logging setup must NEVER prevent the wizard from booting.
    print(f"[wizard.app] structured logging install skipped: {_exc!r}",
          file=sys.stderr)

# P3.5 — Prometheus /metrics endpoint.
try:
    from wizard.metrics_exporter import install as _install_metrics
    _install_metrics(app)
except Exception as _exc:                                              # noqa: BLE001
    print(f"[wizard.app] metrics install skipped: {_exc!r}",
          file=sys.stderr)

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
def landing():
    """P1.2 — Marketing landing page.

    Before v3.5 the wizard chrome was served from ``/``.  Now the
    root is a marketing surface (hero, value prop, how-it-works,
    CTA) and the wizard lives at ``/wizard``.  Bookmarks that
    deep-linked via ``/?step=X`` are forwarded to the wizard so
    external docs and saved links don't break.

    P1.2.5 — the card stats on the landing read from the actual
    benchmark output at render time.  If ``benchmarks/last-run.json``
    is missing or stale, the landing falls back to a "see how it
    works" tagline instead of inventing numbers.
    """
    from flask import render_template, redirect, request
    if request.args.get("step"):
        return redirect("/wizard?" + request.query_string.decode("utf-8"), code=301)
    bench = _load_benchmark()
    return render_template("landing.html", bench=bench)


def _load_benchmark() -> dict:
    """Read ``benchmarks/last-run.json`` if present so the landing's
    card stats stay grounded in real numbers.  Returns ``None`` when
    no benchmark has been run yet — the template treats that as the
    "show capability statements instead of numbers" case."""
    path = os.path.join(ROOT, "benchmarks", "last-run.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not data.get("ok"):
            return None
        # Pretty-print 1429 -> "1,429".
        data["owl_properties_human"] = f"{data.get('owl_properties', 0):,}"
        return data
    except (OSError, ValueError):
        return None


@app.route("/wizard")
def wizard():
    """The interactive wizard — what used to live at ``/``."""
    from flask import render_template
    return render_template("index.html")


# ── P1.4 — Project dashboard ──────────────────────────────────────────


@app.route("/projects")
def projects():
    """Standalone dashboard that lists every saved ontology with one-
    click resume.  Lives outside the wizard chrome so a returning user
    can jump straight from the marketing landing to "their work."
    """
    from flask import render_template
    return render_template("projects.html")


@app.route("/index")
def _legacy_index():
    """Redirect for legacy bookmarks that hit /index or /?step=...
    Send them to the wizard so deep-linking from external docs still
    works after the route reshuffle."""
    from flask import redirect, request
    qs = request.query_string.decode("utf-8")
    target = "/wizard" + ("?" + qs if qs else "")
    return redirect(target, code=301)


@app.route("/health")
def health():
    """Back-compat alias.  Behaves like /live — returns 200 as long
    as the process is responding to HTTP.  New deployments should
    prefer /live (k8s livenessProbe) + /ready (readinessProbe)."""
    return jsonify({"ok": True, "timestamp": _now()})


# ── P3.3 — Differentiated liveness / readiness probes ─────────────────


@app.route("/live")
def live():
    """**Liveness probe.**  Cheap, no I/O.  Returns 200 as long as
    the process is alive.  Used by Docker / k8s livenessProbe; a
    failure here means "restart this pod."

    Deliberately does NOT touch the DB or Redis — a pod with a
    broken DB connection is STILL alive and should NOT be killed
    (the restart loop wouldn't help; the DB is the problem)."""
    return jsonify({
        "status":    "alive",
        "version":   _version_string(),
        "timestamp": _now(),
    })


@app.route("/ready")
def ready():
    """**Readiness probe.**  Checks every dependency the wizard
    needs to serve traffic.  Used by k8s readinessProbe + load
    balancer; a failure here means "don't route traffic here yet,"
    but the pod stays alive (so it can recover).

    Currently probes:
      • Saved-ontologies + preferences store (SQLite or Postgres).
      • Event bus (in-memory always passes; Redis pings the server).

    Returns 200 with ``status: ready`` when everything is up.
    Returns 503 with per-dependency detail when anything is down.
    The body shape is stable so monitoring can parse it."""
    checks: dict[str, dict] = {}
    overall_ok = True

    # ── Saved-ontologies store ──
    try:
        _store.list_ontologies(ONTOLOGIES_DB)
        checks["store"] = {"ok": True, "backend": _store_backend_name()}
    except Exception as exc:                                          # noqa: BLE001
        checks["store"] = {"ok": False, "error": str(exc)[:200]}
        overall_ok = False

    # ── Event bus ──
    try:
        if "_src" not in dir():
            import sys as _sys
            _src = os.path.join(ROOT, "src")
            if _src not in _sys.path:
                _sys.path.insert(0, _src)
        from events_bus import get_bus                                # noqa: E402
        stats = get_bus().stats
        checks["events"] = {"ok": True, "backend": stats.get("backend", "unknown")}
    except Exception as exc:                                          # noqa: BLE001
        checks["events"] = {"ok": False, "error": str(exc)[:200]}
        overall_ok = False

    response = {
        "status":     "ready" if overall_ok else "not_ready",
        "checks":     checks,
        "version":    _version_string(),
        "timestamp":  _now(),
    }
    return jsonify(response), (200 if overall_ok else 503)


def _version_string() -> str:
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from ontomesh import __version__                              # noqa: E402
        return __version__
    except Exception:                                                 # noqa: BLE001
        return "unknown"


def _store_backend_name() -> str:
    """Best-effort label for /ready — 'sqlite' or 'postgres'."""
    url = str(ONTOLOGIES_DB)
    if url.startswith("postgresql") or url.startswith("postgres"):
        return "postgres"
    return "sqlite"


# ── P1.1 — Branded error pages ────────────────────────────────────────


@app.errorhandler(404)
def _not_found(e):                                                  # noqa: ARG001
    from flask import render_template as _rt                        # noqa: E402
    return _rt(
        "error.html",
        code="404",
        title="Page not found",
        message="That page isn't here. Maybe it moved during the rename "
                "to Ontomesh, or you followed a stale link.",
    ), 404


@app.errorhandler(500)
def _server_error(e):                                               # noqa: ARG001
    from flask import render_template as _rt                        # noqa: E402
    return _rt(
        "error.html",
        code="500",
        title="Something broke",
        message="An unexpected error stopped the request. Check the "
                "server logs, then try again — your session data is "
                "intact.",
    ), 500


@app.route("/api/events/stream")
def events_stream():
    """P0.3 — Server-Sent Events endpoint.

    Subscribes a new client to the in-memory event bus and streams
    events as ``text/event-stream``. The client uses ``EventSource``
    on this URL; each event arrives as a typed message
    (``metric`` / ``drift`` / ``status`` / ``hello`` / ``ping``).

    A 20-second idle timeout emits a ``: ping`` comment so proxies
    (nginx, gunicorn) don't close the connection.
    """
    from flask import Response, stream_with_context
    try:
        import sys as _sys
        _src = os.path.join(ROOT, "src")
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
        from events_bus import get_bus                              # noqa: E402
    except Exception as exc:                                        # noqa: BLE001
        return jsonify({"error": f"bus unavailable: {exc}"}), 500

    bus = get_bus()
    sub = bus.subscribe()

    def _generate():
        # Hello packet so the client knows the connection is live
        # and which subscriber id it's bound to (useful in dev tools).
        yield (f"event: hello\n"
               f"data: {json.dumps({'subscriber_id': sub.id})}\n\n")
        try:
            while True:
                event = sub.get(timeout=20.0)
                if event is None:
                    # Keep-alive comment — no event name, just a ping.
                    yield ": ping\n\n"
                    continue
                kind = event.get("kind", "message")
                yield (f"event: {kind}\n"
                       f"data: {json.dumps(event)}\n\n")
        except GeneratorExit:
            pass
        finally:
            bus.unsubscribe(sub)

    response = Response(stream_with_context(_generate()),
                        mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"      # nginx hint
    return response


@app.route("/api/events/stats", methods=["GET"])
def events_stats():
    """Tiny GET used by the wizard's dev panel to confirm the bus
    is alive and how many subscribers / events have flowed."""
    try:
        import sys as _sys
        _src = os.path.join(ROOT, "src")
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
        from events_bus import get_bus                              # noqa: E402
    except Exception:                                               # noqa: BLE001
        return jsonify({"available": False})
    return jsonify({"available": True, **get_bus().stats})


@app.route("/log-discovery/help")
def log_discovery_help():
    """Serve the Log Discovery help page — capabilities, algorithms,
    benefits, and the user-facing workflow. Linked from the Step 5
    panel header."""
    return send_from_directory(
        os.path.join(HERE, "templates"), "log_discovery_help.html",
    )


# ── P0.4 — per-phase help pages ────────────────────────────────────────


@app.route("/help/<slug>")
def phase_help(slug):
    """Render the help page for one wizard phase.

    All phases except Log Discovery (which has a bespoke deeper page
    at /log-discovery/help) share one Jinja template fed by the
    ``HELP_PAGES`` dict in ``wizard/help_content.py``."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from help_content import get_help                              # noqa: E402
    # Log Discovery keeps its bespoke deeper page.
    if slug == "log-discovery":
        return log_discovery_help()
    page = get_help(slug)
    if page is None:
        return ("Unknown phase: " + slug, 404)
    from flask import render_template as _rt                       # noqa: E402
    return _rt("phase_help.html", page=page)


@app.route("/help")
def phase_help_index():
    """Redirect /help → first phase help page."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from help_content import all_slugs                             # noqa: E402
    slugs = all_slugs()
    first = slugs[0] if slugs else "domain"
    return phase_help(first)


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
    # P1.5.2 — Whitelist model.  Step 1's template grid now shows
    # ONLY the domains the user has explicitly opted into via Settings,
    # not "everything minus a hidden list."  Default = empty whitelist =
    # nothing on Step 1 until the user picks.
    #
    # The legacy ``landing.hidden_domains`` key is still accepted on
    # writes (for back-compat with older session DBs) but is no longer
    # the source of truth on reads.
    prefs = _store.get_preferences(ONTOLOGIES_DB)
    raw_visible = prefs.get("landing.visible_domains")
    if raw_visible is None:
        # No explicit whitelist yet — return an empty visible list so
        # the wizard's Step 1 grid shows its "pick in Settings" empty
        # state.  Brand-new sessions land here.
        visible_set: set[str] = set()
    else:
        visible_set = set(raw_visible)
    visible = [n for n in out if n in visible_set]
    # We still echo the hidden list (= every template NOT in the
    # whitelist) so existing UI code that reads it keeps working
    # until it's migrated.
    hidden = [n for n in out if n not in visible_set]
    return jsonify({
        "templates": visible,
        "visible":   visible,           # canonical key going forward
        "hidden":    sorted(hidden),    # legacy key
        "all":       out,
    })


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


# ── /api/db — database-direct import + connection profiles ───────────────
#
# Sister to /api/import (which handles file uploads). Two roles:
#   1. Vendor catalogue + profile CRUD so the wizard's "Connect to
#      database" tab can render dynamic forms and remember credentials.
#   2. Schema introspection that lifts a live DB into the same
#      ImportResult shape the JSON-file path produces, so the existing
#      review modal handles both paths identically.


def _db_conn():
    import sqlite3 as _sqlite3
    return _sqlite3.connect(ONTOLOGIES_DB)


def _load_db_profiles_module():
    """Lazy + path-tolerant import of wizard.db_profiles."""
    try:
        from . import db_profiles as _dp
    except ImportError:
        sys.path.insert(0, HERE)
        import db_profiles as _dp                    # type: ignore[no-redef]
    return _dp


@app.route("/api/db/vendors", methods=["GET"])
def db_vendors():
    """Vendor catalogue — id, label, icon, field schema. The browser
    renders forms straight from this; adding a vendor in
    wizard/db_profiles.py surfaces it here without UI changes."""
    dp = _load_db_profiles_module()
    return jsonify({"vendors": dp.vendor_list()})


@app.route("/api/db/profiles", methods=["GET"])
def db_profiles_list():
    dp = _load_db_profiles_module()
    conn = _db_conn()
    try:
        profiles = dp.list_profiles(conn)
    finally:
        conn.close()
    return jsonify({"profiles": [p.to_dict(mask_secrets=True) for p in profiles]})


@app.route("/api/db/profiles", methods=["POST"])
def db_profile_save():
    """Create or update. Body:
        {id?, name, vendor, config: {...}}
    Returns the saved profile with secrets masked."""
    dp = _load_db_profiles_module()
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    vendor = (body.get("vendor") or "").strip()
    config = body.get("config") or {}
    if not (name and vendor):
        return jsonify({"error": "name and vendor are required"}), 400
    if not isinstance(config, dict):
        return jsonify({"error": "config must be an object"}), 400
    pid = body.get("id")
    conn = _db_conn()
    try:
        profile = dp.save_profile(
            conn, name=name, vendor=vendor, config=config,
            profile_id=int(pid) if pid else None,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:                          # noqa: BLE001
        return jsonify({"error": f"save failed: {exc}"}), 500
    finally:
        conn.close()
    return jsonify({"ok": True, "profile": profile.to_dict(mask_secrets=True)})


@app.route("/api/db/profiles/<int:profile_id>", methods=["DELETE"])
def db_profile_delete(profile_id: int):
    dp = _load_db_profiles_module()
    conn = _db_conn()
    try:
        ok = dp.delete_profile(conn, profile_id)
    finally:
        conn.close()
    if not ok:
        return jsonify({"error": "profile not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/db/test", methods=["POST"])
def db_test_connection():
    """Test a connection. Body either:
        {vendor, config}            — try the supplied creds
        {profile_id}                — try a stored profile
    Returns {ok, tables, sample_tables, duration_ms, error?}."""
    dp = _load_db_profiles_module()
    body = request.get_json(force=True) or {}
    vendor = (body.get("vendor") or "").strip()
    config = body.get("config") or {}
    profile_id = body.get("profile_id")
    if profile_id is not None:
        conn = _db_conn()
        try:
            profile = dp.get_profile(conn, int(profile_id))
        finally:
            conn.close()
        if not profile:
            return jsonify({"ok": False, "error": "profile not found"}), 404
        vendor = profile.vendor
        config = profile.config
    if not vendor:
        return jsonify({"error": "vendor is required"}), 400
    res = dp.probe_connection(vendor, config)
    return jsonify(res.to_dict())


@app.route("/api/db/import", methods=["POST"])
def db_import():
    """Introspect a live DB into a wizard session — does not persist.
    The browser's review modal then commits via /api/import/commit so
    file and DB imports share the same final-guard path.

    Body either:
        {vendor, config, domain_name?, base_iri?}
        {profile_id, domain_name?, base_iri?}
    """
    dp = _load_db_profiles_module()
    body = request.get_json(force=True) or {}
    vendor = (body.get("vendor") or "").strip()
    config = body.get("config") or {}
    profile_id = body.get("profile_id")
    if profile_id is not None:
        conn = _db_conn()
        try:
            profile = dp.get_profile(conn, int(profile_id))
        finally:
            conn.close()
        if not profile:
            return jsonify({"error": "profile not found"}), 404
        vendor = profile.vendor
        config = profile.config
    if not vendor:
        return jsonify({"error": "vendor is required"}), 400

    try:
        session = dp.introspect_to_session(
            vendor, config,
            domain_name=(body.get("domain_name") or "").strip(),
            base_iri=(body.get("base_iri") or "").strip(),
        )
    except RuntimeError as exc:
        return jsonify({
            "ok": False, "format": "database",
            "errors": [{"code": "DB_INTROSPECT_FAILED", "severity": "error",
                        "message": str(exc),
                        "fix_hint": "Verify host, port, credentials, and that "
                                    "the user can list tables."}],
            "warnings": [], "stats": {}, "session": None,
        })

    # Shape-compatible with /api/import so the review modal can
    # consume it without branching.
    stats = {
        "entities": len(session.get("entities") or []),
        "relationships": len(session.get("relationships") or []),
        "events": len(session.get("events") or []),
    }
    return jsonify({
        "ok": True, "format": "database",
        "errors": [], "warnings": [],
        "stats": stats,
        "session": session,
    })


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


@app.route("/api/insights/rca-presets", methods=["GET"])
def insights_rca_presets():
    """List RCA prompt presets — keyed by name with the template
    string. The wizard renders them in the Ask Insights panel."""
    from runtime.insights import list_rca_presets
    return jsonify({"presets": list_rca_presets()})


@app.route("/api/insights/rca", methods=["POST"])
def insights_rca():
    """Run an RCA preset against the materialised graph. Body:

        { "preset": "root-cause" | "similar-incidents",
          "event_iri": "https://ontology.example.com/enterprise/dr_a",
          "provider": "openai" (optional),
          "model": "..." (optional) }

    Materialised triples are sent regardless of the toggle since RCA
    only makes sense with the inferred graph. The residency warning
    from :class:`Insights.ask` still fires for public-cloud providers.
    """
    from runtime.insights import Insights, expand_rca_preset
    body = request.get_json(force=True) or {}
    preset = (body.get("preset") or "").strip()
    event_iri = (body.get("event_iri") or "").strip()
    if not (preset and event_iri):
        return jsonify({"error": "preset and event_iri are required"}), 400
    try:
        question = expand_rca_preset(preset, event_iri=event_iri)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400

    ontology_path = os.path.join(OUTPUT_DIR, "ontology", "enterprise.ttl")
    materialised_path = os.path.join(OUTPUT_DIR, "ontology", "materialised.ttl")
    if not os.path.isfile(ontology_path):
        return jsonify({"error": "no ontology — run --phase 2 first"}), 400
    insights = Insights(
        ontology_path,
        materialised_path if os.path.isfile(materialised_path) else None,
    )
    try:
        result = insights.ask(
            question,
            provider=body.get("provider"),
            model=body.get("model"),
            include_materialised=True,    # RCA needs the inferred graph
        )
    except Exception as exc:                # noqa: BLE001
        return jsonify({"error": str(exc)}), 502
    out = result.to_dict()
    out["preset"] = preset
    out["event_iri"] = event_iri
    return jsonify(out)


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


# ── Phase L4 — Log Discovery review surface ──────────────────────────────


_ENTERPRISE_DB = os.path.join(ROOT, "db", "enterprise.db")
_REVIEW_RANKER_PATH = os.path.join(ROOT, "db", "review_ranker.pkl")


def _log_review_conn():
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(_ENTERPRISE_DB)
    # Ensure L9 (and reserved L8) tables exist whenever the wizard
    # opens the proposal store. Cheap — idempotent IF NOT EXISTS.
    try:
        from db.migrations.log_discovery_v2 import migrate as _v2_migrate
        _v2_migrate(conn)
    except Exception:                                      # noqa: BLE001
        pass
    # T1.1 — name_source / name_generated_at columns for the LLM
    # naming pass. Additive nullable, no-op on re-run.
    try:
        from db.migrations.v3_proposal_namer import migrate as _v3_migrate
        _v3_migrate(conn)
    except Exception:                                      # noqa: BLE001
        pass
    return conn


def _load_review_ranker():
    """Forgiving loader for the L9 ranker. Returns None if absent or
    unloadable — callers degrade to SQL-default ordering."""
    try:
        from wizard.review_ranker import ReviewRanker
        return ReviewRanker.load_or_none(_REVIEW_RANKER_PATH)
    except Exception:                                      # noqa: BLE001
        return None


@app.route("/api/log-discovery/summary", methods=["GET"])
def log_discovery_summary():
    """Headline counts per kind/status. Used by the Log Discovery
    sidebar entry to show how many proposals await review."""
    import sqlite3
    from wizard import log_review
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"available": False,
                        "reason": "no enterprise.db — run --phase mine first"})
    conn = _log_review_conn()
    try:
        out = log_review.summary(conn)
    finally:
        conn.close()
    return jsonify(out)


@app.route("/api/log-discovery/candidates", methods=["GET"])
def log_discovery_candidates():
    """List candidates. Query params: kind, status, limit."""
    from wizard import log_review
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"candidates": [], "available": False})
    kind = request.args.get("kind") or None
    status = request.args.get("status") or "PENDING"
    try:
        limit = max(1, min(500, int(request.args.get("limit", "50"))))
    except ValueError:
        limit = 50
    conn = _log_review_conn()
    ranker = _load_review_ranker()
    try:
        cands = log_review.list_candidates(
            conn, kind=kind, status=status, limit=limit, ranker=ranker)
    finally:
        conn.close()
    return jsonify({
        "candidates": cands,
        "available": True,
        "ranked": bool(ranker and ranker.is_fitted()),
    })


@app.route("/api/log-discovery/seed", methods=["POST"])
def log_discovery_seed():
    """Re-seed the proposal store from the latest L1/L2 outputs.

    Body (optional):
        {"log_path": "/path/to/logs", "with_causality": true}

    When ``log_path`` is supplied, re-mines the corpus briefly to get
    the in-memory extractions and runs L3's triangulation gate. Without
    a log_path the seed falls back to the L1-only path (directed PMI
    edges → causal proposals, no statistical gating).
    """
    from wizard import log_review
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"error": "no enterprise.db — run --phase mine first"}), 400
    body = request.get_json(silent=True) or {}
    log_path = (body.get("log_path") or "").strip()
    extractions = None
    if log_path and body.get("with_causality", True):
        try:
            from log_corpus import LogCorpus
            from log_templates import LogTemplateMiner
            miner = LogTemplateMiner(_log_review_conn())
            for rec in LogCorpus(log_path).iter():
                miner.consume(rec.message, timestamp=rec.timestamp,
                              severity=rec.severity,
                              service=rec.fields.get("service") if rec.fields else None,
                              trace_id=rec.fields.get("trace_id") if rec.fields else None)
            miner.flush()
            extractions = miner.extractions
        except Exception:                       # noqa: BLE001 — fall back to L1-only
            extractions = None

    conn = _log_review_conn()
    try:
        counts = log_review.seed_from_mining(conn, extractions=extractions)
    finally:
        conn.close()
    return jsonify({"ok": True, "counts": counts,
                    "triangulation": bool(extractions)})


@app.route("/api/log-discovery/<proposal_id>/approve", methods=["POST"])
def log_discovery_approve(proposal_id):
    from wizard import log_review
    body = request.get_json(force=True) or {}
    edits = body.get("edits") or {}
    session = _load_session()
    conn = _log_review_conn()
    try:
        result = log_review.approve(conn, session, proposal_id, edits=edits)
    except KeyError:
        return jsonify({"error": "proposal not found"}), 404
    finally:
        conn.close()
    _save_session(session)
    return jsonify(result)


@app.route("/api/log-discovery/<proposal_id>/reject", methods=["POST"])
def log_discovery_reject(proposal_id):
    from wizard import log_review
    body = request.get_json(force=True) or {}
    note = (body.get("note") or "").strip()
    conn = _log_review_conn()
    try:
        result = log_review.reject(conn, proposal_id, note=note)
    finally:
        conn.close()
    return jsonify(result)


@app.route("/api/log-discovery/<proposal_id>/merge", methods=["POST"])
def log_discovery_merge(proposal_id):
    from wizard import log_review
    body = request.get_json(force=True) or {}
    into = (body.get("into") or "").strip()
    if not into:
        return jsonify({"error": "into is required"}), 400
    session = _load_session()
    conn = _log_review_conn()
    try:
        result = log_review.merge(conn, session, proposal_id, into_name=into)
    except KeyError:
        return jsonify({"error": "proposal not found"}), 404
    finally:
        conn.close()
    _save_session(session)
    return jsonify(result)


@app.route("/api/log-discovery/llm-rename", methods=["POST"])
def log_discovery_llm_rename():
    """T1.1 — run the LLM proposal namer over PENDING proposals
    whose ``name_source`` is still ``'auto'``. Provider is selected
    by the ``PROPOSAL_NAMER_PROVIDER`` env var; falls back to no-op
    when no provider is configured.

    Body (optional):
        {"force": false, "limit": 50}

    ``force`` re-runs the namer on rows already marked ``llm`` but
    never touches rows that are ``human``."""
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"error": "no enterprise.db — run --phase mine first"}), 400
    try:
        from wizard.proposal_namer import (
            get_provider, rename_pending_proposals,
        )
    except Exception as exc:                                       # noqa: BLE001
        return jsonify({"error": f"namer module unavailable: {exc}"}), 500
    provider = get_provider()
    if provider is None:
        return jsonify({
            "ok": True,
            "skipped": True,
            "reason": (
                "no provider configured — set PROPOSAL_NAMER_PROVIDER "
                "(mock|anthropic|openai) and the matching API key"
            ),
        })
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force", False))
    try:
        limit = max(1, min(500, int(body.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50
    conn = _log_review_conn()
    try:
        stats = rename_pending_proposals(
            conn, provider=provider, force=force, limit=limit,
        )
    finally:
        conn.close()
    return jsonify({"ok": True, **stats})


@app.route("/api/log-discovery/llm-rename-status", methods=["GET"])
def log_discovery_llm_rename_status():
    """Lightweight GET for the UI to decide whether to enable the
    'LLM rename' button. Reports which provider is configured and
    how many proposals are still 'auto' (eligible for renaming)."""
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"available": False, "reason": "no enterprise.db"})
    try:
        from wizard.proposal_namer import get_provider
    except Exception:                                              # noqa: BLE001
        return jsonify({"available": False, "reason": "import"})
    provider = get_provider()
    conn = _log_review_conn()
    try:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(ontology_evolution_proposals)"
        )}
        if "name_source" not in cols:
            return jsonify({"available": False, "reason": "v3 migration"})
        auto_count = conn.execute(
            "SELECT COUNT(*) FROM ontology_evolution_proposals "
            "WHERE name_source = 'auto' AND status = 'PENDING'"
        ).fetchone()[0]
        llm_count = conn.execute(
            "SELECT COUNT(*) FROM ontology_evolution_proposals "
            "WHERE name_source = 'llm'"
        ).fetchone()[0]
    finally:
        conn.close()
    return jsonify({
        "available": True,
        "provider":  provider.name if provider else "none",
        "auto_pending": int(auto_count),
        "llm_named":    int(llm_count),
    })


@app.route("/api/log-discovery/rate-anomalies", methods=["POST"])
def log_discovery_rate_anomalies():
    """L13 — run the GP rate-anomaly detector against the current
    enterprise.db corpus and persist any hits as LOG_EVENT proposals
    with detection_strategy='GP_RATE_DEVIATION'.

    Body (optional): ``{"log_path": "/path/to/logs"}``. When supplied
    we re-extract from the corpus; otherwise we replay the cached
    extractions from log_templates (sample lines only — coarse but
    free)."""
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"error": "no enterprise.db — run --phase mine first"}), 400
    try:
        import sys as _sys
        _src = os.path.join(ROOT, "src")
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
        from log_rate_anomalies import mine_rate_anomalies          # noqa: E402
    except Exception as exc:                                        # noqa: BLE001
        return jsonify({"error": f"module unavailable: {exc}"}), 500

    body = request.get_json(silent=True) or {}
    log_path = (body.get("log_path") or "").strip()
    extractions = []
    if log_path:
        try:
            from log_corpus import LogCorpus                        # noqa: E402
            from log_templates import LogTemplateMiner              # noqa: E402
            miner = LogTemplateMiner(_log_review_conn())
            for rec in LogCorpus(log_path).iter():
                miner.consume(rec.message, timestamp=rec.timestamp,
                              severity=rec.severity,
                              service=rec.fields.get("service") if rec.fields else None,
                              trace_id=rec.fields.get("trace_id") if rec.fields else None)
            miner.flush()
            extractions = list(miner.extractions or [])
        except Exception:                                           # noqa: BLE001
            extractions = []

    conn = _log_review_conn()
    try:
        report = mine_rate_anomalies(extractions, conn) if extractions \
                 else type("R", (), {"as_dict": lambda self: {
                     "templates_examined": 0, "templates_fit": 0,
                     "anomalies": 0, "proposals_persisted": 0,
                     "duration_s": 0.0,
                 }})()
    finally:
        conn.close()
    return jsonify({"ok": True, "report": report.as_dict()})


@app.route("/api/log-discovery/template-embedding", methods=["GET"])
def log_discovery_template_embedding():
    """L12 — return the pPCA viz payload for the Step 5 scatter.

    Body shape (success):
        {"available": true, "points": [...], "merges": [...],
         "n_templates": N, "explained_variance_ratio": [...], ...}
    On any failure (no log_templates table, too few templates,
    sklearn missing) returns ``{'available': False, 'reason': '...'}``
    so the UI degrades gracefully — no scatter, no merge list."""
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"available": False,
                        "reason": "no enterprise.db — run --phase mine first"})
    try:
        import sys as _sys
        _src = os.path.join(ROOT, "src")
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
        from log_templates_embed import TemplateEmbedder         # noqa: E402
    except Exception as exc:                                     # noqa: BLE001
        return jsonify({"available": False, "reason": f"import: {exc}"})
    conn = _log_review_conn()
    try:
        try:
            e = TemplateEmbedder().fit(conn)
        except RuntimeError as exc:
            return jsonify({"available": False, "reason": str(exc)})
        payload = e.viz_payload()
    finally:
        conn.close()
    payload["available"] = True
    return jsonify(payload)


@app.route("/api/log-discovery/rerank", methods=["POST"])
def log_discovery_rerank():
    """L9 — refit the active-learning ranker on the current set of
    APPROVED/REJECTED proposals and persist it to disk. The next
    ``/candidates`` call automatically picks the new model up via
    ``_load_review_ranker``."""
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"error": "no enterprise.db — run --phase mine first"}), 400
    try:
        from wizard.review_ranker import fit_from_conn
    except Exception as exc:                               # noqa: BLE001
        return jsonify({"error": f"ranker module unavailable: {exc}"}), 500
    conn = _log_review_conn()
    try:
        summary = fit_from_conn(conn, _REVIEW_RANKER_PATH)
    finally:
        conn.close()
    return jsonify({"ok": True, **summary})


@app.route("/api/log-discovery/ranker-status", methods=["GET"])
def log_discovery_ranker_status():
    """Tiny GET for the UI badge. Returns the most recent fit metadata
    if a model exists; otherwise ``{'fitted': false}``."""
    if not os.path.isfile(_ENTERPRISE_DB):
        return jsonify({"fitted": False, "reason": "no enterprise.db"})
    try:
        from wizard.review_ranker import latest_meta
    except Exception:                                      # noqa: BLE001
        return jsonify({"fitted": False, "reason": "ranker module unavailable"})
    conn = _log_review_conn()
    try:
        meta = latest_meta(conn)
    finally:
        conn.close()
    ranker = _load_review_ranker()
    fitted = bool(ranker and ranker.is_fitted())
    return jsonify({"fitted": fitted, "latest_meta": meta})


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
    # Read version + branding from the canonical source (ontomesh
    # package) so the boot banner can't drift from pyproject.toml again.
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from ontomesh import __version__ as _version
    except Exception:                                                 # noqa: BLE001
        _version = "unknown"

    parser = argparse.ArgumentParser(
        description=f"Ontomesh — the ontology mesh for GraphRAG (v{_version})",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print()
    print(f"  Ontomesh — the ontology mesh for GraphRAG  ·  v{_version}")
    print(f"  ──────────────────────────────────────────────────────────────")
    print(f"  Landing:     http://{args.host}:{args.port}/")
    print(f"  Wizard:      http://{args.host}:{args.port}/wizard")
    print(f"  Projects:    http://{args.host}:{args.port}/projects")
    print(f"  Docs:        http://{args.host}:{args.port}/help")
    print(f"  Health:      http://{args.host}:{args.port}/health")
    print(f"  Session DB:  {ONTOLOGIES_DB}")
    print(f"  Session JSON:{SESSION_FILE}")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
