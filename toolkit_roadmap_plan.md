# Ontology Toolkit Roadmap

**Implementation plan — April 2026**

Sequenced delivery plan for the 24-item future roadmap. Three phases across 12 months. Critical-path items first, strategic items last.

---

## Summary

| Metric | Value |
|--------|-------|
| Roadmap items | 32 (3 phases + runtime layer) |
| Phase 1 | ✓ Done — Completed Apr 2026 (7 items) |
| Phase 2A | ✓ Done — Completed Apr 2026 (4 items) |
| Phase 2B | ✓ Done — Completed Apr 2026 (4 items) |
| Phase 3 — strategic | 9 items, ~16 sprints |
| Runtime Layer | ✓ Done — Completed Apr 2026 (6 components) |
| Total estimated effort | 326 engineering-days (incl. runtime) |

---

## Phase Overview

### Phase 1 · M1–M3 · ✓ COMPLETED APR 2026 — Seal the gaps
Close P1 items. TMF630 compliance, SPARQL tests, reasoner integration. Makes every existing artifact verifiable.

### Phase 2A · M4–M6 · ✓ COMPLETED APR 2026 — Data & CI/CD
Log connector, CI/CD pipeline, LLM wizard assist. Broadens data sources and automates quality enforcement.

### Phase 2B · M7–M9 · ✓ COMPLETED APR 2026 — TMF & Federation
Remaining TMF domains, conflict resolution, ontology alignment. Completes the telecom vertical and enables multi-domain operation.

### Phase 3 · M10–M12+ — Scale & Community
Graph store deploy, Docker kit, browser wizard, additional templates, W3C community group, drift detection.

### Runtime Layer · Parallel Track · ✓ COMPLETED APR 2026 — Ontology-augmented AI Runtime
The consumption layer that connects toolkit artifacts to LLMs. Payload assembler, flavor registry, SHACL output gate, PROV-O response stamping, ObservationRecord feedback loop. Runs alongside all pipeline phases — not after them.

---

## 12-Month Delivery Timeline

> 2-week sprints

| Item | M1 | M2 | M3 | M4 | M5 | M6 | M7–9 | M10–12 |
|------|----|----|----|----|----|----|------|--------|
| **Phase 1 — Seal the gaps · ✓ COMPLETED APR 2026** | | | | | | | | |
| ✓ TMF630 meta-attrs | ██ | ██ | | | | | | |
| ✓ href URL generation | █ | | | | | | | |
| ✓ EntityRefOrValue pattern | | ██ | | | | | | |
| ✓ OWL profile selection | █ | | | | | | | |
| ✓ Reasoner integration | | ██ | █ | | | | | |
| ✓ SPARQL CQ tests | | | ███ | | | | | |
| ✓ Full 31-criteria scoring | | | | ██ | | | | |
| **Phase 2A — Data & CI/CD · ✓ COMPLETED APR 2026** | | | | | | | | |
| ✓ CI/CD pipeline | | | | | ██ | | | |
| ✓ Log connector | | | | | ████ | | | |
| ✓ LLM-assisted wizard | | | | | | ██ | | |
| ✓ Named-graph RBAC | | | | | | | ██ | |
| **Phase 2B — TMF & Federation · ✓ COMPLETED APR 2026** | | | | | | | | |
| ✓ TMF remaining domains | | | | | | | █ | |
| ✓ TMF Event Hub | | | | | | | █ | |
| ✓ Conflict resolution | | | | | | | ██ | |
| ✓ Ontology alignment | | | | | | | ██ | |
| **Runtime Layer — Parallel Track (M3–M12) · ✓ COMPLETED APR 2026** | | | | | | | | |
| ✓ Ontology flavor registry | | | | ██ | | | | |
| ✓ Data grounding module | | | | ███ | | | | |
| ✓ Payload assembler | | | | | ███ | | | |
| ✓ Output SHACL gate | | | | | | ██ | | |
| ✓ PROV-O response stamping | | | | | | | ██ | |
| ✓ Runtime SDK + docs | | | | | | | | ███ |
| **Phase 3 — Scale & Community** | | | | | | | | |
| P3 Graph store publishing | | | | | | | | █ |
| P3 Docker Compose kit | | | | | | | | █ |
| P3 Industry templates (+5) | | | | | | | | █ |
| P3 Drift detection extension | | | | | | | | █ |
| P3 Browser wizard / modular OWL | | | | | | | | █ |
| P3 W3C Community Group | | | | | | | | █ |

