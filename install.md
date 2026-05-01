# Install & Onboarding

How to install drivers, start a new project, and point the toolkit at an existing database.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Onboarding — start a new project](#2-onboarding--start-a-new-project)
3. [Connecting to an existing database](#3-connecting-to-an-existing-database)
4. [Full pipeline walkthrough](#4-full-pipeline-walkthrough)
5. [CLI reference](#5-cli-reference)
6. [Database backends](#6-database-backends)

---

## 1. Prerequisites

**Python:** 3.10 or later.

**Dependencies are tiered.** Install only what you need — most projects need only the core tier.

```bash
pip install -r requirements-core.txt        # phases 1–5, tmf, test, report (~50 MB)
pip install -r requirements-db.txt          # non-SQLite database drivers
pip install -r requirements-runtime.txt     # LLM adapters (Anthropic / OpenAI / Vertex / OCI / Ollama)
pip install -r requirements-drift.txt       # drift_monitor (infodrift) integration
pip install -r requirements-advanced.txt    # spaCy NLP, Flask wizard, Neptune
```

`pip install -r requirements.txt` pulls everything (CI / kitchen-sink installs).

**Database drivers** — install only the one(s) you actually use. SQLite is built into Python; no driver needed.

```bash
pip install psycopg2-binary          # PostgreSQL
pip install mysql-connector-python   # MySQL / MariaDB
pip install pyodbc                   # SQL Server (also needs ODBC Driver 17 or 18)
pip install oracledb                 # Oracle / Oracle ADB (thin mode — no Instant Client)
pip install ibm_db ibm_db_dbi        # IBM DB2 (also needs DB2 ODBC/CLI driver from IBM)
```

### Install via pip wheel

The toolkit also ships as a pip-installable package (sdist + wheel) built from `pyproject.toml`. Two console scripts (`ontology-toolkit`, `ontology-onboard`) are exposed on install.

```bash
# From a built wheel (see dist/)
pip install dist/ontology_toolkit-3.0.0-py3-none-any.whl

# Pick extras: db drivers, runtime adapters, drift, advanced features
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[db,runtime]"
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[postgres,oracle,anthropic]"
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[all]"
```

Available extras: `postgres`, `mysql`, `mssql`, `oracle`, `db2`, `db` (all DB drivers), `anthropic`, `openai`, `vertex`, `ollama`, `oci`, `runtime` (all runtime adapters), `drift`, `wizard`, `discover`, `neptune`, `test`, `all`.

To rebuild from source:

```bash
python -m build      # produces dist/*.whl and dist/*.tar.gz
```

> Note: the `drift-monitor` dependency (the [infodrift](https://github.com/nrohilla-fibonacci/infodrift) runtime drift package) is a git+VCS reference, so the wheel is intended for private/internal distribution rather than PyPI.

---

## 2. Onboarding — start a new project

If you are starting from scratch — no existing schema, no database — use the onboarding wizard. It guides you through domain definition in plain language and generates everything the pipeline needs.

### Interactive wizard (recommended for new projects)

```bash
python3 onboard.py
```

The wizard walks through six steps:

1. **Domain identity** — name, description, author, base IRI for the ontology
2. **Entities** — the main things in your domain (Asset, Customer, Patient, Order...)
3. **Events** — things that happen (Incident, Inspection, Discharge, Trade...)
4. **Relationships** — how entities connect, written as plain sentences
5. **Competency questions** — the questions the ontology must be able to answer. Auto-suggests starters if you have fewer than 4
6. **Review and run** — summary of everything before generating

No ontology knowledge is required. Answer in plain language.

### Industry starter templates

Skip blank-slate setup by loading a pre-built domain template:

```bash
python3 onboard.py --industry telecom        # Network operations, 5G NFs, alarms, KPIs
python3 onboard.py --industry healthcare     # Patients, encounters, diagnoses, care plans
python3 onboard.py --industry finance        # Accounts, transactions, counterparties, risk
python3 onboard.py --industry manufacturing  # Assets, work orders, quality, supply chain
python3 onboard.py --industry retail         # Products, orders, inventory, promotions
```

Each template pre-populates entities, events, relationships, and 5-8 competency questions. You review and adjust before anything is generated.

### Saving and resuming

The wizard saves your session at every step. If interrupted, resume where you left off:

```bash
python3 onboard.py --from projects/my_domain/session.json
```

### What the wizard generates

Everything lands in `projects/{domain_slug}/`:

```
projects/my_domain/
├── db/
│   ├── schema.sql        ← Working relational schema with PROV-O provenance columns
│   └── seed.sql          ← ontology_metadata rows pre-populated from your answers
├── docs/
│   ├── scope-charter.md  ← Phase 1 scope charter with stakeholder sign-off table
│   └── cq-catalog.md     ← Competency question catalog with SPARQL status tracking
├── output/               ← All generated ontology artifacts (populated by pipeline)
└── session.json          ← Saved wizard session (resumable)
```

After artifact generation the full pipeline runs automatically, producing the ontology, SHACL shapes, JSON-LD context, mapping workbook, and HTML report.

### Dry run — generate files without running the pipeline

```bash
python3 onboard.py --industry healthcare --dry-run
```

---

## 3. Connecting to an existing database

If you already have a database with an existing schema, skip the wizard and point the toolkit directly at it.

### Connection string formats

```bash
# SQLite — file path (backward-compatible)
python3 toolkit.py --db db/enterprise.db
python3 toolkit.py --db sqlite:///db/enterprise.db

# PostgreSQL
python3 toolkit.py --db "postgresql://user:password@host:5432/mydb"
python3 toolkit.py --db "postgresql://user:password@host/mydb?sslmode=require"

# MySQL / MariaDB
python3 toolkit.py --db "mysql://user:password@host:3306/mydb"

# SQL Server
python3 toolkit.py --db "mssql://user:password@host/mydb"
python3 toolkit.py --db "mssql://user:password@host/mydb?driver=ODBC+Driver+17+for+SQL+Server"

# Oracle (standard — thin mode, no Instant Client required)
python3 toolkit.py --db "oracle://user:password@host:1521/service_name"
python3 toolkit.py --db "oracle://user:password@host:1521/ORCLPDB1?schema=MYSCHEMA"

# Oracle Autonomous Database (ADB) — wallet-based mTLS
python3 toolkit.py --db "oracle://ADMIN:password@/myatp_high?wallet=/path/to/wallet&wallet_password=walletpass"

# IBM DB2
python3 toolkit.py --db "db2://db2inst1:password@host:50000/MYDB"
python3 toolkit.py --db "db2://user:password@host:50000/MYDB?schema=PROD"
python3 toolkit.py --db "db2://user:password@host:50000/MYDB?security=SSL&sslcertificate=/certs/db2.arm"
```

### What the toolkit needs in your database

Two system tables must exist. If they are not there, create them from `db/schema.sql`:

```sql
CREATE TABLE ontology_metadata ( ... );  -- semantic annotation control plane
CREATE TABLE semantic_loss_log ( ... );  -- Phase 4 findings log
```

All other tables are introspected automatically. The toolkit does not modify any existing tables.

### Oracle ADB setup

1. Download the wallet zip from OCI Console → your ADB instance → DB Connection → Download Wallet
2. Unzip to a local directory (e.g. `/opt/adb-wallet/`)
3. Note the service name from `tnsnames.ora` inside the wallet (e.g. `myatp_high`)
4. Connect: `oracle://ADMIN:dbpassword@/myatp_high?wallet=/opt/adb-wallet&wallet_password=walletpassword`

The `oracledb` package runs in thin mode — no Oracle Instant Client installation is required.

### IBM DB2 on Cloud (SSL)

```bash
python3 toolkit.py --db "db2://user:pass@hostname.databases.appdomain.cloud:30699/BLUDB?security=SSL&sslcertificate=/path/DigiCertGlobalRootCA.crt"
```

DB2 requires IBM's DB2 ODBC/CLI driver installed on the host OS. Download from [IBM Fix Central](https://www.ibm.com/support/pages/db2-odbc-cli-driver-download-and-installation-information).

---

## 4. Full pipeline walkthrough

### New project — complete flow

```bash
# Step 1: Run the onboarding wizard
python3 onboard.py --industry telecom

# The wizard asks questions, then automatically runs all phases

# Step 2: Open the report
open projects/telecom_network_operations/output/reports/toolkit_report.html

# Step 3: Review the generated ontology
cat projects/telecom_network_operations/output/ontology/enterprise.ttl

# Step 4: Refine and re-run
python3 onboard.py --from projects/telecom_network_operations/session.json
```

### Existing database — complete flow

```bash
# Step 1: Add ontology_metadata annotations (see features.md §3 Semantic metadata control table)

# Step 2: Run the full pipeline
python3 toolkit.py --db "postgresql://user:pass@host/mydb" --out output/

# Step 3: Open the report
open output/reports/toolkit_report.html
```

### Running individual phases

```bash
python3 toolkit.py --phase 1        # Introspect schema and print inventory
python3 toolkit.py --phase 2        # OWL 2 ontology generation only
python3 toolkit.py --phase 3        # SHACL shape generation only
python3 toolkit.py --phase 4        # Mapping workbook + semantic loss only
python3 toolkit.py --phase 5        # JSON-LD, SKOS, MCP tools only
python3 toolkit.py --phase tmf      # TM Forum SID alignment + TMF CQ tests
python3 toolkit.py --phase test     # CQ tests + governance scorecard
python3 toolkit.py --phase report   # HTML report only (from existing CSVs)
python3 toolkit.py --phase log       # Structured log ingestion (requires --log-path)
python3 toolkit.py --phase security  # Named-graph RBAC config generation
python3 toolkit.py --phase conflict  # Multi-agent conflict resolution (Phase 2B)
python3 toolkit.py --phase alignment # Ontology alignment + federation config (Phase 2B)
```

### Log ingestion

```bash
# Ingest a JSON-lines log file
python3 toolkit.py --phase log --log-path /var/log/app.log --log-format jsonl

# Auto-detect format from a glob
python3 toolkit.py --phase log --log-path "/var/log/*.log"

# Dry-run — parse and report without writing to DB
python3 toolkit.py --phase log --log-path /var/log/app.log --dry-run

# Syslog RFC5424
python3 toolkit.py --phase log --log-path /var/log/syslog --log-format syslog

# Named-group regex (custom format)
python3 toolkit.py --phase log --log-path /var/log/app.log --log-format regex \
    --log-regex "(?P<timestamp>\S+) (?P<severity>\w+) (?P<message>.+)"
```

### Named-graph RBAC

```bash
# Generate all three store configs (Stardog, Fuseki, Neptune)
python3 toolkit.py --phase security --store all

# Single store target
python3 toolkit.py --phase security --store stardog
python3 toolkit.py --phase security --store fuseki
python3 toolkit.py --phase security --store neptune
```

---

## 5. CLI reference

### toolkit.py

```
python3 toolkit.py [options]

  --db PATH           Database connection string or SQLite file path
                      Default: db/enterprise.db

  --out PATH          Output directory for generated artifacts
                      Default: output/

  --phase PHASE       Run a specific phase:
                      all | 1 | 2 | 3 | 4 | 5 | tmf | test | report |
                      reasoner | sparql | log | security | conflict | alignment
                      Default: all

  --industry STR      Label for the industry context (used in report header)

  --log-path PATH     Log file path or glob pattern (for --phase log)
  --log-format FMT    Log format: auto | jsonl | syslog | cef | otlp | regex
                      Default: auto
  --log-regex PATTERN Named-group regex (for --log-format regex)
  --dry-run           Parse logs without writing to DB (for --phase log)

  --store TARGET      Graph store for --phase security:
                      all | stardog | fuseki | neptune
                      Default: all
```

### onboard.py

```
python3 onboard.py [options]

  --industry STR  Pre-load a starter template: telecom | healthcare | finance | manufacturing | retail

  --from FILE     Load a saved session JSON and skip the interview

  --dry-run       Generate files without running the pipeline

  --llm           Use Claude Sonnet to auto-suggest entities, events, relationships,
                  and CQs from your domain description.
                  Requires ANTHROPIC_API_KEY environment variable.
```

---

## 6. Database backends

Schema introspection is normalised across all backends — downstream generators see identical models regardless of which database is connected.

| Backend | Introspection source | Port | Scheme |
|---|---|---|---|
| SQLite | PRAGMA table_info, PRAGMA foreign_key_list | file | sqlite:/// |
| PostgreSQL | INFORMATION_SCHEMA | 5432 | postgresql:// |
| MySQL / MariaDB | INFORMATION_SCHEMA | 3306 | mysql:// |
| SQL Server | INFORMATION_SCHEMA | 1433 | mssql:// |
| Oracle / ADB | ALL_TAB_COLUMNS, ALL_CONSTRAINTS | 1521 | oracle:// |
| IBM DB2 | SYSCAT.COLUMNS, SYSCAT.TABCONST | 50000 | db2:// |

When connecting to a non-SQLite database: create `ontology_metadata` and `semantic_loss_log` manually (DDL in `db/schema.sql`), then run phases 2-5 individually. The toolkit does not modify any existing tables.
