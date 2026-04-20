# Ontology Engineering Toolkit — v1.5

**Domain-agnostic · Zero core dependencies · Runs in under 2 seconds**

A complete end-to-end implementation of the [Domain-Agnostic Ontology Engineering Framework v1.1](docs/framework-whitepaper.md). Takes a relational database schema and produces a production-ready OWL 2 ontology, SHACL validation shapes, JSON-LD agent payloads, SKOS vocabulary, and a scored governance report — for any domain, any industry, any major relational database.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Prerequisites](#2-prerequisites)
3. [Onboarding — start a new project](#3-onboarding--start-a-new-project)
4. [Connecting to an existing database](#4-connecting-to-an-existing-database)
5. [Full pipeline walkthrough](#5-full-pipeline-walkthrough)
6. [CLI reference](#6-cli-reference)
7. [Repository structure](#7-repository-structure)
8. [Generated artifacts explained](#8-generated-artifacts-explained)
9. [Semantic metadata control table](#9-semantic-metadata-control-table)
10. [Semantic loss detection](#10-semantic-loss-detection)
11. [Governance scorecard](#11-governance-scorecard)
12. [TM Forum alignment](#12-tm-forum-alignment)
13. [Database backends](#13-database-backends)
14. [Standards used](#14-standards-used)
15. [Extending the toolkit](#15-extending-the-toolkit)
16. [Companion documents](#16-companion-documents)
17. [Runtime — connecting the toolkit to AI and LLMs](#17-runtime--connecting-the-toolkit-to-ai-and-llms)

---

## 1. What it does

Most enterprise data models are structurally sound but semantically weak — field names, not meaning. AI agents that consume these models guess at intent and disagree on concepts. This toolkit closes that gap.

It reads your relational schema and a thin annotation table, then generates every artifact needed to make your data meaningful to AI systems:

| Phase | What runs | What is produced |
|---|---|---|
| Onboard | Interactive wizard | Schema, seed data, scope charter, CQ catalog |
| 1 — Foundation | Schema introspection | Annotated class and property inventory |
| 2 — Modeling | OWL 2 generator | enterprise.ttl, events.ttl, provenance.ttl |
| 3 — Validation | SHACL generator | enterprise-shapes.ttl, agent-gate.ttl |
| 4 — Mapping | Semantic loss detector | Mapping workbook, semantic loss report, orphan analysis |
| 5 — Exchange | JSON-LD + SKOS + MCP | Context file, sample payloads, MCP tool definitions, vocabulary |
| TMF | TM Forum alignment | SID OWL hierarchy (24 APIs, 13 CQs), TMF API coverage |
| conflict | Multi-agent conflict resolution ✓ Phase 2B | 3-tier resolution chain, SHACL shapes, MCP tools, PROV-O invalidation |
| alignment | Ontology alignment & federation ✓ Phase 2B | alignment.ttl (DOLCE/FOAF/Schema.org/SOSA), federation-config.ttl, federated SPARQL queries |
| Test | CQ test runner | 18 SPARQL competency question tests, governance scorecard |
| Report | HTML reporter | Self-contained visual summary report |
| **runtime** | **AI consumption layer ✓ Complete** | **FlavorRegistry (5 flavors), Grounder, PayloadAssembler, InputGate, OutputGate, RuntimeClient (4 LLM adapters)** |

---

## 2. Prerequisites

**Core pipeline:** Python 3.8 or later. No packages required — stdlib only.

**Database drivers** — install only what you need:

```bash
pip install psycopg2-binary          # PostgreSQL
pip install mysql-connector-python   # MySQL / MariaDB
pip install pyodbc                   # SQL Server (also needs ODBC Driver 17 or 18)
pip install oracledb                 # Oracle / Oracle ADB (thin mode — no Instant Client)
pip install ibm_db ibm_db_dbi        # IBM DB2 (also needs DB2 ODBC/CLI driver from IBM)
```

SQLite is built into Python — no driver needed.

---

## 3. Onboarding — start a new project

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

## 4. Connecting to an existing database

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

## 5. Full pipeline walkthrough

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
# Step 1: Add ontology_metadata annotations (see Section 9)

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

## 6. CLI reference

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

## 7. Repository structure

```
ontology-toolkit/
│
├── onboard.py                   ← Onboarding wizard — start here for new projects
├── toolkit.py                   ← Main pipeline CLI
│
├── src/
│   ├── db_connector.py          ← Database abstraction (SQLite, PG, MySQL, MSSQL, Oracle, DB2)
│   ├── db_introspector.py       ← Phase 1: schema + ontology_metadata reader
│   ├── ontology_generator.py    ← Phase 2: OWL 2 Turtle generator
│   ├── shacl_generator.py       ← Phase 3: SHACL NodeShape generator
│   ├── mapping_generator.py     ← Phase 4: mapping workbook + semantic loss detector
│   ├── jsonld_generator.py      ← Phase 5: JSON-LD context, SKOS vocabulary, MCP tools
│   ├── tmf_mapper.py            ← TMF phase: SID hierarchy, Open API map, TMF CQ tests
│   ├── cq_tester.py             ← Test phase: CQ runner + governance auto-scorer (31 criteria)
│   ├── sparql_tester.py         ← SPARQL CQ test runner (Oxigraph / rdflib backends)
│   ├── reasoner.py              ← ROBOT OWL 2 reasoner integration (ELK / HermiT)
│   ├── log_connector.py         ← Phase 2A: structured log ingestion (JSON/syslog/CEF/OTLP)
│   ├── rbac_generator.py        ← Phase 2A: named-graph RBAC config generator
│   ├── conflict_resolver.py     ← Phase 2B: multi-agent conflict resolution (3-tier chain)
│   ├── alignment_generator.py   ← Phase 2B: ontology alignment (DOLCE/FOAF/Schema.org/SOSA) + federation
│   └── reporter.py              ← Report phase: HTML report generator
│
├── db/
│   ├── schema.sql               ← Generic enterprise schema (includes system tables)
│   ├── seed.sql                 ← Generic ontology metadata + telecom sample data
│   ├── tmf_schema.sql           ← TM Forum SID schema (8 domains, 23 tables)
│   └── tmf_seed.sql             ← TMF ontology metadata + 5G sample data
│
├── output/
│   ├── ontology/
│   │   ├── enterprise.ttl           ← Primary OWL 2 ontology
│   │   ├── events.ttl               ← Event subclass hierarchy
│   │   ├── provenance.ttl           ← PROV-O provenance patterns
│   │   └── tmf-sid-hierarchy.ttl    ← TMF SID OWL hierarchy (56 classes, 8 domains)
│   ├── shapes/
│   │   ├── enterprise-shapes.ttl    ← SHACL NodeShapes (37 shapes, 360 constraints)
│   │   └── agent-gate.ttl           ← Agent acceptance gate for pipeline middleware
│   ├── vocab/
│   │   └── enterprise-skos.ttl      ← SKOS terminology scheme (84 concepts)
│   ├── jsonld/
│   │   ├── enterprise-context.json          ← Canonical JSON-LD context (184 terms)
│   │   ├── tmf-context.json                 ← TMF-specific JSON-LD context
│   │   ├── sample-observation-payload.json  ← PROV-O-aligned observation payload
│   │   ├── sample-event-payload.json        ← Domain event payload
│   │   ├── sample-tmf639-resource-payload.json ← TMF639 resource inventory payload
│   │   ├── sample-tmf642-alarm-payload.json    ← TMF642 alarm payload (ITU-T X.733)
│   │   ├── mcp-tool-definitions.json        ← Generic MCP tools (3 tools)
│   │   └── tmf-mcp-tools.json               ← TMF-specific MCP tools (3 tools)
│   ├── mapping/
│   │   ├── logical_physical_map.csv     ← Ontology to table to column traceability
│   │   ├── semantic_loss_report.csv     ← Semantic loss findings
│   │   ├── orphan_candidates.csv        ← Relationship orphan analysis
│   │   └── tmf_api_coverage.csv         ← TMF Open API coverage (18 APIs)
│   └── reports/
│       ├── cq_test_results.csv          ← Generic CQ results (8 tests)
│       ├── tmf_cq_test_results.csv      ← TMF CQ results (9 tests)
│       ├── governance_scorecard.csv     ← Governance checklist scores
│       └── toolkit_report.html          ← Visual summary — open in browser
│
├── projects/                    ← Created by the onboarding wizard
│   └── {domain_slug}/
│       ├── db/schema.sql
│       ├── db/seed.sql
│       ├── docs/scope-charter.md
│       ├── docs/cq-catalog.md
│       ├── output/
│       └── session.json
│
├── runtime/                     ← AI consumption layer (connects toolkit to LLMs) ✓ Complete
│   ├── flavors/                 ← Named ontology views for each agent type
│   │   ├── network-ops.json     ← Resource, NetworkFunction, Alarm, KPI — network agents
│   │   ├── billing.json         ← CustomerBill, Product, Agreement — billing agents
│   │   ├── compliance.json      ← ConflictEvent, Policy, ObservationRecord — compliance agents
│   │   ├── customer.json        ← Party, Service, Product — customer service agents
│   │   └── fault-management.json ← Alarm, TroubleTicket, ServiceQualityReport
│   ├── flavor_registry.py       ← Loads, validates, and serves flavor configs
│   ├── grounder.py              ← Queries DB and serialises records as JSON-LD
│   ├── assembler.py             ← Assembles full 5-component LLM payload
│   ├── output_gate.py           ← SHACL-validates LLM responses + PROV-O stamping
│   ├── input_gate.py            ← SHACL acceptance gate for inbound enterprise data
│   ├── client.py                ← RuntimeClient — end-to-end pipeline, adapter factory
│   └── adapters/                ← LLM-specific adapters
│       ├── anthropic_adapter.py ← Anthropic Messages API (with prompt caching)
│       ├── openai_adapter.py    ← OpenAI Chat Completions
│       ├── vertex_adapter.py    ← Google Vertex AI (Gemini)
│       └── ollama_adapter.py    ← Ollama local LLM
│
├── .github/
│   └── workflows/
│       └── ontology.yml         ← Phase 2A: CI/CD pipeline (5 stages, PR governance comment)
│
└── docs/
    ├── framework-whitepaper.md
    ├── executive-summary.md
    └── technical-blueprint.md
```

---

## 8. Generated artifacts explained

### enterprise.ttl — OWL 2 ontology

Every table becomes an OWL class. Every column becomes a data property (scalar) or object property (FK relationship). Every class carries a sensitivity tier annotation.

```turtle
:Asset
  a owl:Class ;
  rdfs:subClassOf :DomainEntity ;
  rdfs:label "Asset" ;
  rdfs:comment "A physical or logical resource managed by the organization." ;
  :sensitivityTier :Internal ;
  skos:prefLabel "Asset" ;
  skos:altLabel "Resource", "Managed Object" .
```

### events.ttl — event subclass hierarchy

Distinct values in event discriminator columns (e.g. `event_type = INCIDENT`) auto-generate OWL subclasses of `DomainEvent`, making different event types formally distinct without manual modeling.

### provenance.ttl — PROV-O patterns

Custom provenance properties: `wasProducedBy`, `hasConfidenceScore`, `derivationMethod`, `sourceRef`, `governedBy`, `hasParticipant`, `refersToAsset`. Aligns all observation records with the W3C PROV-O standard.

### enterprise-shapes.ttl — SHACL validation

One NodeShape per class. NOT NULL columns get `sh:minCount 1`. FK columns get `sh:class` type constraints. State machine values get `sh:in` enumeration constraints. Severity: `sh:Violation` for Critical/High (blocks pipeline), `sh:Warning` for Medium/Low.

### agent-gate.ttl — agent acceptance gate

Standalone SHACL for AI agent pipeline middleware. Validates PROV-O provenance, timestamp, confidence score (0.0–1.0), derivation method (MEASURED / INFERRED / IMPORTED / SYNTHESIZED), and agent credential before any downstream action is triggered.

### enterprise-context.json — JSON-LD context

Maps JSON field names to ontology IRIs so any agent that loads this context interprets field names identically to every other agent, eliminating semantic drift in multi-agent exchanges.

### mcp-tool-definitions.json — MCP tools

Six MCP tool definitions with `x-semantic-context`, `x-shacl-gate`, and `x-sid-class` annotations. Three generic tools (record_observation, create_domain_event, validate_payload) and three TMF tools (get_network_function_status, raise_alarm, record_kpi).

### enterprise-skos.ttl — SKOS vocabulary

84 SKOS Concepts with preferred labels, synonyms, and definitions. Separate ConceptSchemes for each status and type enumeration. Used by data catalogs and search systems.

### logical_physical_map.csv — mapping workbook

Traces every OWL class and property to its physical table and column. Used in Phase 4 reviews to identify semantic loss.

### toolkit_report.html — visual report

Self-contained HTML. Contains CQ test results, governance scorecard with maturity bars, semantic loss findings by severity, orphan analysis, TMF CQ results, TMF API coverage table, and artifact index.

---

## 9. Semantic metadata control table

The `ontology_metadata` table is the semantic control plane. It annotates your existing schema without modifying operational tables.

### Table-level annotation

```sql
INSERT INTO ontology_metadata (
    target_type, table_name, semantic_type, label, description,
    sensitivity_tier, is_event_class, skos_pref_label, skos_alt_labels, cq_coverage
) VALUES (
    'TABLE', 'patients', 'Patient',
    'Patient', 'A person receiving healthcare services.',
    'Confidential', 0,
    'Patient', 'Service User,Client',
    'CQ-001,CQ-002,CQ-003'
);
```

### Column-level annotation

```sql
INSERT INTO ontology_metadata (
    target_type, table_name, column_name,
    semantic_type, label, description, sensitivity_tier, cq_coverage
) VALUES (
    'COLUMN', 'patients', 'date_of_birth',
    'xsd:date', 'Date of Birth',
    'Patient date of birth.',
    'Restricted', 'CQ-001'
);
```

### Field reference

| Field | Required | Description | Example |
|---|---|---|---|
| `target_type` | Yes | TABLE or COLUMN | TABLE |
| `table_name` | Yes | Physical table name | patients |
| `column_name` | COLUMN only | Physical column name | date_of_birth |
| `semantic_type` | Recommended | OWL class name or xsd type | Patient, xsd:date |
| `label` | Recommended | Human-readable label (rdfs:label) | Patient |
| `description` | Recommended | One-sentence description (rdfs:comment) | A person receiving... |
| `sensitivity_tier` | Recommended | Public, Internal, Confidential, or Restricted | Confidential |
| `is_event_class` | No | 1 if this table models domain events | 1 |
| `skos_pref_label` | No | Preferred term for the SKOS vocabulary | Patient |
| `skos_alt_labels` | No | Comma-separated synonyms | Service User,Client |
| `cq_coverage` | No | Comma-separated CQ IDs this entity supports | CQ-001,CQ-003 |

### TMF-specific annotation columns

| Field | Description | Example |
|---|---|---|
| `sid_domain` | SID domain name | Resource, Service, EngagedParty |
| `sid_abe` | SID Aggregate Business Entity | Logical Resource, Party |
| `tmf_api_id` | Primary TMF Open API | TMF639, TMF632 |
| `tmf_api_version` | API version | v5.0 |
| `tmf_entity_name` | Canonical TMF entity name | LogicalResource, Party |
| `etom_process` | Primary eTOM Level-2 process | 1.1.1 Resource Provisioning |

---

## 10. Semantic loss detection

Phase 4 runs seven automated heuristics. Findings go to `semantic_loss_report.csv` and the `semantic_loss_log` table. Set `resolved = 1` on fixed findings — they will not re-appear on re-run.

| Rule | Severity | What it detects |
|---|---|---|
| STATUS_AS_EVENT | HIGH | A status column exists but no event table records transitions |
| IMPLICIT_ACTOR | CRITICAL | An event table has no FK to an agent or party table |
| OVERLOADED_TYPE | MEDIUM | A type discriminator column has no OWL subclass hint |
| MISSING_TIMESTAMP | HIGH | An event table has no timestamp column |
| FLOATING_VALUE | HIGH | An observation table stores a value with no confidence score |
| MISSING_SOURCE_REF | MEDIUM | An observation table has no source reference column |
| MISSING_METADATA | LOW | A table has no ontology_metadata entry |

STATUS_AS_EVENT is reclassified from HIGH to LOW for SID/TMF lifecycle tables where the eTOM state machine governs the status field by design.

---

## 11. Governance scorecard

The test phase auto-scores all 31 governance checklist criteria (completed in Phase 1). Scores are written to `governance_scorecard.csv` with evidence links.

| Score | Level | Meaning |
|:---:|---|---|
| 0 | Absent | Blocks production deployment |
| 1–2 | Initial | Development only |
| 3 | Developing | Agent pilot minimum |
| 4 | Defined | Production minimum |
| 5 | Optimized | Target for regulated systems |

Minimum production gate thresholds: Coverage ≥ 4, Constraint quality ≥ 4, Agent readiness ≥ 4, all other dimensions ≥ 3.

The included telecom + TMF example scores **4.0 / 5.0** with **17/17 CQ tests passing**.

---

## 12. TM Forum alignment

Run with `--phase tmf` or as part of the full pipeline.

### The SID domains (Phase 2B complete — 24 Open APIs)

| Domain | Key ABEs | Primary APIs | Phase |
|---|---|---|---|
| Resource | LogicalResource, PhysicalResource, NetworkFunction, NetworkSlice | TMF634, TMF639 | 1 |
| Service | CustomerFacingService, ResourceFacingService, ServiceOrder, ServiceProblem | TMF633, TMF638, TMF641, TMF656 | 1 |
| Product | Product, ProductOffering, ProductSpecification, ProductOrder | TMF620, TMF622, TMF637 | 1 |
| EngagedParty | Party, Individual, Organization, PartyRole, CustomerAccount, Agreement | TMF629, TMF632, TMF651, TMF666, TMF669 | 1 |
| Market/Sales | MarketSegment, ProductCatalog, SalesChannel | TMF620 | 1 |
| Supplier/Partner | SupplierAccount, SupplierOrder, SupplierSLA | TMF651 | 1 |
| Enterprise | Policy, UserRole, BusinessInteraction, EventSubscription, ConflictEvent | TMF672, TMF688 | 1 + 2B |
| Common | Characteristic, Note, Attachment, GeographicPlace, GeographicSite | TMF673, TMF674, TMF675 | 1 + 2B |
| **TroubleMgmt** ✓ | **TroubleTicket, ResourceTroubleTicket, CustomerTroubleTicket** | **TMF621** | **2B** |
| **NetworkSliceMgmt** ✓ | **NetworkSliceProfile (3GPP S-NSSAI)** | **TMF645** | **2B** |
| **ServiceQuality** ✓ | **ServiceQualityReport, SLA compliance, KQI** | **TMF657** | **2B** |
| **Billing** ✓ | **CustomerBill, BillingAccount** | **TMF678** | **2B** |
| **Qualification** ✓ | **ProductOfferingQualification, QualificationItem** | **TMF679** | **2B** |

### 5G network functions (3GPP TS 23.501)

`AMF` · `SMF` · `UPF` · `PCF` · `UDM` · `AUSF` · `NRF` · `NEF` · `gNB`

Each is an OWL subclass of `NetworkFunction` with SID annotations, TMF API reference, and eTOM state machine values.

### Alarm model (ITU-T X.733 / TMF642)

Six subtypes: CommunicationsAlarm, EquipmentAlarm, EnvironmentalAlarm, ProcessingErrorAlarm, QualityOfServiceAlarm, SecurityViolation. Full severity ladder (Critical → Cleared), state machine (Active → Acknowledged → Cleared), root cause chaining.

### SID design patterns

**Specification–Instance** — XxxSpec table (catalog template) + instance table pair for Resource, Service, Product.

**Composite** — self-referential parent FK for hierarchies (NetworkSlice composed of NetworkFunctions).

**Characteristic** — polymorphic key-value extensibility table for any entity without schema changes.

### TMF CQ tests (13 tests, all passing)

| CQ | Question | Phase |
|---|---|---|
| CQ-TMF01 | Which 5G NFs are Disabled/Locked and what resources depend on them? | 1 |
| CQ-TMF02 | Which services are Active and which resources realise them? | 1 |
| CQ-TMF03 | Which products are Active and which accounts and orders cover them? | 1 |
| CQ-TMF04 | Which parties hold which roles and which agreements cover those relationships? | 1 |
| CQ-TMF05 | Which SLA agreements are at risk from active alarms or service problems? | 1 |
| CQ-TMF06 | Which Active or uncleared alarms exist by severity and root cause? | 1 |
| CQ-TMF07 | Which KPIs breach thresholds with confidence score and derivation method? | 1 |
| CQ-TMF08 | Full Resource to Service to Product to Customer traceability chain | 1 |
| CQ-TMF09 | Which service orders are incomplete and what product orders triggered them? | 1 |
| **CQ-TMF10** | **Open trouble tickets with resource/service impact and SLA breach status** | **2B** |
| **CQ-TMF11** | **Active network slice profiles with 3GPP S-NSSAI parameters and backing resources** | **2B** |
| **CQ-TMF12** | **Service quality reports showing SLA non-compliance with breached metrics** | **2B** |
| **CQ-TMF13** | **Outstanding and disputed customer bills per account** | **2B** |

### 24 TMF Open APIs mapped

**Phase 1:** TMF620 · TMF622 · TMF629 · TMF632 · TMF633 · TMF634 · TMF637 · TMF638 · TMF639 · TMF641 · TMF642 · TMF651 · TMF656 · TMF666 · TMF669 · TMF672 · TMF673 · TMF688

**Phase 2B:** TMF621 · TMF645 · TMF657 · TMF674 · TMF678 · TMF679

All Apache 2.0. Specifications: [github.com/tmforum-apis](https://github.com/tmforum-apis).

### Phase 2B: Multi-agent conflict resolution (`--phase conflict`)

Implements the 3-tier resolution chain from framework Section 10.1:

- **Tier 1 — SHACL axiom check**: SQL-equivalent consistency rules that catch logically invalid states (e.g. `operational_state=Disabled` + `admin_state=Unlocked`). Escalates violations to Tier 3 automatically.
- **Tier 2 — Derivation-method priority**: When two agents report conflicting values, the higher-priority derivation method wins: `measured > inferred > imported > synthesized > default`. Records PROV-O `wasInvalidatedBy` on the losing assertion.
- **Tier 3 — Human escalation queue**: Unresolvable conflicts are inserted into `tmf_conflict_event` with `escalated_to_human=1` and await review.

Produces: `output/reports/conflict_resolution_report.json`, `output/shapes/conflict-resolution-shapes.ttl`, `output/jsonld/conflict-resolution-mcp-tools.json`.

Three MCP tools: `subscribe_to_events`, `resolve_assertion_conflict`, `get_conflict_queue`.

### Phase 2B: Ontology alignment & federation (`--phase alignment`)

Generates alignment axioms from the toolkit ontology to four external standards:

| Standard | Alignment type | Classes aligned |
|---|---|---|
| DOLCE | `owl:equivalentClass`, `skos:closeMatch` | TmfEntity, DomainEvent, Party, Resource, Service, Agreement |
| FOAF | `owl:equivalentClass` | Party↔foaf:Agent, Individual↔foaf:Person, Organization↔foaf:Organization |
| Schema.org | `owl:equivalentClass`, `skos:closeMatch` | Organization, Product, ProductOrder, GeographicSite, CustomerBill, and 9 more |
| SOSA/SSN | `owl:equivalentClass`, `skos:closeMatch` | ObservationRecord↔sosa:Observation, Resource↔sosa:FeatureOfInterest, Agent↔sosa:Sensor |

Produces: `output/ontology/alignment.ttl` (44 axioms), `output/ontology/federation-config.ttl` (5 named graph endpoints), `output/ontology/federation-queries.sparql` (5 multi-domain federated SPARQL examples).

### Adding more TMF domains

1. Add a table to `db/tmf_schema.sql`
2. Add `ontology_metadata` rows in `db/tmf_seed.sql` with `tmf_api_id`, `sid_domain`, `sid_abe`
3. Add the API to `TMF_API_MAP` in `src/tmf_mapper.py`
4. Add 1-2 CQs to `TMF_COMPETENCY_QUESTIONS` in `src/tmf_mapper.py`
5. Run `python3 toolkit.py`

---

## 13. Database backends

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

---

## 14. Standards used

| Standard | Body | Role |
|---|---|---|
| OWL 2 | W3C | Formal ontology language — classes, properties, restrictions |
| SHACL | W3C | Graph validation and agent acceptance gates |
| PROV-O | W3C | Provenance patterns — entity, activity, agent |
| SKOS | W3C | Controlled vocabulary and terminology scheme |
| JSON-LD 1.1 | W3C | Semantic message format for agent payloads |
| MCP | Anthropic | Agent tool and protocol exchange layer |
| SID v23.0 | TM Forum | Telecom information framework and domain ontology |
| eTOM v21.5 | TM Forum | Telecom business process framework |
| ITU-T X.733 | ITU-T | Alarm reporting and management |
| 3GPP TS 23.501 | 3GPP | 5G system architecture and NF definitions |

---

## 15. Extending the toolkit

### Add a semantic loss rule

Edit `_detect_semantic_loss()` in `src/mapping_generator.py`. Each rule appends a dict with `severity`, `table`, `column`, `loss_type`, `description`, and `remediation`.

### Add a competency question test

Add an entry to `COMPETENCY_QUESTIONS` in `src/cq_tester.py`:

```python
{
    "id": "CQ-010",
    "question": "Which patients have an active care plan?",
    "priority": "Critical",
    "sparql_equiv": "SELECT ?p WHERE { ?cp a :CarePlan ; :assignedTo ?p ; :status 'Active' }",
    "sql": "SELECT p.name FROM care_plans cp JOIN patients p ON cp.patient_id = p.id WHERE cp.status = 'Active'",
    "expected_non_empty": True,
    "validates": "CarePlan-Patient relationship, lifecycle status",
}
```

### Add a new database backend

Subclass `Connector` in `src/db_connector.py`. Implement `get_tables()`, `get_columns()`, `execute()`, `execute_script()`. Add a type normalisation function and register the scheme in `create_connector()`.

### Customise OWL generation

Edit `_class_block()` or `_data_property_block()` in `src/ontology_generator.py`.

### Add a SHACL constraint

Extend `_node_shape()` in `src/shacl_generator.py`.

### Extend the JSON-LD context

Add terms to `_build_context()` in `src/jsonld_generator.py`.

### Add an industry template

Add an entry to `INDUSTRY_TEMPLATES` in `onboard.py`:

```python
"energy": {
    "domain_name": "Energy Operations",
    "domain_description": "Grid asset management, meter reading, outage response, and customer billing.",
    "entities": ["Grid Asset", "Meter", "Customer", "Outage"],
    "events": ["Fault", "Restoration", "Maintenance", "Meter Read"],
    "relationships": [
        ("Outage", "affects", "Grid Asset"),
        ("Meter", "installed at", "Customer"),
    ],
    "cqs": [
        "Which grid assets are currently faulted?",
        "Which customers are affected by an active outage?",
    ],
}
```

---

## 16. Companion documents

| Document | Audience | Purpose |
|---|---|---|
| docs/framework-whitepaper.md | Architects | Full framework specification v1.1 |
| docs/executive-summary.md | Leadership | Non-technical overview — what, why, and first steps |
| docs/technical-blueprint.md | Engineers | Phase-by-phase implementation guide with code patterns |
| ontology_governance_checklist.csv | All teams | 31 scored criteria for assessing ontology maturity |
| output/reports/toolkit_report.html | All teams | Visual run report — open in browser after each pipeline run |

---

*Framework: v1.1 · Toolkit: v1.5 · April 2026*  
*OWL 2 · SHACL · PROV-O · SKOS · JSON-LD · TM Forum SID v23.0 · 6 database backends · Runtime layer (complete)*

---

## 17. Runtime — connecting the toolkit to AI and LLMs

The pipeline phases (1–5, TMF) build the semantic artifacts. The runtime layer is how an enterprise *uses* those artifacts to power AI agents and LLM applications. This section describes the architecture, the five components, and the two flows every deployment follows.

### The core idea

After onboarding, an enterprise has:
- A master OWL 2 ontology describing every domain concept
- SHACL validation shapes enforcing data quality
- A JSON-LD context binding field names to ontology IRIs
- Ontology-annotated enterprise data in a relational database

The runtime layer assembles these into a governed payload sent to an LLM. The LLM responds. The response is validated, stamped with provenance, and stored back as a governed enterprise fact.

### Ontology flavors — scoped views per agent type

An enterprise has many types of AI agents. A network monitoring agent, a billing agent, and a compliance agent all work with different concepts. You do not send the entire enterprise ontology to every agent — you send the relevant slice.

Each **flavor** is a named configuration file that defines:
- The subset of OWL classes and properties relevant to this agent type
- The corresponding SHACL shape subset for validation
- A scoped JSON-LD context with only the terms this agent needs
- The sensitivity-tier access level for this agent's authorisation

Flavors are stored in `runtime/flavors/{name}.json` and auto-generated from `ontology_metadata` `sid_domain` groupings. They can be manually extended.

**Starter flavors (telecom):**

| Flavor | Classes included | Typical agent use |
|---|---|---|
| `network-ops` | Resource, NetworkFunction, Alarm, PerformanceIndicator | Network monitoring, fault detection |
| `billing` | Product, ProductOrder, CustomerAccount, Agreement | Invoice generation, payment processing |
| `compliance` | Policy, Agreement, Party, PartyRole | Regulatory checks, audit trail queries |
| `customer` | Party, Service, Product, CustomerAccount | Customer service, CX analysis |
| `fault-management` | Alarm, ServiceProblem, Resource, Service | Incident management, root cause analysis |

### Two flows

**Flow A — Semantic preparation (offline, runs when schema or ontology changes)**

```
Enterprise DB
    ↓ ontology_metadata annotations
Toolkit pipeline (Phases 1–5, TMF)
    ↓ OWL ontology + SHACL shapes + JSON-LD context
Flavor registry
    ↓ named scoped views over the master ontology
Ready for runtime consumption
```

This flow runs once per schema change or major ontology update. It populates the `output/` directory with artifacts the runtime layer reads at query time.

**Flow B — Runtime inference (per question, per agent invocation)**

```
Step 1 — Select flavor
  Incoming question → choose relevant flavor (network-ops, billing, etc.)

Step 2 — Ground the data  ← THE CRITICAL STEP MOST IMPLEMENTATIONS MISS
  Query enterprise DB for records relevant to the question
  Serialise records as JSON-LD using the flavor's scoped context
  Result: every field value is bound to its ontology IRI — not raw data

Step 3 — Validate inbound data
  Run SHACL acceptance gate on the grounded records
  Reject malformed, incomplete, or low-confidence records here
  Bad data rejected before reaching the LLM

Step 4 — Assemble the payload
  Component 1: System prompt — ontology summary + domain rules + agent role
  Component 2: Ontology flavor — class and property definitions in natural language
  Component 3: Grounded data — JSON-LD serialised enterprise records
  Component 4: PROV-O context — provenance of each data point
  Component 5: Question + output format instructions

Step 5 — Send to LLM of choice
  Anthropic, OpenAI, Google, Llama, or any custom endpoint
  The payload is LLM-agnostic — JSON-LD works with any model

Step 6 — Govern the output  ← THE MISSING STEP IN MOST DESIGNS
  SHACL validate structured response against ontology shapes
  Stamp PROV-O provenance:
    prov:wasGeneratedBy = LLM identifier + model version
    prov:generatedAtTime = timestamp
    confidence_score = extracted from model output or metadata
    derivation_method = SYNTHESIZED
  Store as ObservationRecord back into the semantic layer
```

### Why the grounding step matters

Raw enterprise data sitting next to an ontology in a prompt does not connect the two. An LLM reading a field called `status = Enabled` cannot infer that this maps to the OWL class `NetworkFunction` with `hasOperationalState = Enabled` — unless something makes that binding explicit. JSON-LD serialisation is that binding mechanism. Without it, you have data and a schema in the same prompt; with it, you have semantically typed assertions the model can reason over with precision.

### Why the output governance step matters

An LLM response is a new assertion entering your enterprise knowledge base. Without output governance, it is an ungovernable, untraceable string. With PROV-O stamping it becomes a first-class enterprise fact with a full provenance chain: who asked, which model answered, when, with what confidence, derived from which source records. This is what makes AI output auditable — and what regulators increasingly require.

### Running the runtime phase

```bash
# Validate all flavors and generate runtime MCP tools
python3 toolkit.py --phase runtime

# Ground data for a question, output JSON-LD to stdout
python3 runtime/grounder.py --flavor network-ops \
    --question "Which NFs are degraded?" \
    --db db/enterprise.db

# Validate inbound records against SHACL shapes before they reach the LLM
python3 -c "
import sys; sys.path.insert(0, 'runtime')
from input_gate import InputGate
gate = InputGate('db/enterprise.db', min_confidence=0.6)
accepted, rejected = gate.screen_db_query('tmf_resource', flavor_name='network-ops')
print(gate.summary(accepted, rejected))
"
```

### Runtime SDK

```python
import sys; sys.path.insert(0, 'runtime')
from client import RuntimeClient

client = RuntimeClient(
    db_path="db/enterprise.db",
    adapter="anthropic",         # or "openai", "vertex", "ollama"
    model="claude-sonnet-4-5",
)

result = client.ask(
    question="Which 5G network functions are currently degraded and what is their impact on active services?",
    flavor="network-ops",
    output_format="json",
)

print(result["answer"])           # LLM response text
print(result["valid"])            # True if output gate SHACL check passed
print(result["observation_iri"])  # IRI of the PROV-O ObservationRecord stored
print(result["prov"])             # Full provenance dict: model, timestamp, confidence
```

### Supported LLM adapters

| Adapter | `adapter=` key | Default model | Install |
|---|---|---|---|
| Anthropic Messages API | `"anthropic"` | `claude-sonnet-4-5` | `pip install anthropic` |
| OpenAI Chat Completions | `"openai"` | `gpt-4o` | `pip install openai` |
| Google Vertex AI (Gemini) | `"vertex"` | `gemini-1.5-pro` | `pip install google-cloud-aiplatform` |
| Ollama (local) | `"ollama"` | `llama3` | Ollama server running at `localhost:11434` |

All adapters are optional — the core runtime modules (`grounder`, `assembler`, `input_gate`, `output_gate`) have zero external dependencies. Install only the adapter you need. The Anthropic adapter uses prompt caching on the system prompt for reduced latency and cost.

### Runtime MCP tools

The runtime phase generates `output/jsonld/runtime-mcp-tools.json` with four MCP tool definitions: `ground_data`, `assemble_payload`, `validate_response`, and `ask_ontology`. These tools let any MCP-compatible agent call the runtime pipeline directly.

### What the runtime layer does NOT do

The runtime layer is not a replacement for the toolkit pipeline. It does not generate ontologies, create SHACL shapes, or manage database schemas. Those are the pipeline's responsibility. The runtime layer is strictly a consumption layer — it reads the pipeline's outputs and uses them to power governed, auditable LLM interactions.

The runtime layer also does not choose which LLM to use. That is an enterprise decision. The payload it assembles is LLM-agnostic, and adapters for Anthropic, OpenAI, Google Vertex, and Ollama handle API-specific mechanics while the semantic payload remains identical.

### Status — ✓ Complete (Apr 2026)

| Component | Status | Output |
|---|---|---|
| FlavorRegistry | ✓ Complete | 5 starter flavors, auto-discovery from `runtime/flavors/` |
| Grounder | ✓ Complete | JSON-LD nodes with `@type`, ontology IRI bindings, PROV-O grounding record |
| InputGate | ✓ Complete | SHACL acceptance screening, rejection log to `semantic_loss_log` |
| PayloadAssembler | ✓ Complete | 5-component payload, token budget, LLM-agnostic dict output |
| OutputGate | ✓ Complete | SHACL response validation, PROV-O stamping, `ObservationRecord` storage |
| RuntimeClient | ✓ Complete | Full pipeline in one call, async support, 4 LLM adapters |