---

## Sprint-Level Delivery Plan

> 2-week sprints · effort in days

---

### Phase 1 — Seal the gaps · Months 1–3 · ~27 engineering-days · ✓ COMPLETED APR 2026

| Phase | Sprint | Item | Scope & Deliverable | Roles | Depends on | Effort |
|-------|--------|------|---------------------|-------|------------|--------|
| ✓ | S1 | **TMF630 meta-attributes** | Add `@baseType`, `@schemaLocation`, `@referredType` to `tmf-context.json` and all 4 sample payloads. Add to MCP tool output schemas. Update CQ-TMF tests to validate presence. Update TMF630 compliance assessment. | Ontology Eng | — | 2d |
| ✓ | S1 | **href URL generation** | Add `href` as a computed annotation in the JSON-LD context following `/{apiRoot}/{resource}/{id}` pattern. Populate in all payloads. Document URL pattern per TMF API in `TMF_API_MAP`. | Ontology Eng | ↑ meta-attrs | 1d |
| ✓ | S1 | **OWL profile selection** | Add profile detection to onboarding wizard (Step 2): if generated axiom count >50K → suggest EL; if role chains or nominals present → require DL. Outputs a `profile_recommendation.md` alongside the schema. | Ontology Eng | — | 2d |
| ✓ | S2 | **EntityRefOrValue pattern** | Add `RefOrValue` support to `jsonld_generator.py`: a reference form (id + href + @referredType only) and a value form (full inline). Update all FK-linked properties in sample payloads to demonstrate both forms. Add SHACL shape for reference form validation. | Ontology Eng, Data Eng | ↑ meta-attrs | 5d |
| ✓ | S3 | **Reasoner integration** | Integrate ROBOT framework: `robot reason` (ELK for EL profile, HermiT for DL) run after Phases 2 and 3. Class hierarchy snapshot stored; diff fails the build on unexpected hierarchy changes. Unsatisfiable classes reported as CRITICAL findings. | Platform Eng, Ontology Eng | ROBOT CLI | 5d |
| ✓ | S4 | **SPARQL CQ test suite** | Load generated Turtle into Oxigraph (lightweight, zero-install SPARQL engine). Run all CQ tests as SPARQL SELECT/ASK against the RDF graph. Replace SQL equivalents. Results include graph-path validation that SQL cannot provide (e.g. multi-hop PROV-O chains). New `tests/sparql/*.sparql` files. | Ontology Eng, Platform Eng | Oxigraph binary | 8d |
| ✓ | S5 | **Full 31-criteria auto-score** | Automate the remaining 17 governance criteria by introspecting: shape coverage per class (Structural Constraints), CQ coverage per ontology class (Competency Question Coverage), SPARQL test pass rate (Semantic Rule Coverage), sensitivity annotation completeness. Score written into `governance_scorecard.csv` with evidence links. | Governance, Ontology Eng | ↑ SPARQL CQs, ↑ Reasoner | 4d |

---

### Phase 2A — Data & CI/CD · Months 4–6 · ~34 engineering-days · ✓ COMPLETED APR 2026

| Phase | Sprint | Item | Scope & Deliverable | Roles | Depends on | Effort |
|-------|--------|------|---------------------|-------|------------|--------|
| ✓ | S6 | **CI/CD pipeline** | Ship `.github/workflows/ontology.yml` (GitHub Actions) and `Jenkinsfile`. Stages: (1) reasoner consistency, (2) SHACL validation, (3) SPARQL CQ tests, (4) regression gate, (5) governance score delta report as PR comment. Blocks merge on Critical SHACL violations or CQ regressions. | Platform Eng | ↑ SPARQL CQs, ↑ Reasoner | 6d |
| ✓ | S6–S8 | **Structured log connector** | New `src/log_connector.py`. Format detectors: syslog RFC5424, JSON-lines, CEF, OpenTelemetry trace, plain regex. Entity extractor anchored to `ontology_metadata` class names and external_id patterns. Produces ObservationRecord instances with `derivation_method=IMPORTED`, `source_ref=file:line`, `confidence_score` from match certainty. CLI: `python3 toolkit.py --phase log --log-path /var/log/*.log` | Data Eng, Ontology Eng | PROV-O patterns, ontology_metadata | 15d |
| ✓ | S7 | **LLM-assisted wizard** | Add optional `--llm` flag to `onboard.py`. On domain description entry, call the Anthropic API (claude-sonnet) to suggest entities, events, relationships, and 8 CQs. User reviews and edits suggestions rather than typing from scratch. Estimated onboarding time: 15 minutes → <5 minutes. | Data Eng | Anthropic API key | 5d |
| ✓ | S8 | **Named-graph RBAC** | Generate working access control configs from sensitivity tier annotations: (1) Stardog RBAC policy file, (2) Apache Fuseki/Shiro config, (3) Amazon Neptune IAM policy JSON. Each config partitions the RDF store into 4 named graphs (Public, Internal, Confidential, Restricted) with role-based access. CLI: `python3 toolkit.py --phase security --store stardog` | Platform Eng, Security | Sensitivity tiers, Graph store | 8d |

