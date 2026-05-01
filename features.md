# Features & Capabilities

Detailed reference for what the toolkit produces, how it's structured, and what each phase and runtime layer adds. For install and onboarding see [install.md](install.md). For the 5-minute integration recipe see [docs/integrate.md](docs/integrate.md). For governance thresholds, exit gates, and CQ-test matrix see [gates.md](gates.md).

---

## Capability map

The toolkit is organised in tiers. Most projects use Tier 1 only — everything else is opt-in.

### Tier 1 — Core pipeline (always run)

Generates the OWL ontology, SHACL shapes, JSON-LD context, mapping workbook, and HTML report from any relational schema.

| Phase | What runs | Output |
|---|---|---|
| Onboard (`onboard.py`) | Interactive wizard for new projects | Schema, seed data, scope charter, CQ catalog |
| 1 — Foundation | Schema introspection | Annotated class and property inventory |
| 2 — Modeling | OWL 2 generator | `enterprise.ttl`, `events.ttl`, `provenance.ttl` |
| 3 — Validation | SHACL generator | `enterprise-shapes.ttl`, `agent-gate.ttl` |
| 4 — Mapping | Semantic loss detector | Mapping workbook, semantic loss report, orphan analysis |
| 5 — Exchange | JSON-LD + SKOS + MCP | Context file, sample payloads, MCP tool definitions, vocabulary |
| TMF | TM Forum alignment | SID OWL hierarchy (24 APIs, 13 CQs) |
| test | CQ runner + governance scorer | 18+ SPARQL CQ tests, scorecard |
| report | HTML reporter | Self-contained run summary |

### Tier 2 — Choose what you need

| Group | Phases | Why you'd add it |
|---|---|---|
| **Runtime layer** — connect ontology to LLMs | `runtime` | SHACL input/output gates, OWL grounding, prompt assembly, 5 LLM adapters (Anthropic, OpenAI, Vertex, Ollama, OCI). See §8. |
| **Drift monitoring** — production-grade | `drift`, `monitor` | OWL hierarchy + SHACL shapes drive `drift_monitor` (infodrift) entity registration. Drift events become PROV-O records. See §9 + [examples/infodrift/](../examples/infodrift/). |
| **Graph publishing** | `publish` | One-command upload to Fuseki / Stardog / Oxigraph / Neptune / GraphDB with named-graph sensitivity partitioning. |
| **Industry templates** | `--industry <name>` | 10 pre-built domains: telecom, healthcare, finance, manufacturing, retail, energy (IEC CIM), logistics, government (DCAT/INSPIRE), insurance, pharma (IDMP). |
| **Wizard (browser)** | `wizard/app.py` | Flask web app — drag-and-drop entity/relationship builder. |

### Tier 3 — Advanced / opt-in

These are real features for specific needs but distract on day 1. Each has its own §-number below.

- **Conflict resolution** — multi-agent 3-tier resolution, PROV-O invalidation (§ Phase 2B in §9)
- **Alignment & federation (basic)** — DOLCE/FOAF/Schema.org/SOSA alignment + SPARQL federation
- **Modular OWL** — `modules.json`, `master.ttl` with `owl:imports`, cycle detection
- **Log entity discovery** — NLP co-occurrence on log corpora (spaCy)
- **TMF630 Task + Bulk** — TmfTask / Import / Export OWL+SHACL
- **Reasoner** — ROBOT-driven OWL 2 consistency (ELK / HermiT)
- **Agentic Semantic Memory** — recall/diff/consolidate (§10)
- **Autonomous Ontology Evolution** — proposal store, anomaly monitor, review workflow (§11)
- **Cross-Enterprise Federation** — Ed25519-signed manifests, trust handshake, W3C CG draft (§12)
- **Regulatory Compliance Evidence** — EU AI Act, Basel IV, HIPAA, Ofcom (§13)
- **Ontology-Bounded Vector Retrieval** — hybrid retriever, 5 vector store adapters (§14)

Run `python3 toolkit.py --help` for every flag.

---

## Contents

