# Ontology Engineering Toolkit — v3.0

**Domain-agnostic · Phase 3 complete · Scale & Community edition**

A complete end-to-end implementation of the [Domain-Agnostic Ontology Engineering Framework v1.1](docs/framework-whitepaper.md). Takes a relational database schema and produces a production-ready OWL 2 ontology, SHACL validation shapes, JSON-LD agent payloads, SKOS vocabulary, and a scored governance report — for any domain, any industry, any major relational database.

---

## Documentation

This README is the landing page. Detailed reference is split across three files:

| File | Contents |
|---|---|
| **[install.md](install.md)** | Prerequisites · onboarding wizard · database connection strings (SQLite, PostgreSQL, MySQL, MSSQL, Oracle/ADB, DB2) · full pipeline walkthrough · CLI reference |
| **[features.md](features.md)** | Repository structure · generated artifacts · semantic metadata control table · semantic loss detection · TM Forum alignment (24 Open APIs, 13 CQs) · standards · extending the toolkit · runtime layer · Phase 3 (Scale & Community) · all five Generation 2 workstreams |
| **[gates.md](gates.md)** | Governance scorecard (34 criteria) · Phase 3 + Workstream 1–5 exit gates · consolidated 43-test SPARQL CQ matrix |
| **[docs/sdk.md](docs/sdk.md)** | Python SDK reference (ReDoc-style) — `RuntimeClient`, `FlavorRegistry`, `Grounder`, `PayloadAssembler`, `InputGate`, `OutputGate`, `AgentMemory`, `HybridRetriever`, `runtime.drift.*` (P1–P5), all LLM adapters, vector store adapters, pipeline modules |

---

