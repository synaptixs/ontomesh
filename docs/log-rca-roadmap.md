# Log-Driven RCA — Phased Roadmap

> Goal: point the toolkit at a folder of logs, mine **entities, relationships, and events**, surface them to an engineer for review, and emit a domain-shaped ontology that downstream `--phase reason` + Insights can run **root-cause analysis** queries against.
>
> Status: plan only — nothing in this document is implemented yet. References to `src/log_connector.py`, `src/entity_discoverer.py`, `runtime/drift/`, the Studio Rules step, Phase B (`materializer.py`), and Phase D (`materialised-lineage.ttl`) are existing capability the plan **builds on**, not duplicates.

---

## 1. What we already have

Don't rebuild these. The roadmap reuses each one.

| Capability | Where | What it does today |
|---|---|---|
| **Folder-pointer log ingest** | `src/log_connector.py` | Reads JSON-Lines / syslog RFC 5424 / CEF / OTLP / regex from any path or glob — no upload. Writes `observations` + `domain_events` rows anchored to `ontology_metadata`. CLI: `--phase log --log-path /var/log/*.log`. |
| **NLP entity discovery** | `src/entity_discoverer.py` | spaCy NER + co-occurrence over log corpora, candidate scoring (TF-IDF style), CSV + JSON output. Already designed to **never auto-add** — feedback into the wizard is the intended path. CLI: `--phase discover --log-path …`. |
| **Drift monitoring** | `runtime/drift/{monitor,enricher,gate,propagator}.py` | OWL hierarchy + SHACL shapes drive runtime drift detection on incoming records. |
| **Evolution proposal store** | `db/schema.sql` → `ontology_evolution_proposals` | Pending / approved / rejected workflow with confidence + 5 scoring dimensions. Today populated by the autonomous evolution monitor; the same table is the right home for engineer-reviewed log candidates. |
| **Rules step in Studio** | `wizard/rules.py`, `wizard/templates/index.html` (Step 5.5) | Slot-fill SHACL builder, SPARQL/OWL editors, validation, library, test-fire preview, NL drafting, rule-impact heat overlay. Authors rules that downstream `--phase reason` consumes. |
| **Materialisation + explain** | `src/materializer.py`, `output/ontology/materialised.ttl`, `materialised-lineage.ttl` | OWL-RL ⊕ SHACL `sh:rule` ⊕ SPARQL CONSTRUCT engines emit `prov:wasDerivedFrom` per derived triple. The Viewer's Materialised tab renders premise trees. |
| **LLM Insights** | `runtime/insights.py` | Provider-agnostic grounding (OpenAI / OCI / Anthropic / Vertex / Ollama) with materialised-triple toggle and IRI hallucination filter. |

## 2. What's missing for log-driven RCA

1. **Pattern recognition is shallow.** `entity_discoverer.py` does NER + frequency + co-occurrence — fine for surfacing common nouns. RCA needs sequence mining, template clustering (Drain-style), causal-pair inference, temporal correlation, anomaly scoring. None of Bishop's machinery is there.
2. **No relationship extraction with directionality.** Co-occurrence pairs are unordered. RCA needs ordered `(cause, predicate, effect)` triples with temporal evidence.
3. **No event templating.** Each log line becomes an `observations` row, but operationally we want **event types** clustered by message template (`"NF_DEREGISTERED triggered after 3 missed heartbeats"` → `NfHeartbeatTimeoutEvent`).
4. **No engineer-review surface specifically for log-mined proposals.** The `ontology_evolution_proposals` table exists but the wizard doesn't have a "review log discoveries" step — discoveries land in a CSV/JSON file outside the editing loop.
5. **No RCA-specific generated ontology shape.** The current generator produces a domain-entity / data-property hierarchy. RCA wants a **causal graph** with `:hasCause`, `:triggers`, `:precededBy` properties, time intervals, severity tiers, and propagation rules.
6. **No closed loop.** Today's flow is log → CSV → engineer copies into wizard. We want log → review → ontology → materialise → query.

---

## 3. Pattern-recognition stack — what to add and where it sits

Bishop's PRML is the spine. Each technique maps to a concrete pipeline step. We do not need to ship every chapter — just the four that earn their keep on log corpora.