---

### Phase 2B — TMF & Federation · Months 7–9 · ~49 engineering-days · ✓ COMPLETED APR 2026

| Phase | Sprint | Item | Scope & Deliverable | Roles | Depends on | Effort |
|-------|--------|------|---------------------|-------|------------|--------|
| ✓ | S9–S11 | **TMF remaining domains** | Add ~8 tables and ~15 TMF Open APIs not yet in schema: Revenue Management (TMF678 Customer Bill, TMF679 Product Offering Qualification), Trouble (TMF621), Network Slice Mgmt (TMF645), Service Quality (TMF657), Geographic Site (TMF674). Update SID hierarchy, seed data, CQ catalog, TMF API coverage map. | Ontology Eng, Data Eng | TMF SID hierarchy, TMF seed data | 20d |
| ✓ | S9 | **TMF Event Hub** | Model TMF630 Part 1 §5 notification pattern: `EventSubscription` OWL class, `tmf_event_subscription` table (callback_url, event_type, status), SHACL shape, MCP tool `subscribe_to_events`. Enables async agent notification in ODA-compliant deployments. | Ontology Eng | TMF schema, JSON-LD context | 5d |
| ✓ | S10–S11 | **Multi-agent conflict resolution** | Implement the 3-tier resolution chain (framework Section 10.1): Tier 1 — SHACL axiom check rejects logically inconsistent assertion. Tier 2 — priority chain (measured > derived > imported > default). Tier 3 — human escalation queue (`tmf_conflict_event` table). SPARQL ASK conflict detection query. PROV-O `wasInvalidatedBy` on losing assertions. | Ontology Eng, AI/ML Eng | PROV-O patterns, SHACL agent gate | 10d |
| ✓ | S11–S12 | **Ontology alignment & federation** | Generate `owl:equivalentClass` and `skos:exactMatch` axioms aligning the generated ontology with DOLCE, FOAF, Schema.org, and SOSA (W3C Sensor ontology for observations). Produce alignment ontology as separate Turtle module. SPARQL SERVICE federation endpoint configuration for multi-domain queries across named graphs. | Ontology Eng | OWL ontology, SID hierarchy | 12d |

---

### Runtime Layer · Parallel Track M3–M12 · ~55 engineering-days · ✓ COMPLETED APR 2026

> The consumption bridge between toolkit artifacts and AI/LLM systems

