# Import-from-file examples

End-to-end examples for the wizard's **Import from file** feature (issue #16). Drop any of these files on Step 1 of the browser wizard and watch the full loop — load → parse → validate → review → accept → generate ontology — without writing any SQL or OWL by hand.

## Files in this folder

| File | Format | What it demonstrates |
|---|---|---|
| [`smart_building.json`](smart_building.json) | wizard-session JSON | The happy path. Clean import: 0 errors, 0 warnings, 0 suggestions. Hydrates a complete Smart Building Operations domain ready to generate. |
| [`payments_schema.json`](payments_schema.json) | data-catalog / dbt-style JSON | A `{tables: [...]}` schema description. Triggers 2 warnings + 3 sensitivity suggestions + 1 description-wording suggestion. |
| [`retail_orders.sql`](retail_orders.sql) | Postgres pg_dump-style SQL | The full SQL feature set: `ALTER TABLE` foreign keys, `COMMENT ON TABLE/COLUMN`, line + block comments, PII-named columns, an event-shaped table, a soft FK, and 4 description-wording suggestions for un-commented columns. |

## Run the wizard

From the repo root:

```bash
pip install -r requirements.txt        # one-time
python3 wizard/app.py                  # serves on http://localhost:5000
```

Open `http://localhost:5000` in your browser. You're on Step 1 (Domain Identity).

## Walkthrough — the SQL example

This is the most complete demo because it exercises every step of the importer pipeline. The two JSON files follow the same flow.

### 1. Drop the file

On the **Import from file** card, drag [`retail_orders.sql`](retail_orders.sql) onto the dashed area (or click to browse). The Import Review modal opens.

### 2. Read the Summary tab

```
domain:    Retail Orders
industry:  finance (or whatever you set)
entities:  2  (customer, orders)
events:    1  (order_event_log — auto-classified by the _log suffix)
relationships: 1  (orders → references → customer)
CQs:       0
description coverage: ~50 %
```

Plus a diff against your current wizard session ("added: 2E / 1V · removed: …") and a one-paragraph "what happens on Accept" recap.

### 3. Errors tab (0)

The file parses cleanly. No blockers.

### 4. Warnings tab (2)

| Code | Why |
|---|---|
| `MISSING_BASE_IRI` | Schema files don't carry an IRI; you'll set one on Step 1 after import. |
| `NO_CQS` | No competency questions inferred from a SQL dump. Add them on Step 5 before generating. |

Warnings don't block — Accept is still available. The footer status reads:

> 2 warnings — import is allowed; quality may be lower than ideal.

### 5. Suggestions tab (8) — interactive

Each row has Accept / Reject buttons. Try **Accept all pending** to apply every fix at once.

| Code | Suggestion | What "Accept" does |
|---|---|---|
| `SUGGEST_PROPERTY_SENSITIVITY` | `customer.email` looks like Confidential-tier data. | Sets `entities[customer].properties[email].sensitivity = "Confidential"`. |
| `SUGGEST_PROPERTY_SENSITIVITY` | `customer.dob` looks like Confidential-tier data. | Same, on `dob`. |
| `SUGGEST_PROPERTY_SENSITIVITY` | `customer.password_hash` looks like Restricted-tier data. | Sets to `"Restricted"`. |
| `SUGGEST_SOFT_FK` | `order_event_log.order_id` looks like a foreign key to `orders`. Confidence 0.75 — plural-form match. | Adds a relationship `Order Event Log → references → Orders` to the session. |
| `SUGGEST_DESCRIPTION` × 4 | Un-commented columns get heuristic wording (e.g. *"Surrogate identifier for the customer."* for `customer.id`, *"Timestamp at which this customer was created (UTC)."* for `created_at`). | Sets `entities[i].properties[j].description = "<suggested text>"`. |

Accepted rows go green and dim out; rejected rows strike-through. The Summary stat counts refresh in real time.

### 6. Preview tab

Shows the in-memory normalised session as JSON, including any accepted suggestions. Use this to verify what will land on disk before you click Accept.

### 7. Click "Accept & replace session"

The wizard:
1. Re-validates the session server-side (final guard — refuses to commit if errors slipped in).
2. Persists the normalised session to disk.
3. Closes the modal, refreshes the wizard, jumps you to **Step 2 (Entities)** with everything pre-filled.
4. Toast: *"Imported 2 entities · 1 events · 2 relationships"*.

### 8. Refine on Steps 2–5 (optional)

- **Step 1**: set the Base IRI (e.g. `https://ontology.example.com/retail/`).
- **Step 2 (Entities)**: edit the auto-imported entities, change descriptions, tweak sensitivity tiers.
- **Step 4 (Relationships)**: open the Graph tab to visualise the topology — orphan entities and missing back-edges become obvious.
- **Step 5 (CQs)**: add the questions your ontology must answer (drives the SPARQL test suite + governance scorecard).

### 9. Generate the ontology

On **Step 6 (Generate)**, the Pre-flight check shows ✓ for required items (domain name, ≥1 entity) and ⚠ for any recommended ones still missing. Click **Run Pipeline**. ~3 seconds later you have:

```
projects/<your_domain>/output/
├── ontology/
│   ├── enterprise.ttl              # OWL 2 ontology
│   ├── events.ttl                  # event subclass hierarchy
│   └── provenance.ttl              # PROV-O patterns
├── shapes/
│   ├── enterprise-shapes.ttl       # SHACL NodeShapes (one per entity)
│   └── agent-gate.ttl
├── jsonld/
│   └── enterprise-context.json     # JSON-LD context
├── vocab/
│   └── enterprise-skos.ttl
├── mapping/
│   └── logical_physical_map.csv    # OWL class → table → column traceability
└── reports/
    ├── toolkit_report.html         # ← open this first
    ├── governance_scorecard.csv
    └── sparql_cq_test_results.csv
```

## Walkthrough — the JSON examples

### `smart_building.json` (wizard-session shape)

The cleanest possible import. Every field already populated, every entity described, every relationship structured. The review modal opens with **0 errors, 0 warnings, 0 suggestions** — Accept lands you straight on Step 2 with a 6-entity, 2-event, 6-relationship, 5-CQ Smart Building Operations domain ready to generate.

Use this file as a template when authoring sessions by hand for users who want to skip the wizard entirely (`onboard.py --from examples/import/smart_building.json` also works).

### `payments_schema.json` (data-catalog shape)

A thin `{tables: [...]}` description — the shape that data-catalog tools (dbt, Atlan, OpenMetadata) export and that OpenAPI / JSON-Schema converters produce. The importer:

1. Detects the `tables` key → switches to schema-mode parsing.
2. Walks each table → entity (or event by `_log` / `_event` suffix).
3. Walks each column → property with type + description.
4. Walks each declared `foreign_keys` → relationship.

You'll see the same kind of suggestions tab as the SQL example, plus the warnings about missing IRI and CQs.

> **Note:** soft-FK suggestions only fire on the SQL import path. For JSON schemas, foreign keys must be declared explicitly in the `foreign_keys` array — name-based heuristics aren't run. (This is a design choice — JSON tooling that emits this shape usually has FK info available, so guessing produces noise.)

## Validation tier reference

What every import is checked against, per [the issue #16 design](../../docs/integrate.md):

### Errors — block

| Code | Meaning |
|---|---|
| `INVALID_JSON` / `ENCODING` / `ROOT_NOT_OBJECT` | File can't be parsed at all. |
| `MISSING_DOMAIN_NAME` | No `domain.name` — required for OWL IRI namespace. |
| `NO_ENTITIES` | Empty entity list — the resulting ontology would be empty. |
| `DUPLICATE_ENTITY` | Two entities share the same label. |
| `UNSAFE_ENTITY_NAME` | Name contains characters not safe inside an IRI. |
| `REL_BAD_ENDPOINT` | Relationship references an entity that isn't defined. |
| `SQL_PARSE` / `NO_TABLES` / `SQLGLOT_MISSING` | SQL-only — file unparseable / no `CREATE TABLE` / sqlglot not installed. |

### Warnings — advisory

| Code | Meaning |
|---|---|
| `MISSING_BASE_IRI` | The toolkit will pick a default; you should set a stable one. |
| `NO_CQS` | No competency questions — the governance scorecard will be weak. |
| `NO_RELATIONSHIPS` | Multiple entities but no relationships — unconnected graph. |
| `ENTITY_NO_DESCRIPTION` | The LLM grounding step uses descriptions verbatim — empty = guessing. |
| `ORPHAN_ENTITY` | Entity has no incoming or outgoing relationships. |

### Suggestions — opt-in (per-row Accept / Reject)

| Code | Carries `apply` payload that does this |
|---|---|
| `SUGGEST_SENSITIVITY` | Sets entity sensitivity tier from PII-shaped name. |
| `SUGGEST_PROPERTY_SENSITIVITY` | Sets property sensitivity tier. |
| `SUGGEST_EVENT` | Moves a non-event entity into the events list. |
| `SUGGEST_DESCRIPTION` | Sets a heuristic wording for any column with no description (uses suffix patterns: `_id` → identifier, `_at` → timestamp, `_amount` → monetary, etc.). |
| `SUGGEST_SOFT_FK` (SQL only) | Adds a relationship from a name-only FK match (confidence 0.60–0.85). |

## API direct (no browser)

For automation, the `/api/import` route works without the wizard UI. Same validation, same response shape:

```bash
curl -F file=@examples/import/retail_orders.sql \
     -F format=auto \
     http://localhost:5000/api/import
```

Returns the structured `{session, errors, warnings, suggestions, stats, diff, format, ok}` payload. Persist with:

```bash
curl -X POST -H 'Content-Type: application/json' \
     -d '{"session": <the session object from /api/import>}' \
     http://localhost:5000/api/import/commit
```

Both routes refuse to persist if errors are present — same final-guard logic the modal applies.

## Where the test fixtures live

Lower-level fixtures (one per code path, used by `pytest`) live under [`tests/fixtures/import/`](../../tests/fixtures/import/) — minimal files designed to exercise specific validation codes. The files in *this* folder are richer, fully-annotated examples meant to be **read** by a user trying to understand the importer end-to-end.
