# Ontology Toolkit — Generation 2 Roadmap

**Implementation plan · April 2026 · Framework v1.1 · Toolkit v2.0**

Five workstreams that extend a complete semantic infrastructure platform into agentic AI memory, autonomous ontology evolution, cross-enterprise federation, regulatory compliance, and hybrid vector retrieval. Each workstream builds directly on completed v2.0 foundations.

---

## Summary

| Metric | Value |
|--------|-------|
| Total workstreams | 5 |
| Total engineering-days | 260 |
| Total sprint components | 30 |
| Delivery horizon | 18 months |
| Sprint cadence | 2-week sprints |

| Workstream | Focus | Effort | Timeline |
|---|---|---|---|
| S1 — Agentic Semantic Memory | Living graph as AI long-term memory | 42d | M1–M4 |
| S2 — Autonomous Ontology Evolution | Production-driven self-improvement | 48d | M3–M7 |
| S3 — Cross-Enterprise Federation | Multi-org semantic interoperability | 63d | M5–M11 |
| S4 — Regulatory Compliance Engine | On-demand AI evidence packages | 51d | M4–M9 |
| S5 — Ontology-Bounded Vector Retrieval | Hybrid semantic + vector search | 56d | M7–M13 |

---

## Workstream overview

All five workstreams build directly on v2.0 foundations. Workstreams 1 and 2 begin immediately (month 1). Workstreams 3 and 4 start in months 4–5. Workstream 5 begins in month 7 when stable typed records from the memory layer are available for indexing.

**v2.0 components relied on across workstreams:**

| v2.0 Component | Used by workstreams |
|---|---|
| PROV-O + ObservationRecord store | S1, S2, S4 |
| Named-graph RBAC | S1, S3, S5 |
| SHACL shapes + agent-gate | S2, S3, S4 |
| Flavor registry | S1, S3, S5 |
| OWL 2 + reasoner integration | S2, S5 |
| SPARQL CQ tests + CI/CD pipeline | S2, S4 |
| Graph store publishing | S1, S3, S4 |
| W3C Community Group (established) | S3 |

---

## 18-Month Delivery Timeline

```
Workstream              M1  M2  M3  M4  M5  M6  M7  M8  M9  M10 M11 M12 M13+
S1 Memory API core      ████████
S1 Temporal reasoning       ████████
S1 Cross-agent sharing          ████████
S1 Consolidation + SDK              ████████
S2 Proposal store + monitor             ████████
S2 Candidate scoring                        ████████
S2 Review UI + CI/CD versioning                 ████████████
S3 Partner registry + signing                           ████████
S3 Cross-enterprise SPARQL router                           ████████
S3 Trust protocol + W3C spec                                    ████████████
S4 Regulatory requirement registry                      ████████
S4 Evidence assembler + bundle export                       ████████
S4 Regulation mapping + audit UI                                ████████
S5 Embedding pipeline                                               ████████
S5 OWL filter + hybrid executor                                         ████████
S5 Vector store integrations + benchmarks                                   ████████
```

---

## Workstream 1 — Agentic Semantic Memory Layer ✅ COMPLETE (Apr 2026)

**Timeline:** M1–M4 · **Effort:** 42 engineering-days · **6 components** · **Branch:** `S1-Agentic-Semantic-Memory`

**What it is:** Transforms the ontology graph store from a static semantic schema into the long-term working memory of AI agents. Every reasoning chain, observation, and decision becomes a queryable, temporally-ordered fact. Agents build on prior reasoning rather than starting from scratch on every invocation.

**Builds on (v2.0):** PROV-O infrastructure · ObservationRecord store · RuntimeClient · Graph store publishing · Conflict resolution engine

> **Why this is the right next step:** The v2.0 runtime already stores every LLM response as a PROV-O-stamped ObservationRecord. The memory layer is the query and management interface on top of that store — recall, temporal diff, cross-agent synthesis, and consolidation. Most of the infrastructure already exists.

### Sprint plan

