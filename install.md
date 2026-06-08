# Install & Onboarding

How to install the toolkit, point it at a database, and get a working ontology. If you're new, also read [docs/integrate.md](docs/integrate.md) — same content, even shorter.

## Contents

1. [Install](#1-install)
2. [Start a new project (wizard)](#2-start-a-new-project-wizard)
3. [Connect to an existing database](#3-connect-to-an-existing-database)
4. [Database backends](#4-database-backends)
5. [Going further](#5-going-further)

---

## 1. Install

**Python:** 3.10 or later.

```bash
pip install ontoforge
```

Or run the published container image — no Python install required:

```bash
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:latest
```

That's it. ~50 MB, no compile, no API keys. The toolkit runs against any SQLite database. For PostgreSQL / MySQL / Oracle / SQL Server / DB2, also install the matching driver — see §4 below.

### Optional add-ons (install only when you need them)

| You want to… | Add |
|---|---|
| Connect a non-SQLite database | `pip install -r requirements-db.txt` (or just one driver — see §4) |
| Wire LLM calls through the toolkit's runtime gates | `pip install -r requirements-runtime.txt` |
| Monitor production data drift | `pip install -r requirements-drift.txt` |
| Use the browser wizard, log entity discovery, or AWS Neptune | `pip install -r requirements-advanced.txt` |
| Everything (CI / kitchen-sink) | `pip install -r requirements.txt` |

### Install via pip wheel

The toolkit also ships as a pip-installable package built from `pyproject.toml`. Two console scripts (`ontology-toolkit`, `ontology-onboard`) are exposed on install.

```bash
pip install dist/ontology_toolkit-3.0.0-py3-none-any.whl
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[db,runtime]"
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[all]"
```

Available extras: `postgres`, `mysql`, `mssql`, `oracle`, `db2`, `db`, `anthropic`, `openai`, `vertex`, `ollama`, `oci`, `runtime`, `drift`, `wizard`, `discover`, `neptune`, `test`, `all`.

Rebuild from source:

```bash
python -m build      # produces dist/*.whl and dist/*.tar.gz
```

> The `drift-monitor` dependency is a git+VCS reference to [infodrift](https://github.com/synaptixs/infodrift), so the wheel is intended for private/internal distribution rather than PyPI.

---

## 2. Start a new project (wizard)

If you don't have a database yet, use the wizard. Plain language, no OWL knowledge required.

```bash
python3 onboard.py
```

The wizard walks through six steps:

1. **Domain identity** — name, description, author, base IRI for the ontology
2. **Entities** — the things in your domain (Asset, Customer, Patient, Order, …)
3. **Events** — things that happen (Incident, Inspection, Discharge, Trade, …)
4. **Relationships** — how entities connect, in plain sentences
5. **Competency questions** — what the ontology must answer
6. **Review and run** — summary before generation

When done, the toolkit produces the ontology, validation shapes, JSON-LD context, mapping workbook, and an HTML report — all under `projects/{your_domain}/output/`.

### Industry starters

Skip the blank slate by loading a pre-built domain:

```bash
python3 onboard.py --industry telecom        # Network operations, 5G NFs, alarms, KPIs
python3 onboard.py --industry healthcare     # Patients, encounters, diagnoses, care plans
python3 onboard.py --industry finance        # Accounts, transactions, counterparties, risk
python3 onboard.py --industry manufacturing  # Assets, work orders, quality, supply chain
python3 onboard.py --industry retail         # Products, orders, inventory, promotions
```

Each pre-populates entities, events, relationships, and 5–8 competency questions. You review and adjust before anything is generated.

### Save and resume

The wizard auto-saves at every step:

```bash
python3 onboard.py --from projects/my_domain/session.json
```

### Dry run

Generate files without running the pipeline:

```bash
python3 onboard.py --industry healthcare --dry-run
```

### `onboard.py` flags

```
--industry STR  Pre-load a starter template
--from FILE     Resume a saved session
--dry-run       Generate files without running the pipeline
--llm           Use Claude to auto-suggest entities/events/relationships/CQs
                from your domain description (needs ANTHROPIC_API_KEY)
```

### Browser wizard

Same six steps, but in a drag-and-drop web UI instead of the terminal. Useful if you'd rather click than type, or if a non-technical stakeholder is doing the onboarding.

**Install the wizard's deps (Flask):**

```bash
pip install -r requirements-advanced.txt        # Flask + Flask-CORS + spaCy + boto3
# or just the wizard, nothing else:
pip install flask flask-cors
```

**Start the wizard:**

```bash
python3 wizard/app.py                           # dev server on http://localhost:5000
python3 wizard/app.py --host 0.0.0.0 --port 5000   # listen on all interfaces
```

Open `http://localhost:5000` in a browser. The wizard walks through Domain → Entities → Events → Relationships → CQs → Generate. The "Generate" step runs the toolkit pipeline and links to the resulting `output/reports/toolkit_report.html`.

**Load an industry template** in the UI (Templates tab) or via the CLI before launching:

```bash
python3 onboard.py --industry telecom --dry-run    # writes projects/telecom_network_operations/session.json
python3 wizard/app.py                              # opens the same session for editing
```

**Stop the wizard:** `Ctrl+C` in the terminal. Sessions are saved to `projects/{your_domain}/session.json` and can be resumed from either the CLI (`onboard.py --from …`) or by reopening the wizard.

---

## 3. Connect to an existing database

If you already have a database, skip the wizard and point the toolkit at it directly.

### Run it

```bash
python3 toolkit.py --db "postgresql://user:password@host/mydb" --out output/
open output/reports/toolkit_report.html
```

That's the whole loop. The toolkit reads your schema, generates the ontology and supporting artifacts, and writes everything under `--out`.

### One-time setup: two annotation tables

The toolkit needs a small annotation control plane in your database — two tables, *no changes to your existing tables*. Copy the DDL from `db/schema.sql`:

```sql
CREATE TABLE ontology_metadata (...);   -- semantic annotation control plane
CREATE TABLE semantic_loss_log (...);   -- where the toolkit writes findings
```

Then add a few rows to `ontology_metadata` describing your most important tables and columns (semantic class, business term, sensitivity tier). The minimum viable set is in [docs/integrate.md](docs/integrate.md). Re-run the toolkit and refine over time.

### Connection strings

```bash
# SQLite (default)
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

# Oracle (thin mode — no Instant Client)
python3 toolkit.py --db "oracle://user:password@host:1521/service_name"
python3 toolkit.py --db "oracle://user:password@host:1521/ORCLPDB1?schema=MYSCHEMA"

# Oracle Autonomous Database (wallet-based mTLS)
python3 toolkit.py --db "oracle://ADMIN:password@/myatp_high?wallet=/path/to/wallet&wallet_password=walletpass"

# IBM DB2
python3 toolkit.py --db "db2://db2inst1:password@host:50000/MYDB"
python3 toolkit.py --db "db2://user:password@host:50000/MYDB?security=SSL&sslcertificate=/certs/db2.arm"
```

### Oracle ADB

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

## 4. Database backends

Schema introspection is normalised across all backends — downstream generators see identical models regardless of which database is connected.

| Backend | Driver to install | Port | Scheme |
|---|---|---|---|
| SQLite | (built into Python) | file | `sqlite:///` |
| PostgreSQL | `psycopg2-binary` | 5432 | `postgresql://` |
| MySQL / MariaDB | `mysql-connector-python` | 3306 | `mysql://` |
| SQL Server | `pyodbc` (+ ODBC Driver 17/18) | 1433 | `mssql://` |
| Oracle / ADB | `oracledb` | 1521 | `oracle://` |
| IBM DB2 | `ibm_db` `ibm_db_dbi` (+ DB2 CLI driver) | 50000 | `db2://` |

The toolkit does not modify any existing tables.

---

## 5. Going further

Once the basic loop works, look at:

- [docs/integrate.md](docs/integrate.md) — minimum-viable annotation set, what artifact to read first, what to ignore
- [features.md](features.md) — what every output file is for, every advanced flag, the runtime layer, drift monitoring, federation, compliance, vector retrieval
- [docs/sdk.md](docs/sdk.md) — Python SDK if you're embedding the toolkit in your own application
- [examples/](examples/) — runnable demos (retail, 5G, drift monitoring)

Run `python3 toolkit.py --help` for the full CLI; advanced flags are documented in features.md.