| Phase | Sprint | Item | Scope & Deliverable | Roles | Depends on | Effort |
|-------|--------|------|---------------------|-------|------------|--------|
| ✓ | S5–S6 | **Ontology flavor registry** | Configuration layer that defines named agent views over the master ontology. Each flavor specifies: OWL class subset, SHACL shape subset, scoped JSON-LD context terms, and sensitivity-tier access level. Stored as `runtime/flavors/{name}.json`. Flavors are generated automatically from `ontology_metadata` sid_domain groupings and can be manually extended. Ships with 5 starter flavors: network-ops, billing, compliance, customer, fault-management. | Ontology Eng | OWL ontology, SHACL shapes, JSON-LD context | 5d |
| ✓ | S6–S8 | **Data grounding module** | The critical missing step in most LLM + enterprise data architectures. `runtime/grounder.py` takes a question and a flavor, queries the enterprise database for relevant records, and serialises those records as JSON-LD using the flavor's scoped context — binding each field value to its ontology IRI. Output: typed, ontology-grounded data ready for LLM payload. Without this step, raw data sits next to the ontology in a prompt without being connected to it. CLI: `python3 runtime/grounder.py --flavor network-ops --question "Which NFs are degraded?" --db <connection>` | Ontology Eng, Data Eng | Flavor registry, db_connector | 10d |
| ✓ | S7–S9 | **Payload assembler** | Assembles the full LLM payload from five components: (1) system prompt — ontology summary + domain rules + agent role description, (2) ontology flavor — relevant class and property definitions in natural language, (3) grounded data — JSON-LD serialised enterprise records from the grounder, (4) PROV-O context — provenance of each data point in the payload, (5) question + output format instructions. Returns a structured payload dict that any LLM API client can consume. LLM-agnostic — works with Anthropic, OpenAI, Google, Llama, or any custom endpoint. | Data Eng, AI/ML Eng | Flavor registry, Grounding module, PROV-O patterns | 12d |
| ✓ | S8–S10 | **Output SHACL gate + PROV-O stamping** | Governs LLM responses — the step missing from almost every production implementation. For structured responses: SHACL validates the output against the relevant ontology shapes before any downstream action. For all responses: stamps PROV-O provenance (agent = LLM identifier + model version, `prov:generatedAtTime`, confidence extracted from model output, `derivation_method=SYNTHESIZED`). Stores validated response as an `ObservationRecord` with `source_ref` pointing to the payload ID. | Ontology Eng, AI/ML Eng | SHACL shapes, PROV-O patterns, Payload assembler | 10d |
| ✓ | S9–S10 | **SHACL input gate (inbound data validation)** | Validates enterprise data against SHACL shapes *before* it enters the LLM payload. Rejects malformed, incomplete, or low-confidence records at the acceptance gate rather than letting bad data reach the model. Integrates with the existing `agent-gate.ttl`. Reports rejected records to `semantic_loss_log` with `loss_type=REJECTED_AT_RUNTIME_GATE`. | Ontology Eng | SHACL shapes, agent-gate.ttl | 5d |
| ✓ | S13–S15 | **Runtime SDK + multi-LLM adapters + documentation** | Package the runtime layer as a lightweight Python SDK: `pip install ontology-toolkit-runtime`. Ships with LLM-specific adapters (Anthropic Messages API, OpenAI Chat Completions, Google Vertex, Ollama local). Includes a `RuntimeClient` class, async support, streaming response handling, and a worked example notebook per industry template. | Data Eng, AI/ML Eng | All RT modules, Industry templates | 13d |

---

### Phase 3 — Scale & Community · Months 10–12+ · ~161 engineering-days

