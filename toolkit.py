#!/usr/bin/env python3
"""
toolkit.py — Ontology Toolkit CLI
────────────────────────────────────
End-to-end pipeline: DB introspection → OWL generation → SHACL →
mapping + semantic loss → JSON-LD + SKOS → CQ tests → HTML report.

Usage:
  python toolkit.py                   # full pipeline
  python toolkit.py --phase 1         # setup DB only
  python toolkit.py --phase 2         # ontology generation
  python toolkit.py --phase 3         # SHACL generation
  python toolkit.py --phase 4         # mapping + semantic loss
  python toolkit.py --phase 5         # JSON-LD + SKOS
  python toolkit.py --phase reason    # materialisation (OWL-RL + SHACL + SPARQL)
  python toolkit.py --phase test      # CQ tests + governance score
  python toolkit.py --phase report    # HTML report only

Options:
  --db PATH       SQLite database path (default: db/enterprise.db)
  --out PATH      Output directory (default: output)
  --industry STR  Label for the industry context (default: Enterprise)
"""

import sys
import os
import json
import argparse
import sqlite3
from datetime import datetime, timezone

# ── Path setup ───────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, "src")
sys.path.insert(0, SRC)

DB_PATH  = os.path.join(HERE, "db", "enterprise.db")
OUT_PATH = os.path.join(HERE, "output")


# ── Helpers ──────────────────────────────────────────────────────────────

def banner(title: str):
    width = 62
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def step(n: int, title: str):
    print(f"\n{'─'*62}")
    print(f"  Phase {n}: {title}")
    print(f"{'─'*62}")


def setup_db(db_path: str, mode: str = "both"):
    """Create and seed the database.
    mode='generic' uses schema.sql + seed.sql
    mode='tmf'     uses tmf_schema.sql + tmf_seed.sql
    mode='both'    loads both (default)
    """
    schema_sql = os.path.join(HERE, "db", "schema.sql")
    seed_sql   = os.path.join(HERE, "db", "seed.sql")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    if mode in ("generic", "both"):
        schema_sql = os.path.join(HERE, "db", "schema.sql")
        seed_sql   = os.path.join(HERE, "db", "seed.sql")
        with open(schema_sql) as f:
            conn.executescript(f.read())
        try:
            count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            if count == 0:
                with open(seed_sql) as f:
                    conn.executescript(f.read())
                print(f"  ✓ Generic schema seeded → {db_path}")
            else:
                print(f"  ✓ Generic schema exists → {db_path} ({count} assets)")
        except Exception:
            with open(seed_sql) as f:
                conn.executescript(f.read())
            print(f"  ✓ Generic schema seeded → {db_path}")

    if mode in ("tmf", "both"):
        tmf_schema = os.path.join(HERE, "db", "tmf_schema.sql")
        tmf_seed   = os.path.join(HERE, "db", "tmf_seed.sql")
        # Migrate ontology_metadata if TMF columns missing
        # Add TMF columns if not present (SQLite only — other DBs managed by migration tools)
        try:
            existing = [r["name"] for r in conn.execute("SELECT * FROM ontology_metadata LIMIT 0")]
        except Exception:
            existing = []
        # Fallback: use PRAGMA for SQLite
        if not existing:
            try:
                existing = [r[1] for r in conn.execute("PRAGMA table_info(ontology_metadata)").fetchall()]
            except Exception:
                existing = []
        for col, defn in [("sid_domain","TEXT"),("sid_abe","TEXT"),("tmf_api_id","TEXT"),
                          ("tmf_api_version","TEXT"),("tmf_entity_name","TEXT"),("etom_process","TEXT")]:
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE ontology_metadata ADD COLUMN {col} {defn}")
                except Exception:
                    pass
        try:
            conn.commit()
        except Exception:
            pass
        with open(tmf_schema) as f:
            conn.executescript(f.read())
        try:
            count = conn.execute("SELECT COUNT(*) FROM tmf_resource").fetchone()[0]
            if count == 0:
                with open(tmf_seed) as f:
                    conn.executescript(f.read())
                print(f"  ✓ TMF schema seeded     → {db_path}")
            else:
                print(f"  ✓ TMF schema exists     → {db_path} ({count} resources)")
        except Exception:
            with open(tmf_seed) as f:
                conn.executescript(f.read())
            print(f"  ✓ TMF schema seeded     → {db_path}")

    conn.close()


# ── Pipeline phases ──────────────────────────────────────────────────────

def phase1_foundation(db_path: str, out_path: str):
    step(1, "Foundation — DB Setup & Introspection")
    os.makedirs(os.path.join(out_path, "reports"), exist_ok=True)

    setup_db(db_path)

    from db_introspector import DBIntrospector
    intro = DBIntrospector(db_path)
    tables = intro.introspect_all()

    print(f"\n  Introspection summary:")
    print(f"  {'Table':<30} {'OWL Class':<25} {'Sensitivity':<15} {'Event?'}")
    print(f"  {'─'*30} {'─'*25} {'─'*15} {'─'*6}")
    for t in tables:
        print(f"  {t.name:<30} {t.class_name:<25} {t.sensitivity_tier:<15} {'✓' if t.is_event_class else ''}")

    total_cols = sum(len(t.columns) for t in tables)
    obj_props  = sum(len(t.object_properties) for t in tables)
    data_props = sum(len(t.data_properties) for t in tables)
    print(f"\n  Tables: {len(tables)}  |  Columns: {total_cols}  "
          f"|  Data props: {data_props}  |  Object props: {obj_props}")
    intro.close()


def phase2_ontology(db_path: str, out_path: str):
    step(2, "Canonical Modeling — OWL 2 Ontology Generation")
    from db_introspector import DBIntrospector
    from ontology_generator import generate_ontology

    # Load the wizard session if present so log-discovery (Phase L5)
    # classes + RCA taxonomy land in enterprise.ttl automatically.
    session = None
    session_path = os.path.join(HERE, ".wizard_session.json")
    if os.path.isfile(session_path):
        try:
            with open(session_path) as f:
                session = json.load(f)
        except Exception:
            session = None

    intro = DBIntrospector(db_path)
    generate_ontology(intro, os.path.join(out_path, "ontology"),
                      session=session)
    intro.close()

    # Reasoner integration — classify and snapshot (graceful if ROBOT absent)
    from reasoner import run_and_report
    ontology_path = os.path.join(out_path, "ontology", "enterprise.ttl")
    profile_path  = os.path.join(out_path, "ontology", "profile_recommendation.md")
    profile = "OWL 2 EL"
    try:
        if os.path.isfile(profile_path):
            with open(profile_path) as f:
                for line in f:
                    if "**Recommended profile:**" in line:
                        profile = line.split("**Recommended profile:**")[1].strip().rstrip("  ").rstrip()
                        break
    except Exception:
        pass
    run_and_report(ontology_path, os.path.join(out_path, "ontology"), profile)


def phase_targets(db_path: str, out_path: str, targets_arg: str):
    """T1.5 — multi-target generation. Builds a GenerationContext from
    the introspected schema + the wizard session + the APPROVED log-
    discovery proposals, then renders every requested target under
    ``out_path``.

    ``targets_arg`` is the raw ``--targets`` string from argparse —
    comma-separated names. Unknown names produce warnings, not errors.
    """
    step("T1.5", "Multi-target generation")
    from db_introspector import DBIntrospector
    from targets import (
        AVAILABLE_TARGETS, GenerationContext, render_targets,
    )
    from targets.registry import write_target_outputs

    if not targets_arg:
        print(f"  no --targets specified; available: "
              f"{', '.join(AVAILABLE_TARGETS)}")
        return

    names = [n.strip() for n in (targets_arg or "").split(",") if n.strip()]

    # Wizard session
    session = None
    session_path = os.path.join(HERE, ".wizard_session.json")
    if os.path.isfile(session_path):
        try:
            with open(session_path) as f:
                session = json.load(f)
        except Exception:
            session = None

    # APPROVED proposals — the rule of thumb: generate from approved
    # truth, not pending guesses. Targets see only what reviewers
    # have endorsed.
    proposals: list = []
    enterprise_db = os.path.join(HERE, "db", "enterprise.db")
    if os.path.isfile(enterprise_db):
        try:
            import sqlite3
            conn = sqlite3.connect(enterprise_db)
            cur = conn.execute(
                "SELECT proposal_id, proposal_type, title, "
                "       evidence_sample, confidence_score "
                "FROM ontology_evolution_proposals "
                "WHERE status = 'APPROVED'"
            )
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                rd = dict(zip(cols, row))
                rd["kind"] = rd.get("proposal_type")
                proposals.append(rd)
            conn.close()
        except Exception:
            proposals = []

    try:
        intro = DBIntrospector(db_path) if os.path.isfile(db_path) else None
    except Exception:
        intro = None
    ctx = GenerationContext.from_introspector(
        intro, session=session, proposals=proposals,
    )
    if intro is not None:
        intro.close()

    results = render_targets(ctx, names=names)
    written = write_target_outputs(results, out_path)

    for name, res in results.items():
        if res.warnings:
            for w in res.warnings:
                print(f"  ⚠  {name}: {w}")
        if res.stats:
            stats_str = ", ".join(f"{k}={v}" for k, v in res.stats.items())
            print(f"  • {name}: {len(res.files)} file(s) — {stats_str}")
    if written:
        print(f"  ✓ {len(written)} target files written under {out_path}")