| PRML reference | Technique | Pipeline role | Existing nearest neighbour |
|---|---|---|---|
| Ch. 9 — Mixture models, EM | **Template clustering** (Drain-style trees + EM refinement). Each cluster = one event type. | Step 2 (Mine) | nothing — new |
| Ch. 8 — Graphical models | **Bayesian co-occurrence network** scored by mutual information, not raw counts. Edge direction inferred from temporal ordering. | Step 2 (Mine) | `entity_discoverer.py` co-occurrence is the seed; replace counting with PMI |
| Ch. 13 — Sequential data | **HMM / linear-chain CRF** over message sequences to learn typical event-trajectories per service. Anomalies = low-likelihood paths. | Step 3 (Sequence) | nothing — new |
| Ch. 11 — Sampling / Ch. 14 — Combining models | **Granger / transfer-entropy causality test** on event-rate time series across services. Surfaces "A's spike precedes B's spike" candidates. | Step 4 (Causality) | nothing — new |
| Ch. 12 — Continuous latent vars | **PCA / t-SNE** for a clustering visualisation per template, used **only** in the review UI to help engineers see structure — not in the generated ontology. | Step 5 (Review) | nothing — new |
| Ch. 1 — Decision theory | **Confidence scoring** with calibrated probabilities so the review queue is ordered by `precision × consequence`, not raw counts. | Step 5 (Review) | proposal-store already has `confidence_score` + 5 `dim_*` columns — reuse |

**Out of scope deliberately:**

- Neural sequence models (LSTM / Transformer log embedding) — heavy, opaque, and the engineer-review burden goes *up*, not down, when the candidate is a black-box embedding distance. Add only if our four classical techniques plateau.
- LLM-based extraction at mining time. The LLM has a real role in **review** (suggest a label, summarise a cluster) and **materialisation grounding** — but driving entity extraction with an LLM at scale on a folder of logs is expensive, drifts, and is hard to audit. Keep extraction deterministic.

---

## 4. End-to-end target flow

```
   logs/ folder
        │
        ▼
┌──────────────────┐   reuse src/log_connector.py
│ 1. Ingest        │   normalises → observations + domain_events
└────────┬─────────┘   (already exists)
         │
         ▼
┌──────────────────┐   NEW src/log_miner.py
│ 2. Mine          │   template clustering (Drain + EM)
│                  │   PMI-weighted entity graph
│                  │   relationship-pair extraction
└────────┬─────────┘
         │
         ▼
┌──────────────────┐   NEW src/sequence_learner.py
│ 3. Sequence      │   HMM per service trajectory
│                  │   anomalous path → candidate event
└────────┬─────────┘
         │
         ▼
┌──────────────────┐   NEW src/causality_miner.py
│ 4. Causality     │   PMI + temporal-ordering → directed edges
│                  │   Granger / transfer-entropy on rates
└────────┬─────────┘
         │
         ▼
┌──────────────────┐   NEW wizard step
│ 5. Engineer      │   list / cluster-card / mini-graph view of every
│    review        │   candidate (entity / relationship / event-template)
│                  │   reuses ontology_evolution_proposals table
│                  │   approve / reject / merge / edit-then-approve
└────────┬─────────┘
         │
         ▼
┌──────────────────┐   reuse ontology_generator.py + Phase A axioms
│ 6. Generate RCA  │   adds :hasCause / :triggers / :precededBy taxonomy
│    ontology      │   adds time-interval data props + propagation rules
└────────┬─────────┘
         │
         ▼
┌──────────────────┐   reuse --phase reason (Phase B)
│ 7. Materialise   │   OWL-RL ⊕ SHACL ⊕ SPARQL CONSTRUCT
│                  │   produces materialised.ttl with :rootCause edges
└────────┬─────────┘
         │
         ▼
┌──────────────────┐   reuse Phase D + Phase E
│ 8. RCA query     │   Insights with materialised-triples toggle ON
│    via Insights  │   "what caused outage 42?" → derived :rootCause
│                  │   with prov:wasDerivedFrom premise tree
└──────────────────┘
```

**Three of eight steps already exist (1, 6 partial, 7, 8). Five are new (2, 3, 4, 5, and the RCA-shaped extensions to 6).**

