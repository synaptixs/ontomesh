# Features & Capabilities

Index of what the toolkit produces and what each capability is for. Each capability lives in its own focused doc — read only the ones relevant to your job.

> **First time here?** Read [docs/integrate.md](docs/integrate.md) instead. This file is the capability map; integrate.md is the 5-minute recipe.

---

## Capability map

The toolkit is organised in tiers. Most projects use Tier 1 only — everything else is opt-in.

### Tier 1 — Core pipeline (always run)

Generates the OWL ontology, SHACL shapes, JSON-LD context, mapping workbook, and HTML report from any relational schema.

| Phase | What it produces |
|---|---|
| Onboard (`onboard.py`) | Schema, seed data, scope charter, CQ catalog (for new projects) |
| 1 — Foundation | Annotated class and property inventory |
| 2 — Modeling | `enterprise.ttl`, `events.ttl`, `provenance.ttl`, `dimensions.ttl` |
| 3 — Validation | `enterprise-shapes.ttl`, `agent-gate.ttl` |
| reason — Materialisation | `materialised.ttl` + `materialised-lineage.ttl` from OWL-RL ⊕ SHACL `sh:rule` ⊕ SPARQL CONSTRUCT |
| 4 — Mapping | Mapping workbook, semantic loss report, orphan analysis |
| 5 — Exchange | Context file, sample payloads, MCP tool definitions, vocabulary |
| **abox — Instance data** | `instances.ttl` — individuals materialised from your rows, with reified PROV chains and tier gating |
| TMF | TM Forum SID OWL hierarchy (24 APIs, 13 CQs) |
| **quality — Ontology quality** | `ontology_quality.csv` — OOPS! pitfalls, structural metrics, consistency |
| test | SPARQL CQ tests, 36-criterion governance scorecard |
| report | Self-contained HTML run summary |

Or run the lot: `python toolkit.py --phase all --db db/enterprise.db --out output`.

What each output file is for: [docs/artifacts.md](docs/artifacts.md) · What the ontology
actually contains: [docs/concepts/ontology-model.md](docs/concepts/ontology-model.md) ·
How to drive generation: [docs/metadata.md](docs/metadata.md).

### What the ontology gives you

| Capability | What it means in practice |
|---|---|
| **OWL 2 DL with real class expressions** | `owl:Restriction` blocks, defined classes with `owl:equivalentClass` — a reasoner classifies rather than just parsing |
| **`owl:hasKey` from UNIQUE constraints** | Identity semantics: two records sharing an external id are the same thing |
| **Reified PROV-O chains** | `Entity → Activity → Agent` is traversable, not a flat foreign key |
| **Bitemporal modelling** | Valid time (when a fact was true) kept distinct from transaction time (when you recorded it) |
| **United quantities** | A magnitude and its unit are one object, so `15` is never ambiguous |
| **Reified participation** | *Who* took part and *in what role*, not just that they did |
| **Deprecation lifecycle** | Removed terms become `owl:deprecated` tombstones, so held IRIs still resolve |

### Tier 2 — Choose what you need

