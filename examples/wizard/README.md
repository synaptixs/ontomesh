# Wizard demo — Smart Building Operations

End-to-end walkthrough of the **onboarding wizard** producing a production-ready ontology from a plain-language domain description. Uses the wizard's own session format — no SQL, no OWL knowledge, no metadata table editing required.

## Why this example exists

The toolkit's two strongest adoption paths are the wizards (CLI `onboard.py` and browser `wizard/app.py`). Both walk a six-step interview — domain identity, entities, events, relationships, competency questions, review — and produce:

- a working SQLite schema with `ontology_metadata` annotations,
- a competency question catalog,
- the full OWL ontology + SHACL shapes + JSON-LD context + HTML report.

This demo runs that flow non-interactively against a pre-built session for a domain the toolkit doesn't ship as a starter — **Smart Building Operations** — to show the wizard is genuinely domain-agnostic and produces a non-trivial ontology in one command.

## What domain is modelled

A portfolio of commercial smart buildings: real-time sensing, HVAC control, occupancy tracking, access management, and maintenance ticketing.

| Type | Things |
|---|---|
| Business entities (7) | Building · Floor · Room · Sensor · HVAC Unit · Tenant · Access Card |
| Event types (5) | Temperature Reading · Occupancy Event · Access Event · Maintenance Ticket · Alert |
| Relationships (11) | e.g. `Sensor installed in Room`, `HVAC Unit serves Floor`, `Tenant occupies Room`, `Maintenance Ticket raised against HVAC Unit`, `Alert triggered by Sensor` |
| Competency questions (8) | "Which HVAC units have open critical maintenance tickets?" · "Which access cards were used to enter restricted rooms outside business hours?" · 6 more |

The full domain definition is in [`smart_building_session.json`](smart_building_session.json) — the same JSON the wizard saves at the end of an interactive session, so this file is also a worked example of the session schema.

## Run it

From the repo root:

```bash
./examples/wizard/demo_wizard.sh           # full flow: generate + run pipeline
./examples/wizard/demo_wizard.sh --dry-run # generate skeleton only, skip pipeline
./examples/wizard/demo_wizard.sh --fresh   # wipe projects/smart_building first
./examples/wizard/demo_wizard.sh --browser # generate, then start the browser wizard
```

Prerequisites: just the core install (`pip install -r requirements-core.txt`). No API keys, no LLM, no Flask unless you use `--browser`.

## What the demo does

1. **Loads** [`smart_building_session.json`](smart_building_session.json) — the saved wizard state for the Smart Building domain.
2. **Generates the project skeleton** under `projects/smart_building/`:
   - `db/schema.sql` — relational schema with one table per entity, FK columns inferred from the relationships, plus the `ontology_metadata` and `semantic_loss_log` system tables.
   - `db/seed.sql` — `ontology_metadata` rows pre-populated from your wizard answers (semantic class, label, description, sensitivity tier, event flag).
   - `docs/scope-charter.md` — auto-generated scope charter listing entities, events, relationships, CQs, and a stakeholder sign-off table.
   - `docs/cq-catalog.md` — competency question catalog with SPARQL placeholder slots for each CQ.
   - `session.json` — resumable wizard state.
3. **Runs the toolkit pipeline** against the generated DB, producing:
   - `output/ontology/enterprise.ttl` — OWL 2 ontology (31 classes/properties for this domain).
   - `output/shapes/enterprise-shapes.ttl` — SHACL NodeShapes (16 shapes).
   - `output/jsonld/enterprise-context.json` — canonical JSON-LD context.
   - `output/reports/toolkit_report.html` — visual run report.

## Inspect what you got

```bash
# OWL classes (one per entity + one per event)
grep "a owl:Class" projects/smart_building/output/ontology/enterprise.ttl

# Object properties (one per relationship)
grep "a owl:ObjectProperty" projects/smart_building/output/ontology/enterprise.ttl

# SHACL shapes
grep "a sh:NodeShape" projects/smart_building/output/shapes/enterprise-shapes.ttl

# Open the visual report
open projects/smart_building/output/reports/toolkit_report.html
```

## Modify the domain and re-run

Edit [`smart_building_session.json`](smart_building_session.json) — add an entity, change a relationship, append a new CQ — then re-run with `--fresh`. The whole pipeline regenerates in seconds, no manual SQL writing.

You can also resume the session in the wizards:

```bash
# CLI wizard — interactive review and edit
python3 onboard.py --from examples/wizard/smart_building_session.json

# Browser wizard — drag-and-drop, click "Generate" when done
python3 wizard/app.py
# then load examples/wizard/smart_building_session.json from the Templates tab
```

## Build your own domain in 5 minutes

The wizard runs identically against any domain — the only difference is the answers you give in the six steps. Two ways to start:

```bash
# CLI: free-form interview
python3 onboard.py

# CLI with industry starter (telecom / healthcare / finance / manufacturing / retail)
python3 onboard.py --industry telecom

# CLI with LLM auto-suggestion of entities/events/relationships/CQs
ANTHROPIC_API_KEY=... python3 onboard.py --llm

# Browser: same interview in a web UI
python3 wizard/app.py
```

The session file you produce works exactly like `smart_building_session.json` — runnable with the demo script above, editable by hand, resumable in either wizard.

## Where to go next

- [docs/integrate.md](../../docs/integrate.md) — the 5-minute integration recipe.
- [docs/metadata.md](../../docs/metadata.md) — what each `ontology_metadata` field controls (the wizard hides this; this doc explains it).
- [docs/artifacts.md](../../docs/artifacts.md) — what every generated file is for.
- [examples/retail/](../retail/) — comparing ontology-grounded vs. baseline LLM answers on the wizard-style schema.