---

## 5. Phased plan

### Phase L1 — Log mining (template + entity graph)

**New module:** `src/log_miner.py`

- **Template clustering.** Implement Drain (proven over 16 log datasets in the LogPAI benchmark) with an EM refinement pass to merge near-duplicate templates. Each cluster gets a stable id and a representative template (`"NF_DEREGISTERED triggered after <num> missed heartbeats"`).
- **Variable slot extraction.** Parameters extracted from `<*>` slots become candidate **data properties** when their values cluster (IP, NF-id, timestamp, severity); become candidate **object property targets** when they reference IRIs of known entities.
- **PMI-weighted entity graph.** Replace `entity_discoverer.py`'s raw co-occurrence with pointwise mutual information `PMI(x,y) = log P(x,y) / (P(x)P(y))`. Threshold ≥ τ gives the candidate edge set.
- **Temporal ordering.** For each PMI edge, count how often `x` precedes `y` within a configurable window; direction is set when the ratio passes a confidence threshold, otherwise the edge stays bidirectional and review flags it.

**Output:** `output/mining/templates.json`, `output/mining/entity_graph.json`, `output/mining/candidates.csv`.

**Effort:** ~3 days (Drain alone is 1 day; PMI + temporal is 1; integration with existing log_connector is 1).

### Phase L2 — Sequence + anomaly learning

**New module:** `src/sequence_learner.py`

- **Per-service trajectories.** Group event-template ids by service/host/component. Each trajectory is a sequence of cluster ids.
- **HMM training.** Fit a small HMM per service (≤ 16 hidden states by default, BIC-selected). Compute per-sequence likelihood under the trained model.
- **Anomaly surfacing.** Sequences in the lower percentile are surfaced as **candidate root-cause events** — their position in the trajectory tells us where the regime change started. The cluster id at the change point becomes a candidate event class.

**Output:** appended to `candidates.csv` with `dim_consistency_risk` filled in.

**Effort:** ~2 days.

### Phase L3 — Causality candidates

**New module:** `src/causality_miner.py`