1. [Repository structure](#1-repository-structure)
2. [Generated artifacts explained](#2-generated-artifacts-explained)
3. [Semantic metadata control table](#3-semantic-metadata-control-table)
4. [Semantic loss detection](#4-semantic-loss-detection)
5. [TM Forum alignment](#5-tm-forum-alignment)
6. [Standards used](#6-standards-used)
7. [Extending the toolkit](#7-extending-the-toolkit)
8. [Runtime — connecting the toolkit to AI and LLMs](#8-runtime--connecting-the-toolkit-to-ai-and-llms)
9. [Phase 3 — Scale & Community](#9-phase-3--scale--community)
10. [Generation 2 — Agentic Semantic Memory Layer](#10-generation-2--agentic-semantic-memory-layer)
11. [Generation 2 — Autonomous Ontology Evolution](#11-generation-2--autonomous-ontology-evolution)
12. [Generation 2 — Cross-Enterprise Federated Ontology Network](#12-generation-2--cross-enterprise-federated-ontology-network)
13. [Generation 2 — Regulatory AI Compliance Evidence Engine](#13-generation-2--regulatory-ai-compliance-evidence-engine)
14. [Generation 2 — Ontology-Bounded Vector Retrieval](#14-generation-2--ontology-bounded-vector-retrieval)

---

## 1. Repository structure

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
│       ├── ollama_adapter.py    ← Ollama local LLM
│       └── oci_adapter.py       ← Oracle Cloud (OCI Generative AI)
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

## 2. Generated artifacts explained

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

## 3. Semantic metadata control table

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

## 4. Semantic loss detection

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

## 5. TM Forum alignment

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

## 6. Standards used

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

## 7. Extending the toolkit

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

## 8. Runtime — connecting the toolkit to AI and LLMs

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
| Oracle Cloud (OCI Generative AI) | `"oci"` | `cohere.command-r-plus` | `pip install oci` — see OCI setup in [README.md](README.md#oci-generative-ai-setup) |

All adapters are optional — the core runtime modules (`grounder`, `assembler`, `input_gate`, `output_gate`) have zero external dependencies. Install only the adapter you need. The Anthropic adapter uses prompt caching on the system prompt for reduced latency and cost.

### Runtime MCP tools

The runtime phase generates `output/jsonld/runtime-mcp-tools.json` with four MCP tool definitions: `ground_data`, `assemble_payload`, `validate_response`, and `ask_ontology`. These tools let any MCP-compatible agent call the runtime pipeline directly.

### What the runtime layer does NOT do

The runtime layer is not a replacement for the toolkit pipeline. It does not generate ontologies, create SHACL shapes, or manage database schemas. Those are the pipeline's responsibility. The runtime layer is strictly a consumption layer — it reads the pipeline's outputs and uses them to power governed, auditable LLM interactions.

The runtime layer also does not choose which LLM to use. That is an enterprise decision. The payload it assembles is LLM-agnostic, and adapters for Anthropic, OpenAI, Google Vertex, and Ollama handle API-specific mechanics while the semantic payload remains identical.

### Runtime components

| Component | Output |
|---|---|
| FlavorRegistry | 5 starter flavors, auto-discovery from `runtime/flavors/` |
| Grounder | JSON-LD nodes with `@type`, ontology IRI bindings, PROV-O grounding record |
| InputGate | SHACL acceptance screening, rejection log to `semantic_loss_log` |
| PayloadAssembler | 5-component payload, token budget, LLM-agnostic dict output |
| OutputGate | SHACL response validation, PROV-O stamping, `ObservationRecord` storage |
| RuntimeClient | Full pipeline in one call, async support, 4 LLM adapters |

### 8.x OCI Generative AI setup

The runtime layer ships with an Oracle Cloud Infrastructure (OCI) adapter alongside Anthropic, OpenAI, Vertex AI, and Ollama. Use it when you want to route the toolkit's governed payloads to Cohere or Llama models hosted on OCI Generative AI.

**1. Install the SDK**

```bash
pip install oci
```

**2. Configure credentials**

The adapter follows the standard OCI config-file pattern documented at [docs.oracle.com — Python SDK Configuration](https://docs.oracle.com/en-us/iaas/tools/python/latest/configuration.html). Create `~/.oci/config` (or run `oci setup config`) with at least:

```ini
[DEFAULT]
user=ocid1.user.oc1..<your-user-ocid>
fingerprint=<api-key-fingerprint>
key_file=~/.oci/oci_api_key.pem
tenancy=ocid1.tenancy.oc1..<your-tenancy-ocid>
region=us-chicago-1
```

**3. Set the compartment**

OCI Generative AI requires a compartment OCID for routing and billing:

```bash
export OCI_COMPARTMENT_ID=ocid1.compartment.oc1..<your-compartment-ocid>
```

Optional environment overrides:

| Variable | Default | Purpose |
|---|---|---|
| `OCI_CONFIG_FILE` | `~/.oci/config` | Path to the OCI config file |
| `OCI_CONFIG_PROFILE` | `DEFAULT` | Profile name within the config file |
| `OCI_GENAI_ENDPOINT` | `https://inference.generativeai.us-chicago-1.oci.oraclecloud.com` | Service endpoint (set this for non-Chicago regions) |

**4. Use it from the runtime**

```python
from runtime import RuntimeClient

client = RuntimeClient(
    db_path="db/enterprise.db",
    adapter="oci",
    model="cohere.command-r-plus",   # or a Meta/Llama model OCID
)

result = client.ask(question="Which network functions are degraded?", flavor="network-ops")
print(result["answer"])
```

The adapter defaults to the Cohere request shape. To target a Meta/generic model, instantiate `OCIAdapter` directly with `provider="meta"` and pass it via `RuntimeClient(adapter=<instance>)`.

---

## 9. Phase 3 — Scale & Community

Phase 3 completes the toolkit with deployment infrastructure, additional industry verticals, ML monitoring integration, and a browser-based authoring interface. All 8 items are implemented in v2.0. Exit-gate checklist in [gates.md §2](gates.md#2-phase-3-exit-gates).

### 9.1 Graph Store Publishing

One-command upload of all Turtle artifacts to a supported graph store with named-graph partitioning by sensitivity tier.

```bash
# Apache Jena Fuseki
python3 toolkit.py --phase publish --store fuseki --endpoint http://localhost:3030/dataset

# Stardog
python3 toolkit.py --phase publish --store stardog --endpoint http://localhost:5820/mydb \
  --gstore-user admin --gstore-password admin

# Oxigraph (Docker)
python3 toolkit.py --phase publish --store oxigraph --endpoint http://localhost:7878

# Amazon Neptune (SigV4 — set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars)
python3 toolkit.py --phase publish --store neptune \
  --endpoint https://my-cluster.neptune.amazonaws.com:8182 --aws-region us-east-1

# Ontotext GraphDB
python3 toolkit.py --phase publish --store graphdb --endpoint http://localhost:7200/repositories/myrepo
```

Named-graph partitioning:

| Sensitivity | Named Graph |
|---|---|
| Public | `https://ontology.example.com/graph/public` |
| Internal | `https://ontology.example.com/graph/internal` |
| Confidential | `https://ontology.example.com/graph/confidential` |
| Restricted | `https://ontology.example.com/graph/restricted` |

Output: `output/reports/publish_summary.json`

### 9.2 Docker Compose Kit

Full-stack demo in one command — toolkit + Oxigraph SPARQL endpoint + SHACL validation service + nginx API gateway with TMF URL patterns.

```bash
# Start the full stack
docker-compose up -d

# Browser wizard
open http://localhost:5000

# Oxigraph SPARQL endpoint
open http://localhost:7878

# API gateway (TMF URL patterns)
open http://localhost:8080

# Publish pipeline output to Oxigraph
docker-compose exec toolkit python toolkit.py --phase publish \
  --store oxigraph --endpoint http://oxigraph:7878
```

Pre-loaded example: telecom schema with TMF seed data.

### 9.3 Drift Detection Ontology Extension

Extends `PerformanceIndicator` with ML monitoring metrics as first-class OWL citizens.

```bash
python3 toolkit.py --phase drift
```

**Generates:**
- `output/ontology/drift.ttl` — `DriftObservation` OWL subclass hierarchy
  - `PSIDriftObservation` — Population Stability Index (WARNING >0.1, CRITICAL >0.25)
  - `KLDriftObservation` — Kullback-Leibler divergence
  - `JSDriftObservation` — Jensen-Shannon divergence (bounded 0–1)
  - `CalibrationDriftObservation` — Expected Calibration Error
  - `LogTemplateDriftObservation` — log template cluster shift
- `output/shapes/drift-shapes.ttl` — SHACL shapes with threshold enforcement
- `output/vocab/drift-skos.ttl` — drift taxonomy (10 SKOS concepts)

### 9.4 Industry Templates (10 total)

Load a pre-built domain model instead of starting from scratch. 5 new templates added in Phase 3:

```bash
python3 toolkit.py --phase templates --template energy_utilities
python3 toolkit.py --phase templates --template logistics_supply_chain
python3 toolkit.py --phase templates --template government
python3 toolkit.py --phase templates --template insurance
python3 toolkit.py --phase templates --template pharmaceuticals
python3 toolkit.py --phase templates --template all   # all 5 at once
```

Or load directly from the browser wizard's template picker.

| Template | Standard Alignment | Entities | CQs |
|---|---|---|---|
| energy_utilities | IEC CIM 61968/61970 | 8 | 10 |
| logistics_supply_chain | GS1, Schema.org | 8 | 10 |
| government | DCAT v3, INSPIRE, FOAF | 8 | 10 |
| insurance | ACORD, FIBO | 8 | 10 |
| pharmaceuticals | IDMP (ISO 11616), HL7 FHIR R4 | 9 | 10 |
| telecom | TM Forum SID v23.0 | existing | 13 |
| healthcare | HL7 FHIR | existing | 8 |
| finance | FIBO | existing | 8 |

### 9.5 Modular OWL

Multi-team ontology authoring with `owl:imports` support, acyclicity enforcement, and IRI conflict detection.

```bash
python3 toolkit.py --phase modular
```

**Generates:**
- `output/ontology/master.ttl` — master ontology `owl:imports`-ing all modules
- `output/ontology/modules.json` — full module manifest (IRIs, versions, import graph)

**Checks performed:**
1. **Acyclicity** — detects import cycles that would break OWL reasoners
2. **IRI conflict detection** — flags the same IRI defined in multiple modules
3. **Per-module versioning** — reads `owl:versionInfo` from each `.ttl` file

### 9.6 Log Entity Discovery (NLP)

Statistical co-occurrence analysis over log corpora to surface candidate entities not yet in the ontology. Requires spaCy.

```bash
# Install NLP deps first
pip install spacy && python -m spacy download en_core_web_sm

# Run discovery
python3 toolkit.py --phase discover --log-path /var/log/app.log
python3 toolkit.py --phase discover --log-path /var/log/*.log --min-freq 5
```

**Outputs:**
- `output/reports/entity_discovery_candidates.csv` — top 200 candidates with TF-IDF score, frequency, and co-occurring terms
- `output/reports/entity_discovery_summary.json` — pipeline summary

Candidates are for expert review only — nothing is auto-added to the ontology.

### 9.7 TMF630 Task + Bulk Operations (Parts 4 & 7)

Required for full TMF Open API conformance certification.

```bash
python3 toolkit.py --phase tmf630
```

**Generates:**
- `output/ontology/tmf630-task-bulk.ttl` — `TmfTask`, `TmfImportJob`, `TmfExportJob` OWL classes + SHACL shapes
- `output/jsonld/tmf630-task-mcp-tools.json` — 4 MCP tools: `create_task`, `poll_task_status`, `create_import_job`, `create_export_job`
- DB tables: `tmf_task`, `tmf_import_job`, `tmf_export_job`
- 3 new TMF CQ tests (CQ-TMF-14/15/16)

### 9.8 Browser Wizard

Web-based equivalent of `onboard.py` with a drag-and-drop entity/relationship builder.

```bash
python3 toolkit.py --phase wizard
# or directly:
python3 wizard/app.py
```

Open `http://localhost:5000` in your browser.

**Features:**
- 6-step wizard: Domain → Entities → Events → Relationships → CQs → Generate
- Template picker (loads any YAML template into the wizard)
- One-click pipeline execution from the browser
- Real-time pipeline log streaming
- Artifact browser (download generated files directly from the UI)
- Session persistence (`.wizard_session.json`)

**API endpoints** (for integration):

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | GET | Browser wizard UI |
| `/api/session` | GET/POST | Load / save session JSON |
| `/api/templates` | GET | List available templates |
| `/api/template/<name>` | GET | Load template as session |
| `/api/generate` | POST | Run pipeline phases |
| `/api/pipeline/status` | GET | Poll pipeline progress |
| `/api/output` | GET | List generated artifacts |
| `/api/output/<subdir>/<file>` | GET | Download artifact |

---

## 10. Generation 2 — Agentic Semantic Memory Layer

**Workstream 1 — Generation 2.** Exit gates in [gates.md §3](gates.md#3-workstream-1-exit-gates--agentic-semantic-memory).

Transforms the ontology graph store from a static semantic schema into the long-term working memory of AI agents. Every reasoning chain, observation, and decision is now a queryable, temporally-ordered fact. Agents build on prior reasoning rather than starting from scratch on every invocation.

**Builds on:** PROV-O infrastructure · ObservationRecord store · RuntimeClient · Graph store publishing · Conflict resolution (v2.0)

### 10.1 Memory API Core (`runtime/memory.py`)

Three primary memory operations — all return typed JSON-LD objects ready for payload injection:

```python
from runtime.memory import AgentMemory

mem = AgentMemory(db_path="db/enterprise.db")

# Recall prior reasoning about a subject
results = mem.recall("degraded network functions", flavor="network-ops")
print(f"Found {results['result_count']} prior observations")

# Find where two agents disagreed on the same entity
diff = mem.diff("network-ops", "fault-management", subject="AMF-East-01")
print(f"Disagreements: {diff['disagreement_count']}")

# Point-in-time snapshot — what did agents know at 02:00 on 10 April?
snapshot = mem.snapshot(at="2026-04-10T02:00:00+00:00", entity_iri="AMF-East-01")

# Run consolidation — reduce graph size, escalate conflicts
summary = mem.consolidate(older_than_days=90)
print(f"Graph reduced by {summary['reduction_pct']}%")
```

| Method | Description |
|---|---|
| `recall(query, flavor, time_range, record_type, limit)` | SPARQL over ObservationRecord graph, filtered by time window and flavor |
| `diff(agent_a, agent_b, subject, limit)` | Assertions where two agent flavors disagreed on the same entity |
| `consolidate(older_than_days, dry_run)` | Three-strategy graph consolidation — supersession, compression, conflict escalation |
| `snapshot(at, entity_iri, flavor)` | Point-in-time view: what did agents know at timestamp T? |
| `influence_graph(agent, limit)` | `prov:wasInfluencedBy` graph — which agents build on whose prior reasoning |

### 10.2 Temporal Reasoning Layer (`runtime/temporal_queries/`)

Five parameterised SPARQL templates for temporal graph patterns:

```python
from runtime.temporal_queries import fill_template

# Point-in-time snapshot
sparql = fill_template("TQ-01", {
    "AT_TIMESTAMP": "2026-04-10T02:00:00Z",
    "ENTITY_IRI":   "AMF-East-01",
})

# Sliding-window KPI aggregation
sparql = fill_template("TQ-02", {
    "WINDOW_START": "2026-04-01T00:00:00Z",
    "WINDOW_END":   "2026-04-10T23:59:59Z",
    "KPI_TYPE":     "throughput",
    "ENTITY_IRI":   "",
})
```

| Template | Purpose |
|---|---|
| `TQ-01` | Point-in-time ontology snapshot |
| `TQ-02` | Sliding-window KPI aggregation over PerformanceIndicator time series |
| `TQ-03` | Bi-temporal query (valid-time × transaction-time) |
| `TQ-04` | Temporal diff between two agent flavors on the same entity |
| `TQ-05` | Provenance invalidation chain traversal |

All templates are in `runtime/temporal_queries/` as `.sparql` files with `{{PARAM}}` placeholders.

### 10.3 Cross-Agent Memory Sharing + PROV-O

Memory sharing policies are defined per-flavor in the flavor JSON files under `runtime/flavors/`.  Each flavor declares:

- `can_read_from` — which other flavors' observations it may query
- `can_be_read_by` — which other flavors may read its observations
- `max_readable_tier` — highest sensitivity tier accessible
- `prov_influence_enabled` — whether `prov:wasInfluencedBy` links are emitted

Access enforcement via the `FlavorRegistry`:

```python
from runtime.flavor_registry import FlavorRegistry

reg = FlavorRegistry()

# Check if network-ops may read fault-management observations
allowed = reg.check_memory_access(
    requesting_flavor="network-ops",
    target_flavor="fault-management",
    target_tier="Internal",
)

# Get the full sharing policy for a flavor
policy = reg.get_memory_sharing_policy("compliance")
# → {"can_read_from": [...], "can_be_read_by": [...], ...}
```

Default sharing matrix:

| Flavor | Can read from | Can be read by |
|---|---|---|
| `network-ops` | network-ops, fault-management | fault-management, compliance |
| `fault-management` | network-ops, fault-management | network-ops, compliance |
| `compliance` | all flavors (up to Confidential) | compliance only |
| `billing` | billing only | compliance only |
| `customer` | customer only | billing, compliance |

### 10.4 Memory Consolidation Daemon (`runtime/consolidation_daemon.py`)

Background process applying three consolidation strategies on a configurable schedule:

```bash
# One-shot consolidation pass
python3 runtime/consolidation_daemon.py --db db/enterprise.db --once

# Dry-run (report only, no DB changes)
python3 runtime/consolidation_daemon.py --db db/enterprise.db --once --dry-run

# Scheduled mode (reads cron from consolidation_config.json, default: nightly at 02:00)
python3 runtime/consolidation_daemon.py --db db/enterprise.db
```

**Strategies:**

| Strategy | What it does |
|---|---|
| Supersession | MEASURED observation ⟹ marks prior INFERRED as `prov:wasInvalidatedBy` |
| Temporal compression | Aggregates point observations >90d old into summary records, invalidates originals |
| Conflict escalation | Contradicting MEASURED observations → raises `ConflictEvent` for human review |

Configure via `runtime/consolidation_config.json` — retention by sensitivity tier, schedule cron, alert thresholds, per-strategy on/off switches.

### 10.5 RuntimeClient SDK Update

`RuntimeClient.ask()` extended with memory-aware parameters:

```python
from runtime.client import RuntimeClient

client = RuntimeClient(db_path="db/enterprise.db", adapter="anthropic")

# Memory-augmented query — prepends prior reasoning to the payload
result = client.ask(
    question="Which NFs are currently degraded?",
    flavor="network-ops",
    memory_recall=True,          # prepend relevant prior observations
    memory_recall_limit=5,       # top-5 most recent matching observations
)
print(f"Memory context injected: {result['memory_context_count']} prior observations")

# Standalone recall — returns typed JSON-LD
prior = client.remember("AMF-East-01", flavor="network-ops")
print(f"Found {prior['result_count']} prior observations about AMF-East-01")
```

New SDK additions:
- `RuntimeClient.ask(..., memory_recall=True)` — injects prior reasoning into payload
- `RuntimeClient.ask(..., memory_recall_limit=N)` — caps prior context size
- `RuntimeClient.ask(..., memory_time_range=(from, to))` — time-scopes the recall
- `RuntimeClient.remember(subject, flavor, limit, time_range)` — standalone recall
- `RuntimeClient.memory` property — exposes the `AgentMemory` instance directly

---

## 11. Generation 2 — Autonomous Ontology Evolution

**Workstream 2 — Generation 2.** Exit gates in [gates.md §4](gates.md#4-workstream-2-exit-gates--autonomous-ontology-evolution).

Closes the loop between what AI agents observe in production and what the ontology formally models. A monitoring daemon detects patterns the ontology doesn't yet capture, scores them as evolution candidates across five dimensions, routes them through a human review gate, and auto-increments the ontology version when an approved axiom passes the full CI/CD reasoner + SPARQL CQ gate.

> **Critical distinction:** This workstream does not auto-update the ontology. It surfaces *proposals*. Every proposed change passes through a human review gate and the existing CI/CD pipeline before any axiom is added. The autonomy is in detection and scoring — governance remains with the domain expert.

**Builds on:** ObservationRecord store · NLP log entity discovery · CI/CD pipeline · SHACL shapes · SPARQL CQ tests (v2.0, WS1)

### 11.1 Proposal store + SHACL shape

- **SQL:** `ontology_evolution_proposals` + `ontology_version_ledger` tables in [db/schema.sql](db/schema.sql)
- **SHACL:** [output/shapes/evolution-shapes.ttl](output/shapes/evolution-shapes.ttl) — validates proposal_id, type, turtle, sparql, strategy, score, and an approval gate that blocks APPROVED rows without `reviewer_id` + semver `version_target`.

### 11.2 Production anomaly monitor (`src/evolution_monitor.py`)

Four detection strategies — each writes scored PENDING proposals to the store:

| Strategy | Trigger | Proposal type |
|---|---|---|
| `SHACL_VIOLATION_ACCUMULATION` | Repeated `sh:in` rejections on the same column | `NEW_CONSTRAINT` (extend enumeration) |
| `CARDINALITY_BREACH` | FK-like IRI refs in payloads with no ObjectProperty counterpart | `NEW_PROPERTY` |
| `CLASS_COOCCURRENCE` | Entity pairs repeatedly observed together without a declared relationship | `NEW_PROPERTY` |
| `NLP_CANDIDATE_PROMOTION` | Log-discovery candidates seen in ≥N confirmed observations | `NEW_CLASS` |

```bash
# Run all 4 strategies + score all PENDING proposals
python3 toolkit.py --phase evolve

# Single-strategy run
python3 toolkit.py --phase evolve --strategy NLP_CANDIDATE_PROMOTION --min-evidence 5
```

### 11.3 Candidate scoring engine (`src/evolution_scorer.py`)

Composite 0.0–1.0 score from a weighted blend of five dimensions:

| Dimension | Weight | What it measures |
|---|---|---|
| `evidence_volume` | 0.25 | Distinct occurrences of the candidate |
| `evidence_recency` | 0.20 | Exponential decay on latest matching observation (30-day half-life) |
| `cross_domain` | 0.20 | Number of distinct `source_ref` flavors that reference it |
| `consistency_risk` | 0.20 | 1 − reasoner-hazard proxy by proposal type |
| `schema_alignment` | 0.15 | Penalty if the term overlaps an existing class or metadata label |

Bands: **≥ 0.80 → REVIEW_NOW** · **0.50–0.80 → WEEKLY_BATCH** · **< 0.50 → CANDIDATE**.

### 11.4 Human review workflow

**CLI:**
```bash
# List PENDING proposals sorted by composite score
python3 toolkit.py --phase evolve --review

# APPROVE / REJECT / DEFER
python3 toolkit.py --phase evolve --action APPROVE \
    --proposal-id 3c7d1e80-... --version-target 1.2.0 \
    --reviewer-id nrohilla@fibonacci.example --note "extends CQ-003"

# Apply an APPROVED proposal through the CI/CD auto-versioner
python3 toolkit.py --phase evolve --apply 3c7d1e80-... --open-pr
```

**Browser wizard:** An *Evolution Review* tab is registered in [wizard/templates/index.html](wizard/templates/index.html). It lists PENDING proposals with band, score, and type; clicking a row opens a detail card rendering the proposed Turtle axiom, the evidence SPARQL, the dimensional breakdown, and APPROVE / REJECT / DEFER / Apply controls. All actions route through the Flask API (`/api/evolve/…`).

### 11.5 CI/CD auto-versioning on approval (`src/evolution_reviewer.py::apply_approved`)

On an APPROVED proposal:

1. The candidate axiom is appended to `output/ontology/enterprise.ttl` inside a fenced `# ── Evolution proposal <id> ──` block.
2. `owl:versionIRI` / `owl:versionInfo` are bumped to MINOR+1 (or an explicit `--version-target`).
3. The ROBOT reasoner re-runs; any unsatisfiable class rolls the change back automatically.
4. The SPARQL CQ suite re-runs; any failure rolls the change back automatically.
5. A row is appended to `ontology_version_ledger` recording `reasoner_status`, `shacl_status`, `sparql_status`, and the (optional) GitHub PR URL.
6. If `--open-pr` is set and `gh` is on PATH, a draft PR is opened on the branch `evolve/<pid>-v<version>`.

Governance retains the final gate: the domain expert reviews the PR before merge.

### 11.6 Deliverables

| Artefact | Path |
|---|---|
| Evolution monitor (4 strategies) | [src/evolution_monitor.py](src/evolution_monitor.py) |
| Candidate scoring engine (5 dimensions) | [src/evolution_scorer.py](src/evolution_scorer.py) |
| Review workflow + CI/CD auto-versioner | [src/evolution_reviewer.py](src/evolution_reviewer.py) |
| Proposal store + version ledger DDL | [db/schema.sql](db/schema.sql) |
| SHACL proposal-validation shapes | [output/shapes/evolution-shapes.ttl](output/shapes/evolution-shapes.ttl) |
| Wizard Evolution Review tab | [wizard/templates/index.html](wizard/templates/index.html) + [wizard/app.py](wizard/app.py) |
| CLI wiring | [toolkit.py](toolkit.py) — `--phase evolve` |

---

## 12. Generation 2 — Cross-Enterprise Federated Ontology Network

**Workstream 3 — Generation 2.** Exit gates in [gates.md §5](gates.md#5-workstream-3-exit-gates--cross-enterprise-federation).

Extends the toolkit from single-enterprise to multi-enterprise semantic interoperability. Each organisation retains full sovereignty over its ontology: partners publish cryptographically signed capability manifests declaring what they expose, to whom, and at what sensitivity tier. A boundary gate validates every inbound triple before any partner data enters local reasoning scope.

> **Design rule:** no partner data ever persists in the local graph. Federated query results are *transient* — provenance-stamped, sensitivity-checked, and discarded once the requesting agent has consumed them.

**Builds on:** SPARQL federation · Named-graph RBAC · Ontology alignment (DOLCE/FOAF/Schema.org/SOSA) · W3C Community Group (v2.0)

### 12.1 Partner capability registry (`federation/partner_registry.py`)

Two back-ends kept in step:
- **`federation/partner_registry.json`** — committed seed, human-readable, one row per partner.
- **`federation_partners`** SQLite table — fast runtime lookup for the router and trust ledger.

Each partner row carries partner IRI, SPARQL endpoint, Ed25519 public key, exposed class whitelist, `max_shareable_tier` (capped at `Confidential` — `Restricted` is never federable), and the current `trust_state` on the 6-step ladder.

```bash
# Register a partner from declared parameters
python3 toolkit.py --phase federate \
    --register-partner https://partner.example.com/ontology \
    --partner-iri https://partner.example.com/ontology#self \
    --partner-endpoint https://partner.example.com/sparql \
    --partner-public-key <base64> \
    --exposed-classes "https://ontology.example.com/tmf/NetworkFunction,https://ontology.example.com/tmf/PerformanceIndicator" \
    --max-tier Internal

# Enumerate every registered partner
python3 toolkit.py --phase federate --list-partners
```

Set `ONTOLOGY_FED_REGISTRY=/tmp/test.json` to redirect the JSON registry during CI runs so the committed file is never mutated by tests.

### 12.2 Capability manifest generator + Ed25519 signing (`federation/manifest.py`)

Every enterprise publishes a signed JSON-LD capability manifest at a well-known URI (`/.well-known/ontology-capability.jsonld`). The manifest declares: ontology IRI, exposed classes/properties, sensitivity tier per class, inbound SHACL shape list, signer IRI, public key, validity window, and an Ed25519 signature.

Signing and verification are pure stdlib RFC 8032 (`federation/_crypto.py`) — no external crypto dependency. Canonical signing bytes exclude `fed:signature` and the derived `fed:payloadSha256` so `verify(sign(m))` is byte-for-byte deterministic.

```bash
# Generate the enterprise's Ed25519 keypair (secret persisted 0600)
python3 toolkit.py --phase federate --generate-keys --key-name enterprise

# Build + sign the local capability manifest
python3 toolkit.py --phase federate --build-manifest \
    --enterprise-iri https://my-enterprise.example.com/ontology#self \
    --exposed-classes "https://ontology.example.com/tmf/NetworkFunction,https://ontology.example.com/tmf/PerformanceIndicator"
```

Signed manifests are written under `federation/manifests/`.

### 12.3 Cross-enterprise SPARQL router (`federation/router.py`)

Extends intra-enterprise SPARQL federation to cross-enterprise queries. Pipeline:

1. Parse every `SERVICE <url>` clause and resolve the endpoint to a registered partner row — unknown endpoints are rejected as `UNREGISTERED_PARTNER`.
2. Verify the requesting flavor's `sensitivity_tier` is ≤ the partner's `max_shareable_tier`; otherwise `FLAVOR_DENIED`.
3. Rewrite the query with a mandatory `FILTER (?tier IN (…allowed…))` layer — `Restricted` is never even requested.
4. Dispatch to the partner endpoint via the SPARQL HTTP protocol (online) or via an injected fixture map (offline — the CQ-FED test suite uses this path).
5. Hand every returned row to the boundary validator (§12.4) before surfacing it to the caller.
6. Append a row to `federation_query_log` with partner ID, flavor, original/rewritten query, accepted-triple count, violation count, duration.

### 12.4 Sensitivity enforcement at the boundary (`federation/boundary.py` + `output/shapes/federation-shapes.ttl`)

Three invariants enforced on every inbound row:

| Invariant | Failure mode |
|---|---|
| `Restricted`-tier triples are an absolute block | Rejected + CRITICAL entry to `semantic_loss_log` |
| `owl_class` must be in the partner's `exposedClasses` whitelist | Rejected + HIGH entry to `semantic_loss_log` |
| `prov:wasAttributedTo` must name the partner IRI | Rejected + HIGH entry to `semantic_loss_log` |

Clusters of violations auto-open a `NEW_CONSTRAINT` row in `ontology_evolution_proposals` so governance can tighten the partner's exposure agreement through the existing Workstream 2 review flow. Accepted rows are stamped with `fed:sourcePartner` + `fed:sensitivityTier` so downstream joins can separate local from federated facts.

### 12.5 Trust-bootstrap protocol (`federation/trust.py`)

3-step state machine per bilateral relationship, backed by the append-only `federation_trust_ledger` table:

```
PROPOSED ─ handshake() ▶ HANDSHAKE_SENT ─ countersign() ▶ COUNTERSIGNED ─ activate() ▶ ACTIVE
                                                                            │
                                                           valid_until      ▼
                                                                            EXPIRED
```

```bash
# Kick off the handshake with a remote partner
python3 toolkit.py --phase federate --handshake https://partner.example.com \
    --partner-iri https://partner.example.com/ontology#self \
    --key-name enterprise
```

Each transition (`MANIFEST_SENT`, `MANIFEST_RECEIVED`, `COUNTERSIGNED`, `ACTIVATED`, `TEST_QUERY`, `REVOKED`, `EXPIRED`) is persisted with the signature and SHA-256 of the signed payload. `expire_overdue()` auto-demotes ACTIVE partners past their `valid_until`.

### 12.6 W3C interoperability protocol specification

Formal Community Group Draft Report at [`federation/specs/cross-enterprise-ontology-interop.md`](federation/specs/cross-enterprise-ontology-interop.md). Covers:

- **§3** capability manifest format (normative JSON-LD schema)
- **§4** trust-bootstrap handshake (normative protocol + state machine)
- **§5** federation query patterns (informative SPARQL examples)
- **§6** sensitivity enforcement (normative SHACL profile)
- **§7** conformance criteria (RFC 2119)
- **§8** security considerations

Reference implementation: the toolkit's `federation/` module.

### 12.7 Deliverables

| Artefact | Path |
|---|---|
| Partner registry (JSON seed) | [federation/partner_registry.json](federation/partner_registry.json) |
| Partner registry (code) | [federation/partner_registry.py](federation/partner_registry.py) |
| Capability manifest generator | [federation/manifest.py](federation/manifest.py) |
| Ed25519 primitives (RFC 8032) | [federation/_crypto.py](federation/_crypto.py) |
| Cross-enterprise SPARQL router | [federation/router.py](federation/router.py) |
| Boundary validator | [federation/boundary.py](federation/boundary.py) |
| Trust-bootstrap protocol | [federation/trust.py](federation/trust.py) |
| Federation SHACL shapes | [output/shapes/federation-shapes.ttl](output/shapes/federation-shapes.ttl) |
| W3C CG draft report | [federation/specs/cross-enterprise-ontology-interop.md](federation/specs/cross-enterprise-ontology-interop.md) |
| DDL additions | [db/schema.sql](db/schema.sql) (`federation_partners`, `federation_query_log`, `federation_trust_ledger`) |
| CLI wiring | [toolkit.py](toolkit.py) — `--phase federate` |

---

## 13. Generation 2 — Regulatory AI Compliance Evidence Engine

**Workstream 4 — Generation 2.** Exit gates in [gates.md §6](gates.md#6-workstream-4-exit-gates--regulatory-ai-compliance).

Turns the toolkit's existing governance outputs — PROV-O chains, SHACL validation records, governance scorecard, SPARQL CQ results — into on-demand, signed, machine-verifiable evidence packages mapped to named regulatory frameworks. Compliance evidence becomes automatic rather than manually reconstructed.

> **Design rule:** compliance bundles are *immutable once signed*. The Ed25519 signature in `manifest.json` covers the SHA-256 of every file in the ZIP; any tamper with the ZIP breaks verification on a cold machine.

**Builds on:** PROV-O provenance · SHACL validation records · Governance scorecard (34 criteria) · ObservationRecord store · CI/CD pipeline (v2.0) · Federation Ed25519 primitives (Workstream 3)

### 13.1 Regulatory requirement registry (`compliance/registry.py`)

Every regulation is a single JSON file under `compliance/regulations/`. Ships with four pre-built frameworks:

| File | Framework | Effective | Jurisdiction |
|---|---|---|---|
| [eu-ai-act.json](compliance/regulations/eu-ai-act.json) | EU AI Act — Article 13 (Transparency and Provision of Information) | 2026-08-02 | European Union |
| [basel-iv-sr-11-7.json](compliance/regulations/basel-iv-sr-11-7.json) | Basel IV — SR 11-7 Supervisory Guidance on Model Risk Management | 2011-04-04 | United States |
| [hipaa-164-312.json](compliance/regulations/hipaa-164-312.json) | HIPAA Security Rule — §164.312 Technical Safeguards (AI Addendum) | 2003-04-21 | United States |
| [ofcom-network-transparency.json](compliance/regulations/ofcom-network-transparency.json) | Ofcom Network Transparency Code (AI-Assisted Network Operations) | 2025-03-26 | United Kingdom |

Each requirement maps to one of five toolkit artefact types: `SPARQL_CQ`, `SHACL_SHAPE`, `PROV_O_CHAIN`, `GOVERNANCE_SCORECARD_CRITERION`, or `OBSERVATION_RECORD`. Organisations add custom regulations simply by dropping a new JSON file that follows the schema — the loader validates it on read.

```bash
# List every loaded regulation
python3 toolkit.py --phase comply --list-regulations
```

Point `ONTOLOGY_REGULATIONS_DIR=/path/to/overlay` to use an alternate registry (useful in multi-tenant deployments).

### 13.2 Evidence assembler (`compliance/assembler.py`)

Given a regulation ID, an optional decision IRI, and an optional time range, the assembler walks every requirement and resolves it against the appropriate toolkit artefact. Each evidence item returns with status `SATISFIED` / `INSUFFICIENT` / `NOT_APPLICABLE` / `MISSING`, the source query or file, the raw result, and a human-readable note.

```bash
# Assemble evidence + export a signed bundle for one decision
python3 toolkit.py --phase comply \
    --regulation eu-ai-act \
    --decision https://ontology.example.com/enterprise/observation/obs-001
```

`pass_expression` is a tiny declarative DSL (`status in ('PASS','PASS-STRUCTURAL')`, `score >= 3`, `chain_depth >= 2`, `exists`) so custom regulations do not need Python code.

### 13.3 Signed compliance bundle exporter (`compliance/bundle.py`)

Packages evidence into a portable, tamper-evident ZIP containing:

| File | Contents |
|---|---|
| `manifest.json` | per-file SHA-256 digests + Ed25519 signature + public key |
| `evidence.jsonld` | signed JSON-LD evidence envelope |
| `sparql_results.csv` | all SPARQL CQ / scorecard evidence rows |
| `prov_chain.ttl` | Turtle serialisation of the decision's PROV-O chain |
| `shacl_report.txt` | SHACL shape evidence snapshot |
| `governance_scorecard.csv` | scorecard snapshot at assemble time |
| `evidence_summary.txt` | human-readable per-requirement summary |

Ed25519 signing uses the same stdlib RFC 8032 primitives as Workstream 3 (no external crypto dependency). Verification re-reads the ZIP from disk, validates every file digest against the manifest, and checks the signature against the embedded public key — passes on any cold machine with no prior state.

```bash
# Verify a bundle on a cold machine
python3 toolkit.py --phase comply --verify compliance/bundles/<bundle>.zip
```

Every exported bundle is registered in the `compliance_bundles` SQLite table (sensitivity = `Restricted`) so the graph carries an auditable pointer.

### 13.4 Regulation ↔ toolkit mapping + gap analysis (`compliance/mapping.py`)

Bidirectional index computed on the fly:

- **`by_regulation`** — `reg_id → [requirement → artefact]`
- **`by_artefact`** — `(artefact_type:selector) → [regulation + requirement]`

Powers two reports:

- **Uncovered requirements** — regulatory items whose artefact is missing from this toolkit run
- **Orphan artefacts** — toolkit CQs / shapes / scorecard rows that satisfy no regulation

```bash
python3 toolkit.py --phase comply --gap-analysis
```

Also produces the aggregate `coverage_score()` that feeds the new **Regulatory Evidence Coverage** scorecard criterion (% of loaded regulations at ≥80% coverage).

### 13.5 Compliance Dashboard (wizard)

New **Compliance Dashboard** tab in the browser wizard:

- Per-regulation coverage with green/amber/red traffic lights (`≥80%` / `≥50%` / below)
- One-click evidence assembly (regulation picker + optional decision IRI)
- Exported-bundle timeline with verification badge
- Gap-analysis panel with concrete remediation recommendations

Flask routes: `/api/comply/regulations`, `/api/comply/coverage`, `/api/comply/assemble`, `/api/comply/bundles`, `/api/comply/verify`, `/api/comply/gap`.

Every `python3 toolkit.py --phase report` (and every `--phase all` run) regenerates `output/reports/compliance_summary.html` and `compliance_summary.csv` alongside the toolkit HTML report.

### 13.6 Deliverables

| Artefact | Path |
|---|---|
| Registry loader | [compliance/registry.py](compliance/registry.py) |
| Pre-built regulations (×4) | [compliance/regulations/*.json](compliance/regulations/) |
| Evidence assembler | [compliance/assembler.py](compliance/assembler.py) |
| Signed bundle exporter + verifier | [compliance/bundle.py](compliance/bundle.py) |
| Mapping index + gap analysis | [compliance/mapping.py](compliance/mapping.py) |
| Dashboard summary generator | [compliance/dashboard.py](compliance/dashboard.py) |
| Wizard Compliance Dashboard tab | [wizard/templates/index.html](wizard/templates/index.html) + [wizard/app.py](wizard/app.py) (`/api/comply/*`) |
| DDL additions | [db/schema.sql](db/schema.sql) (`compliance_bundles`) |
| CLI wiring | [toolkit.py](toolkit.py) — `--phase comply` |

---

## 14. Generation 2 — Ontology-Bounded Vector Retrieval

**Workstream 5 · Branch:** `S5-Ontology-Bounded-Vector-Retrieval`. Exit gates in [gates.md §7](gates.md#7-workstream-5-exit-gates--ontology-bounded-vector-retrieval).

The OWL class hierarchy becomes a hard semantic filter on vector similarity search. Where RAG retrieves whatever is numerically closest in embedding space, ontology-bounded retrieval first constrains the search population by OWL class expression, then ranks within it by vector similarity. Precision increases; irrelevant-but-similar results are eliminated.

### Usage

```bash
# 1. Index every flavor's records as ontology-typed embeddings
python3 toolkit.py --phase embed

# 2. Query with an OWL class expression as a hard filter
python3 toolkit.py --phase retrieve \
    --flavor network-ops \
    --question "Which network functions are degraded or failed?" \
    --class-expression "tmf:NetworkFunction" \
    --top-k 5

# 3. Compare all three retrieval strategies side-by-side
python3 toolkit.py --phase retrieve \
    --flavor network-ops \
    --question "Show open critical alarms" \
    --class-expression "tmf:Alarm" \
    --strategy-compare

# 4. Run the benchmark suite
python3 toolkit.py --phase retrieve --benchmark
```

### SDK — `RuntimeClient.ask(retrieval="hybrid", ...)`

```python
from runtime.client import RuntimeClient

client = RuntimeClient(db_path="db/enterprise.db")
result = client.ask(
    question         = "Which network functions are degraded?",
    flavor           = "network-ops",
    retrieval        = "hybrid",
    class_expression = "tmf:NetworkFunction | tmf:Alarm",
    retrieval_k      = 5,
)
print(result["hybrid_context_count"], "ontology-bounded hits injected into payload")

# Retrieval-only (no LLM call):
hits = client.retrieve(
    question          = "What KPIs breached thresholds?",
    flavor            = "network-ops",
    class_expression  = "tmf:PerformanceIndicator",
    k                 = 5,
)
```

### Architecture

1. **Embedding pipeline** ([runtime/embeddings/pipeline.py](runtime/embeddings/pipeline.py)) — walks each flavor's `db_tables`, serialises every row into a text representation anchored by its OWL class name, and upserts into the configured vector store. Incremental reindex via SHA-256 content hash.
2. **OWL class hierarchy filter** ([runtime/embeddings/class_filter.py](runtime/embeddings/class_filter.py)) — parses a SPARQL class expression (`tmf:NetworkFunction | tmf:Alarm`) + flavor scope, walks the reasoner-computed class hierarchy in the generated Turtle, and emits a portable metadata filter `{owl_classes_in, owl_classes_all, max_tier}`. Sensitivity tier filtering is a second mandatory layer — RESTRICTED-tier embeddings are inaccessible to agents whose flavor lacks RESTRICTED access.
3. **Hybrid query executor** ([runtime/hybrid_retriever.py](runtime/hybrid_retriever.py)) — embeds the question, runs ANN search with the metadata filter, enriches each hit with the full JSON-LD record from the graph store, and ranks by `vector_similarity × prov_confidence × recency_weight`.
4. **Vector-store adapters** ([runtime/embeddings/adapters.py](runtime/embeddings/adapters.py)) — common interface across **memory** (reference · SQLite-backed · the default in CI), **Qdrant**, **Chroma**, **Weaviate**, and **pgvector**. Each adapter exposes its native filter translator (`build_payload_filter` / `build_where_clause` / `build_graphql_filter` / `build_sql`) for integration testing.
5. **Per-flavor embedding config** ([runtime/flavors/*.json](runtime/flavors/)) — each flavor JSON declares its embedding `model`, `vector_store`, indexable `owl_classes`, and `chunk_size`. Pharma can use `allenai/scibert_scivocab_uncased` while network-ops stays on the local hash embedder.
6. **Benchmark suite** ([runtime/embeddings/benchmark.py](runtime/embeddings/benchmark.py)) — runs each query across UNFILTERED_VECTOR, ONTOLOGY_BOUNDED, and PURE_SPARQL strategies; emits precision@k, MRR, latency p50/p95, improvement-over-baseline, and wrong-class-blocked metrics.

### Deliverables

| Artefact | Path |
|---|---|
| Embedding pipeline | [runtime/embeddings/pipeline.py](runtime/embeddings/pipeline.py) |
| OWL class hierarchy filter | [runtime/embeddings/class_filter.py](runtime/embeddings/class_filter.py) |
| Hybrid query executor | [runtime/hybrid_retriever.py](runtime/hybrid_retriever.py) |
| Vector-store adapters (×5) | [runtime/embeddings/adapters.py](runtime/embeddings/adapters.py) |
| Embedding model registry | [runtime/embeddings/embedder.py](runtime/embeddings/embedder.py) |
| Benchmark suite | [runtime/embeddings/benchmark.py](runtime/embeddings/benchmark.py) |
| Retrieval dashboard | [runtime/embeddings/dashboard.py](runtime/embeddings/dashboard.py) |
| Flavor embedding config | [runtime/flavor_registry.py](runtime/flavor_registry.py) (`get_embedding_config`) + every [runtime/flavors/*.json](runtime/flavors/) |
| RuntimeClient `retrieval="hybrid"` + `retrieve()` | [runtime/client.py](runtime/client.py) |
| Wizard Vector Retrieval tab | [wizard/templates/index.html](wizard/templates/index.html) + [wizard/app.py](wizard/app.py) (`/api/retrieve/*`) |
| DDL additions | [db/schema.sql](db/schema.sql) (`embedding_indexes`, `embedding_records`, `vector_query_log`, `retrieval_benchmarks`) |
| CLI wiring | [toolkit.py](toolkit.py) — `--phase embed` / `--phase retrieve` |