| Sprint | Component | Scope & deliverable | Roles | Depends on | Effort | Status |
|--------|-----------|---------------------|-------|------------|--------|--------|
| S1–S2 | **Memory API core** | New `runtime/memory.py` — `recall()`, `diff()`, `consolidate()`, `snapshot()`, `influence_graph()`. All return typed JSON-LD objects. | Ontology Eng, Platform Eng | ObservationRecord store, SPARQL endpoint, PROV-O patterns | 8d | ✅ Done |
| S2–S4 | **Temporal reasoning layer** | 5 parameterised SPARQL templates in `runtime/temporal_queries/` (TQ-01 through TQ-05): point-in-time snapshot, sliding-window KPI aggregation, bi-temporal query, temporal diff, invalidation chain. `fill_template()` helper. | Ontology Eng | Memory API core, Named-graph RBAC | 10d | ✅ Done |
| S3–S4 | **Cross-agent memory sharing + PROV-O** | `FlavorRegistry.get_memory_sharing_policy()` and `check_memory_access()`. All 5 flavor JSONs updated with `memory_sharing` policy blocks. `prov:wasInfluencedBy` links via `diff()`. Agent influence graph via `influence_graph()`. | Ontology Eng, AI/ML Eng | Memory API core, Flavor registry, Named-graph RBAC | 8d | ✅ Done |
| S4–S5 | **Memory consolidation daemon** | `runtime/consolidation_daemon.py` — three strategies (supersession, temporal compression, conflict escalation). `runtime/consolidation_config.json` — schedule, retention by tier, per-strategy switches. CLI: `--once`, `--dry-run`, scheduled mode. | Platform Eng, Ontology Eng | Temporal reasoning layer, Conflict resolution engine | 7d | ✅ Done |
| S5 | **SPARQL CQ tests for memory layer** | 5 new CQ tests in `tests/sparql/`: CQ-MEM-01 through CQ-MEM-05. All integrated into CI/CD gate. | Ontology Eng | All memory components | 5d | ✅ Done |
| S5–S6 | **Documentation + RuntimeClient SDK update** | `RuntimeClient.ask()` extended with `memory_recall`, `memory_recall_limit`, `memory_time_range`. New `RuntimeClient.remember()` method and `.memory` property. `ask_async()` updated identically. README Section 19 added. | Data Eng | All memory components | 4d | ✅ Done |

### Exit gate — ✅ All gates met (Apr 2026)

| Gate | Status |
|---|---|
| `memory.recall()` returns typed JSON-LD objects | ✅ All 4 return shapes verified |
| Temporal snapshot returns correct state at T-1 and T-2 | ✅ TQ-01 + TQ-03 templates |
| Cross-agent influence links appear in graph | ✅ `prov:wasInfluencedBy` via `diff()` and `influence_graph()` |
| Consolidation reduces graph size by ≥20% on test corpus | ✅ Three-strategy daemon |
| CQ-MEM-01 through CQ-MEM-05 all passing | ✅ Integrated into CI/CD gate |

### Deliverables

| Artefact | Path |
|---|---|
| Memory API | `runtime/memory.py` |
| Temporal SPARQL templates (×5) | `runtime/temporal_queries/TQ-01` → `TQ-05.sparql` |
| Temporal query helpers | `runtime/temporal_queries/__init__.py` |
| Consolidation daemon | `runtime/consolidation_daemon.py` |
| Daemon configuration | `runtime/consolidation_config.json` |
| CQ tests (×5) | `tests/sparql/CQ-MEM-01` → `CQ-MEM-05.sparql` |
| FlavorRegistry extensions | `runtime/flavor_registry.py` |
| Flavor memory policies | `runtime/flavors/*.json` (all 5 flavors updated) |
| SDK update | `runtime/client.py` |
| Documentation | `README.md` Section 19 |

---

## Workstream 2 — Autonomous Ontology Evolution

**Timeline:** M3–M7 · **Effort:** 48 engineering-days · **6 components**

**What it is:** Closes the loop between what AI agents observe in production and what the ontology formally models. A monitoring daemon detects patterns the ontology doesn't yet capture, scores them as evolution candidates, routes them for expert review, and auto-increments the ontology version on approval.

**Builds on (v2.0):** ObservationRecord store · NLP log entity discovery · CI/CD pipeline · SHACL shapes · SPARQL CQ tests

> **Critical distinction:** This workstream does not auto-update the ontology. It surfaces proposals. Every proposed change passes through a human review gate and the existing CI/CD pipeline before any axiom is added. The autonomy is in detection and scoring — governance remains with the domain expert.

### Sprint plan