| Phase | Sprint | Item | Scope & Deliverable | Roles | Depends on | Effort |
|-------|--------|------|---------------------|-------|------------|--------|
| P3 | S13 | **Graph store publishing** | One-command upload of all Turtle artifacts to: Apache Jena Fuseki, Stardog, Oxigraph, Amazon Neptune, Ontotext GraphDB. With named-graph partitioning by sensitivity tier. CLI: `python3 toolkit.py --phase publish --store fuseki --endpoint http://host:3030` | Platform Eng | ↑ SPARQL CQs, ↑ Named-graph RBAC | 8d |
| P3 | S13 | **Docker Compose kit** | Single `docker-compose.yml` spinning up: toolkit (Python), Oxigraph SPARQL endpoint, SHACL validation service, OpenAPI gateway with TMF URL patterns, pgAdmin (if PostgreSQL selected). Full stack demo in one command. Includes pre-loaded telecom and healthcare examples. | Platform Eng | ↑ Graph store publish, ↑ CI/CD | 5d |
| P3 | S14 | **Drift detection ontology extension** | Extend `PerformanceIndicator` class to natively model ML monitoring metrics: PSI (Population Stability Index), KL/JS divergence, calibration score, log template shift. Adds `DriftObservation` OWL subclass, dedicated SHACL shapes, and SKOS concepts. Direct semantic home for the ML Drift Monitoring white paper. | ML Eng, Ontology Eng | PerformanceIndicator | 8d |
| P3 | S14–S16 | **Industry templates (+5)** | Add: Energy & Utilities (IEC CIM alignment), Logistics & Supply Chain, Government (DCAT/INSPIRE alignment), Insurance, Pharmaceuticals (IDMP alignment). Each template includes domain-specific entities, events, relationships, 8+ CQs, and a sensitivity classification guide. | Ontology Eng, Domain SMEs | Onboarding wizard | 25d |
| P3 | S15–S17 | **Modular OWL + browser wizard** | Modular: `owl:imports` support for multi-team authoring — acyclicity check, cross-module IRI conflict detection, per-module versioning. Browser wizard: web form equivalent of `onboard.py` with drag-and-drop entity/relationship builder. Generates session JSON consumed by CLI pipeline. | Ontology Eng, Frontend | Session JSON stable | 30d |
| P3 | S15–S20 | **Log entity discovery (NLP)** | Statistical co-occurrence analysis over log corpora to surface candidate entities and relationships not yet in the ontology. Requires NLP pipeline (spaCy). Produces a scored candidate list for expert review — does not auto-add to ontology. Feeds back into onboarding wizard as entity suggestions. | ML Eng | ↑ Log connector, spaCy / NLP lib | 30d |
| P3 | S16–S18 | **TMF630 Task + bulk operations** | TMF630 Parts 4 and 7: async Task resource (OWL class, table, SHACL shape, MCP tool) and bulk import/export job pattern (ImportJob, ExportJob classes). Required for full TMF Open API conformance certification against the TMF Test Orchestration Platform. | Ontology Eng, Data Eng | ↑ TMF domains, ↑ EntityRefOrValue | 12d |
| P3 | S18+ | **W3C Community Group** | Publish framework and toolkit to a W3C Community Group. Prerequisites: CI/CD pipeline green, full 31-criteria governance auto-scored, SPARQL CQ tests in place, at least 3 pilot deployments documented. Migrate GitHub repo to community ownership. Define IPR policy, contribution governance, and versioning committee. | Program Lead, Ontology Eng | ↑ CI/CD, ↑ Full scoring, 3+ pilots | 60d |

---

## Phase Exit Gates

### Runtime Layer ✓ Complete · Apr 2026
- ✓ Flavor registry: 5 starter flavors loaded and validated (`network-ops`, `billing`, `compliance`, `customer`, `fault-management`)
- ✓ Grounder: JSON-LD output with `@type`, ontology IRI bindings, and PROV-O grounding record
- ✓ InputGate: SHACL acceptance screening; rejections logged to `semantic_loss_log`
- ✓ Assembler: 5-component payload with token budget; LLM-agnostic output
- ✓ OutputGate: SHACL response validation + PROV-O stamping + `ObservationRecord` storage
- ✓ RuntimeClient: end-to-end `ask()` pipeline with 4 adapters (Anthropic, OpenAI, Vertex, Ollama)
- ✓ 3 new SPARQL CQ tests (CQ-RT-01/02/03) — 18 total passing

### Phase 1 ✓ Complete · Apr 2026
- ✓ `@baseType` / `@schemaLocation` in all payloads
- ✓ SPARQL CQs all passing (not SQL)
- ✓ Reasoner: zero unsatisfiable classes
- ✓ 31/31 governance criteria auto-scored
- ✓ Average governance score ≥ 4.2 / 5.0

### Phase 2A ✓ Complete · Apr 2026
- ✓ CI/CD pipeline blocks on Critical violations
- ✓ Log connector processes syslog + JSON
- ✓ RBAC config generated for ≥ 2 graph stores
- ✓ Onboarding time ≤ 5 min (LLM-assisted)

### Phase 2B ✓ Complete · Apr 2026
- ✓ 6 new TMF APIs integrated (TMF621, TMF645, TMF657, TMF674, TMF678, TMF679) — 24 total
- ✓ Conflict resolution: all 3 tiers implemented and tested (13 CQs passing)
- ✓ Alignment axioms generated for DOLCE, FOAF, Schema.org, SOSA (31 class + 13 property alignments)
- ✓ Multi-domain SPARQL federation config and example queries generated

### Phase 3 Exit
- One-command Docker stack running
- 10 industry templates available
- ≥ 3 documented pilot deployments
- W3C Community Group charter filed

---

## Key Risks and Mitigations