- **Pairwise Granger test** on event-rate time series across the entity graph (downsampled to minute buckets). Surfaces directed `(cause, effect)` candidates with a p-value.
- **Transfer-entropy fallback** for non-stationary series (heavy-tailed event rates routinely break Granger's stationarity assumption — the entropy estimator handles those).
- **Triangulation.** A candidate causal edge is only proposed when (a) PMI > τ, (b) temporal ordering confidence > τ, and (c) Granger or transfer-entropy confirms direction. Three orthogonal signals keep false-positive rate manageable.

**Output:** `output/mining/causality.csv` with rows `(cause_template, effect_template, lag_seconds, p_value, n_samples, confidence)`.

**Effort:** ~1.5 days.

### Phase L4 — Engineer review step in the Studio

**New wizard step: 2.5 — Log Discovery**

A new sidebar entry between Entities (Step 2) and Events (Step 3), backed by the existing `ontology_evolution_proposals` table (proposal_type extended with `LOG_ENTITY`, `LOG_RELATIONSHIP`, `LOG_EVENT`, `LOG_CAUSAL_EDGE`).

UI surfaces:

- **List view** — every candidate from steps L1–L3, sortable by confidence × consequence. Each row has: ✓ approve · ✕ reject · ✎ edit · 🔀 merge with existing.
- **Cluster card** — for an event-template candidate, shows the representative template, a sample of the originating log lines, the inferred variables, and a one-click "promote to event class with these data properties."
- **Mini graph** — for a relationship / causal-edge candidate, draws the two endpoint classes (lit up on the main Relationships graph) with the edge tagged with confidence, lag, p-value.
- **PCA / t-SNE 2D plot** of the template clusters (read-only, for the engineer to spot ill-fitting groupings before approving).
- **LLM-assist** *(optional, behind the Insights provider)* — "summarise this cluster in one sentence" and "suggest an OWL class name" using the existing `runtime/insights.py` adapter pipeline. Output goes into editable fields; the engineer always confirms.

**API endpoints:** `GET /api/log-discovery/candidates`, `POST /api/log-discovery/{id}/approve|reject|merge|edit`.

Approved candidates flow into `session.entities`, `session.events`, `session.relationships`, and a new `session.causal_rules` array.

**Effort:** ~3 days (the existing rule editor / mini-graph patterns make the surface area smaller than it looks).

### Phase L5 — RCA-shaped ontology generation

**Extends:** `src/ontology_generator.py`

- **Causal taxonomy.** Always emit a small top-level taxonomy:
  ```
  :CausalEvent       a owl:Class .
  :hasCause          a owl:ObjectProperty ; rdfs:domain :CausalEvent ; rdfs:range :CausalEvent .
  :triggers          a owl:ObjectProperty ; owl:inverseOf :hasCause .
  :precededBy        a owl:ObjectProperty, owl:TransitiveProperty .
  :rootCause         a owl:ObjectProperty .
  ```
- **Time interval properties.** Every log-derived event class gains `:startedAt`, `:endedAt`, `:duration` data properties typed `xsd:dateTime` / `xsd:duration`.
- **Severity tier.** Maps from log severity (`DEBUG/INFO/WARN/ERROR/CRITICAL`) into the existing `:sensitivityTier` pattern (reuse, don't fork).
- **Propagation rules emitted from approved causal edges.** Each approved causal edge becomes a SPARQL CONSTRUCT rule in `output/sparql_rules/causal-<id>.rq`:
  ```sparql
  CONSTRUCT { ?e :hasCause ?c . ?c :triggers ?e }
  WHERE     { ?c a :HeartbeatTimeoutEvent ; :occurredOn ?nf .
              ?e a :NfDeregisteredEvent  ; :occurredOn ?nf .
              FILTER (?e_time - ?c_time < "PT30S"^^xsd:duration) }
  ```
- **Generator integration.** The wizard's approved `session.causal_rules` is exported by `wizard/rules.py:export_rules` exactly like today's hand-authored rules — Phase B materialisation already consumes that path.

**Effort:** ~1.5 days.

### Phase L6 — RCA query templates + Insights wiring

**New starter library:** `templates/rules/rca.yaml`

Three rule families authors get for free:

1. **Cause-chain closure** — derive `:rootCause` as the transitive closure of `:hasCause` minus any node that itself has a cause.
2. **Concurrent-cause flagging** — when two causal candidates share an effect within Δt, mark the effect as `:multipleCandidateCauses` so the engineer doesn't get tunnel vision.
3. **Heartbeat / timeout inference** — converts the heartbeat-timeout vs explicit-deregister ambiguity (the 3GPP R4 case from the 5G demo) into derived `:derivationMethod :INFERRED` vs `:MEASURED`.

**Insights prompts.** Ship two RCA-shaped prompts in the Insights box:

- *"What caused {event_iri}?"* → Insights answers with the asserted + materialised graph, returning the `:rootCause` IRI plus the premise tree via Phase D's lineage.
- *"Show similar past incidents to {event_iri}."* → SPARQL pattern match over `:CausalEvent` instances sharing severity / type / affected-asset.

**Effort:** ~0.5 day.

### Phase L7 — Closed-loop drift hook (optional, ship after L1–L6 settle)

Wire `runtime/drift/monitor.py` into the log feed so once an ontology is generated, **new** log lines that don't match any approved template become drift candidates routed back into the same review queue from Phase L4. The engineer's review queue becomes the single point of human attention for both bootstrap and steady-state.

**Effort:** ~1 day.

---

## 6. Recommended ordering + dependencies

| Order | Phase | Effort | Dependencies |
|---|---|---|---|
| 1 | L1 — Log mining | 3 d | none (consumes existing `log_connector`) |
| 2 | L2 — Sequence learning | 2 d | L1 (uses template ids) |
| 3 | L3 — Causality candidates | 1.5 d | L1, L2 |
| 4 | L4 — Engineer review step | 3 d | L1–L3 (consumes their candidates) |
| 5 | L5 — RCA ontology shape | 1.5 d | L4 (consumes approved candidates) |
| 6 | L6 — RCA templates + Insights | 0.5 d | L5 |
| 7 | L7 — Closed-loop drift | 1 d | L1, L4, L6 |

**Total: ~12.5 person-days** for the full loop. The smallest shippable slice that demonstrates value is **L1 + L4 + L5** (~7.5 days) — that gives engineers a "logs in → ontology out, with a review step" story without the sequence / causality machinery, which can land in a v2.

---

## 7. Acceptance criteria for the v1 milestone (L1 + L4 + L5)

1. `python toolkit.py --phase mine --log-path /var/log/myservice/` runs on a 100k-line corpus in **under 60 seconds** on a developer laptop.
2. The Studio's new **Log Discovery** step lists at least 20 candidates for that corpus, each with a confidence score and a sample of the originating log lines.
3. After an engineer approves ≥ 5 candidates and runs `--phase 2 --phase reason`, the resulting `materialised.ttl` contains at least one derived `:hasCause` triple with a `prov:wasDerivedFrom` block that names the rule and lists premises.
4. The Insights "what caused {event}?" prompt returns an answer whose `grounded_iris` array contains the engineer-approved class names with zero `unknown_iris` for those names.

---

## 8. Risks worth naming now

- **Pattern false-positives.** Drain over a noisy corpus produces hundreds of micro-clusters; without aggressive merging the review queue is unusable. Mitigation: BIC-selected EM merging in L1 with an upper-bound on cluster count (default 200), surfaced as a slider in the review UI.
- **Causality vs correlation.** Granger and transfer-entropy detect statistical dependence, not causation. The review UI must label these candidates as **"statistically dependent — engineer to validate causality."** Never auto-promote them to the generated ontology without approval.
- **PII in log values.** Mined data-property values can contain user IDs, emails, IPs. Inherit the existing `:sensitivityTier` machinery: the miner classifies every slot via a small regex+entropy heuristic and tags candidate properties with a minimum tier of **Confidential** unless the engineer downgrades.
- **Review-queue fatigue.** If we generate 500 candidates on first run, no one reviews. Mitigation: confidence × consequence sort (Bishop Ch. 1), top-50 default cap, and a "batch approve cluster" affordance for templates the engineer recognises at a glance.
- **Generated ontology bloat.** A bad approval session can produce hundreds of overlapping event classes. Mitigation: the existing OWL profile detector already reports axiom counts; we add a soft warning when log-derived classes exceed `2 × hand-authored classes`.

---

## 9. Open questions to resolve before coding L1

1. **Storage for raw templates.** SQLite (one row per template, version-bumped on EM refinement) or a flat JSON in `output/mining/`? Lean towards SQLite so the review UI can query incrementally.
2. **Per-corpus or global model?** A single global HMM across services is cheaper but less useful for RCA. Per-service is the right default; revisit if memory pressure shows up.
3. **Default look-back window.** 7 days? 30 days? Should be a CLI flag (`--since`) defaulting to whatever the log files actually contain.
4. **Tokenisation for spaCy vs Drain.** Drain works on the raw line; spaCy on the cleaned message body. Need to agree on the cleaner once so both pipelines see the same input.
5. **Bishop chapters we deferred (Ch. 5 NN, Ch. 6 kernels, Ch. 10 variational inference).** Worth revisiting after L1–L3 ship — there's a real argument for variational Bayes over the causal-edge prior. Park until we have a baseline.

---

## 10. Out of scope (for this roadmap)

- Real-time streaming ingest. The toolkit's batch model (folder + `--phase mine`) is the right fit for ontology bootstrap. Streaming belongs to the drift monitor once L7 lands.
- Distributed mining across log shards. Single-laptop, single-folder for v1. Sharding is mechanical once the algorithms are correct.
- LLM-based root-cause reasoning. The LLM grounds the **query**; the *reasoning* is SPARQL/SHACL/OWL-RL over the materialised graph. Mixing the two at RCA time hurts auditability.

---

## 11. Where this leaves us

Once L1–L6 are in production, the toolkit does for **log-driven RCA** what v3.1 did for hand-authored ontology rules: it turns the engineer's tacit knowledge into a validated, materialised, queryable graph — with full lineage. The Bishop-style ML earns its place by **shortening the engineer's path from logs to reviewed candidates**, not by replacing the engineer. Every derived `:rootCause` triple is still backed by a rule the engineer approved, and the premise tree on the Materialised tab lets an auditor follow the chain back to specific log lines.