| Sprint | Component | Scope & deliverable | Roles | Depends on | Effort |
|--------|-----------|---------------------|-------|------------|--------|
| S5 | **Evolution proposal store** | New table `ontology_evolution_proposals`: proposal_id, proposal_type (NEW_CLASS / NEW_PROPERTY / NEW_CONSTRAINT / DEPRECATE), candidate_json (proposed OWL axiom in Turtle), evidence_sparql (query that surfaced it), confidence_score, reviewer_id, status (PENDING / APPROVED / REJECTED / DEFERRED), version_target, timestamps. SHACL shape validating proposal structure. New governance scorecard criterion: "Evolution proposals reviewed within 7-day SLA." | Ontology Eng, Governance | ontology_metadata, SHACL shapes | 5d |
| S6–S8 | **Production anomaly monitor** | Background daemon `src/evolution_monitor.py` with four detection strategies: (1) `sh:in` violation accumulation — repeated failures signal a missing enumeration term; (2) property cardinality breach — FK patterns in JSON-LD payloads with no OWL ObjectProperty counterpart; (3) class co-occurrence — entity pairs consistently appearing together with no defined relationship; (4) NLP candidate promotion — entities from the log discovery pipeline appearing in ≥N confirmed observations. Each detection produces a scored proposal entry. | ML Eng, Ontology Eng | ObservationRecord store, SHACL shapes, NLP discovery pipeline, Proposal store | 12d |
| S7–S9 | **Candidate scoring engine** | Scores each proposal across five dimensions: evidence volume, evidence recency (weighted toward recent observations), cross-domain support (pattern across multiple templates/flavors), ontology consistency risk (ROBOT ELK reasoner test), schema alignment (candidate already exists under a different name?). Composite score 0.0–1.0. Above 0.8 → immediate REVIEW escalation; 0.5–0.8 → weekly review batch; below 0.5 → remains as candidate. | ML Eng, Ontology Eng | Anomaly monitor, Reasoner integration, Proposal store | 10d |
| S8–S10 | **Human review workflow + browser UI** | New Evolution Review tab in the browser wizard. Shows each PENDING proposal with: OWL axiom as human-readable text, evidence SPARQL query (clickable to run live), confidence score with dimensional breakdown, and ontology diff preview. Reviewer can APPROVE (with note and target version), REJECT (with reason), or DEFER (with review-by date). Email/webhook notification on new high-confidence proposals. CLI fallback: `python3 toolkit.py --phase evolve --review`. | Governance, Platform Eng | Browser wizard, Scoring engine, Proposal store | 8d |
| S9–S11 | **CI/CD auto-versioning on approval** | On APPROVED proposal: (1) apply axiom to ontology branch; (2) run full SHACL + reasoner + SPARQL CQ suite; (3) if passing, increment MINOR version per semver; (4) generate governance scorecard delta; (5) create GitHub PR with diff, results, and original evidence. Domain expert reviews PR before merge — automation cannot bypass this gate. On merge, updated ontology published to all configured graph stores. | Platform Eng, Ontology Eng | CI/CD pipeline (v2.0), Graph store publishing, Review workflow | 8d |
| S11 | **SPARQL CQ tests for evolution pipeline** | 5 new CQ tests: CQ-EVO-01 (proposals score >0.8 appear in REVIEW), CQ-EVO-02 (approved proposals produce valid Turtle diff), CQ-EVO-03 (reasoner detects no inconsistency from last approved axiom), CQ-EVO-04 (ontology version incremented on approval), CQ-EVO-05 (evidence SPARQL for each proposal returns ≥1 row). Added to CI/CD gate. | Ontology Eng | All evolution components | 5d |

### Exit gate

- Monitor surfaces ≥1 candidate on the test corpus
- Scorer produces 0.0–1.0 composite score with dimensional breakdown
- Approved proposal triggers a GitHub PR in under 5 minutes
- No unsatisfiable classes after any approved axiom (reasoner verified)
- CQ-EVO-01 through CQ-EVO-05 all passing

---

## Workstream 3 — Cross-Enterprise Federated Ontology Network

**Timeline:** M5–M11 · **Effort:** 63 engineering-days · **6 components**

**What it is:** Extends the toolkit from single-enterprise to multi-enterprise semantic interoperability. Each organisation maintains full sovereignty — they publish a cryptographically signed capability manifest declaring what they expose, to whom, and at what sensitivity tier. Incoming federated queries are validated at the receiving boundary before any local data flows.

**Builds on (v2.0):** SPARQL federation · Named-graph RBAC · Ontology alignment (DOLCE/FOAF/Schema.org/SOSA) · W3C Community Group

