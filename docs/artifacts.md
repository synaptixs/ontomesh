# Generated artifacts

Reference for the directory layout the toolkit produces and what each generated file is for. For the integration recipe see [integrate.md](integrate.md). For the metadata control plane that drives generation see [metadata.md](metadata.md).

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

Distinct values in event discriminator columns (e.g. `event_type = INCIDENT`) auto-generate OWL subclasses of `DomainEvent`. These are **defined classes** — each carries an `owl:equivalentClass` restriction on the discriminator value, so a reasoner classifies an event into its subclass rather than the membership rule living only in a comment.

### provenance.ttl — PROV-O patterns

The provenance profile: `:Agent` aligned to `prov:Agent`, a `:DerivationActivity` class under `prov:Activity`, and `:wasProducedBy` as a subproperty of `prov:wasAttributedTo`. Also declares semantic aliases (`:refersToAsset`, `:derivationMethod`) as `owl:equivalentProperty` to their structural counterparts, so either name is valid in a query.

The chain itself is materialised into `instances.ttl` — see below.

### dimensions.ttl — time, quantity, participation

The three dimensions a relational schema flattens away.

* **Time** — `:TemporalExtent` (an OWL-Time `time:TemporalEntity`) with `:validFrom` / `:validUntil`, kept distinct from transaction time. Answers "what was true then, as we understood it then".
* **Quantity** — `:QuantityValue` aligned to `qudt:QuantityValue`, pairing a magnitude with its unit so a number cannot be read without one.
* **Participation** — `:Participation` reifying the n-ary event/agent/role relation, so *in what capacity* an agent took part survives.

### instances.ttl — the ABox

Individuals materialised from your rows, driven by `logical_physical_map.csv`. Generated by `--phase abox`.

```turtle
<https://ontology.example.com/enterprise/Asset/6>
  a :Asset ;
  :sensitivityTier :Internal ;
  rdfs:label "Core Router 12" ;
  :hasExternalId "RTR-012" ;
  :assetType <https://ontology.example.com/enterprise/AssetType/3> .
```

Provenance-bearing records additionally carry a reified `prov:wasGeneratedBy` → `prov:wasAssociatedWith` chain.

!!! danger "Tier gating"

    An ABox is a copy of your data in a portable file. Columns above `--max-tier` are withheld, `Restricted` is excluded by default, and each run reports what it held back.

### ontology_quality.csv — pitfalls, metrics, consistency

Written by `--phase quality`. Ten OOPS!-style pitfall checks, structural metrics (depth, inheritance/attribute richness, restriction and defined-class counts) and an `owlrl` consistency result. See [Quality gates](reference/quality-gates.md).

### ontology_baseline.json — the artifact ratchet

Committed at the repository root. Records the agreed value of each measurable artifact property so CI can fail on *regression* rather than on the existence of known debt. Regenerate with `python scripts/ontology_gate.py --update-baseline` — in the same commit as the change that justifies it.

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

