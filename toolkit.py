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
  python toolkit.py --phase test      # CQ tests + governance score
  python toolkit.py --phase report    # HTML report only

Options:
  --db PATH       SQLite database path (default: db/enterprise.db)
  --out PATH      Output directory (default: output)
  --industry STR  Label for the industry context (default: Enterprise)
"""

import sys
import os
import argparse
import sqlite3
from datetime import datetime

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

    intro = DBIntrospector(db_path)
    generate_ontology(intro, os.path.join(out_path, "ontology"))
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


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ontology Engineering Toolkit — full 5-phase pipeline"
    )
    parser.add_argument("--db",       default=DB_PATH,  help="SQLite database path")
    parser.add_argument("--out",      default=OUT_PATH, help="Output directory")
    parser.add_argument("--phase",    default="all",
                        choices=["all","1","2","3","4","5","tmf","test","report","reasoner","sparql"],
                        help="Run a specific phase only")
    parser.add_argument("--industry", default="Enterprise", help="Industry label for output")
    args = parser.parse_args()

    start = datetime.utcnow()
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

    phases = {
        "1":       [(phase1_foundation, [args.db, args.out])],
        "2":       [(phase2_ontology,   [args.db, args.out])],
        "3":       [(phase3_shacl,      [args.db, args.out])],
        "4":       [(phase4_mapping,    [args.db, args.out])],
        "5":       [(phase5_exchange,   [args.db, args.out])],
        "tmf":     [(phase_tmf,         [args.db, args.out])],
        "test":    [(phase_test,        [args.db, args.out])],
        "report":  [(phase_report,      [args.out])],
        "reasoner":[(phase_reasoner,    [args.db, args.out])],
        "sparql":  [(phase_sparql,      [args.db, args.out])],
        "all": [
            (phase1_foundation, [args.db, args.out]),
            (phase2_ontology,   [args.db, args.out]),
            (phase3_shacl,      [args.db, args.out]),
            (phase4_mapping,    [args.db, args.out]),
            (phase5_exchange,   [args.db, args.out]),
            (phase_tmf,         [args.db, args.out]),
            (phase_test,        [args.db, args.out]),
            (phase_report,      [args.out]),
        ]
    }

    for fn, fargs in phases[args.phase]:
        fn(*fargs)

    elapsed = (datetime.utcnow() - start).total_seconds()
    print(f"\n{'='*62}")
    print(f"  ✓ Pipeline complete in {elapsed:.1f}s")
    print(f"  Output directory: {args.out}/")
    print(f"  Open: {args.out}/reports/toolkit_report.html")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