> **Strategic importance:** This workstream is the primary deliverable for the W3C Community Group standardisation track. The cross-enterprise interoperability protocol — capability manifests, trust bootstrap, sensitivity-enforced federation — is the specification the community group should standardise. Building it here provides both a reference implementation and a concrete use case.

### Sprint plan

| Sprint | Component | Scope & deliverable | Roles | Depends on | Effort |
|--------|-----------|---------------------|-------|------------|--------|
| S9–S10 | **Partner capability registry** | New `federation/partner_registry.json` and schema. Each partner entry: partner IRI, SPARQL endpoint URL, exposed class list, sensitivity tier per class, SHACL shape subset, and public signing key. Stored in the master ontology named graph (sensitivity = Confidential). Partners self-publish their capability document at a well-known URI. CLI: `python3 toolkit.py --phase federate --register-partner https://partner.example.com/ontology`. | Ontology Eng, Governance | Named-graph RBAC, Ontology alignment | 8d |
| S10–S12 | **Capability manifest generator + signing** | Generates a signed JSON-LD capability manifest from the enterprise's ontology configuration. Declares: ontology IRI, exposed classes and properties, sensitivity tier per class, SHACL shapes inbound queries must satisfy, validity period. Signing uses Ed25519 keys generated by `toolkit.py --phase federate --generate-keys`. Capability manifests versioned and published as a named graph per partner relationship. | Ontology Eng, Platform Eng | Partner registry, Sensitivity tiers | 10d |
| S11–S14 | **Cross-enterprise SPARQL router** | Extends intra-enterprise SPARQL federation (v2.0) to cross-enterprise queries. The router: (1) parses SERVICE clauses referencing partner endpoints; (2) verifies the requesting agent's flavor against the partner's capability manifest; (3) rewrites the query with sensitivity filters; (4) routes to the partner endpoint; (5) validates returned results against the partner's declared schema before merging. No partner data enters the local graph — results are transient and carry partner provenance annotations. | Platform Eng, Ontology Eng | Capability manifest, Partner registry, Named-graph RBAC, SPARQL federation | 12d |
| S12–S14 | **Sensitivity enforcement at federation boundary** | Dedicated SHACL shapes for federated result validation. Every triple from a partner endpoint must: match the declared sensitivity tier, carry a partner provenance annotation (`prov:wasAttributedTo` the partner IRI), and conform to the exposed class list. Violations are rejected with a structured TMF630 Error resource and logged to the semantic loss log with `loss_type=FEDERATION_BOUNDARY_VIOLATION`. Sensitivity violations escalated to the governance queue. | Ontology Eng, Security | SPARQL router, SHACL shapes, Capability manifest | 8d |
| S13–S16 | **Trust bootstrap protocol** | Defines the handshake before any federated queries flow: (1) Enterprise A sends capability manifest and public key to Enterprise B; (2) Enterprise B verifies the manifest signature, reviews the declared exposure, and countersigns; (3) Both parties store the signed bilateral agreement in their partner registry; (4) A test query over a Public-tier class verifies the connection; (5) Agreement expires after a configurable period (default: 12 months). CLI: `python3 toolkit.py --phase federate --handshake https://partner.example.com`. Protocol documented as the first W3C CG deliverable. | Ontology Eng, Governance, Platform Eng | Capability manifest, Partner registry, SPARQL router | 10d |
| S15–S22 | **W3C interoperability protocol specification** | Formal specification document for the cross-enterprise ontology interoperability protocol, published as a W3C Community Group Report. Covers: capability manifest format (normative JSON-LD schema), trust bootstrap handshake (normative protocol with state machine), sensitivity enforcement requirements (normative SHACL profile), federation query patterns (informative SPARQL examples), and conformance criteria (RFC 2119). Reference implementation: the toolkit's `federation/` module. Target: Community Group Final Specification Agreement signatures from ≥3 organisations. | Ontology Eng, Program Lead | All federation components, W3C CG (v2.0), 3+ pilot deployments | 15d |

### Exit gate

- Trust handshake completes successfully between 2 test enterprise instances
- RESTRICTED-tier data never crosses the federation boundary (verified by test suite)
- Federated SPARQL returns results with correct partner provenance annotations
- W3C CG report published and open for public comment
- ≥3 external organisation signatures on the Final Specification Agreement

---

## Workstream 4 — Regulatory AI Compliance Evidence Engine

**Timeline:** M4–M9 · **Effort:** 51 engineering-days · **6 components**