| Group | What it adds | Read |
|---|---|---|
| **Log-Driven RCA** *(new in v3.2)* | Folder-pointer log ingest, Drain template clustering, PMI entity graph, HMM trajectory anomalies, Granger-gated causal edges, Studio Step 2.5 engineer review, RCA-shaped ontology with `:CausalEvent / :hasCause / :rootCause`, drift template loop | [docs/release-notes.md](docs/release-notes.md) |
| **Rules & Reasoning** *(new in v3.1)* | OWL axioms from wizard inputs, materialised inference (`--phase reason`), per-triple lineage (`prov:wasDerivedFrom`), Studio rule editor with slot-fill / NL drafting / test-fire / premise tree, rule-impact heat map, provider-agnostic LLM Insights | [docs/release-notes.md](docs/release-notes.md) |
| Runtime layer — connect ontology to LLMs | SHACL input/output gates, OWL grounding, prompt assembly, 5 LLM adapters | [docs/runtime.md](docs/runtime.md) |
| Drift monitoring — production-grade | OWL hierarchy + SHACL shapes drive `drift_monitor` (infodrift) | [examples/infodrift/](examples/infodrift/) · [docs/advanced.md §Drift](docs/advanced.md) |
| Graph publishing | One-command upload to Fuseki / Stardog / Oxigraph / Neptune / GraphDB | [docs/advanced.md §Graph publishing](docs/advanced.md) |
| Industry templates | 10 pre-built domains (telecom, healthcare, finance, retail, energy, logistics, government, insurance, pharma, manufacturing) | [install.md §2](install.md#2-start-a-new-project-wizard) · [docs/advanced.md](docs/advanced.md) |
| Browser wizard | Drag-and-drop entity/relationship builder | [docs/advanced.md §Wizard](docs/advanced.md) |

### Tier 3 — Advanced / opt-in

Real features for specific needs, distracting on day 1. All grouped in [docs/advanced.md](docs/advanced.md).

- Conflict resolution — multi-agent 3-tier resolution, PROV-O invalidation
- Ontology alignment & federation (basic) — DOLCE / FOAF / Schema.org / SOSA
- Modular OWL — `modules.json`, `master.ttl`, cycle detection
- Log entity discovery — NLP co-occurrence on log corpora (spaCy)
- TMF630 Task + Bulk operations
- OWL 2 reasoner — ROBOT / ELK / HermiT
- Agentic Semantic Memory — recall / diff / consolidate
- Autonomous Ontology Evolution — proposal store, anomaly monitor, review workflow
- Cross-Enterprise Federation — Ed25519-signed manifests, trust handshake
- Regulatory Compliance Evidence — EU AI Act, Basel IV, HIPAA, Ofcom
- Ontology-Bounded Vector Retrieval — hybrid retriever, 5 vector store adapters

Run `python3 toolkit.py --help` for every flag.

---

## Documentation index

| Doc | Audience | What's in it |
|---|---|---|
| [docs/integrate.md](docs/integrate.md) | First-time adopter | 5-minute SQLite path, 30-minute existing-DB path, what to ignore |
| [install.md](install.md) | Anyone installing | Install command, wizard, connection strings, database backends |
| [docs/artifacts.md](docs/artifacts.md) | Integrator | Repository layout + every generated file explained, standards used |
| [docs/metadata.md](docs/metadata.md) | Integrator | `ontology_metadata` control table fields and semantic loss detection |
| [docs/tmf.md](docs/tmf.md) | Telco engineer | TM Forum SID alignment, 24 Open APIs, 13 CQs, 5G NFs, ITU-T X.733 alarms |
| [docs/runtime.md](docs/runtime.md) | LLM application engineer | Runtime layer, flavors, gates, adapters, OCI Generative AI |
| [docs/advanced.md](docs/advanced.md) | Power user / evaluator | Phase 3 + all five Gen 2 workstreams (publish, drift, federate, comply, evolve, memory, retrieve) |
| [docs/extending.md](docs/extending.md) | Toolkit contributor | Add a loss rule / CQ test / DB backend / SHACL constraint / industry template |
| [docs/sdk.md](docs/sdk.md) | Application developer | Python SDK reference (ReDoc-style) — every public class/function |
| [examples/](examples/) | Engineer | Runnable demos — retail, 5G, drift monitoring |

---

## Governance

The pipeline auto-scores generated ontologies against a 34-criterion checklist and emits the result to `output/reports/governance_scorecard.csv` (regenerated each `--phase test` run).

Thresholds:

| Score | Meaning |
|---|---|
| ≥ 4.0 / 5.0 | Production-ready |
| ≥ 3.0 / 5.0 | Above minimum gate (CI passes) |
| < 3.0 / 5.0 | CI fails — investigate before shipping |

The CI workflow at [.github/workflows/ontology.yml](.github/workflows/ontology.yml) enforces these thresholds on every PR.
