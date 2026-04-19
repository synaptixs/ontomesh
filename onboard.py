#!/usr/bin/env python3
"""
onboard.py — Ontology Toolkit Onboarding Wizard
─────────────────────────────────────────────────
Guides anyone through setting up a new domain ontology from scratch.

No prior ontology knowledge required.

What it does
────────────
1. Asks about your domain in plain language
2. Helps you define entities, events, and relationships interactively
3. Generates a relational schema (schema.sql)
4. Generates ontology metadata and seed data (seed.sql)
5. Generates a starter competency question catalog (docs/cq-catalog.md)
6. Generates a scope charter (docs/scope-charter.md)
7. Runs the full pipeline automatically

Usage
─────
  python3 onboard.py                    # interactive (recommended)
  python3 onboard.py --from config.json  # load a saved session
  python3 onboard.py --industry telecom  # pre-load TMF starter template
  python3 onboard.py --industry healthcare
  python3 onboard.py --industry finance
  python3 onboard.py --industry manufacturing
  python3 onboard.py --industry retail

No external dependencies.
"""

import os
import sys
import json
import re
import textwrap
import argparse
import subprocess
from datetime import datetime
from typing import List, Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

# ── Colour helpers (degrades gracefully if terminal has no colour) ────────
def _c(code, text):
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def bold(t):    return _c("1", t)
def blue(t):    return _c("34", t)
def cyan(t):    return _c("36", t)
def green(t):   return _c("32", t)
def yellow(t):  return _c("33", t)
def dim(t):     return _c("2", t)
def red(t):     return _c("31", t)


# ── Banner ────────────────────────────────────────────────────────────────
def banner():
    print()
    print(bold(blue("=" * 60)))
    print(bold(blue("  Ontology Engineering Toolkit — Onboarding Wizard")))
    print(bold(blue("=" * 60)))
    print(dim("  No ontology experience needed. Answer in plain language."))
    print()


# ── Prompts ───────────────────────────────────────────────────────────────
def ask(prompt: str, default: str = "", required: bool = True) -> str:
    if default:
        disp = f"{prompt} {dim(f'[{default}]')}: "
    else:
        disp = f"{prompt}: "
    while True:
        raw = input(disp).strip()
        if not raw and default:
            return default
        if raw or not required:
            return raw
        print(red("  This field is required."))


def ask_list(prompt: str, hint: str = "", min_items: int = 1) -> List[str]:
    print(f"\n{prompt}")
    if hint:
        print(dim(f"  {hint}"))
    print(dim("  Enter one per line. Empty line when done."))
    items = []
    i = 1
    while True:
        val = input(f"  {i}. ").strip()
        if not val:
            if len(items) >= min_items:
                break
            print(red(f"  Please enter at least {min_items} item(s)."))
        else:
            items.append(val)
            i += 1
    return items


def confirm(prompt: str, default: bool = True) -> bool:
    suffix = dim("[Y/n]") if default else dim("[y/N]")
    raw = input(f"{prompt} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def section(title: str):
    print()
    print(cyan("─" * 60))
    print(cyan(f"  {title}"))
    print(cyan("─" * 60))


# ── Name normalisation ────────────────────────────────────────────────────
def to_snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9 _]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s.lower()


def to_camel(s: str) -> str:
    parts = re.split(r"[\s_]+", s.strip())
    return "".join(w.capitalize() for w in parts if w)