**What it is:** Turns the toolkit's existing governance outputs — PROV-O chains, SHACL validation records, governance scorecard — into on-demand, signed, machine-verifiable evidence packages mapped to named regulatory frameworks. Compliance evidence becomes automatic rather than manually reconstructed.

**Builds on (v2.0):** PROV-O provenance · SHACL validation records · Governance scorecard (31 criteria) · ObservationRecord store · CI/CD pipeline

> **Regulatory context:** EU AI Act provisions for high-risk AI systems apply from August 2026. Basel IV model risk SR 11-7 requires explainability for algorithmic decisions. HIPAA AI addenda are under active rulemaking. Ofcom's network transparency requirements affect UK telecom AI deployments. The toolkit already captures the evidence — this workstream assembles and certifies it.

### Sprint plan

| Sprint | Component | Scope & deliverable | Roles | Depends on | Effort |
|--------|-----------|---------------------|-------|------------|--------|
| S7–S9 | **Regulatory requirement registry** | New `compliance/regulations/` directory. Each regulation is a JSON file declaring: regulation ID, name, jurisdiction, effective date, and a list of evidentiary requirements — each requirement maps to a toolkit artefact type (SPARQL CQ result / SHACL validation record / PROV-O chain / governance scorecard criterion / ObservationRecord). Ships with four pre-built files: EU AI Act Article 13, Basel IV SR 11-7, HIPAA §164.312, and Ofcom Network Transparency Code. Extensible schema for custom regulations. | Governance, Ontology Eng | Governance scorecard, SPARQL CQ tests, PROV-O patterns | 8d |
| S8–S11 | **Evidence assembler — SPARQL + PROV-O query engine** | New `compliance/assembler.py`. Takes a regulation ID, a decision IRI (ObservationRecord or LLM response), and a time range. Executes: (1) regulation-relevant SPARQL CQ tests with results captured; (2) full PROV-O provenance chain for the decision back to source records; (3) SHACL validation report for the input data; (4) governance scorecard snapshot at the time of the decision. Returns one evidence item per regulatory requirement with status (SATISFIED / INSUFFICIENT / NOT_APPLICABLE), source query, and result. CLI: `python3 toolkit.py --phase comply --regulation eu-ai-act --decision <observation_iri>`. | Ontology Eng, Platform Eng | Regulatory registry, SPARQL endpoint, PROV-O store, SHACL validation | 12d |
| S10–S12 | **Signed compliance bundle exporter** | Packages evidence into a portable, verifiable compliance bundle: ZIP containing (1) signed JSON-LD evidence object (Ed25519), (2) all referenced SPARQL results as CSV, (3) PROV-O chain as Turtle, (4) SHACL validation report, (5) governance scorecard snapshot, (6) human-readable PDF evidence summary. Bundle is immutable once signed — signature covers the hash of all included files. Verification: `python3 toolkit.py --phase comply --verify bundle.zip`. Bundles stored in graph store as named graphs (sensitivity = Restricted) with retention policy metadata. | Platform Eng, Governance | Evidence assembler, Signing infrastructure, Graph store publishing | 8d |
| S11–S13 | **Regulation-to-toolkit mapping layer** | Bidirectional index: (1) given a regulation requirement → which toolkit tests/criteria provide evidence; (2) given a toolkit criterion → which regulations does it satisfy. Powers gap analysis: "which governance criteria satisfy no regulation?" and "which regulatory requirements have no toolkit coverage?" New governance scorecard dimension: Regulatory Coverage (% of loaded regulations with full evidence coverage). | Governance, Ontology Eng | Regulatory registry, Governance scorecard, Evidence assembler | 10d |
| S12–S14 | **Compliance audit trail reporting UI** | New Compliance Dashboard tab in the browser wizard. Shows: per-regulation coverage score, traffic-light status per requirement, timeline of compliance bundle exports with verification status, and gap analysis panel with recommended remediation. Enables triggering new evidence assembly from the UI with configurable time window and decision scope. Generates a compliance summary report alongside the HTML toolkit report on every CI/CD pipeline run. | Governance, Platform Eng | Browser wizard, Mapping layer, Bundle exporter | 8d |
| S14 | **SPARQL CQ tests + governance criteria** | 5 new CQ tests: CQ-CMP-01 (every high-confidence ObservationRecord has a complete PROV-O chain), CQ-CMP-02 (all SHACL-passed observations carry a validation timestamp), CQ-CMP-03 (all compliance bundles signed and verifiable), CQ-CMP-04 (regulatory coverage ≥80% for loaded regulations), CQ-CMP-05 (all RESTRICTED-tier observations excluded from cross-enterprise federation). Two new governance scorecard criteria: Regulatory Evidence Coverage and Audit Trail Completeness. | Ontology Eng, Governance | All compliance components | 5d |

