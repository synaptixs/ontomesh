# Integration guide — get value in 5 minutes, not 5 days

The shortest path from *clone the repo* to *running ontology against your data*. If you read nothing else in this repository, read this. Deeper reference lives in [install.md](../install.md), [features.md](../features.md), and [gates.md](../gates.md).

## Contents

1. [5-minute SQLite path](#5-minute-sqlite-path)
2. [30-minute existing-database path](#30-minute-existing-database-path)
3. [What you actually got](#what-you-actually-got)
4. [Adding LLMs / drift / federation later](#adding-llms--drift--federation-later)
5. [You probably don't need (yet)](#you-probably-dont-need-yet)

---

## 5-minute SQLite path

Three commands, one bundled SQLite database, no API keys, no driver compiles.

```bash
# 1. Clone + minimum dependencies (~50 MB, no compile)
git clone https://github.com/nrohilla-fibonacci/ontology.git
cd ontology
pip install -r requirements-core.txt

# 2. Run the full pipeline against the bundled retail demo DB
python3 toolkit.py --db db/demo.db --out output/demo

# 3. Open the report
open output/demo/reports/toolkit_report.html
```

That's it. You now have a working OWL ontology, SHACL shapes, JSON-LD context, mapping workbook, and a governance scorecard — all under `output/demo/`. Skim the HTML report and you've seen everything the pipeline produces.

To use your own SQLite file, swap in its path. Nothing else changes.

---

## 30-minute existing-database path

For PostgreSQL, MySQL, SQL Server, Oracle, or DB2.

### Step 1 — install the right driver only

```bash
pip install -r requirements-core.txt
pip install psycopg2-binary          # or mysql-connector-python / pyodbc / oracledb / ibm_db
```

### Step 2 — add two system tables

The toolkit needs a small **annotation control plane** in your DB. Two tables, one-time setup, *no changes to your existing tables*:

```sql
-- copy from db/schema.sql (the relevant CREATE TABLE statements)
CREATE TABLE ontology_metadata (
    table_name      TEXT NOT NULL,
    column_name     TEXT,
    semantic_class  TEXT,        -- e.g. 'Customer', 'Order', 'NetworkFunction'
    business_term   TEXT,        -- plain-language meaning of this column
    sensitivity     TEXT,        -- Public | Internal | Confidential | Restricted
    -- ...other optional columns; see db/schema.sql for the full list
    PRIMARY KEY (table_name, column_name)
);

CREATE TABLE semantic_loss_log (
    finding_id      TEXT PRIMARY KEY,
    severity        TEXT,        -- info | warn | error
    description     TEXT,
    captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Step 3 — annotate the columns that matter

You don't need to annotate every column. The minimum that produces a useful ontology is:

- **One row per important table** with a `semantic_class` (e.g. `Customer`, `Order`).
- **One row per primary key column** so it becomes the identifier.
- **Sensitivity tier** on any PII or restricted column.

Skip everything else on day 1. Re-run the pipeline and refine over time.

```sql
INSERT INTO ontology_metadata (table_name, column_name, semantic_class, business_term, sensitivity) VALUES
  ('orders',    NULL,          'Order',    'A customer purchase',                'Internal'),
  ('orders',    'id',          'Order',    'Order identifier',                   'Internal'),
  ('orders',    'customer_id', 'Customer', 'Foreign key to the placing customer','Internal'),
  ('customers', NULL,          'Customer', 'A person or organisation',           'Confidential'),
  ('customers', 'email',       'Customer', 'Primary contact address',            'Confidential');
```

### Step 4 — run the pipeline

```bash
python3 toolkit.py --db "postgresql://user:pass@host/mydb" --out output/
open output/reports/toolkit_report.html
```

If you'd rather start from a wizard with no SQL writing, see [install.md §2](../install.md#2-onboarding--start-a-new-project).

---

## What you actually got

After `output/` is populated, three files matter on day 1:

| File | Why you care |
|---|---|
| `output/reports/toolkit_report.html` | One-page visual run summary — open this first |
| `output/ontology/enterprise.ttl` | The OWL 2 ontology you can hand to any RDF tool, reasoner, or graph store |
| `output/jsonld/enterprise-context.json` | The JSON-LD context used by every downstream agent payload |

Everything else (SHACL shapes, SKOS vocab, mapping workbook, MCP tool definitions) is real value but not required to evaluate the toolkit's output.

---

## Adding LLMs / drift / federation later

These are **opt-in**. Skip them on day 1 — the pipeline runs fine without any of them.

| When you want to… | Install | Read |
|---|---|---|
| Wire LLM calls through the SHACL gates and OWL grounding | `pip install -r requirements-runtime.txt` | [features.md §8 Runtime](../features.md#8-runtime--connecting-the-toolkit-to-ai-and-llms) · [docs/sdk.md](sdk.md) |
| Monitor production data drift against the ontology | `pip install -r requirements-drift.txt` | [examples/infodrift/README.md](../examples/infodrift/README.md) · [ontology_infodrift_integration.md](../ontology_infodrift_integration.md) |
| Use the browser-based wizard | `pip install -r requirements-advanced.txt` | [install.md §2](../install.md#2-onboarding--start-a-new-project) |
| Publish to Fuseki / Stardog / Neptune / GraphDB | `pip install -r requirements-advanced.txt` (Neptune only) | [features.md §9](../features.md#9-phase-3--scale--community) |
| Federate with another organisation's ontology | core only | [features.md §12](../features.md#12-generation-2--cross-enterprise-federated-ontology-network) |
| Generate compliance evidence bundles | core only | [features.md §13](../features.md#13-generation-2--regulatory-ai-compliance-evidence-engine) |

---

## You probably don't need (yet)

These are advanced features. Useful when you have a specific need — distracting otherwise. Each lives behind a `--phase` flag and is documented inside [features.md](../features.md).

- `--phase reasoner` — OWL 2 consistency checking via ROBOT (needs Java + a 100 MB jar)
- `--phase modular` — splits the ontology into importable modules with cycle detection
- `--phase discover` — NLP entity discovery from log corpora (requires spaCy + an English model)
- `--phase tmf630` — TMF Open API Task + Bulk operations
- `--phase evolve` — autonomous ontology evolution proposals
- `--phase federate` — cross-enterprise federation with signed manifests
- `--phase comply` — regulatory evidence bundles (EU AI Act, Basel IV, HIPAA, Ofcom)
- `--phase embed` / `--phase retrieve` — ontology-bounded vector retrieval
- `--phase monitor` — production drift monitoring (drift_monitor / infodrift)

Run `python3 toolkit.py --help` to see every flag, but ignore most of them on first contact.

---

## When to read what

| Document | When |
|---|---|
| **This file** | First contact, integration recipe, "what's the minimum?" |
| [install.md](../install.md) | You hit a database driver issue or want every connection-string format |
| [features.md](../features.md) | You want to know what a specific phase, artifact, or runtime component does |
| [gates.md](../gates.md) | You're owning ontology governance and need the scorecard / exit-gate matrix |
| [docs/sdk.md](sdk.md) | You're writing application code that calls `RuntimeClient`, `Grounder`, etc. |
| [examples/](../examples/) | You want to see a runnable end-to-end demo |