def to_label(s: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[\s_]+", s.strip()))


# ── Industry starter templates ────────────────────────────────────────────
INDUSTRY_TEMPLATES = {
    "telecom": {
        "domain_name": "Telecom Network Operations",
        "domain_description": "Network element management, service fulfilment, alarm handling, and performance monitoring for a telecommunications operator.",
        "entities": ["Network Element", "Service", "Customer", "Alarm", "Work Order"],
        "events": ["Incident", "Maintenance", "Configuration Change", "Service Activation"],
        "relationships": [
            ("Service", "realised by", "Network Element"),
            ("Alarm", "raised against", "Network Element"),
            ("Work Order", "assigned to", "Engineer"),
        ],
        "cqs": [
            "Which network elements are currently degraded or offline?",
            "Which services are affected when a network element fails?",
            "Which alarms are unacknowledged and of Critical severity?",
            "Which engineer is responsible for a given work order?",
            "What is the availability of each network element over the last 30 days?",
        ],
    },
    "healthcare": {
        "domain_name": "Clinical Operations",
        "domain_description": "Patient encounters, clinical observations, care plans, medication administration, and provider management.",
        "entities": ["Patient", "Provider", "Encounter", "Observation", "Medication", "Care Plan"],
        "events": ["Admission", "Discharge", "Diagnosis", "Medication Administration", "Care Plan Update"],
        "relationships": [
            ("Encounter", "involves", "Patient"),
            ("Observation", "recorded during", "Encounter"),
            ("Care Plan", "assigned to", "Patient"),
            ("Medication", "prescribed by", "Provider"),
        ],
        "cqs": [
            "Which patients have an active care plan?",
            "Which medications were administered to a patient during an encounter?",
            "Which provider recorded a given clinical observation?",
            "What is the complete encounter history for a patient?",
            "Which diagnoses were recorded with high confidence in the last 90 days?",
        ],
    },
    "finance": {
        "domain_name": "Financial Operations",
        "domain_description": "Account management, transaction processing, risk assessment, compliance monitoring, and counterparty relationships.",
        "entities": ["Account", "Transaction", "Counterparty", "Product", "Risk Assessment"],
        "events": ["Trade", "Settlement", "Risk Alert", "Compliance Review", "Account Opening"],
        "relationships": [
            ("Transaction", "involves", "Account"),
            ("Transaction", "linked to", "Counterparty"),
            ("Risk Assessment", "covers", "Account"),
            ("Product", "held by", "Account"),
        ],
        "cqs": [
            "Which accounts have open risk alerts above threshold?",
            "Which transactions are pending settlement?",
            "Which counterparties are associated with flagged transactions?",
            "What is the position history for a given account?",
            "Which compliance reviews are overdue?",
        ],
    },
    "manufacturing": {
        "domain_name": "Manufacturing Operations",
        "domain_description": "Asset management, work order tracking, quality control, supply chain, and production event management.",
        "entities": ["Asset", "Work Order", "Product", "Supplier", "Quality Inspection"],
        "events": ["Production Run", "Maintenance", "Quality Failure", "Shipment", "Inventory Adjustment"],
        "relationships": [
            ("Work Order", "performed on", "Asset"),
            ("Quality Inspection", "covers", "Product"),
            ("Shipment", "fulfilled by", "Supplier"),
            ("Production Run", "uses", "Asset"),
        ],
        "cqs": [
            "Which assets are currently under maintenance?",
            "Which production runs failed quality inspection?",
            "Which suppliers delivered non-conforming materials in the last quarter?",
            "What is the maintenance history for a given asset?",
            "Which work orders are overdue?",
        ],
    },
    "retail": {
        "domain_name": "Retail Operations",
        "domain_description": "Product catalog, inventory, order management, customer relationships, and store operations.",
        "entities": ["Product", "Order", "Customer", "Store", "Inventory"],
        "events": ["Purchase", "Return", "Stock Replenishment", "Price Change", "Promotion"],
        "relationships": [
            ("Order", "placed by", "Customer"),
            ("Order", "contains", "Product"),
            ("Inventory", "located at", "Store"),
            ("Promotion", "applies to", "Product"),
        ],
        "cqs": [
            "Which products are below reorder threshold in which stores?",
            "Which customers have placed orders in the last 30 days?",
            "Which promotions are currently active?",
            "What is the return rate for a given product?",
            "Which orders are awaiting fulfilment?",
        ],
    },
}


# ── Domain session model ──────────────────────────────────────────────────
class DomainSession:
    def __init__(self):
        self.domain_name        = ""
        self.domain_slug        = ""
        self.domain_description = ""
        self.author             = ""
        self.base_iri           = ""
        self.sensitivity_default = "Internal"
        self.entities: List[Dict] = []   # {name, label, description, sensitivity, is_event}
        self.relationships: List[Dict] = []  # {from_entity, label, to_entity}
        self.cqs: List[str] = []
        self.out_dir            = ""
        self.db_path            = ""
        self.created_at         = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict:
        return {
            "domain_name":        self.domain_name,
            "domain_slug":        self.domain_slug,
            "domain_description": self.domain_description,
            "author":             self.author,
            "base_iri":           self.base_iri,
            "sensitivity_default": self.sensitivity_default,
            "entities":           self.entities,
            "relationships":      self.relationships,
            "cqs":                self.cqs,
            "out_dir":            self.out_dir,
            "db_path":            self.db_path,
            "created_at":         self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict):
        s = cls()
        for k, v in d.items():
            setattr(s, k, v)
        return s


# ── Interview steps ───────────────────────────────────────────────────────

def step_domain(session: DomainSession, template: dict = None):
    section("Step 1 of 6 — Domain identity")
    print("  Let's start with what this ontology is about.\n")

    session.domain_name = ask(
        bold("  What is the name of this domain or project?"),
        default=template.get("domain_name", "") if template else ""
    )
    session.domain_slug = to_snake(session.domain_name)

    session.domain_description = ask(
        bold("  Describe it in one or two sentences (what it manages, who uses it)"),
        default=template.get("domain_description", "") if template else "",
    )
    session.author = ask(
        bold("  Your name (for the scope charter and ontology header)"),
        default=os.environ.get("USER", "")
    )
    session.base_iri = ask(
        bold("  Base IRI for your ontology (e.g. https://mycompany.com/ontology/myproject/)"),
        default=f"https://ontology.example.com/{session.domain_slug}/"
    )
    session.sensitivity_default = ask(
        bold("  Default sensitivity tier for entities"),
        default="Internal"
    )
    session.out_dir = os.path.join(HERE, "projects", session.domain_slug)
    session.db_path = os.path.join(session.out_dir, f"{session.domain_slug}.db")

    print(f"\n  {green('✓')} Domain: {bold(session.domain_name)}")
    print(f"    Output will be written to: {dim(session.out_dir)}")


def step_entities(session: DomainSession, template: dict = None):
    section("Step 2 of 6 — Entities")
    print("  Entities are the main 'things' in your domain.")
    print(dim("  Examples: Customer, Asset, Order, Patient, Network Element, Policy\n"))

    defaults = template.get("entities", []) if template else []
    if defaults:
        print(f"  Suggested for this domain: {dim(', '.join(defaults))}")
        use = confirm("  Use these as a starting point?", default=True)
        if use:
            raw_entities = list(defaults)
        else:
            raw_entities = ask_list(bold("  Enter your entities"), min_items=2)
    else:
        raw_entities = ask_list(bold("  What are the key entities in your domain?"), min_items=2)

    print(f"\n  {green('✓')} {len(raw_entities)} entities captured. Now let's add detail.\n")

    for name in raw_entities:
        label = to_label(name)
        print(f"  {cyan('→')} {bold(label)}")
        desc = ask(
            f"    Describe what a {label} is (one sentence)",
            default=f"A {label.lower()} in the {session.domain_name} domain.",
            required=False
        )
        sensitivity = ask(
            f"    Sensitivity tier (Public / Internal / Confidential / Restricted)",
            default=session.sensitivity_default,
            required=False
        ) or session.sensitivity_default

        is_event = confirm(
            f"    Is this an EVENT that happens (vs a persistent thing)?",
            default=False
        )

        session.entities.append({
            "name":        to_camel(name),
            "table_name":  to_snake(name),
            "label":       label,
            "description": desc or f"A {label.lower()} in the {session.domain_name} domain.",
            "sensitivity": sensitivity,
            "is_event":    is_event,
        })


def step_events(session: DomainSession, template: dict = None):
    section("Step 3 of 6 — Domain events")
    print("  Events are things that HAPPEN — inspections, incidents, orders, changes.")
    print(dim("  Any entity you already marked as an event is included automatically.\n"))

    existing_events = [e["label"] for e in session.entities if e["is_event"]]
    if existing_events:
        print(f"  Already marked as events: {dim(', '.join(existing_events))}\n")

    defaults = template.get("events", []) if template else []
    add_more = confirm("  Do you want to add more event types?", default=bool(defaults))
    if add_more:
        suggested = [e for e in (defaults or []) if e not in existing_events]
        if suggested:
            print(f"  Suggested: {dim(', '.join(suggested))}")
        new_events = ask_list(
            bold("  Additional event types"),
            hint="E.g. Maintenance, Inspection, Incident, Approval",
            min_items=0
        )
        for name in new_events:
            if not any(e["label"].lower() == name.lower() for e in session.entities):
                label = to_label(name)
                session.entities.append({
                    "name":        to_camel(name),
                    "table_name":  to_snake(name),
                    "label":       label,
                    "description": f"A {label.lower()} event in the {session.domain_name} domain.",
                    "sensitivity": session.sensitivity_default,
                    "is_event":    True,
                })

    print(f"\n  {green('✓')} {len([e for e in session.entities if e['is_event']])} event types defined.")


def step_relationships(session: DomainSession, template: dict = None):
    section("Step 4 of 6 — Relationships")
    print("  Relationships connect entities. Write them as: Entity A [verb] Entity B")
    print(dim("  Examples:"))
    print(dim("    Order  →  placed by  →  Customer"))
    print(dim("    Alarm  →  raised against  →  Network Element\n"))

    entity_names = [e["label"] for e in session.entities]
    print(f"  Your entities: {dim(', '.join(entity_names))}\n")

    defaults = template.get("relationships", []) if template else []
    if defaults:
        print(f"  Suggested relationships:")
        for r in defaults:
            print(f"    {dim(f'{r[0]}  →  {r[1]}  →  {r[2]}')}")
        use = confirm("  Use these as a starting point?", default=True)
        if use:
            for r in defaults:
                session.relationships.append({
                    "from_entity": r[0],
                    "label":       r[1],
                    "to_entity":   r[2],
                })

    add = confirm("  Add more relationships?", default=not bool(defaults))
    while add:
        print()
        from_e = ask(f"    From entity (e.g. {entity_names[0] if entity_names else 'Order'})")
        label  = ask(f"    Relationship verb (e.g. 'placed by', 'assigned to', 'covers')")
        to_e   = ask(f"    To entity (e.g. {entity_names[1] if len(entity_names) > 1 else 'Customer'})")
        session.relationships.append({
            "from_entity": from_e,
            "label":       label,
            "to_entity":   to_e,
        })
        print(f"  {green('✓')} Added: {from_e} → {label} → {to_e}")
        add = confirm("  Add another?", default=False)

    print(f"\n  {green('✓')} {len(session.relationships)} relationships defined.")


def step_cqs(session: DomainSession, template: dict = None):
    section("Step 5 of 6 — Competency questions")
    print("  These are the questions your ontology must be able to answer.")
    print("  Write them as plain English questions. They become your test suite.\n")

    defaults = template.get("cqs", []) if template else []
    if defaults:
        print("  Suggested questions:")
        for i, q in enumerate(defaults, 1):
            print(f"    {dim(str(i) + '.')} {q}")
        use = confirm("\n  Use these as a starting point?", default=True)
        if use:
            session.cqs = list(defaults)

    add = confirm("  Add more questions?", default=not bool(session.cqs))
    while add:
        q = ask("    Question")
        session.cqs.append(q)
        print(f"  {green('✓')} Added.")
        add = confirm("  Add another?", default=False)

    # Auto-suggest basic CQs if fewer than 4
    if len(session.cqs) < 4:
        print(f"\n  {yellow('Tip:')} You have {len(session.cqs)} question(s). A minimum of 8 is recommended.")
        auto = confirm("  Auto-generate starter questions from your entities?", default=True)
        if auto:
            events = [e["label"] for e in session.entities if e["is_event"]]
            things = [e["label"] for e in session.entities if not e["is_event"]]
            auto_qs = []
            if things:
                auto_qs.append(f"Which {things[0].lower()}s exist and what is their current status?")
            if events and things:
                auto_qs.append(f"Which {events[0].lower()}s have occurred against each {things[0].lower()}?")
            if len(session.relationships) > 0:
                r = session.relationships[0]
                auto_qs.append(f"Which {r['from_entity'].lower()} is {r['label']} which {r['to_entity'].lower()}?")
            auto_qs.append("Which records were produced by which agent, with what confidence?")
            auto_qs.append("What is the full provenance chain for any given fact?")
            for q in auto_qs:
                if q not in session.cqs:
                    session.cqs.append(q)
                    print(f"  {green('+')} {q}")

    print(f"\n  {green('✓')} {len(session.cqs)} competency questions defined.")


def step_confirm(session: DomainSession):
    section("Step 6 of 6 — Review and generate")
    print(f"\n  {bold('Domain:')} {session.domain_name}")
    print(f"  {bold('Entities:')} {', '.join(e['label'] for e in session.entities if not e['is_event'])}")
    print(f"  {bold('Events:')}   {', '.join(e['label'] for e in session.entities if e['is_event']) or '(none)'}")
    print(f"  {bold('Relationships:')} {len(session.relationships)}")
    print(f"  {bold('CQs:')} {len(session.cqs)}")
    print(f"  {bold('Output:')} {session.out_dir}")
    print()
    return confirm(bold("  Generate all artifacts and run the full pipeline?"), default=True)


# ── SQL schema generator ──────────────────────────────────────────────────

def generate_schema_sql(session: DomainSession) -> str:
    lines = [
        f"-- {session.domain_name} Schema",
        f"-- Generated by Ontology Toolkit onboarding wizard",
        f"-- Author: {session.author}  |  Date: {session.created_at[:10]}",
        "",
        "PRAGMA foreign_keys = ON;",
        "",
        "-- ── SYSTEM TABLES ─────────────────────────────────────────────────",
        "CREATE TABLE IF NOT EXISTS ontology_metadata (",
        "    id               INTEGER PRIMARY KEY AUTOINCREMENT,",
        "    target_type      TEXT NOT NULL CHECK(target_type IN ('TABLE','COLUMN')),",
        "    table_name       TEXT NOT NULL,",
        "    column_name      TEXT,",
        "    semantic_type    TEXT,",
        "    label            TEXT,",
        "    description      TEXT,",
        "    sensitivity_tier TEXT DEFAULT 'Internal'",
        "                     CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),",
        "    is_event_class   INTEGER DEFAULT 0,",
        "    skos_pref_label  TEXT,",
        "    skos_alt_labels  TEXT,",
        "    cq_coverage      TEXT,",
        "    created_at       TEXT DEFAULT (datetime('now'))",
        ");",
        "",
        "CREATE TABLE IF NOT EXISTS semantic_loss_log (",
        "    id           INTEGER PRIMARY KEY AUTOINCREMENT,",
        "    table_name   TEXT NOT NULL,",
        "    column_name  TEXT,",
        "    loss_type    TEXT NOT NULL,",
        "    description  TEXT NOT NULL,",
        "    severity     TEXT CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),",
        "    remediation  TEXT,",
        "    detected_at  TEXT DEFAULT (datetime('now')),",
        "    resolved     INTEGER DEFAULT 0",
        ");",
        "",
    ]

    # Generate one table per entity
    for e in session.entities:
        tname = e["table_name"]
        label = e["label"]
        is_ev = e["is_event"]

        # Find FKs from relationships
        fk_cols = []
        for r in session.relationships:
            if r["from_entity"].lower() == label.lower():
                ref_table = to_snake(r["to_entity"])
                rel_col   = to_snake(r["to_entity"]) + "_id"
                fk_cols.append((rel_col, ref_table, r["label"]))

        lines += [
            f"-- ── {label} {'(Event)' if is_ev else ''} ──────────────────────────────────",
            f"CREATE TABLE IF NOT EXISTS {tname} (",
            f"    id          INTEGER PRIMARY KEY AUTOINCREMENT,",
            f"    {tname}_iri TEXT UNIQUE,             -- persistent IRI for PROV-O",
            f"    name        TEXT NOT NULL,",
        ]

        # Add FK columns from relationships
        for fk_col, ref_table, rel_label in fk_cols:
            lines.append(f"    {fk_col:<28} INTEGER REFERENCES {ref_table}(id), -- {rel_label}")

        if is_ev:
            lines += [
                "    status      TEXT DEFAULT 'OPEN'",
                "                CHECK(status IN ('OPEN','IN_PROGRESS','COMPLETED','FAILED','CANCELLED')),",
                "    outcome     TEXT,",
                "    -- Provenance",
                "    initiated_by_iri TEXT,",
                "    started_at  TEXT,",
                "    completed_at TEXT,",
            ]
        else:
            lines += [
                "    description TEXT,",
                f"    status      TEXT DEFAULT 'ACTIVE',",
            ]

        lines += [
            "    -- PROV-O provenance",
            "    confidence_score REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),",
            "    derivation_method TEXT CHECK(derivation_method IN",
            "                      ('MEASURED','INFERRED','IMPORTED','SYNTHESIZED')),",
            "    source_ref  TEXT,",
            "    sensitivity TEXT DEFAULT '" + e["sensitivity"] + "',",
            "    created_at  TEXT DEFAULT (datetime('now')),",
            "    updated_at  TEXT DEFAULT (datetime('now'))",
            ");",
            "",
        ]

    return "\n".join(lines)


# ── Ontology metadata seed generator ─────────────────────────────────────

def generate_seed_sql(session: DomainSession) -> str:
    lines = [
        f"-- {session.domain_name} — Ontology Metadata Seed",
        f"-- Generated: {session.created_at[:10]}",
        "",
        "-- ── ENTITY ANNOTATIONS ──────────────────────────────────────",
    ]

    cq_all = f"CQ-{',CQ-'.join(str(i+1).zfill(3) for i in range(len(session.cqs)))}"

    for i, e in enumerate(session.entities):
        cq_ids = cq_all
        lines += [
            f"INSERT INTO ontology_metadata",
            f"  (target_type, table_name, semantic_type, label, description,",
            f"   sensitivity_tier, is_event_class, skos_pref_label, cq_coverage)",
            f"VALUES",
            f"  ('TABLE', '{e['table_name']}', '{e['name']}',",
            f"   '{e['label']}', '{e['description'].replace(chr(39), chr(39)+chr(39))}',",
            f"   '{e['sensitivity']}', {1 if e['is_event'] else 0},",
            f"   '{e['label']}', '{cq_ids}');",
            "",
        ]

    return "\n".join(lines)


# ── Scope charter generator ───────────────────────────────────────────────

def generate_scope_charter(session: DomainSession) -> str:
    entity_list   = "\n".join(f"- {e['label']}" for e in session.entities if not e["is_event"])
    event_list    = "\n".join(f"- {e['label']}" for e in session.entities if e["is_event"]) or "- (none defined yet)"
    rel_list      = "\n".join(f"- {r['from_entity']} → {r['label']} → {r['to_entity']}" for r in session.relationships)

    return f"""# Scope Charter — {session.domain_name}

**Author:** {session.author}
**Date:** {session.created_at[:10]}
**Version:** 1.0
**Status:** Draft — pending stakeholder sign-off

---

## Domain description

{session.domain_description}

---

## In-scope concepts

### Entities
{entity_list}

### Events
{event_list}

### Key relationships
{rel_list}

---

## Out-of-scope (explicitly excluded)

> *Complete this section with your domain SME before Phase 2 modeling begins.*

- (Add items here)

---

## Primary use cases

1. Support the competency questions in the CQ catalog
2. Enable AI agents to reason over domain data with shared semantics
3. Provide a validation gate for data quality and provenance

---

## Stakeholder sign-off

| Role | Name | Date |
|---|---|---|
| Domain SME | | |
| Data Architect | {session.author} | {session.created_at[:10]} |
| Data Governance | | |

---

*Generated by Ontology Toolkit onboarding wizard v1.2*
"""


# ── CQ catalog generator ──────────────────────────────────────────────────

def generate_cq_catalog(session: DomainSession) -> str:
    rows = []
    for i, q in enumerate(session.cqs, 1):
        cq_id = f"CQ-{str(i).zfill(3)}"
        rows.append(
            f"| {cq_id} | {q} | Critical | Not written | — |"
        )

    table = "\n".join(rows)

    return f"""# Competency Question Catalog — {session.domain_name}

**Domain:** {session.domain_name}
**Author:** {session.author}
**Date:** {session.created_at[:10]}

Competency questions define what the ontology must be able to answer.
Each question is converted to a SPARQL/SQL test query in Phase 3.

---

## Questions

| CQ-ID | Question | Priority | SPARQL status | Notes |
|---|---|---|---|---|
{table}

---

## How to add a question

1. Write the question in plain English
2. Identify which entities and relationships it requires
3. Sketch the graph path: EntityA → property → EntityB → property → EntityC
4. Add a row to the table above
5. Write the SPARQL test in `tests/sparql/{cq_id.lower()}.sparql`

---

*Generated by Ontology Toolkit onboarding wizard v1.2*
"""


# ── Session save/load ─────────────────────────────────────────────────────

def save_session(session: DomainSession, path: str):
    with open(path, "w") as f:
        json.dump(session.to_dict(), f, indent=2)
    print(f"  {green('✓')} Session saved → {dim(path)}")


def load_session(path: str) -> DomainSession:
    with open(path) as f:
        return DomainSession.from_dict(json.load(f))


# ── Write all artifacts ───────────────────────────────────────────────────

def write_artifacts(session: DomainSession):
    os.makedirs(session.out_dir, exist_ok=True)
    os.makedirs(os.path.join(session.out_dir, "db"), exist_ok=True)
    os.makedirs(os.path.join(session.out_dir, "docs"), exist_ok=True)
    os.makedirs(os.path.join(session.out_dir, "output"), exist_ok=True)

    artifacts = {
        os.path.join(session.out_dir, "db", "schema.sql"): generate_schema_sql(session),
        os.path.join(session.out_dir, "db", "seed.sql"):   generate_seed_sql(session),
        os.path.join(session.out_dir, "docs", "scope-charter.md"): generate_scope_charter(session),
        os.path.join(session.out_dir, "docs", "cq-catalog.md"):    generate_cq_catalog(session),
        os.path.join(session.out_dir, "session.json"):             json.dumps(session.to_dict(), indent=2),
    }

    for path, content in artifacts.items():
        with open(path, "w") as f:
            f.write(content)
        rel = os.path.relpath(path, HERE)
        print(f"  {green('✓')} {rel}")


# ── Run the pipeline ──────────────────────────────────────────────────────

def run_pipeline(session: DomainSession):
    section("Running the full pipeline")

    # Set up a minimal toolkit.py config pointing to the new project
    schema_path = os.path.join(session.out_dir, "db", "schema.sql")
    seed_path   = os.path.join(session.out_dir, "db", "seed.sql")
    db_path     = session.db_path
    out_path    = os.path.join(session.out_dir, "output")

    # Temporarily copy schema/seed to toolkit's db/ and run
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(schema_path) as f:
        conn.executescript(f.read())
    with open(seed_path) as f:
        conn.executescript(f.read())
    conn.close()
    print(f"  {green('✓')} Database initialised → {dim(db_path)}")

    # Run each pipeline phase using the toolkit
    toolkit_py = os.path.join(HERE, "toolkit.py")
    for phase in ["2", "3", "4", "5", "test", "report"]:
        result = subprocess.run(
            [sys.executable, toolkit_py,
             "--db", db_path,
             "--out", out_path,
             "--industry", session.domain_name,
             "--phase", phase],
            capture_output=True, text=True, cwd=HERE
        )
        lines = (result.stdout + result.stderr).strip().split("\n")
        for line in lines:
            if any(x in line for x in ["✓", "✗", "PASS", "FAIL", "ERROR", "complete", "Phase"]):
                print(f"  {line.strip()}")
        if result.returncode != 0:
            print(red(f"  Phase {phase} had errors — check output above."))

    print(f"\n  {green(bold('Pipeline complete!'))}")
    print(f"  Report: {dim(os.path.join(out_path, 'reports', 'toolkit_report.html'))}")
    print(f"  Ontology: {dim(os.path.join(out_path, 'ontology', 'enterprise.ttl'))}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ontology Toolkit — Onboarding Wizard"
    )
    parser.add_argument("--from",     dest="from_file", help="Load a saved session (JSON)")
    parser.add_argument("--industry", help=f"Pre-load an industry template: {', '.join(INDUSTRY_TEMPLATES.keys())}")
    parser.add_argument("--dry-run",  action="store_true", help="Generate artifacts without running the pipeline")
    args = parser.parse_args()

    banner()

    template = None
    session  = None

    # Load from saved session
    if args.from_file:
        print(f"  Loading session from {dim(args.from_file)} ...")
        session = load_session(args.from_file)
        print(f"  {green('✓')} Loaded: {session.domain_name}\n")
        if not confirm("  Run the pipeline with this session?", default=True):
            sys.exit(0)
        write_artifacts(session)
        if not args.dry_run:
            run_pipeline(session)
        return

    # Load industry template
    if args.industry:
        key = args.industry.lower()
        if key in INDUSTRY_TEMPLATES:
            template = INDUSTRY_TEMPLATES[key]
            print(f"  {green('✓')} Loaded {key} starter template.")
        else:
            print(red(f"  Unknown industry '{key}'. Available: {', '.join(INDUSTRY_TEMPLATES.keys())}"))
            sys.exit(1)

    # Interactive interview
    session = DomainSession()

    try:
        step_domain(session, template)
        step_entities(session, template)
        step_events(session, template)
        step_relationships(session, template)
        step_cqs(session, template)

        if not step_confirm(session):
            save_session(session, f"{session.domain_slug}_session.json")
            print(f"\n  Session saved. Resume later with: python3 onboard.py --from {session.domain_slug}_session.json")
            sys.exit(0)

    except KeyboardInterrupt:
        print(f"\n\n  {yellow('Interrupted.')} Saving partial session ...")
        if session.domain_slug:
            path = f"{session.domain_slug}_session.json"
            save_session(session, path)
            print(f"  Resume with: python3 onboard.py --from {path}")
        sys.exit(0)

    section("Generating artifacts")
    write_artifacts(session)
    save_session(session, os.path.join(session.out_dir, "session.json"))

    if not args.dry_run:
        run_pipeline(session)
    else:
        print(f"\n  {yellow('Dry run — pipeline skipped.')}")
        print(f"  Run manually: python3 toolkit.py --db {session.db_path} --out {session.out_dir}/output")

    print()
    print(bold(green("=" * 60)))
    print(bold(green("  Your ontology project is ready.")))
    print(bold(green("=" * 60)))
    print(f"""
  {bold('Next steps:')}

  1. Review and sign off the scope charter:
     {dim(os.path.join(session.out_dir, 'docs', 'scope-charter.md'))}

  2. Review the generated ontology:
     {dim(os.path.join(session.out_dir, 'output', 'ontology', 'enterprise.ttl'))}

  3. Add more entities or refine the model:
     {dim(f"python3 onboard.py --from {os.path.join(session.out_dir, 'session.json')}")}

  4. Validate governance score:
     {dim(os.path.join(session.out_dir, 'output', 'reports', 'toolkit_report.html'))}

  5. When ready for a production database:
     {dim(f"python3 toolkit.py --db postgresql://user:pass@host/mydb --out {os.path.join(session.out_dir, 'output')}")}
    """)


if __name__ == "__main__":
    main()