| Risk | Level | Impact | Mitigation |
|------|-------|--------|------------|
| SPARQL/reasoner toolchain adds install friction | **High** | Oxigraph or ROBOT not available in restricted environments. Breaks CI/CD integration. | Ship pre-built binaries in a `bin/` directory. Provide Docker-only fallback. Make SPARQL tests optional (degrade gracefully to SQL). |
| LLM API cost and latency in wizard | **Medium** | Anthropic API calls add cost and latency to onboarding. Air-gapped environments cannot use it. | Keep LLM assistance strictly opt-in (`--llm` flag). Wizard remains fully functional without it. Cache suggestions in session JSON. |
| DB2 / Oracle client library complexity | **Medium** | IBM DB2 CLI driver and Oracle ODBC require OS-level installation that blocks adoption in container environments. | Oracle thin mode (oracledb) already avoids this. For DB2: document Docker base image with pre-installed CLI driver. Provide `Dockerfile.db2`. |
| TMF membership paywall on API specs | **Medium** | Some TMF specifications require membership to access. Blocks complete TMF630 conformance work. | All 18 current Open APIs are Apache 2.0 on GitHub. TMF630 design guidelines are available as older versions (4.2.0). Work from public sources; flag where v5.0 paywall blocks. |
| W3C Community Group consensus overhead | **Low** | Community group governance slows iteration and version decisions. | Incubate in a personal/org GitHub repo until ≥3 external contributors and ≥3 pilot deployments exist. Only then propose migration. |
| Log format diversity underestimated | **High** | 5G NF logs, BSS/OSS logs, and cloud platform logs are far more heterogeneous than the 4 planned formats. MVP log connector may cover <30% of real log volume. | Scope the connector to JSON-structured + syslog as the MVP. Build a plugin interface for custom format detectors from day one. Community contributions fill the gaps. |
| Grounding step produces oversized payloads | **High** | JSON-LD serialisation of enterprise records can expand payload size significantly, potentially exceeding LLM context windows or increasing latency beyond acceptable thresholds. | Implement relevance scoring in the grounder — retrieve only records pertinent to the question via semantic similarity. Support chunked payloads and streaming. Expose a `max_tokens` budget parameter to the assembler. |
| LLM output structure inconsistency | **Medium** | SHACL validation of LLM output requires structured responses. Models often produce semi-structured or free-text that does not conform to the expected shape, causing the output gate to reject valid answers. | Use constrained output (JSON mode / structured outputs) where the LLM supports it. For free-text responses, apply PROV-O stamping but skip SHACL shape validation. Design instructions in the payload to guide structured output format. |
| Flavor proliferation management | **Low** | As teams define more agent-specific flavors, the registry becomes hard to govern — overlapping definitions, conflicting sensitivity assignments, and stale flavors that no longer match the master ontology. | Auto-generate flavors from `ontology_metadata` sid_domain groupings as the canonical source of truth. Manual flavors must pass a validation check against the master OWL ontology on every pipeline run. Deprecate unused flavors via `owl:deprecated`. |

---

## Recommended Team Model

| Role | Responsibilities | Phases Active | FTE |
|------|-----------------|---------------|-----|
| **Ontology Engineer** | OWL modeling, SHACL shapes, SID alignment, TMF domain extensions, alignment axioms, modular OWL. Primary owner of all Phase 2 ontology artifacts. | All phases | 1.0 |
| **Platform / Data Engineer** | CI/CD pipeline, SPARQL endpoint, graph store publishing, Docker Compose, database connectors, log connector format adapters, RBAC configuration generation. | P1 S3+, P2, P3 | 0.5–1.0 |
| **ML / AI Engineer** | LLM-assisted wizard, conflict resolution logic, log entity discovery NLP pipeline, drift detection ontology extension. Cross-cuts with ML monitoring white paper outputs. | P2A S7, P3 | 0.25–0.5 |
| **Governance / Domain SME** | Signs off scope charters per industry template, validates sensitivity classifications, reviews 31-criteria governance scorecard, approves MAJOR version increments. Provides domain-specific CQs for new templates. | All phases (part-time) | 0.1–0.2 |
| **Frontend Engineer** | Browser-based onboarding wizard (Phase 3 only). Drag-and-drop entity/relationship builder. Generates session JSON consumed by CLI pipeline. React or plain HTML — no framework required. | P3 S15+ only | 0.5 (P3 only) |

---

*Ontology Toolkit Roadmap · Prepared April 2026 · Framework v1.1 · Toolkit v1.5*

*Total estimated effort: 326 engineering-days (271 pipeline + 55 runtime) across 12 months*
