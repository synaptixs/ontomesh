# Demo Test Plan — Ontology vs No-Ontology LLM Output

**Purpose.** Demonstrate, side-by-side, the difference in answer quality, semantic precision, and auditability when an LLM is asked the same question (a) directly over raw SQLite rows and (b) through the toolkit's runtime layer with a generated OWL ontology, SHACL shapes, JSON-LD grounding, and PROV-O output stamping.

**Audience.** Demo viewers — architects, data leaders, governance teams.

**Models under test.** Anthropic `claude-sonnet-4-5` · OpenAI `gpt-4o`. Same prompt, same data, same question in every row of the comparison matrix.

---

## 1. Scope

**In scope**

- A small retail schema in SQLite (7 tables, ~50 rows of seed data) with well-defined foreign keys, state-machine columns, and an event table.
- Toolkit pipeline run end-to-end against that SQLite file: Phases 1–5 + TMF-skip + test + report.
- Two runtime configurations per question:
  - **Baseline (no ontology)** — raw SQL rows serialised to JSON and pasted into a plain LLM prompt.
  - **Ontology-grounded** — same records grounded through `RuntimeClient.ask()` with JSON-LD context, SHACL input gate, payload assembly, and SHACL output gate.
- Two LLM vendors: Anthropic and OpenAI.

**Out of scope**

- Cross-enterprise federation, vector retrieval, memory consolidation (those have their own CQ tests — see [gates.md](gates.md)).
- Performance benchmarking beyond wall-clock per call.
- Production deployment.

---

## 2. Success criteria

The demo is considered successful when, for every question in the bank and for both vendors:

| Criterion | Baseline | Ontology-grounded |
|---|---|---|
| Answer references the correct OWL class by name | not required | **required** |
| Every entity reference carries a stable IRI | not required | **required** |
| Output validated by SHACL shape | not required | **required — `valid=True`** |
| Output stamped with PROV-O (model, timestamp, confidence) | absent | **required** |
| Answer is stored as an `ObservationRecord` in the DB | no | **yes** |
| Field-name ambiguity correctly disambiguated | inconsistent | **deterministic** |

At least **3 of 8** questions must produce *materially different* answers between baseline and ontology-grounded modes for the demo to have a teaching moment.

---

## 3. Test environment

| Item | Value |
|---|---|
| OS | macOS 14+ / Linux |
| Python | 3.10+ |
| DB | SQLite 3 (bundled with Python) |
| Toolkit branch | `first-contact` |
| LLM deps | `pip install anthropic openai` |
| Env vars | `ANTHROPIC_API_KEY` · `OPENAI_API_KEY` |
| Output dir | `output/demo/` |

---

## 4. Retail demo schema

A small, self-explanatory retail schema. Seven tables, one event table, one status-driven lifecycle, one provenance-rich observation table, deliberate room for semantic ambiguity (e.g. `status` appears on `customers`, `orders`, `payments`).

```
customers ─┐
           ├─ orders ─── order_items ── products
           │     │
           │     └─ shipments
           │
           └─ payments ─── invoices
                               │
                          order_events  (event table — lifecycle transitions)
```

### 4.1 DDL — `db/demo.sql`

```sql
-- System tables the toolkit needs (DDL from db/schema.sql; truncated here)
CREATE TABLE ontology_metadata (...);
CREATE TABLE semantic_loss_log (...);

-- Domain tables
CREATE TABLE customers (
    id             INTEGER PRIMARY KEY,
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    status         TEXT CHECK (status IN ('Active','Suspended','Closed')) NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE products (
    id             INTEGER PRIMARY KEY,
    sku            TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    unit_price     REAL NOT NULL,
    category       TEXT NOT NULL
);

CREATE TABLE orders (
    id             INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(id),
    placed_at      TEXT NOT NULL,
    status         TEXT CHECK (status IN ('Pending','Confirmed','Shipped','Delivered','Cancelled')) NOT NULL,
    total_amount   REAL NOT NULL
);

CREATE TABLE order_items (
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    product_id     INTEGER NOT NULL REFERENCES products(id),
    quantity       INTEGER NOT NULL,
    line_total     REAL NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE invoices (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    issued_at      TEXT NOT NULL,
    due_at         TEXT NOT NULL,
    amount_due     REAL NOT NULL,
    status         TEXT CHECK (status IN ('Open','Paid','Overdue','Disputed')) NOT NULL
);

CREATE TABLE payments (
    id             INTEGER PRIMARY KEY,
    invoice_id     INTEGER NOT NULL REFERENCES invoices(id),
    paid_at        TEXT NOT NULL,
    amount         REAL NOT NULL,
    method         TEXT CHECK (method IN ('CARD','BANK','WALLET')) NOT NULL,
    status         TEXT CHECK (status IN ('Cleared','Pending','Reversed')) NOT NULL
);

CREATE TABLE shipments (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    shipped_at     TEXT,
    delivered_at   TEXT,
    carrier        TEXT NOT NULL,
    tracking_ref   TEXT NOT NULL UNIQUE
);

-- Event table — lifecycle transitions (drives STATUS_AS_EVENT detection + event OWL subclasses)
CREATE TABLE order_events (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    event_type     TEXT CHECK (event_type IN ('PLACED','CONFIRMED','SHIPPED','DELIVERED','CANCELLED','REFUNDED')) NOT NULL,
    occurred_at    TEXT NOT NULL,
    actor_party    TEXT,
    confidence     REAL CHECK (confidence BETWEEN 0.0 AND 1.0),
    derivation     TEXT CHECK (derivation IN ('MEASURED','INFERRED','IMPORTED','SYNTHESIZED'))
);
```

