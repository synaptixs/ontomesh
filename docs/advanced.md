# Advanced features

Phase 3 (Scale & Community) and the five Generation 2 workstreams. Each is opt-in — most projects do not need any of these on day 1. For the minimum-viable adoption path see [integrate.md](integrate.md).

---

## 9. Phase 3 — Scale & Community

Phase 3 completes the toolkit with deployment infrastructure, additional industry verticals, ML monitoring integration, and a browser-based authoring interface. All 8 items are implemented in v2.0.

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

Or load directly from Ontology Studio's template picker.

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

### 9.8 Ontology Studio

Web-based equivalent of `onboard.py` with a drag-and-drop entity/relationship builder, an Ontology Library for save/load, and post-generation tools (Evolution Review, Compliance Dashboard, Vector Retrieval).

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

**Workstream 1 — Generation 2.**

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

**Workstream 2 — Generation 2.**

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

**Workstream 3 — Generation 2.**

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

Formal Community Group Draft Report at [`federation/specs/cross-enterprise-ontology-interop.md`](https://github.com/synaptixs/ontomesh/blob/main/federation/specs/cross-enterprise-ontology-interop.md). Covers:

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
| W3C CG draft report | [federation/specs/cross-enterprise-ontology-interop.md](https://github.com/synaptixs/ontomesh/blob/main/federation/specs/cross-enterprise-ontology-interop.md) |
| DDL additions | [db/schema.sql](db/schema.sql) (`federation_partners`, `federation_query_log`, `federation_trust_ledger`) |
| CLI wiring | [toolkit.py](toolkit.py) — `--phase federate` |

---

## 13. Generation 2 — Regulatory AI Compliance Evidence Engine

**Workstream 4 — Generation 2.**

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

`pass_expression` is a tiny declarative DSL (`status == 'PASS'`, `score >= 3`, `chain_depth >= 2`, `exists`) so custom regulations do not need Python code.

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

### 13.5 Compliance Dashboard (Ontology Studio)

New **Compliance Dashboard** tab in Ontology Studio:

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

**Workstream 5 · Branch:** `S5-Ontology-Bounded-Vector-Retrieval`.

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