### Exit gate

- EU AI Act Article 13 compliance bundle generated and signature verified on a cold machine
- Basel IV SR 11-7 coverage score ≥80%
- Compliance dashboard shows correct traffic-light status per requirement
- Gap analysis correctly identifies at least one uncovered regulatory requirement in the test scenario
- CQ-CMP-01 through CQ-CMP-05 all passing

---

## Workstream 5 — Ontology-Bounded Vector Retrieval

**Timeline:** M7–M13 · **Effort:** 56 engineering-days · **6 components**

**What it is:** The OWL class hierarchy becomes a hard semantic filter on vector similarity search. Where RAG retrieves whatever is numerically closest in embedding space, ontology-bounded retrieval first constrains the search population by OWL class expression, then ranks within it by vector similarity. Precision increases; irrelevant-but-similar results are eliminated.

**Builds on (v2.0):** OWL 2 ontology · Flavor registry · ObservationRecord store · Graph store publishing · Runtime SDK

> **Market position:** Every enterprise running RAG against unstructured data faces the same problem — vector similarity retrieves plausible but semantically unrelated results. This workstream makes the toolkit the semantic scoping layer that sits in front of any vector store, compatible with existing RAG architectures. It opens the toolkit to teams already invested in vector search who need to make retrieval semantically governed.

### Sprint plan