### 4.2 Seed — `db/demo_seed.sql`

Populate with ~50 rows across the 7 tables: 10 customers, 12 products, 15 orders (mixed statuses), 30 order items, 15 invoices (some Paid / Overdue / Disputed), 12 payments, 8 shipments, and 25 order events spanning the lifecycle. Include one Disputed invoice with a Reversed payment and one Cancelled order with no shipment — those are the interesting edge cases the ontology will surface.

### 4.3 Ontology metadata seed

Annotate every table and every key column in `ontology_metadata`:

| target | table | column | semantic_type | sensitivity | notes |
|---|---|---|---|---|---|
| TABLE | customers | — | Customer | Confidential | Party role |
| TABLE | products | — | Product | Public | |
| TABLE | orders | — | Order | Internal | |
| TABLE | order_items | — | OrderLine | Internal | |
| TABLE | invoices | — | Invoice | Confidential | |
| TABLE | payments | — | Payment | Restricted | PII-adjacent |
| TABLE | shipments | — | Shipment | Internal | |
| TABLE | order_events | — | OrderEvent | Internal | `is_event_class=1` |
| COLUMN | order_events | event_type | event discriminator | — | triggers OWL subclass generation |
| COLUMN | order_events | confidence | xsd:decimal | — | PROV-O confidence |
| COLUMN | order_events | derivation | xsd:string | — | MEASURED/INFERRED/IMPORTED/SYNTHESIZED |

---

## 5. Phases

### Phase 1 — Build the database

```bash
sqlite3 db/demo.db < db/demo.sql
sqlite3 db/demo.db < db/demo_seed.sql
sqlite3 db/demo.db "SELECT COUNT(*) FROM orders;"   # sanity: 15
```

**Expected:** `db/demo.db` exists, all 7 tables populated, `ontology_metadata` has ≥20 rows.

### Phase 2 — Generate the ontology

```bash
python3 toolkit.py --db db/demo.db --out output/demo/
open output/demo/reports/toolkit_report.html
```

**Expected artifacts in `output/demo/`:**

- `ontology/enterprise.ttl` — 8 OWL classes, FK→object-property mapping
- `ontology/events.ttl` — 6 `OrderEvent` subclasses (one per `event_type` value)
- `ontology/provenance.ttl` — PROV-O patterns
- `shapes/enterprise-shapes.ttl` — 8 NodeShapes, ~60 constraints
- `shapes/agent-gate.ttl` — runtime acceptance gate
- `jsonld/enterprise-context.json` — term-to-IRI bindings
- `vocab/enterprise-skos.ttl` — SKOS for every status enumeration
- `mapping/semantic_loss_report.csv` — expected findings:
  - `FLOATING_VALUE` on `payments.amount` (no confidence score) — MEDIUM
  - `STATUS_AS_EVENT` on `customers.status` (status without event table) — HIGH
  - `IMPLICIT_ACTOR` on `order_events` (no FK to party) — CRITICAL

**Governance scorecard target:** ≥ 3.5 / 5.0 on first run, ≥ 4.0 after resolving the CRITICAL finding.

### Phase 3 — Build the question bank

Eight questions, chosen so three are semantically ambiguous, three require event/lifecycle reasoning, and two require provenance:

| # | Question | Why it exposes the ontology delta |
|---|---|---|
| Q1 | *"Which customers are Active?"* | `status="Active"` exists on 3 tables — baseline guesses which one |
| Q2 | *"Show me overdue invoices and the customers who owe them."* | Two-hop join (invoice → order → customer) — baseline often omits the customer entity |
| Q3 | *"Which orders never reached the Delivered state?"* | Needs the event table, not the `orders.status` column — baseline conflates the two |
| Q4 | *"Are there any disputed invoices with reversed payments?"* | State-machine intersection across two tables |
| Q5 | *"What is the full customer-to-payment traceability chain for order 7?"* | Exercises FK→object-property chaining, JSON-LD `@id` linking |
| Q6 | *"Which cancellation events were inferred rather than measured?"* | Requires PROV-O `derivation` — baseline has no vocabulary for this |
| Q7 | *"List active orders whose shipment is missing."* | Ambiguity between order status and shipment status |
| Q8 | *"Summarise this customer's standing in one sentence."* | Free-form — tests whether grounded output remains structurally valid |

### Phase 4 — Run baseline (no ontology)

For each question × each model:

```python
# baseline.py  (see scripts/demo_baseline.py)
import anthropic, openai, sqlite3, json

# 1. Dump relevant rows as plain JSON
rows = sqlite3.connect("db/demo.db").execute(
    "SELECT * FROM customers LIMIT 50"
).fetchall()
context = json.dumps([dict(r) for r in rows])

# 2. Plain-prompt LLM — no ontology, no SHACL, no PROV-O
prompt = f"""
You are a helpful analyst. Data:
{context}

Question: Which customers are Active?
"""

# Call Anthropic + OpenAI, save to output/demo/baseline_{model}_{q}.json
```

Record: raw answer text, wall-clock, token counts. No validation, no provenance.

### Phase 5 — Run ontology-grounded

```python
# grounded.py  (see scripts/demo_grounded.py)
from runtime.client import RuntimeClient

for vendor, model in [("anthropic","claude-sonnet-4-5"),
                      ("openai","gpt-4o")]:
    client = RuntimeClient(db_path="db/demo.db",
                           adapter=vendor, model=model)
    for q in QUESTIONS:
        result = client.ask(question=q.text,
                            flavor="retail",       # auto-generated from sid_domain groupings
                            output_format="json")
        save(result, f"output/demo/grounded_{vendor}_{q.id}.json")
```

Each `result` contains `answer`, `valid` (SHACL output-gate pass), `observation_iri`, and `prov` (model + timestamp + confidence + derivation_method).

### Phase 6 — Build the comparison report

For each of the 32 cells (8 questions × 2 vendors × 2 modes), render a side-by-side table:

| Question | Vendor | Baseline answer | Grounded answer | SHACL valid | PROV stamped | Δ notes |
|---|---|---|---|---|---|---|
| Q1 | Anthropic | … | … | ✓ | ✓ | e.g. baseline returned all "Active" rows across three tables; grounded returned only Customer-class |
| … | | | | | | |

Write results to:

- `output/demo/comparison.csv`
- `output/demo/comparison.html` (self-contained, open in a browser)

---

## 6. Comparison axes

1. **Semantic precision** — did the answer name the right OWL class?
2. **IRI stability** — can every named entity be clicked through to a stable IRI?
3. **Structural validity** — does the output pass SHACL shape validation?
4. **Auditability** — is there a PROV-O chain (model, timestamp, confidence, derivation)?
5. **Cross-vendor consistency** — do Anthropic and OpenAI give *equivalent* grounded answers (IRIs, class names)? Baseline answers typically do not.
6. **Error surface** — how do the two modes behave when the question is under-specified? (Grounded should fail shape validation; baseline will hallucinate.)

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM API rate limits during a live demo | Pre-run Phase 4 + 5, cache outputs to disk, play back from `output/demo/` |
| A model refuses a PII-adjacent question | `payments` is marked `Restricted`; the `retail` flavor excludes it by default — demonstrates sensitivity-tier enforcement |
| SHACL shapes reject a well-formed answer | Keep one negative-case question to *intentionally* fail and show rollback behavior |
| Vendor output schema differences | All adapter outputs are normalised by `OutputGate` before comparison |
| Non-deterministic LLM output | Seed + low temperature (0.2); run each call 3× and report modal answer |

---

## 8. Deliverables

| Artefact | Path |
|---|---|
| DDL + seed | `db/demo.sql` · `db/demo_seed.sql` |
| Generated ontology | `output/demo/ontology/*.ttl` |
| SHACL shapes | `output/demo/shapes/*.ttl` |
| JSON-LD context | `output/demo/jsonld/enterprise-context.json` |
| Baseline LLM outputs | `output/demo/baseline_{vendor}_{qid}.json` |
| Grounded LLM outputs | `output/demo/grounded_{vendor}_{qid}.json` |
| Side-by-side report | `output/demo/comparison.html` · `output/demo/comparison.csv` |
| Demo script | `scripts/demo_baseline.py` · `scripts/demo_grounded.py` · `scripts/demo_report.py` |
| This test plan | [test-plan.md](test-plan.md) · [test-plan.html](test-plan.html) |

---

## 9. Demo narrative (5-minute version)

1. **30 s — The data.** Show the SQLite DB. Seven tables, one event table. Point out that `status` appears on three tables.
2. **60 s — The toolkit.** Run `python3 toolkit.py --db db/demo.db`. Open `toolkit_report.html`. Walk through the OWL hierarchy, SHACL shapes, and the `semantic_loss_report.csv` findings.
3. **90 s — Baseline.** Paste Q1, Q3, Q6 into each model. Note the inconsistency across vendors and the hallucination on Q6 ("inferred" has no grounding anywhere in the raw rows).
4. **90 s — Grounded.** Run the same three questions through `RuntimeClient.ask(flavor="retail")`. Show identical OWL class names and IRIs from both vendors. Open the stored `ObservationRecord` in SQLite — it has `prov:wasGeneratedBy`, `generatedAtTime`, `confidence`, and `derivation`.
5. **30 s — The takeaway.** The raw-rows prompt is a guess. The grounded prompt is an auditable, governed enterprise fact.

---

*Branch: `first-contact` · Toolkit: v2.0*
