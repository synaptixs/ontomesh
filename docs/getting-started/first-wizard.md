# Your first wizard run — guided walkthrough

This is a longer, narrated version of the [Quickstart](quickstart.md). Where the quickstart hands you commands, this page explains *why* each step exists.

!!! tip "Use the **Telecom** starter"

    It's the largest, most opinionated starter and exercises every wizard surface. Other starters work the same way with smaller catalogues.

## Step 1 — Domain

You're declaring **what you're modelling** and how sensitive it is.

The four fields:

- **Domain** — telecom / healthcare / finance / etc.  Drives default sensitivity tier and which compliance frame the wizard pre-loads.
- **Sub-domain** — e.g. "customer experience" inside telecom.  Used as the namespace prefix.
- **Sensitivity tier** (1–5) — 1 = public, 5 = restricted PII.  Every class inherits this default; you can override per-class later.
- **Compliance frame** — GDPR / HIPAA / DORA / ISO 27001 / TMF.  Pre-loads SHACL shapes that enforce that frame's constraints.

## Step 2 — Entities

The seed catalogue from your starter is shown as a grid.  Each entity card lets you:

- Edit `rdfs:label`, `rdfs:comment`, `:sensitivityTier`.
- Add properties (string, integer, IRI reference, …).
- Mark the entity as the **subject** or **target** of standard relationships.

Click **Add entity** to introduce a new one. The wizard auto-generates an IRI matching the namespace.

## Step 3 — Events

Events represent **changes** to entities — order placed, alarm raised, payment cleared.

Each event needs:

- A **trigger entity** (the entity that emitted the event).
- A **lifecycle phase** (created / modified / retired / archived).
- An optional **payload schema** referenced from your competency questions.

## Step 4 — Relationships

The wizard renders the entity graph as nodes and lets you draw OWL object-property edges between them.

Each edge becomes an `owl:ObjectProperty` with `rdfs:domain` and `rdfs:range`. Cardinality and inverse relationships are configured per edge.

## Step 5 — Log discovery (optional)

Paste 100–10,000 representative log lines. The wizard runs the Drain3 template-clustering algorithm and surfaces the templates with the highest entity-extraction yield — typically you'll find 5–15 templates that mention real entity names in your domain.

You can accept the inferred entity → log-template mappings or skip this step entirely.

## Step 6 — Competency questions

Capture the questions the ontology must answer. Each CQ is graded by priority (must / should / nice) and linked to the entities + events that answer it.

The wizard auto-generates a `cq_<domain>.csv` report and (when `[runtime]` is installed) translates each CQ to executable SPARQL.

## Step 7 — Rules

For SWRL / Datalog enrichment. Optional but powerful.

The seed starters ship with 3–8 rules each as examples (e.g. *"if Order is in PartiallyAllocated state for >24h, mark for Review"*).

## Step 8 — Generate

The big button. Materialises:

- `output/ontology/<domain>.ttl` — OWL Turtle
- `output/ontology/<domain>-inferred.ttl` — OWL-RL materialised
- `output/shapes/<domain>.shacl` — SHACL shapes
- `output/jsonld/<domain>.jsonld` — JSON-LD context for runtime
- `output/skos/<domain>-vocab.ttl` — SKOS controlled vocabulary
- `output/reports/materialisation_report.md`

## Step 9 — Evolution review

Shows diff against the previous saved version. Drift signals (drift-monitor or imported observation traces) are mapped to specific classes; the wizard suggests evolutions ranked by impact.

## Step 10 — Compliance

Runs your compliance frame's checklist against the generated ontology. Surfaces missing alignments and proposes fixes.

## Step 11 — Vector retrieval

Builds a hybrid retriever (BM25 + dense embeddings) over the ontology's labels, comments, and SKOS broader/narrower terms. Indexed into FAISS or Chroma.

Test queries are run against your competency questions and a precision/recall table is shown.

## What's saved when

The wizard auto-saves to `<data-dir>/ontologies.db` after every step. You can leave at any point and pick up via the [project dashboard](http://localhost:5051/projects).

## Where to next

- [Concepts → Pipeline phases](../concepts/pipeline.md) — what each `--phase` flag does under the hood.
- [Reference → SDK](../sdk.md) — drive the same flow from Python instead of the UI.