## What it does

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
| **publish** | **Graph store publishing ✓ Phase 3** | **One-command upload to Fuseki/Stardog/Oxigraph/Neptune/GraphDB with named-graph sensitivity partitioning** |
| **drift** | **Drift detection extension ✓ Phase 3** | **drift.ttl (DriftObservation OWL hierarchy), drift-shapes.ttl, drift-skos.ttl (PSI/KL/JS/Calibration/LogShift)** |
| **templates** | **Industry templates ✓ Phase 3** | **5 new domains: Energy (IEC CIM), Logistics, Government (DCAT/INSPIRE), Insurance, Pharma (IDMP). 10 templates total.** |
| **modular** | **Modular OWL ✓ Phase 3** | **modules.json manifest, master.ttl (owl:imports graph), cycle detection, IRI conflict report** |
| **discover** | **Log entity discovery ✓ Phase 3** | **entity_discovery_candidates.csv, entity_discovery_summary.json (NLP co-occurrence, spaCy)** |
| **tmf630** | **TMF630 Task + Bulk ✓ Phase 3** | **tmf630-task-bulk.ttl, tmf630-task-mcp-tools.json, TmfTask/TmfImportJob/TmfExportJob OWL+SHACL** |
| **wizard** | **Browser wizard ✓ Phase 3** | **Flask web app — drag-and-drop entity/relationship builder, template picker, pipeline runner** |
| **memory** | **Agentic Semantic Memory ✓ Gen 2 / WS1** | **AgentMemory (recall/diff/consolidate/snapshot), 5 temporal SPARQL templates, consolidation daemon, 5 CQ-MEM tests, RuntimeClient memory_recall + remember()** |
| **evolve** | **Autonomous Ontology Evolution ✓ Gen 2 / WS2** | **Proposal store + ledger, 4-strategy anomaly monitor, 5-dim candidate scorer, review workflow (Flask + CLI), CI/CD auto-versioner (reasoner + SPARQL gate), 5 CQ-EVO tests** |
| **federate** | **Cross-Enterprise Federation ✓ Gen 2 / WS3** | **Partner registry (JSON + DB), Ed25519-signed capability manifests, cross-enterprise SPARQL router, boundary SHACL + RESTRICTED block, 3-step trust handshake + ledger, W3C CG draft spec, 5 CQ-FED tests** |
| **comply** | **Regulatory AI Compliance Evidence Engine ✓ Gen 2 / WS4** | **4 pre-built regulation files (EU AI Act · Basel IV SR 11-7 · HIPAA §164.312 · Ofcom Network Transparency), evidence assembler, Ed25519-signed ZIP bundles with SHA-256 manifest, regulation↔toolkit mapping layer + gap analysis, Compliance Dashboard UI, compliance_summary.html, 5 CQ-CMP tests, 2 new scorecard criteria** |
| **embed** / **retrieve** | **Ontology-Bounded Vector Retrieval ✓ Gen 2 / WS5** | **Flavor-scoped embedding indexes, OWL class-hierarchy filter + sensitivity tier gate, hybrid query executor (vector × PROV-O confidence × recency), 5 vector-store adapters (memory/Qdrant/Chroma/Weaviate/pgvector), benchmark suite (UNFILTERED_VECTOR vs ONTOLOGY_BOUNDED vs PURE_SPARQL — precision@k / MRR / latency p50/p95), retrieval_summary.html, Wizard Vector Retrieval tab, 5 CQ-VEC tests, RuntimeClient.ask(retrieval="hybrid", class_expression=...)** |
| **monitor** | **Production Drift Monitoring ✓ v3.0 / infodrift** | **Runtime integration of [infodrift](https://github.com/nrohilla-fibonacci/infodrift) drift_monitor (P1–P5): `runtime/drift/` enricher + monitor + propagator + gate, ontology-aware PSI/KL/JS/Calibration/LogShift detectors wired into RuntimeClient, drift events propagated to PROV-O graph and SHACL agent gate, 12 integration tests** |

---

## Quickstart

```bash
# New project — interactive wizard
python3 onboard.py --industry telecom

# Existing database — point the pipeline at it
python3 toolkit.py --db "postgresql://user:pass@host/mydb"

# Open the HTML report
open output/reports/toolkit_report.html
```

Prerequisites, driver installs, and connection strings for every backend: see [install.md](install.md).

---

## Install via pip

The toolkit ships as a pip-installable package (sdist + wheel) built from `pyproject.toml`. Two console scripts (`ontology-toolkit`, `ontology-onboard`) are exposed on install.

```bash
# From a built wheel (see dist/)
pip install dist/ontology_toolkit-3.0.0-py3-none-any.whl

# With all DB drivers (postgres, mysql, mssql, oracle, db2, oci, neptune)
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[all]"

# Pick individual extras instead
pip install "dist/ontology_toolkit-3.0.0-py3-none-any.whl[postgres,oracle]"
```

To rebuild the artifacts from source:

```bash
python -m build      # produces dist/*.whl and dist/*.tar.gz
```

Note: the `drift-monitor` dependency (the [infodrift](https://github.com/nrohilla-fibonacci/infodrift) runtime drift package) is a git+VCS reference, so the wheel is intended for private/internal distribution rather than PyPI.

---

## First-contact demos — ontology vs baseline LLM

Two self-contained demos compare an LLM answering the same questions with and without the toolkit-generated ontology. Each runs end-to-end in ~4 seconds against SQLite, produces an engineering-facing full matrix (8 questions × 2 vendors × 2 modes) and an executive one-page view, and falls back to ground-truth-derived illustrative answers when no API keys are set.

| Domain | Test plan | Schema | Runner | What it exposes |
|---|---|---|---|---|
| Retail | [test-plan.md](test-plan.md) · [demo.md](demo.md) | [db/demo.sql](db/demo.sql) | `./demo.sh` | `status` overload across 3 tables, PROV-O MEASURED vs INFERRED events, FK→object-property traversal, SHACL output gating |
| 5G Core NFs | [test-plan-5g.md](test-plan-5g.md) | [db/demo_5g.sql](db/demo_5g.sql) | `./demo_5g.sh` | `active` overload across 5 tables (3GPP TS 29.510), composite S-NSSAI (TS 23.003), heartbeat-inferred deregistration (TS 29.510 §5.2.2), NR/LTE PM counter collision (TS 28.552 vs 32.425), SUPI redaction |

Both use the same toolkit pipeline, SHACL gates, and `RuntimeClient` — only the schema, runtime flavor, and question bank differ. Run with `--live` and `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` to swap the illustrative answers for real LLM output through the full governance pipeline.

---

## OCI Generative AI setup

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

## Standards used

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

## Companion documents

| Document | Audience | Purpose |
|---|---|---|
| [install.md](install.md) | All teams | Install, onboarding, CLI, database connection |
| [features.md](features.md) | Engineers | Artifacts, metadata control, runtime, Gen 2 workstreams |
| [gates.md](gates.md) | All teams | Governance scorecard, exit gates, CQ-test matrix |
| [test-plan.md](test-plan.md) · [demo.md](demo.md) | Demo viewers | Retail first-contact test plan — ontology-vs-baseline LLM comparison |
| [test-plan-5g.md](test-plan-5g.md) | Demo viewers · telco | 5G-NF first-contact test plan — 3GPP / GSMA / O-RAN-anchored semantic issues |
| [docs/sdk.md](docs/sdk.md) | Application developers | Python SDK reference — every public class/function with signature, parameters, returns, and examples |
| [docs/framework-whitepaper.md](docs/framework-whitepaper.md) | Architects | Full framework specification v1.1 |
| [docs/executive-summary.md](docs/executive-summary.md) | Leadership | Non-technical overview — what, why, and first steps |
| [docs/technical-blueprint.md](docs/technical-blueprint.md) | Engineers | Phase-by-phase implementation guide with code patterns |
| [ontology_governance_checklist.csv](ontology_governance_checklist.csv) | All teams | 34 scored criteria for assessing ontology maturity |
| `output/reports/toolkit_report.html` | All teams | Visual run report — open in browser after each pipeline run |

---

*Framework: v1.1 · Toolkit: v3.0 · April 2026*
*OWL 2 · SHACL · PROV-O · SKOS · JSON-LD · TM Forum SID v23.0 · 6 database backends · Runtime layer (complete) · Generation 2 workstreams 1–5 complete · Production drift monitoring (infodrift P1–P5) · pip-installable*