def phase_reason(db_path: str, out_path: str):
    """Phase B — materialisation. Runs OWL-RL, SHACL sh:rule, and SPARQL
    CONSTRUCT engines over `enterprise.ttl` and writes the four derived
    artefacts (`enterprise-inferred.ttl`, `inferred-shacl.ttl`,
    `inferred-sparql.ttl`, `materialised.ttl`) plus a report.

    Inputs are auto-discovered from the standard pipeline output layout:
        ontology/      enterprise.ttl, events.ttl, provenance.ttl
        shapes/        enterprise.ttl  (SHACL — optional)
        sparql_rules/  *.rq             (SPARQL CONSTRUCTs — optional)
    """
    step("B", "Reasoning — Materialisation (OWL-RL + SHACL + SPARQL)")
    from materializer import materialize

    ont_dir = os.path.join(out_path, "ontology")
    ontology = os.path.join(ont_dir, "enterprise.ttl")
    if not os.path.isfile(ontology):
        print(f"  ✗ {ontology} not found — run phase 2 first.")
        return

    # Phase C — export session.rules to disk before materialisation.
    # The wizard persists rules at <repo>/.wizard_session.json; we look
    # for them silently and skip if absent.
    session_path = os.path.join(HERE, ".wizard_session.json")
    if os.path.isfile(session_path):
        try:
            with open(session_path) as f:
                session = json.load(f)
            session_rules = session.get("rules") or []
            causal_rules = session.get("causal_rules") or []
            if session_rules:
                sys.path.insert(0, HERE)
                from wizard.rules import export_rules
                export = export_rules(session_rules, out_path)
                counts = export["counts"]
                print(f"  ↪ Rules exported: {counts['shacl']} SHACL, "
                      f"{counts['sparql']} SPARQL, {counts['owl']} OWL "
                      f"({counts['skipped']} skipped)")
                for rid, msg in export["skipped"]:
                    print(f"    ✗ {rid}: {msg}")
            # L5.3 — approved LOG_CAUSAL_EDGE entries compile to SPARQL
            # CONSTRUCTs that Phase B materialisation picks up.
            if causal_rules:
                sys.path.insert(0, HERE)
                from wizard.rules import export_causal_rules
                cexp = export_causal_rules(causal_rules, out_path)
                if cexp["written"]:
                    print(f"  ↪ Causal rules exported: {len(cexp['written'])}")
                for rid, msg in cexp.get("skipped", []):
                    print(f"    ✗ causal {rid}: {msg}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ Rule export failed: {exc}")

    extras = [
        os.path.join(ont_dir, "events.ttl"),
        os.path.join(ont_dir, "provenance.ttl"),
    ]
    extras = [p for p in extras if os.path.isfile(p)]

    # Collect every .ttl under output/shapes/ — phase 3 emits
    # `enterprise-shapes.ttl` / `agent-gate.ttl`; phase C exports
    # session-authored sh:rule constructs to `rules.ttl`. Merge them
    # into a single union shapes graph for the materializer.
    shapes = None
    shapes_dir = os.path.join(out_path, "shapes")
    if os.path.isdir(shapes_dir):
        ttl_files = sorted(p for p in os.listdir(shapes_dir) if p.endswith(".ttl"))
        if ttl_files:
            from rdflib import Graph as _G
            union = _G()
            for fname in ttl_files:
                if fname == "_combined.ttl":
                    continue
                try:
                    union.parse(os.path.join(shapes_dir, fname), format="turtle")
                except Exception:
                    pass
            combined = os.path.join(shapes_dir, "_combined.ttl")
            union.serialize(destination=combined, format="turtle")
            shapes = combined

    rules_dir = os.path.join(out_path, "sparql_rules")
    if not os.path.isdir(rules_dir):
        rules_dir = None

    result = materialize(
        ontology, ont_dir,
        shapes_path=shapes,
        extra_ontology_paths=extras,
        sparql_rules_dir=rules_dir,
    )

    print(f"  Asserted:        {result.asserted_count:,} triples")
    print(f"  Derived (total): {result.total_derived:,} triples")
    print(f"  Materialised:    {result.materialised_count:,} triples")
    for e in result.engines:
        marker = "✓" if e.status == "PASS" else ("~" if e.status == "SKIPPED" else "✗")
        print(f"  {marker} {e.name:<8} [{e.status}]: {e.message}")
    if result.sensitivity_warnings:
        print(f"  ⚠ {len(result.sensitivity_warnings)} sensitivity warning(s) — see report")
    print(f"  ✓ Materialised graph    → {result.materialised_path}")
    print(f"  ✓ Materialisation report → {result.report_path}")


def phase3_shacl(db_path: str, out_path: str):
    step(3, "Validation — SHACL Shape Generation")
    from db_introspector import DBIntrospector
    from shacl_generator import generate_shacl

    intro = DBIntrospector(db_path)
    generate_shacl(intro, os.path.join(out_path, "shapes"))
    intro.close()


def phase4_mapping(db_path: str, out_path: str):
    step(4, "Mapping & Critique — Logical/Physical Map + Semantic Loss")
    from db_introspector import DBIntrospector
    from mapping_generator import generate_mapping

    intro = DBIntrospector(db_path)
    generate_mapping(intro, os.path.join(out_path, "mapping"))
    intro.close()


def phase5_exchange(db_path: str, out_path: str):
    step(5, "Agent Enablement — JSON-LD, SKOS, MCP Tools")
    from db_introspector import DBIntrospector
    from jsonld_generator import generate_jsonld

    intro = DBIntrospector(db_path)
    generate_jsonld(
        intro,
        os.path.join(out_path, "jsonld"),
        os.path.join(out_path, "vocab")
    )
    intro.close()