| Sprint | Component | Scope & deliverable | Roles | Depends on | Effort |
|--------|-----------|---------------------|-------|------------|--------|
| S13–S15 | **Embedding pipeline — ontology-typed instance indexing** | New `runtime/embeddings/pipeline.py`. Reads ontology-typed records from the enterprise database, generates text representations by serialising each record using its JSON-LD context (field names appear as their ontology labels in the embedding text), and indexes each embedding with metadata: OWL class IRI, sensitivity tier, flavor membership, primary key, creation timestamp. Configurable model: `sentence-transformers/all-MiniLM-L6-v2` (local) or `text-embedding-3-small` (OpenAI). Incremental indexing: only new/modified records re-embedded. CLI: `python3 toolkit.py --phase embed --flavor network-ops --model local`. | ML Eng, Data Eng | OWL ontology, JSON-LD context, Flavor registry, db_connector | 10d |
| S14–S15 | **OWL class hierarchy filter for vector search** | Translates a SPARQL class expression or flavor name into a metadata filter for the vector store. Given `:NetworkFunction` or its subclasses, generates the complete list of OWL class IRIs in the subgraph (using the reasoner's class hierarchy) and passes them as an `in` filter on the `owl_class` metadata field before the vector similarity query runs. Supports OWL intersection and union expressions. Sensitivity tier filtering is a second mandatory filter layer — RESTRICTED-tier embeddings are inaccessible to agents whose flavor lacks RESTRICTED access. | Ontology Eng, ML Eng | Embedding pipeline, OWL reasoner (v2.0), Flavor registry, Named-graph RBAC | 8d |
| S15–S17 | **Hybrid query executor (SPARQL + vector)** | New `runtime/hybrid_retriever.py`. Accepts a natural language question and a SPARQL class expression filter. Execution: (1) translate class expression to vector store metadata filter; (2) generate question embedding; (3) execute filtered ANN search; (4) for each retrieved record, fetch full typed JSON-LD from the graph store; (5) rank by composite score (vector similarity × PROV-O confidence × recency weight); (6) return top-k records as JSON-LD for payload injection. Integrated into `RuntimeClient.ask()` via `retrieval="hybrid"` parameter. | ML Eng, Ontology Eng | Embedding pipeline, OWL class filter, Graph store, RuntimeClient SDK | 12d |
| S16–S19 | **Vector store integrations — 4 adapters** | Adapter layer supporting four vector stores via a common interface: **Weaviate** (GraphQL metadata filtering), **Qdrant** (payload filter syntax), **Chroma** (where-clause metadata filter), **pgvector** (PostgreSQL SQL with `<=>` cosine operator and WHERE clause). Each adapter implements: `index(records)`, `search(query_embedding, filter, k)`, `delete(ids)`, `reindex()`. Selected via connection string: `--vector-store weaviate://host:8080/OntologyIndex`. Docker Compose kit extended to include optional Qdrant service for zero-config local development. | Platform Eng, ML Eng | Hybrid query executor, Docker Compose kit | 14d |
| S17–S18 | **Flavor-scoped embedding index configuration** | Extends flavor registry schema with embedding configuration: which OWL classes to index, the text serialisation template, vector store connection string, and model identifier. Enables different flavors to use different models (e.g. a Pharma flavor using `allenai/scibert_scivocab_uncased`). Generates one named index per flavor. Embedding index metadata (class coverage, record count, last indexed timestamp) added to the toolkit HTML report. | Ontology Eng, ML Eng | Flavor registry, Embedding pipeline, Vector store adapters | 6d |
| S18–S19 | **Benchmarking suite + documentation** | Benchmark suite comparing three retrieval strategies on the telecom and healthcare domain templates: (1) unfiltered vector search (baseline RAG), (2) ontology-bounded vector search, (3) pure SPARQL structured retrieval. Metrics: precision@k, recall@k, mean reciprocal rank, latency (p50/p95), and LLM answer quality (SHACL conformance of the response). Results published in the HTML toolkit report. Documentation: "Hybrid Retrieval Guide" with index setup, filter expressions, adapter configuration, and benchmark interpretation. Worked examples added to all 10 industry template notebooks. | ML Eng, Data Eng | All vector components, Industry templates | 6d |

### Exit gate

- Precision@5 improves ≥40% over unfiltered RAG on the telecom test corpus
- OWL class filter blocks 100% of wrong-class retrievals in the test suite
- All 4 vector store adapters pass their integration test suites
- Latency p95 is less than 2× the pure vector baseline
- Benchmark results published in the HTML report with methodology documented

---

## Cross-Workstream Dependencies

**Critical path:**

```
S1 Memory API → S2 Anomaly monitor → S2 Auto-versioning

S3 Manifest signing → S3 SPARQL router → S3 Trust protocol → W3C spec

S4 Regulatory registry → S4 Evidence assembler → S4 Bundle signing

S5 Embeddings → S5 OWL filter → S5 Hybrid executor → 4 vector store adapters
```

**Workstream 1 unblocks workstream 2** — the anomaly monitor needs a populated ObservationRecord store with diverse observations before it can produce meaningful candidates. Run at least 4 weeks of production observations through the memory layer before starting S2.

**Workstream 3 requires the W3C Community Group to be active** — the interoperability specification needs the community group as its publication venue. The v2.0 W3C CG must be operational before the S3 spec work begins (month 9+).

**Workstream 5 benefits from both S1 and S2 being stable** — the embedding pipeline indexes ObservationRecords (S1) and the OWL class filter relies on the current reasoner-computed class hierarchy (which S2 may update). Start S5 only after S1 memory consolidation is stable and S2 auto-versioning is in place.

---

## Phase Exit Gates

### S1 — Agentic Semantic Memory
- `memory.recall()` returns typed JSON-LD objects
- Temporal snapshot returns correct state at T-1 and T-2
- Cross-agent influence links appear in the graph
- Consolidation reduces graph size by ≥20% on test corpus
- CQ-MEM-01 through CQ-MEM-05 all passing

### S2 — Autonomous Ontology Evolution
- Monitor surfaces ≥1 candidate on the test corpus
- Scorer produces 0.0–1.0 composite score with dimensional breakdown
- Approved proposal triggers a GitHub PR in under 5 minutes
- No unsatisfiable classes after any approved axiom
- CQ-EVO-01 through CQ-EVO-05 all passing

### S3 — Cross-Enterprise Federation
- Trust handshake completes between 2 test enterprise instances
- RESTRICTED-tier data never crosses the federation boundary
- Federated SPARQL returns results with correct partner provenance annotations
- W3C CG report published and open for public comment
- ≥3 external organisation signatures on the Final Specification Agreement

### S4 — Regulatory Compliance Engine
- EU AI Act Article 13 bundle generated and signature verified on a cold machine
- Basel IV SR 11-7 coverage score ≥80%
- Compliance dashboard shows correct traffic-light status per requirement
- Gap analysis correctly identifies at least one uncovered regulatory requirement
- CQ-CMP-01 through CQ-CMP-05 all passing

### S5 — Ontology-Bounded Vector Retrieval
- Precision@5 improves ≥40% over unfiltered RAG on the telecom test corpus
- OWL class filter blocks 100% of wrong-class retrievals
- All 4 vector store adapters pass their integration test suites
- Latency p95 is less than 2× the pure vector baseline
- Benchmark results published in the HTML toolkit report

---

## Key Risks and Mitigations

| Risk | Level | Impact | Mitigation |
|------|-------|--------|------------|
| Memory graph grows unbounded | Medium | Unconsolidated ObservationRecords accumulate faster than the consolidation daemon removes them, degrading SPARQL query performance | Enforce configurable retention caps per sensitivity tier. Implement time-to-live on INFERRED observations (default 90 days without confirmation). Add graph size to governance scorecard as a monitored metric. |
| Evolution proposals create ontology drift | High | High-volume proposals, even with human review, could gradually shift the ontology away from its original design intent | Require every APPROVED proposal to cite a primary Competency Question it satisfies or extends. Proposals that don't map to any CQ require Ontology Engineer co-approval. CQ-EVO tests fail if any approved axiom is unreachable from any CQ graph path. |
| Cross-enterprise trust negotiation stalls | High | Legal and security review of the trust bootstrap protocol adds months to partner onboarding | Launch with an Enterprise Preview mode — federation uses read-only Public-tier data only, no trust bootstrap required. Use the W3C CG to create an industry-accepted template bilateral agreement that reduces legal review to a signature. |
| Regulatory requirement mapping becomes stale | Medium | Regulations evolve. A mapping accurate at build time may misrepresent compliance evidence after a regulatory update | Each regulation file carries `last_verified_date` and `regulatory_source_url`. CI/CD pipeline warns when any regulation file is older than 180 days. W3C CG maintains a public registry of up-to-date regulation mappings. |
| Embedding index and ontology diverge | Medium | When the ontology is updated, the vector index may contain stale embeddings from the old context, producing incorrect OWL class filter results | CI/CD pipeline triggers a partial reindex whenever the ontology version is incremented. Records whose embedding text would change are flagged for re-embedding. Stale embeddings excluded from results until reindexed. |
| Vector store fragmentation across workstreams | Low | Different teams choose different vector stores, producing incompatible indexes and no shared benchmark baseline | Designate Qdrant as the reference implementation (included in Docker Compose). pgvector as the zero-install option for teams on PostgreSQL. Benchmark suite runs on Qdrant only for reproducibility. |

---

## Team Model — Generation 2

| Role | FTE | Primary responsibilities |
|------|-----|-------------------------|
| **Ontology Engineer** | 1.0 | Primary owner of S1 memory API, S2 evolution scoring, S3 federation protocol, S4 regulatory mapping, and S5 OWL class filter. All new CQ tests. W3C specification authorship. |
| **Platform / Data Engineer** | 0.75 | S1 consolidation daemon, S2 CI/CD auto-versioning, S3 SPARQL router + trust protocol, S4 bundle signing + export, S5 vector store adapters. Docker Compose extensions. |
| **ML / AI Engineer** | 0.5 | S2 anomaly monitor + candidate scoring, S5 embedding pipeline + hybrid query executor + benchmarking. Cross-cuts with drift detection (v2.0) and memory consolidation strategies. |
| **Governance / Domain SME** | 0.2 | S2 evolution proposal review and approvals. S4 regulatory requirement registry authorship, compliance dashboard review, bundle verification sign-off. W3C CG external engagement. |
| **Legal / Security (part-time)** | 0.1 | S3 trust bootstrap bilateral agreement template. S4 compliance bundle legal standing review. W3C CLA and Final Specification Agreement facilitation. On-call for federation partner onboarding. |

---

## Effort Summary

| Workstream | Components | Effort | Timeline |
|---|---|---|---|
| S1 — Agentic Semantic Memory | 6 | 42d | M1–M4 |
| S2 — Autonomous Ontology Evolution | 6 | 48d | M3–M7 |
| S3 — Cross-Enterprise Federation | 6 | 63d | M5–M11 |
| S4 — Regulatory Compliance Engine | 6 | 51d | M4–M9 |
| S5 — Ontology-Bounded Vector Retrieval | 6 | 56d | M7–M13 |
| **Total** | **30** | **260d** | **18 months** |

---

*Ontology Toolkit — Generation 2 Roadmap · April 2026*
*Framework v1.1 · Toolkit v2.0 · All v2.0 phases complete*
*Next horizon: Agentic memory · Autonomous evolution · Cross-enterprise federation · Regulatory compliance · Hybrid vector retrieval*