def phase_tmf(db_path: str, out_path: str):
    """Phase TMF — TM Forum SID alignment, Open API coverage, TMF CQ tests."""
    step(0, "TMF Alignment — SID Hierarchy, Open API Coverage, TMF CQ Tests")
    from db_introspector import DBIntrospector
    from tmf_mapper import (generate_sid_hierarchy, generate_tmf_jsonld,
                             generate_tmf_api_coverage, TMF_COMPETENCY_QUESTIONS)
    import csv as _csv

    intro = DBIntrospector(db_path)
    generate_sid_hierarchy(os.path.join(out_path, "ontology"))
    generate_tmf_jsonld(os.path.join(out_path, "jsonld"))
    generate_tmf_api_coverage(intro, os.path.join(out_path, "mapping"))

    print(f"\n  Running {len(TMF_COMPETENCY_QUESTIONS)} TMF competency question tests...")
    results = []
    passed = failed = 0
    for cq in TMF_COMPETENCY_QUESTIONS:
        try:
            rows = intro._connector.execute(cq["sql"].strip())
            row_count = len(rows)
            ok = (row_count > 0) == cq["expected_non_empty"]
            if ok: passed += 1
            else:  failed += 1
            status = "PASS" if ok else "FAIL"
            sample = str(rows[0]) if rows else "(empty)"
        except Exception as e:
            status = "ERROR"; row_count = 0; sample = str(e); failed += 1
        results.append({
            "cq_id": cq["id"], "priority": cq["priority"], "status": status,
            "question": cq["question"], "row_count": row_count,
            "sample": sample[:100], "validates": cq["validates"],
        })
        icon = "✓" if status == "PASS" else "✗"
        print(f"    {icon} {cq['id']} [{cq['priority']:8s}] {status:5s}  "
              f"rows={row_count}  — {cq['question'][:58]}")
    print(f"  TMF CQ Tests: {passed} passed, {failed} failed of {len(TMF_COMPETENCY_QUESTIONS)}")

    rpt_dir = os.path.join(out_path, "reports")
    os.makedirs(rpt_dir, exist_ok=True)
    path = os.path.join(rpt_dir, "tmf_cq_test_results.csv")
    with open(path, "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader(); w.writerows(results)
    print(f"  ✓ TMF CQ test results   → {path}")
    intro.close()


def _generate_runtime_mcp_tools(out_path: str):
    """Write the runtime MCP tool definitions JSON to output/jsonld/."""
    import json as _json
    tools = [
        {
            "name": "ground_data",
            "description": (
                "Ground a natural-language question against the enterprise database "
                "using the specified ontology flavor. Retrieves relevant records from "
                "the flavor's DB tables via keyword matching and serialises them as "
                "JSON-LD nodes using the flavor's scoped context. Returns a grounded "
                "data payload ready for LLM consumption."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural-language question driving data retrieval."
                    },
                    "flavor": {
                        "type": "string",
                        "description": "Ontology flavor name (e.g. 'network-ops', 'billing', 'fault-management').",
                        "enum": ["network-ops", "billing", "compliance", "customer", "fault-management"]
                    },
                    "max_records": {
                        "type": "integer",
                        "description": "Maximum number of records to retrieve across all tables.",
                        "default": 50
                    },
                    "db_path": {
                        "type": "string",
                        "description": "Path to the SQLite enterprise database. Defaults to db/enterprise.db."
                    }
                },
                "required": ["question", "flavor"]
            }
        },
        {
            "name": "assemble_payload",
            "description": (
                "Assemble a complete LLM input payload from a grounded data set, "
                "system prompt, ontology flavor section, PROV-O context, and output "
                "format instructions. The returned payload dict is LLM-agnostic and "
                "can be consumed by any registered adapter (Anthropic, OpenAI, Vertex, Ollama)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural-language question to answer."
                    },
                    "flavor": {
                        "type": "string",
                        "description": "Ontology flavor name.",
                        "enum": ["network-ops", "billing", "compliance", "customer", "fault-management"]
                    },
                    "grounded_data": {
                        "type": "object",
                        "description": "Pre-grounded JSON-LD data dict (output of ground_data). If omitted, auto-grounds."
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Desired response format from the LLM.",
                        "enum": ["json", "jsonld", "text", "table"],
                        "default": "json"
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Token budget for the assembled payload.",
                        "default": 4000
                    }
                },
                "required": ["question", "flavor"]
            }
        },
        {
            "name": "validate_response",
            "description": (
                "Validate an LLM response against SHACL shapes for the active flavor "
                "and stamp it with PROV-O provenance. Stores an ObservationRecord in "
                "the database capturing the model, payload ID, and confidence score. "
                "Returns validation status, violation messages, and the observation IRI."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "description": "The raw LLM response string (JSON or plain text)."
                    },
                    "payload_id": {
                        "type": "string",
                        "description": "The UUID payload_id from the assembled payload."
                    },
                    "model_id": {
                        "type": "string",
                        "description": "The LLM model identifier (e.g. 'claude-sonnet-4-5')."
                    },
                    "flavor": {
                        "type": "string",
                        "description": "Ontology flavor name used for SHACL shape selection.",
                        "enum": ["network-ops", "billing", "compliance", "customer", "fault-management"]
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Optional confidence score override (0.0–1.0).",
                        "minimum": 0.0,
                        "maximum": 1.0
                    }
                },
                "required": ["response", "payload_id", "model_id", "flavor"]
            }
        },
        {
            "name": "ask_ontology",
            "description": (
                "Run the full ontology-augmented AI pipeline in a single call: "
                "ground → screen → assemble → LLM call → validate+stamp. "
                "Equivalent to RuntimeClient.ask(). Returns the answer, PROV-O "
                "provenance, validation status, and observation IRI."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural-language question to answer."
                    },
                    "flavor": {
                        "type": "string",
                        "description": "Ontology flavor name.",
                        "enum": ["network-ops", "billing", "compliance", "customer", "fault-management"]
                    },
                    "adapter": {
                        "type": "string",
                        "description": "LLM adapter to use.",
                        "enum": ["anthropic", "openai", "vertex", "ollama"],
                        "default": "anthropic"
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional model override (e.g. 'claude-sonnet-4-5', 'gpt-4o')."
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Desired response format.",
                        "enum": ["json", "jsonld", "text", "table"],
                        "default": "json"
                    },
                    "max_records": {
                        "type": "integer",
                        "description": "Maximum DB records to include in context.",
                        "default": 50
                    },
                    "min_confidence": {
                        "type": "number",
                        "description": "Minimum confidence score for InputGate screening.",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.0
                    }
                },
                "required": ["question", "flavor"]
            }
        }
    ]

    jsonld_dir = os.path.join(out_path, "jsonld")
    os.makedirs(jsonld_dir, exist_ok=True)
    out_file = os.path.join(jsonld_dir, "runtime-mcp-tools.json")
    with open(out_file, "w") as f:
        _json.dump({"tools": tools}, f, indent=2)
    print(f"  ✓ Runtime MCP tools       → {out_file}")


def phase_runtime(db_path: str, out_path: str):
    """Phase RT — Runtime Layer: Flavor Registry, Grounder, Assembler, Gates, SDK."""
    step(0, "Runtime Layer — Flavor Registry · Grounder · Assembler · Gates · SDK")
    sys.path.insert(0, os.path.join(HERE, "runtime"))
    from flavor_registry import FlavorRegistry
    from grounder import Grounder
    from assembler import PayloadAssembler
    from output_gate import OutputGate
    from input_gate import InputGate

    # Generate runtime MCP tools JSON
    _generate_runtime_mcp_tools(out_path)

    # Validate all 5 flavor files load correctly
    reg = FlavorRegistry()
    for fname in reg.list_flavors():
        f = reg.load(fname)
        errs = reg.validate(f)
        if errs:
            print(f"  WARN flavor {fname}: {errs}")
        else:
            print(f"  ✓  flavor '{fname}' valid ({len(f['owl_classes'])} classes, tier={f['sensitivity_tier']})")
    print(f"  ✓  {len(reg.list_flavors())} flavors registered")


def phase_test(db_path: str, out_path: str):
    step(0, "CQ Tests + Governance Scorecard")
    from db_introspector import DBIntrospector
    from cq_tester import run_cq_tests

    intro = DBIntrospector(db_path)
    run_cq_tests(intro, os.path.join(out_path, "reports"))
    intro.close()

    # SPARQL CQ test suite
    from sparql_tester import run_sparql_cq_tests
    run_sparql_cq_tests(
        os.path.join(out_path, "ontology"),
        os.path.join(out_path, "reports"),
    )


def phase_report(out_path: str):
    step(0, "HTML Report Generation")
    from reporter import generate_report
    generate_report(out_path)
    # Generate compliance summary report alongside the toolkit report
    try:
        sys.path.insert(0, HERE)
        from compliance import dashboard as _dash
        _dash.write_summary(out_path=out_path,
                            db_path=os.path.join(HERE, "db", "enterprise.db"))
        print(f"  ✓ Compliance summary    → {out_path}/reports/compliance_summary.html")
    except Exception as exc:
        print(f"  ⚠  Compliance summary skipped: {exc}")
    # Workstream 5 — retrieval summary
    try:
        sys.path.insert(0, HERE)
        sys.path.insert(0, os.path.join(HERE, "runtime"))
        from runtime.embeddings import dashboard as _vec_dash
        _vec_dash.write_summary(out_path=out_path,
                                db_path=os.path.join(HERE, "db", "enterprise.db"))
        print(f"  ✓ Retrieval summary     → {out_path}/reports/retrieval_summary.html")
    except Exception as exc:
        print(f"  ⚠  Retrieval summary skipped: {exc}")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ontology Engineering Toolkit — full 5-phase pipeline"
    )
    parser.add_argument("--db",       default=DB_PATH,  help="SQLite database path")
    parser.add_argument("--out",      default=OUT_PATH, help="Output directory")
    parser.add_argument("--phase",    default="all",
                        choices=["all","1","2","3","4","5","reason","tmf","test","report","reasoner","sparql","log","mine","sequence","drift-templates","security","conflict","alignment","runtime",
                                 "publish","drift","templates","modular","discover","tmf630","wizard","evolve","federate","comply",
                                 "embed","retrieve","targets","abox"],
                        help="Run a specific phase only")
    # ── T1.5 — Multi-target generation ─────────────────────────────────
    parser.add_argument("--targets", default=None,
                        help=("Comma-separated list of additional generation "
                              "targets to emit alongside OWL/SHACL — e.g. "
                              "'cypher,graphql,detection_rules'. Use --phase "
                              "targets to run targets without re-generating "
                              "the OWL/SHACL artefacts."))
    # ── Workstream 2 (evolve) flags ────────────────────────────────────
    parser.add_argument("--review", action="store_true",
                        help="Enter interactive review mode for pending evolution proposals (--phase evolve)")
    parser.add_argument("--apply", default=None,
                        help="Apply an APPROVED proposal (proposal-id) through the CI/CD auto-versioner")
    parser.add_argument("--action", default=None, choices=["APPROVE", "REJECT", "DEFER"],
                        help="Decision to record against a proposal (--phase evolve --proposal-id ...)")
    parser.add_argument("--proposal-id", default=None,
                        help="Proposal UUID for --action / --apply")
    parser.add_argument("--reviewer-id", default="cli:reviewer",
                        help="Reviewer identifier persisted on the proposal")
    parser.add_argument("--note", default="",
                        help="Reviewer note (APPROVE/REJECT/DEFER)")
    parser.add_argument("--version-target", default=None,
                        help="Explicit semver target on APPROVE (e.g. 1.2.0). Omit for MINOR auto-bump.")
    parser.add_argument("--min-evidence", type=int, default=3,
                        help="Minimum co-occurrence count required to promote a candidate (--phase evolve)")
    parser.add_argument("--strategy", default=None,
                        choices=["SHACL_VIOLATION_ACCUMULATION", "CARDINALITY_BREACH",
                                 "CLASS_COOCCURRENCE", "NLP_CANDIDATE_PROMOTION"],
                        help="Restrict --phase evolve to a single detection strategy")
    parser.add_argument("--open-pr", action="store_true",
                        help="On --apply, open a draft GitHub PR with the diff (requires gh CLI)")
    # ── Workstream 3 (federate) flags ──────────────────────────────────
    parser.add_argument("--generate-keys", action="store_true",
                        help="Generate a local Ed25519 signing keypair (--phase federate)")
    parser.add_argument("--key-name", default="enterprise",
                        help="Keypair name for --phase federate --generate-keys")
    parser.add_argument("--register-partner", default=None, metavar="URL",
                        help="Register a partner by capability-manifest URL (--phase federate)")
    parser.add_argument("--partner-iri", default=None,
                        help="Partner IRI for --phase federate operations")
    parser.add_argument("--partner-endpoint", default=None,
                        help="Partner SPARQL endpoint (for --register-partner)")
    parser.add_argument("--partner-display-name", default=None,
                        help="Human-readable partner name (for --register-partner)")
    parser.add_argument("--partner-public-key", default=None,
                        help="Partner Ed25519 public key b64 (for --register-partner)")
    parser.add_argument("--exposed-classes", default=None,
                        help="Comma-separated OWL class IRIs exposed by the partner")
    parser.add_argument("--max-tier", default="Internal",
                        choices=["Public", "Internal", "Confidential"],
                        help="Maximum sensitivity tier shareable with the partner")
    parser.add_argument("--handshake", default=None, metavar="URL",
                        help="Start the trust-bootstrap handshake with a partner (--phase federate)")
    parser.add_argument("--list-partners", action="store_true",
                        help="List every registered federation partner")
    parser.add_argument("--build-manifest", action="store_true",
                        help="Build + sign the local capability manifest (--phase federate)")
    parser.add_argument("--enterprise-iri",
                        default="https://enterprise.example.com/ontology#self",
                        help="Enterprise IRI used when building a capability manifest")
    # ── Workstream 4 (comply) flags ────────────────────────────────────
    parser.add_argument("--regulation", default=None,
                        help="Regulation ID for --phase comply (e.g. eu-ai-act)")
    parser.add_argument("--decision", default=None, metavar="IRI",
                        help="Decision/ObservationRecord IRI for --phase comply")
    parser.add_argument("--time-range", default=None, metavar="FROM,TO",
                        help="Time range ISO8601 pair for --phase comply evidence assembly")
    parser.add_argument("--verify", default=None, metavar="BUNDLE",
                        help="Verify a compliance bundle zip (--phase comply)")
    parser.add_argument("--list-regulations", action="store_true",
                        help="List every loaded regulation (--phase comply)")
    parser.add_argument("--gap-analysis", action="store_true",
                        help="Run gap analysis across the registry (--phase comply)")
    parser.add_argument("--bundle-signer", default="https://enterprise.example.com/compliance#signer",
                        help="Signer IRI embedded in compliance bundles")
    # ── Workstream 5 (embed / retrieve) flags ──────────────────────────
    parser.add_argument("--flavor", default=None,
                        help="Flavor name for --phase embed / retrieve")
    parser.add_argument("--vector-store", default=None, metavar="CONN",
                        help="Vector store connection string "
                             "(e.g. memory://net, qdrant://localhost:6333/net)")
    parser.add_argument("--embed-model", default=None,
                        help="Embedding model ID (default: flavor's declared model "
                             "or hash-local-384)")
    parser.add_argument("--force-reindex", action="store_true",
                        help="Re-embed every record regardless of content hash")
    parser.add_argument("--question", default=None,
                        help="Natural-language question for --phase retrieve")
    parser.add_argument("--class-expression", default=None,
                        help="OWL class expression filter for --phase retrieve "
                             "(e.g. tmf:NetworkFunction | tmf:Alarm)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Top-k hybrid-retrieval results to return")
    parser.add_argument("--benchmark", action="store_true",
                        help="Run the retrieval benchmark suite (--phase retrieve)")
    parser.add_argument("--list-indexes", action="store_true",
                        help="List every registered embedding index (--phase embed)")
    parser.add_argument("--strategy-compare", action="store_true",
                        help="Run all three strategies for the given question")
    parser.add_argument("--log-path",  default=None, help="Log file path or glob (for --phase log)")
    parser.add_argument("--log-format", default="auto",
                        choices=["auto","jsonl","syslog","cef","otlp","regex"],
                        help="Log format for --phase log (default: auto-detect)")
    parser.add_argument("--log-regex",  default=None, help="Named-group regex for --log-format regex")
    parser.add_argument("--dry-run",    action="store_true", help="Log ingest dry-run (no DB writes)")
    parser.add_argument("--store",      default="all",
                        choices=["all","stardog","fuseki","neptune","oxigraph","graphdb"],
                        help="Graph store target for --phase security or --phase publish")
    parser.add_argument("--endpoint",   default="", help="Graph store endpoint URL for --phase publish")
    parser.add_argument("--gstore-user",     default="", help="Graph store username (Fuseki/Stardog/GraphDB)")
    parser.add_argument("--gstore-password", default="", help="Graph store password")
    parser.add_argument("--aws-region",      default="us-east-1", help="AWS region for Neptune")
    parser.add_argument("--template",   default="all", help="Industry template name for --phase templates")
    parser.add_argument("--min-freq",   type=int, default=3, help="Min co-occurrence frequency for --phase discover")
    parser.add_argument("--industry", default="Enterprise", help="Industry label for output")
    args = parser.parse_args()

    start = datetime.now(timezone.utc)
    banner(f"Ontology Engineering Toolkit  |  {args.industry}  |  {start.strftime('%Y-%m-%d %H:%M UTC')}")

    os.makedirs(args.out, exist_ok=True)

    def phase_reasoner(db_path: str, out_path: str):
        step(0, "Reasoner — OWL 2 Consistency Check + Hierarchy Snapshot")
        from reasoner import run_and_report
        ontology_path = os.path.join(out_path, "ontology", "enterprise.ttl")
        run_and_report(ontology_path, os.path.join(out_path, "ontology"))

    def phase_sparql(db_path: str, out_path: str):
        step(0, "SPARQL CQ Tests")
        from sparql_tester import run_sparql_cq_tests
        run_sparql_cq_tests(
            os.path.join(out_path, "ontology"),
            os.path.join(out_path, "reports"),
        )

    def phase_log(db_path: str, out_path: str):
        step(0, "Structured Log Ingestion")
        from log_connector import run_log_ingest
        log_path = args.log_path
        if not log_path:
            print("  ⚠ --log-path is required for --phase log")
            print("    Example: python3 toolkit.py --phase log --log-path /var/log/app.log")
            return
        run_log_ingest(
            db_path=db_path,
            out_path=out_path,
            log_path=log_path,
            fmt=args.log_format,
            custom_regex=args.log_regex,
            dry_run=args.dry_run,
        )

    def phase_mine(db_path: str, out_path: str):
        """Phase L1 — Log mining for RCA bootstrap.

        Reads logs from a folder (or glob, or single file), clusters
        them into templates via Drain, classifies the variable slots,
        builds a PMI-weighted entity graph with temporal direction,
        and persists every layer to SQLite for the engineer-review step.

        See docs/log-rca-roadmap.md and docs/log-rca-dev-plan.md.

        Inputs are gathered from existing CLI flags:
          --log-path <folder|glob|file>   (required)
          --log-format auto|jsonl|syslog|cef|otlp|regex
          --log-regex <pattern>           (regex format only)
          --db                            (output SQLite path)
        """
        step("L1", "Log Mining — Templates · Slot Typing · PMI Graph")
        log_path = args.log_path
        if not log_path:
            print("  ⚠ --log-path is required for --phase mine")
            print("    Example: python3 toolkit.py --phase mine "
                  "--log-path examples/log-rca/sample/")
            return
        try:
            from log_corpus import LogCorpus
            from log_miner import mine_corpus
            from db.migrations.log_rca_proposals import migrate as _migrate_proposals
        except ImportError as exc:
            print(f"  ✗ {exc}")
            print("    Install the mining extras: pip install -e .[mining]")
            return

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path)
        # Make sure the proposal store can receive log-mined candidates
        # if/when L4 review pushes them. Idempotent.
        _migrate_proposals(conn)

        corpus = LogCorpus(log_path, fmt=args.log_format,
                           custom_regex=args.log_regex)
        files = corpus.resolve_files()
        print(f"  ↪ corpus: {len(files)} file(s) under {log_path}")
        if not files:
            print("  ⚠ no log files matched — supported extensions: "
                  ".jsonl .json .log .syslog .cef .otlp .txt")
            return

        report = mine_corpus(corpus, conn)
        r = report.as_dict()

        # L3 — triangulation-gate the directed edges + seed proposals.
        try:
            from log_templates import LogTemplateMiner
            from wizard.log_review import seed_from_mining
            # Build a fresh extractions list for L3 — cheap compared to
            # re-running the whole pipeline. We seed proposals using
            # those extractions so the causality gate runs.
            seed_miner = LogTemplateMiner(conn)
            for rec in corpus.iter():
                seed_miner.consume(
                    rec.message, timestamp=rec.timestamp,
                    severity=rec.severity,
                    service=rec.fields.get("service") if rec.fields else None,
                    trace_id=rec.fields.get("trace_id") if rec.fields else None)
            seed_miner.flush()
            seed_counts = seed_from_mining(conn, extractions=seed_miner.extractions)
            r["proposals_seeded"] = sum(seed_counts.values())
            r["proposal_breakdown"] = seed_counts
        except Exception as exc:                # noqa: BLE001
            r["proposals_seeded_error"] = str(exc)[:120]

        print(f"  ✓ records ingested      {r['records_ingested']:>6,}")
        print(f"  ✓ templates             {r['templates']:>6,}"
              f"  (after EM merge: {r['templates_after_em']}, "
              f"merges: {r['em_merges']})")
        print(f"  ✓ slots profiled        {r['slots_profiled']:>6,}")
        print(f"  ✓ entity edges          {r['edges_persisted']:>6,}")
        if "proposal_breakdown" in r:
            pb = r["proposal_breakdown"]
            print(f"  ✓ proposals seeded      "
                  f"{r['proposals_seeded']:>6,}  "
                  f"(event={pb['log_event']} entity={pb['log_entity']} "
                  f"rel={pb['log_relationship']} causal={pb['log_causal_edge']})")
        print(f"  ✓ duration              {r['duration_s']:>6}s")
        # Write a small JSON summary alongside the standard reports dir
        # so the wizard's Log Discovery step (L4) can show the headline
        # numbers without re-running the pipeline.
        reports_dir = os.path.join(out_path, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        summary_path = os.path.join(reports_dir, "log_mining_summary.json")
        with open(summary_path, "w") as f:
            json.dump(r, f, indent=2)
        print(f"  ✓ summary               → {summary_path}")
        conn.close()

    def phase_sequence(db_path: str, out_path: str):
        """Phase L2 — Sequence + anomaly learning.

        Reads the L1 mining artefacts, builds per-service trajectories,
        fits a per-service Categorical HMM (BIC-selected state count),
        and flags anomalous trajectories into the proposal store.
        Re-runs --phase mine first so the sequence pass always sees a
        fresh template catalogue — cheap on small corpora, idempotent
        on larger ones.
        """
        step("L2", "Sequence Learning — Trajectories · HMM · Anomalies")
        log_path = args.log_path
        if not log_path:
            print("  ⚠ --log-path is required for --phase sequence")
            return
        try:
            from log_corpus import LogCorpus
            from log_miner import mine_corpus
            from log_templates import LogTemplateMiner
            from sequence_learner import mine_sequences
            from db.migrations.log_rca_proposals import migrate as _migrate
        except ImportError as exc:
            print(f"  ✗ {exc}")
            print("    Install the mining extras: pip install -e .[mining]")
            return

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path)
        _migrate(conn)

        corpus = LogCorpus(log_path, fmt=args.log_format,
                           custom_regex=args.log_regex)
        files = corpus.resolve_files()
        if not files:
            print(f"  ⚠ no log files matched: {log_path}")
            return
        print(f"  ↪ corpus: {len(files)} file(s)")

        # Re-mine so the HMM sees the latest cluster ids.
        miner = LogTemplateMiner(conn)
        for rec in corpus.iter():
            miner.consume(rec.message,
                          timestamp=rec.timestamp,
                          severity=rec.severity,
                          service=rec.fields.get("service") if rec.fields else None,
                          trace_id=rec.fields.get("trace_id") if rec.fields else None)
        miner.flush()
        miner.refine()

        seq_report = mine_sequences(miner.extractions, conn)
        r = seq_report.as_dict()
        print(f"  ✓ trajectories          {r['trajectories']}")
        print(f"  ✓ services fit          {r['services_fit']}")
        print(f"  ✓ anomalies             {r['anomalies']}")
        print(f"  ✓ proposals             {r['proposals_persisted']}")
        print(f"  ✓ duration              {r['duration_s']}s")
        conn.close()

    def phase_drift_templates(db_path: str, out_path: str):
        """Phase L7 — closed-loop drift on log templates.

        Re-runs Drain against ``--log-path``, comparing each line to the
        approved template catalogue. Lines that yield *new* clusters
        graduate into the proposal store as ``DRIFT_ON_NEW_TEMPLATE``
        once they clear the hit floor. Engineers see them in the same
        Step 2.5 review queue alongside bootstrap candidates.
        """
        step("L7", "Drift Detection — New Log Templates")
        log_path = args.log_path
        if not log_path:
            print("  ⚠ --log-path is required for --phase drift-templates")
            return
        try:
            from log_corpus import LogCorpus
            from runtime.drift.log_template_drift import detect_template_drift
            from db.migrations.log_rca_proposals import migrate as _migrate
        except ImportError as exc:
            print(f"  ✗ {exc}")
            print("    Install the mining extras: pip install -e .[mining]")
            return
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path)
        _migrate(conn)

        corpus = LogCorpus(log_path)
        files = corpus.resolve_files()
        if not files:
            print(f"  ⚠ no log files matched: {log_path}")
            conn.close()
            return
        print(f"  ↪ scanning {len(files)} file(s) against approved templates")
        rep = detect_template_drift(corpus, conn)
        r = rep.as_dict()
        print(f"  ✓ lines seen            {r['lines_seen']:>6,}")
        print(f"  ✓ new templates         {r['new_templates']:>6,}")
        print(f"  ✓ proposals queued      {r['new_proposals']:>6,}")
        print(f"  ✓ duration              {r['duration_s']:>6}s")
        conn.close()

    def phase_security(db_path: str, out_path: str):
        step(0, "Named-Graph RBAC Config Generation")
        from db_introspector import DBIntrospector
        from rbac_generator import generate_rbac
        intro = DBIntrospector(db_path)
        generate_rbac(intro, os.path.join(out_path, "security"), store=args.store)
        intro.close()

    def phase_conflict(db_path: str, out_path: str):
        step(0, "Multi-Agent Conflict Resolution — 3-Tier Chain")
        from conflict_resolver import (
            run_conflict_resolution,
            generate_conflict_shacl,
            generate_conflict_mcp_tools,
        )
        run_conflict_resolution(db_path, out_path)
        generate_conflict_shacl(os.path.join(out_path, "shapes"))
        generate_conflict_mcp_tools(os.path.join(out_path, "jsonld"))

    def phase_alignment(db_path: str, out_path: str):
        step(0, "Ontology Alignment & Federation — DOLCE/FOAF/Schema.org/SOSA")
        from alignment_generator import run_alignment
        run_alignment(out_path)

    # ── Phase 3 handlers ─────────────────────────────────────────────────

    def phase_publish(db_path: str, out_path: str):
        step(0, "Phase 3 — Graph Store Publishing")
        from graph_publisher import run_publish, generate_publish_summary
        if not args.endpoint:
            print("  ⚠  --endpoint is required for --phase publish")
            print("    Example: python3 toolkit.py --phase publish --store fuseki --endpoint http://localhost:3030/dataset")
            return
        store = args.store if args.store != "all" else "fuseki"
        results = run_publish(
            out_path,
            store=store,
            endpoint=args.endpoint,
            user=args.gstore_user,
            password=args.gstore_password,
            region=args.aws_region,
        )
        generate_publish_summary(results, out_path, store, args.endpoint)

    def phase_drift(db_path: str, out_path: str):
        step(0, "Phase 3 — Drift Detection Ontology Extension")
        from drift_detector import run_drift_detection
        run_drift_detection(out_path)

    def phase_templates(db_path: str, out_path: str):
        step(0, "Phase 3 — Industry Templates")
        from template_loader import run_templates
        run_templates(out_path, template_name=args.template)

    def phase_abox(db_path: str, out_path: str):
        step(0, "Phase 4 — ABox materialisation (instances from the source rows)")
        from abox_generator import run_abox
        run_abox(db_path, out_path, max_tier=args.max_tier)

    def phase_modular(db_path: str, out_path: str):
        step(0, "Phase 3 — Modular OWL (owl:imports + cycle + IRI conflict detection)")
        from modular_owl import run_modular_owl
        run_modular_owl(out_path)

    def phase_discover(db_path: str, out_path: str):
        step(0, "Phase 3 — Log Entity Discovery (NLP co-occurrence analysis)")
        from entity_discoverer import run_entity_discovery
        log_path = args.log_path
        if not log_path:
            print("  ⚠  --log-path is required for --phase discover")
            print("    Example: python3 toolkit.py --phase discover --log-path /var/log/app.log")
            return
        run_entity_discovery(
            log_path=log_path,
            db_path=db_path,
            out_path=out_path,
            min_freq=args.min_freq,
        )

    def phase_tmf630(db_path: str, out_path: str):
        step(0, "Phase 3 — TMF630 Task + Bulk Operations (Parts 4 & 7)")
        from tmf_mapper import run_tmf630_task_phase
        run_tmf630_task_phase(db_path, out_path)

    def phase_evolve(db_path: str, out_path: str):
        step(0, "Workstream 2 — Autonomous Ontology Evolution")

        from evolution_monitor import run_evolution_monitor
        from evolution_scorer  import score_pending
        from evolution_reviewer import (list_pending, get_proposal,
                                         record_decision, apply_approved)

        # Route 1 — record a decision on a specific proposal
        if args.action and args.proposal_id:
            result = record_decision(
                db_path=db_path,
                proposal_id=args.proposal_id,
                action=args.action,
                reviewer_id=args.reviewer_id,
                note=args.note,
                version_target=args.version_target,
            )
            print(f"  Decision: {result}")
            return

        # Route 2 — apply an APPROVED proposal (CI/CD auto-versioning)
        if args.apply:
            result = apply_approved(
                db_path=db_path,
                out_path=out_path,
                proposal_id=args.apply,
                open_pr=args.open_pr,
            )
            print(f"  Apply result: {json.dumps(result, indent=2)}")
            return

        # Route 3 — interactive review listing
        if args.review:
            pending = list_pending(db_path=db_path, limit=200)
            print(f"\n  {len(pending)} PENDING proposals "
                  "(sorted by composite score):\n")
            print(f"  {'ID':<10} {'Band':<13} {'Score':>6}  Type             Title")
            print(f"  {'─'*10} {'─'*13} {'─'*6}  {'─'*16} {'─'*40}")
            for p in pending[:50]:
                pid = (p["proposal_id"] or "")[:8]
                band = p.get("band") or "CANDIDATE"
                score = p["confidence_score"]
                score_s = f"{score:.2f}" if score is not None else "  —  "
                ptype = p["proposal_type"] or ""
                title = (p["title"] or "")[:55]
                print(f"  {pid:<10} {band:<13} {score_s:>6}  {ptype:<16} {title}")
            print(
                "\n  To act on a proposal:\n"
                "    python3 toolkit.py --phase evolve --action APPROVE "
                "--proposal-id <id>\n"
                "    python3 toolkit.py --phase evolve --apply <id> --open-pr\n"
            )
            return

        # Route 4 (default) — run the full monitor + scorer pipeline
        _ = run_evolution_monitor(
            db_path=db_path,
            out_path=out_path,
            min_evidence=args.min_evidence,
            strategy=args.strategy,
        )
        scoring = score_pending(db_path=db_path, out_path=out_path)
        print(
            f"  {scoring['pending_total']} PENDING  "
            f"| review_now={scoring['review_now']}  "
            f"weekly={scoring['weekly_batch']}  "
            f"candidate={scoring['candidates']}"
        )

    def phase_federate(db_path: str, out_path: str):
        step(0, "Workstream 3 — Cross-Enterprise Federated Ontology Network")

        sys.path.insert(0, HERE)
        from federation import (
            partner_registry, manifest as fed_manifest, trust as fed_trust,
        )

        # Route 1 — generate a local Ed25519 signing keypair
        if args.generate_keys:
            result = fed_manifest.generate_keypair(key_name=args.key_name)
            print(f"  ✓ Keypair generated")
            print(f"    secret : {result['sk_path']} (mode 0600)")
            print(f"    public : {result['pk_path']}")
            print(f"    pk b64 : {result['public_key']}")
            return

        # Route 2 — list every registered partner
        if args.list_partners:
            partners = partner_registry.list_partners(db_path)
            if not partners:
                print("  (no partners registered)")
                return
            print(f"\n  {len(partners)} partners registered:\n")
            print(f"  {'ID':<10} {'State':<14} {'Tier':<14} Name")
            print(f"  {'─'*10} {'─'*14} {'─'*14} {'─'*40}")
            for p in partners:
                pid = (p.get("partner_id") or "")[:8]
                state = p.get("trust_state") or ""
                tier = p.get("max_shareable_tier") or ""
                name = (p.get("display_name") or "")[:40]
                print(f"  {pid:<10} {state:<14} {tier:<14} {name}")
            return

        # Route 3 — register a new partner from declared parameters
        if args.register_partner:
            if not args.partner_public_key:
                print("  ⚠  --partner-public-key is required for --register-partner")
                return
            classes = [c.strip() for c in (args.exposed_classes or "").split(",") if c.strip()]
            iri = args.partner_iri or args.register_partner
            result = partner_registry.register_partner(
                db_path,
                partner_iri=iri,
                display_name=args.partner_display_name or iri,
                sparql_endpoint=args.partner_endpoint or args.register_partner,
                public_key=args.partner_public_key,
                exposed_classes=classes,
                max_shareable_tier=args.max_tier,
                manifest_url=args.register_partner,
            )
            print(f"  ✓ Partner registered: {result}")
            return

        # Route 4 — build + sign the local capability manifest
        if args.build_manifest:
            sk = fed_manifest.load_secret_key(args.key_name)
            pk = fed_manifest.load_public_key(args.key_name)
            if not sk or not pk:
                print(f"  ⚠  No keypair named '{args.key_name}' — "
                      "run --generate-keys first.")
                return
            classes = [c.strip() for c in (args.exposed_classes or "").split(",") if c.strip()]
            if not classes:
                classes = [
                    "https://ontology.example.com/tmf/NetworkFunction",
                    "https://ontology.example.com/tmf/PerformanceIndicator",
                ]
            m = fed_manifest.build_manifest(
                enterprise_iri=args.enterprise_iri,
                ontology_iri=f"{args.enterprise_iri.rstrip('#self').rstrip('/')}/enterprise.ttl",
                exposed_classes=classes,
                public_key=pk,
                signer_iri=args.enterprise_iri,
            )
            signed = fed_manifest.sign_manifest(m, secret_key_b64=sk)
            path = fed_manifest.write_manifest(signed)
            check = fed_manifest.verify_manifest(signed)
            print(f"  ✓ Capability manifest signed → {path}")
            print(f"    verify: {check}")
            return

        # Route 5 — run the trust-bootstrap handshake
        if args.handshake:
            partner_iri = args.partner_iri or args.handshake
            sk = fed_manifest.load_secret_key(args.key_name)
            pk = fed_manifest.load_public_key(args.key_name)
            if not sk:
                print(f"  ⚠  No keypair '{args.key_name}' — run --generate-keys first.")
                return
            # Build local manifest on the fly (exposure defaults are fine for demo)
            local_m = fed_manifest.build_manifest(
                enterprise_iri=args.enterprise_iri,
                ontology_iri=f"{args.enterprise_iri.rstrip('#self').rstrip('/')}/enterprise.ttl",
                exposed_classes=[
                    "https://ontology.example.com/tmf/NetworkFunction",
                    "https://ontology.example.com/tmf/PerformanceIndicator",
                ],
                public_key=pk,
                signer_iri=args.enterprise_iri,
            )
            hs = fed_trust.handshake(
                db_path, partner_iri=partner_iri,
                local_manifest=local_m, secret_key_b64=sk,
            )
            print(f"  ✓ Handshake: {hs.get('ok')}  "
                  f"(partner_id={hs.get('partner_id', '—')[:8]})")
            if hs.get("ok"):
                print("    Send the signed manifest to the partner and run "
                      "--handshake again on their response to countersign.")
            return

        # Route 6 (default) — show a concise status summary
        partners = partner_registry.list_partners(db_path)
        active = [p for p in partners if p.get("trust_state") == "ACTIVE"]
        print(f"  Federation status — {len(partners)} partners "
              f"({len(active)} ACTIVE).")
        print("  CLI options:")
        print("    --generate-keys           — create signing keypair")
        print("    --build-manifest          — sign local capability manifest")
        print("    --list-partners           — show every registered partner")
        print("    --register-partner <url>  — register a new partner")
        print("    --handshake <url>         — start bilateral trust handshake")

    def phase_comply(db_path: str, out_path: str):
        step(0, "Workstream 4 — Regulatory AI Compliance Evidence Engine")

        sys.path.insert(0, HERE)
        from compliance import (
            registry as reg_mod,
            assembler as asm_mod,
            bundle    as bun_mod,
            mapping   as map_mod,
        )

        # Route 1 — list regulations
        if args.list_regulations:
            regs = reg_mod.list_regulations()
            if not regs:
                print("  (no regulations registered)")
                return
            print(f"\n  {len(regs)} regulations loaded:\n")
            print(f"  {'ID':<30} {'Jurisdiction':<22} {'Effective':<12} Reqs")
            print(f"  {'─'*30} {'─'*22} {'─'*12} {'─'*5}")
            for r in regs:
                print(f"  {r['regulation_id']:<30} {r['jurisdiction'][:22]:<22} "
                      f"{(r.get('effective_date') or '')[:10]:<12} "
                      f"{r['requirement_count']}")
            return

        # Route 2 — verify a compliance bundle
        if args.verify:
            result = bun_mod.verify_bundle(args.verify)
            if result.get("ok"):
                print(f"  ✓ Bundle verified: {args.verify}")
                print(f"    bundle_id   : {result.get('bundle_id')}")
                print(f"    regulation  : {result.get('regulation_id')}")
                print(f"    signer      : {result.get('signer_iri')}")
                print(f"    file count  : {result.get('file_count')}")
            else:
                print(f"  ✗ Bundle verification FAILED: {result.get('reason')}")
            return

        # Route 3 — gap analysis
        if args.gap_analysis:
            gap = map_mod.gap_analysis(out_path=out_path)
            print(f"\n  Gap analysis\n  {'─'*60}")
            print(f"  Uncovered regulatory requirements: "
                  f"{len(gap['uncovered_requirements'])}")
            for g in gap["uncovered_requirements"][:20]:
                print(f"    • [{g['regulation_id']}] {g['req_id']} — "
                      f"{g['title']}  (wants {g['artefact_type']}:{g['selector']})")
            print(f"  Orphan toolkit artefacts         : "
                  f"{len(gap['orphan_artefacts'])}")
            for o in gap["orphan_artefacts"][:20]:
                print(f"    • {o['artefact_type']}:{o['selector']}")
            print("\n  Recommendations:")
            for rec in gap["recommendations"]:
                print(f"    • {rec}")
            return

        # Route 4 (default) — assemble evidence and export a bundle
        if not args.regulation:
            from compliance import dashboard as dash_mod
            regs = reg_mod.list_regulations()
            print(f"  Compliance status — {len(regs)} regulation(s) loaded.")
            summary = dash_mod.write_summary(out_path=out_path, db_path=db_path)
            print(f"  ✓ Compliance summary    → {summary['html_path']}")
            print(f"  ✓ Coverage CSV          → {summary['csv_path']}")
            print("  CLI options:")
            print("    --list-regulations                — show every loaded regulation")
            print("    --regulation <id> [--decision <iri>] — assemble evidence + export bundle")
            print("    --verify <bundle.zip>             — verify a signed compliance bundle")
            print("    --gap-analysis                    — run coverage gap report")
            return

        tr = None
        if args.time_range and "," in args.time_range:
            a, b = args.time_range.split(",", 1)
            tr = (a.strip(), b.strip())

        ev = asm_mod.assemble_evidence(
            regulation_id=args.regulation,
            decision_iri=args.decision,
            db_path=db_path,
            out_path=out_path,
            time_range=tr,
        )
        print(f"\n  {ev['name']} [{ev['regulation_id']}]")
        print(f"  {'─'*62}")
        for e in ev["evidence"]:
            icon = {"SATISFIED": "✓", "INSUFFICIENT": "✗",
                    "NOT_APPLICABLE": "~", "MISSING": "?"}.get(e["status"], "?")
            print(f"    {icon} {e['req_id']:<18} [{e['status']:14s}] {e['title']}")
        s = ev["summary"]
        print(f"  Coverage: {s['coverage_percent']}%  "
              f"({s['satisfied']}/{s['total_requirements']} satisfied)")

        bundle = bun_mod.export_bundle(
            ev,
            signer_iri=args.bundle_signer,
            publish_to_graph=True,
            db_path=db_path,
        )
        print(f"\n  ✓ Bundle exported → {bundle['bundle_path']}")
        print(f"    sha256   : {bundle['sha256']}")
        print(f"    verified : {bundle['verified']}")

    def phase_embed(db_path: str, out_path: str):
        step(0, "Workstream 5 — Ontology-Bounded Vector Retrieval · Indexing")

        sys.path.insert(0, HERE)
        sys.path.insert(0, os.path.join(HERE, "runtime"))
        from runtime.embeddings import pipeline as pipe_mod
        from runtime.embeddings import dashboard as emb_dash

        if args.list_indexes:
            rows = pipe_mod.list_indexes(db_path)
            if not rows:
                print("  (no embedding indexes registered)")
                return
            print(f"\n  {len(rows)} embedding indexes:\n")
            print(f"  {'Flavor':<22} {'Store':<12} {'Model':<30} {'Dim':>4} "
                  f"{'Records':>7}  Tier")
            print(f"  {'─'*22} {'─'*12} {'─'*30} {'─'*4} {'─'*7}  {'─'*12}")
            for r in rows:
                print(f"  {r['flavor']:<22} {r['vector_store']:<12} "
                      f"{(r['model_id'] or '')[:30]:<30} "
                      f"{r['dimensions']:>4} {r['record_count']:>7}  "
                      f"{r['max_sensitivity']}")
            return

        target = args.flavor
        if target:
            summary = pipe_mod.index_flavor(
                target,
                db_path=db_path,
                connection_string=args.vector_store,
                model_id=args.embed_model,
                force=args.force_reindex,
            )
            print(f"  ✓ Indexed '{summary['flavor']}' → {summary['indexed']} "
                  f"new, {summary['skipped_unchanged']} unchanged, "
                  f"{summary['total_records']} total "
                  f"(model={summary['model']}, dim={summary['dim']}, "
                  f"store={summary['connection']})")
        else:
            results = pipe_mod.reindex_all(
                db_path=db_path,
                force=args.force_reindex,
            )
            for r in results:
                if "error" in r:
                    print(f"  ✗ {r['flavor']:<20} ERROR {r['error']}")
                else:
                    print(f"  ✓ {r['flavor']:<20} indexed={r['indexed']:<5} "
                          f"total={r['total_records']:<5} "
                          f"model={r['model']}")

        emb_dash.write_summary(out_path=out_path, db_path=db_path)

    def phase_retrieve(db_path: str, out_path: str):
        step(0, "Workstream 5 — Ontology-Bounded Vector Retrieval · Query")

        sys.path.insert(0, HERE)
        sys.path.insert(0, os.path.join(HERE, "runtime"))
        from runtime.embeddings import benchmark as bench_mod
        from runtime.embeddings import dashboard as emb_dash
        from runtime.embeddings import pipeline  as pipe_mod
        from runtime.hybrid_retriever import HybridRetriever

        if args.benchmark:
            summary = bench_mod.run_benchmark(db_path=db_path, out_path=out_path)
            print(f"\n  Retrieval benchmark run {summary['run_id'][:8]} "
                  f"({summary['queries']} queries):")
            print(f"  {'Strategy':<22} {'P@5':>6} {'MRR':>6} "
                  f"{'p50ms':>6} {'p95ms':>6} {'Δ%':>6} {'WCB':>6}")
            print(f"  {'─'*22} {'─'*6} {'─'*6} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")
            for s in summary["strategies"]:
                print(f"  {s['strategy']:<22} "
                      f"{s['precision_at_5']:>6} "
                      f"{s['mean_reciprocal_rank']:>6} "
                      f"{s['latency_p50_ms']:>6} "
                      f"{s['latency_p95_ms']:>6} "
                      f"{s['improvement_over_baseline']*100:>5.1f} "
                      f"{s['wrong_class_blocked']:>6}")
            print(f"  ✓ CSV → {summary['csv_path']}")
            emb_dash.write_summary(out_path=out_path, db_path=db_path)
            return

        if not args.question or not args.flavor:
            print("  ⚠  --question and --flavor are required for --phase retrieve")
            print("    Example: python3 toolkit.py --phase retrieve "
                  "--flavor network-ops --question 'degraded NFs?' "
                  "--class-expression tmf:NetworkFunction")
            return

        # Lazy: make sure the flavor is indexed
        rows = [i for i in pipe_mod.list_indexes(db_path) if i["flavor"] == args.flavor]
        if not rows:
            print(f"  (no index for flavor '{args.flavor}' — indexing now)")
            pipe_mod.index_flavor(args.flavor, db_path=db_path,
                                   connection_string=args.vector_store,
                                   model_id=args.embed_model)

        retriever = HybridRetriever(
            flavor=args.flavor,
            db_path=db_path,
            connection_string=args.vector_store,
            model_id=args.embed_model,
        )

        strategies = (["UNFILTERED_VECTOR", "ONTOLOGY_BOUNDED", "PURE_SPARQL"]
                      if args.strategy_compare else ["ONTOLOGY_BOUNDED"])
        for strat in strategies:
            res = retriever.retrieve(
                args.question,
                class_expression=args.class_expression,
                k=args.top_k,
                strategy=strat,
            )
            print(f"\n  [{strat}] {res['result_count']} results "
                  f"(k={res['k']}, latency={res['latency_ms']}ms, "
                  f"classes_resolved={len(res['resolved_classes'])})")
            for i, r in enumerate(res["results"], start=1):
                cls = (r.get("owl_class") or "").split("/")[-1]
                pk = r.get("primary_key") or ""
                tier = r.get("sensitivity_tier") or ""
                score = r.get("composite_score", 0.0)
                print(f"    {i:>2}. [{cls:<24}] pk={pk:<8} tier={tier:<12} "
                      f"score={score:.3f}")

        emb_dash.write_summary(out_path=out_path, db_path=db_path)

    def phase_wizard(db_path: str, out_path: str):
        step(0, "Phase 3 — Ontology Studio (Flask)")
        wizard_path = os.path.join(HERE, "wizard", "app.py")
        if not os.path.exists(wizard_path):
            print(f"  ⚠  Ontology Studio not found at {wizard_path}")
            return
        print(f"  Starting Ontology Studio at http://127.0.0.1:5000")
        print(f"  Press Ctrl+C to stop.")
        os.execv(sys.executable, [sys.executable, wizard_path, "--debug"])

    phases = {
        "1":       [(phase1_foundation, [args.db, args.out])],
        "2":       [(phase2_ontology,   [args.db, args.out])],
        "3":       [(phase3_shacl,      [args.db, args.out])],
        "targets": [(phase_targets,     [args.db, args.out, args.targets])],
        "4":       [(phase4_mapping,    [args.db, args.out])],
        "5":       [(phase5_exchange,   [args.db, args.out])],
        "reason":  [(phase_reason,      [args.db, args.out])],
        "tmf":     [(phase_tmf,         [args.db, args.out])],
        "test":    [(phase_test,        [args.db, args.out])],
        "report":  [(phase_report,      [args.out])],
        "reasoner": [(phase_reasoner,  [args.db, args.out])],
        "sparql":   [(phase_sparql,    [args.db, args.out])],
        "log":       [(phase_log,       [args.db, args.out])],
        "mine":      [(phase_mine,      [args.db, args.out])],
        "sequence":  [(phase_sequence,  [args.db, args.out])],
        "drift-templates": [(phase_drift_templates, [args.db, args.out])],
        "security":  [(phase_security,  [args.db, args.out])],
        "conflict":  [(phase_conflict,  [args.db, args.out])],
        "alignment": [(phase_alignment, [args.db, args.out])],
        "runtime":   [(phase_runtime,   [args.db, args.out])],
        # ── Phase 3 ───────────────────────────────────────────────────────
        "publish":   [(phase_publish,   [args.db, args.out])],
        "drift":     [(phase_drift,     [args.db, args.out])],
        "templates": [(phase_templates, [args.db, args.out])],
        "modular":   [(phase_modular,   [args.db, args.out])],
        "abox":      [(phase_abox,      [args.db, args.out])],
        "discover":  [(phase_discover,  [args.db, args.out])],
        "tmf630":    [(phase_tmf630,    [args.db, args.out])],
        "wizard":    [(phase_wizard,    [args.db, args.out])],
        "evolve":    [(phase_evolve,    [args.db, args.out])],
        "federate":  [(phase_federate,  [args.db, args.out])],
        "comply":    [(phase_comply,    [args.db, args.out])],
        "embed":     [(phase_embed,     [args.db, args.out])],
        "retrieve":  [(phase_retrieve,  [args.db, args.out])],
        "all": [
            (phase1_foundation, [args.db, args.out]),
            (phase2_ontology,   [args.db, args.out]),
            (phase3_shacl,      [args.db, args.out]),
            (phase_reason,      [args.db, args.out]),
            (phase4_mapping,    [args.db, args.out]),
            (phase5_exchange,   [args.db, args.out]),
            (phase_tmf,         [args.db, args.out]),
            (phase_conflict,    [args.db, args.out]),
            (phase_alignment,   [args.db, args.out]),
            (phase_runtime,     [args.db, args.out]),
            (phase_drift,       [args.db, args.out]),
            (phase_templates,   [args.db, args.out]),
            (phase_modular,     [args.db, args.out]),
            (phase_tmf630,      [args.db, args.out]),
            (phase_test,        [args.db, args.out]),
            (phase_report,      [args.out]),
        ]
    }

    for fn, fargs in phases[args.phase]:
        fn(*fargs)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n{'='*62}")
    print(f"  ✓ Pipeline complete in {elapsed:.1f}s")
    print(f"  Output directory: {args.out}/")
    print(f"  Open: {args.out}/reports/toolkit_report.html")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
