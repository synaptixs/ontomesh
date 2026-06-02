# Ontology Toolkit v3 — Roadmap

> **Status:** plan only. Nothing in this document is implemented yet.
> Builds on the v2 work that landed via PR #23 (Log Discovery L8–L13)
> and extends across the rest of the toolkit (schema import, generation
> targets, reasoning, federation, compliance, vector retrieval, drift,
> security).

> **Companion docs:**
> [log-discovery-enhancements-roadmap.md](log-discovery-enhancements-roadmap.md)
> — the v2 plan that this builds on.
> [log-rca-roadmap.md](log-rca-roadmap.md) — the v1 plan.
> [reasoning-roadmap.md](reasoning-roadmap.md) — the prior reasoning plan
> that this doc folds into Tier 2.

---

## 1. Where v2 leaves us

| Capability | Today's state | Roadmap chapter |
|---|---|---|
| Log → templates | Drain3 + EM merge | L1 |
| Slot typing + entity graph | Regex ladder + PMI | L1.5 |
| Per-service trajectory model | Switching SSM (mixture-of-HMM) | L8 |
| Anomaly confidence | VB posterior probability (ECE < 0.05) | L10 |
| Causality | PC algorithm DAG with shared causes | L11 |
| Template viz / merge | pPCA 2D scatter + nearest-neighbour | L12 |
| Rate anomalies | Per-template GP + 99 % posterior band | L13 |
| Review queue | Active-learning ranker + grouped UI | L9 + L4 |
| Schema import | Postgres / MySQL / Oracle / DB2 / SQL Server connectors | `wizard/importer.py` |
| Generation | OWL + SHACL + Turtle | `--phase 2` |
| Vector retrieval | Ontology-bounded retrieval (S5 branch) | partial |
| Federation | Signed manifests across orgs (S3 branch) | partial |
| Compliance evidence | Regulatory registries + signed bundles (S4 branch) | partial |
| Drift monitoring | Tests in place | `feature/monitordrift` |
| Reasoning | Plan-only | `reasoning-roadmap.md` |

Across these, v2 hardened the Log Discovery vertical to a defensible
level. The rest of the toolkit is **uneven** — some surfaces are
production-ready, others are placeholders. v3 is about lifting the
floor.

---

## 2. Where the toolkit is still shallow

Honest inventory, ranked by adoption-blocking severity.

1. **Schema import is structural, not semantic.** Foreign-key chains
   become loose link properties; junction tables become two separate
   properties; NULL semantics is dropped; views and stored procedures
   are ignored. Most enterprise databases encode business meaning in
   exactly those places.

2. **No logical reasoning.** The toolkit emits OWL but never queries
   it via a reasoner. Classification, consistency checking, and
   entailment — the three things that distinguish an ontology from a
   schema — are absent.

3. **Single-shot generation.** OWL + SHACL + Turtle land in `output/`
   and the engineer is on their own to make Neo4j, GraphQL, Datadog,
   or downstream tools consume them. The ontology should be a
   *generator*, not a deliverable.

4. **No cross-corpus memory.** Every project starts from zero.
   Templates we mined for telecom client A teach us nothing about
   telecom client B. This is the biggest blocker to SaaS-style
   adoption.

5. **Batch only.** Logs flow continuously in production but the
   pipeline assumes a static folder. Re-mining the full corpus on
   every run is the only operating mode.

6. **Single-modality.** Logs are mined. Metrics, traces, deploys,
   incidents — all of which would feed the same causal DAG — are
   ignored.

7. **Proposal names are mechanical.** `Event_42`, `AnomalousEvent_99`.
   Engineers spend cognitive overhead translating IDs into meaning
   every time they review the queue.

8. **No policy layer.** Every proposal requires human eyes. There is
   no notion of "auto-approve if confidence > 0.95 AND no PII flag."

9. **No semantic diff between ontology versions.** When v1.2 becomes
   v1.3, a reviewer cannot see *what the change means* — only what
   text moved.

10. **No reasoning-grounded compliance.** Compliance bundles list
    facts; they cannot say *"because the ontology entails X, the
    constraint is satisfied."*

11. **MLOps absent.** No per-phase quality dashboards, no calibration
    drift alerts, no A/B testing harness. The v2 path / v1 path
    toggle is a structural prototype, not a measurement system.

12. **Security / multi-tenancy.** Single-user Flask wizard, plain-text
    DB credentials, no audit trail, no RBAC on proposals. Fine for
    local; impossible for production.

---

## 3. Three tiers of v3 progression

Each tier mixes Log Discovery follow-ons with cross-cutting toolkit
improvements. Tiers compound — Tier 2 leans on Tier 1; Tier 3 leans
on Tier 2.

### Tier 1 — Highest leverage, smallest effort

The "v3.0 slice." Each item independently shippable. ~3–4 months total
if done sequentially; ~6–8 weeks if some run in parallel.

---

#### T1.1 — LLM-assisted naming and explanations

**Domain:** Log Discovery (review surface).
**Problem this fixes.** §2.7 above — engineers translate `Event_42`
into meaning manually.

**Technique.** An LLM (no fine-tuning) used *only* at the labeling
layer:
- Read template + sample line + slot types → propose a class name
  like `:UserAuthFailureRetry` and an `rdfs:comment` line.
- Read a causal-edge candidate → propose a one-line plain-English
  explanation: *"Auth-failure cascades to retry storms; conditioning
  on `deploy_event` removes the spurious dependency."*
- Keep the LLM completely out of inference. The audit trail stays
  statistical; only the *labels* are AI-written, and the engineer
  can override every one.

**New module.** `wizard/proposal_namer.py`. Pure function
`name_proposal(proposal_row) -> {title, description}`. Provider
abstracted behind an env var so we can swap OpenAI / Anthropic /
local model without code changes.

**Acceptance gate.**
- 50 historically-approved LOG_EVENT proposals get re-named; an
  engineer agrees with the new name ≥ 70 % of the time.
- Round-trip latency p99 ≤ 2 s per proposal.
- L9 ranker AUC does not regress when the new names join the
  feature vector.

**Effort.** 1.5 weeks.

**Risk.** LLM hallucination on edge cases. Mitigation: every AI-written
name is a *proposal* the engineer can edit; ranker tracks
edit-vs-keep rate as a quality metric.

---

#### T1.2 — Multi-modal causal DAG

**Domain:** Log Discovery + observability integration.
**Problem this fixes.** §2.6 above — logs only.

**Technique.** L11's PC algorithm already takes
`Dict[node_id, np.ndarray]`. Add adapters that hand it metrics and
trace-span events alongside log rate series.
- **Prometheus adapter.** Pull a configured metric set from a
  Prometheus endpoint; bin into the same time grid.
- **OTel adapter.** Group span events by service.operation; produce
  a rate series equivalent to a log template's.
- **Deploy / config adapter.** Treat deploys, config changes, and
  PagerDuty incidents as point events; their rate series become
  candidate parents in the causal graph.

**New modules.**
- `src/observability_adapter.py` — common interface
  `Adapter.rate_series() -> Dict[node, np.ndarray]`.
- `src/adapters/prometheus.py`, `src/adapters/otel.py`,
  `src/adapters/deploys.py`.

**Wiring.** `causality_dag.learn_pdag` receives a merged dict from
all adapters. Each node gets a `kind` tag (`log`, `metric`, `span`,
`deploy`) so the UI can color-code.

**Acceptance gate.**
- On a synthetic mixed corpus (logs + metrics + one deploy event),
  the deploy node ends up as a confirmed parent of the rate-spike
  log node and the latency-spike metric node.
- v1 single-modality acceptance gates from L11 still pass.

**Effort.** 4 weeks.

**Risk.** Time-bin alignment between modalities. Adapters resample to
a common bin width; sparse-event series get a small Laplace prior
to avoid divide-by-zero in CI tests.

---

#### T1.3 — Streaming / incremental mining

**Domain:** Log Discovery (ingestion + L1 / L8 / L13).
**Problem this fixes.** §2.5 above — batch only.

**Technique.** Drain3 is already online. The two layers that need
incremental update are L8 (mixture-of-HMMs) and L13 (per-template
GP).
- For L8: sufficient-statistics-only updates to Dirichlet parameters.
  The VB-EM update equations are already in `sequence_learner_regimes`
  — they just need to be exposed as `update(new_trajectory)` instead
  of `fit(all_trajectories)`.
- For L13: append new (hour, count) bins to the per-template buffer;
  re-aggregate per-hour-median in O(24). GP refit is cheap on the
  24-point aggregated series.

**Module changes.** Additive `update_*` methods on the existing
classes. No new top-level modules required.

**Acceptance gate.**
- On a streaming replay of the bundled `large/` corpus, incremental
  updates produce the same regime assignments and rate-anomaly
  flags as a batch refit (within tolerance).
- Per-update latency p99 ≤ 100 ms.

**Effort.** 3 weeks.

**Risk.** Drift over very long horizons (the streaming HMM may slowly
forget old regimes). Mitigation: a periodic "consolidation" pass
that re-fits in batch mode and overwrites the streaming state.

---

#### T1.4 — Schema import depth

**Domain:** Schema import (`wizard/importer.py`).
**Problem this fixes.** §2.1 above — structural-not-semantic import.

**Technique.** Four bounded enhancements:
1. **Foreign-key chains → property paths.** Walk multi-step FKs; emit
   them as SPARQL property-path candidates the engineer can promote
   to first-class relationships.
2. **Junction tables → object properties.** Detect M-N tables (two
   FKs, no other meaningful columns); propose a single
   `owl:ObjectProperty` with cardinality.
3. **NULL semantics → cardinality.** `NOT NULL` ⇒ `sh:minCount 1`.
   Column statistics (PgStatTuple, MySQL information_schema) ⇒
   `sh:maxCount`.
4. **View definitions → derived classes.** Parse `CREATE VIEW` SQL;
   the SELECT becomes an OWL class with a SPARQL `CONSTRUCT` rule.

**New module.** `wizard/importer_semantic.py`. Layers on top of the
existing structural importer; engineer toggles per-feature.

**Acceptance gate.**
- On a canonical sample DB (TPC-H or Sakila), the new path produces
  ≥ 30 % more cardinality constraints and ≥ 5 collapsed
  junction-table relationships compared to the structural-only path.
- All proposals remain idempotent on re-import.

**Effort.** 3 weeks.

**Risk.** Database-vendor SQL parsing differences. Mitigation: use
the existing `sqlglot` dependency (already pinned in
`requirements-advanced.txt`).

---

#### T1.5 — Multi-target generation

**Domain:** Build phase (Generate).
**Problem this fixes.** §2.3 above — single-shot OWL output.

**Technique.** Three target adapters, each independent. The ontology
in memory becomes a `GenerationContext` consumed by adapters:
- `targets/cypher.py` — Neo4j schema + property-graph migration
  scripts.
- `targets/graphql.py` — GraphQL SDL with resolvers stubbed against
  the SHACL rules.
- `targets/detection_rules.py` — Datadog / Splunk YAML alerts derived
  from `LOG_CAUSAL_EDGE` proposals.

**Wiring.** `--phase 2 --targets cypher,graphql,owl,shacl` emits all
selected targets in one pass.

**Acceptance gate.**
- Same ontology emits OWL, Cypher, and GraphQL outputs; round-trip
  Cypher → Neo4j → SPARQL bridge query returns the same result set
  as the OWL+TBox query.
- ≥ 3 generated Datadog alerts pass Datadog's YAML linter on a
  sample causal-edge set.

**Effort.** 4 weeks (≈ 1.5 weeks per target plus shared core).

**Risk.** Target-format churn (Neo4j and Datadog both move). Mitigation:
each adapter is small and well-scoped; we version the target schema
explicitly in the output header.

---

#### Tier 1 v3.0 acceptance gate (after T1.1 + T1.2 + T1.3 + T1.4 + T1.5)

A reviewer running on `examples/log-rca/large/` plus a Postgres dump:

1. Schema import surfaces 30 % more cardinality constraints and
   ≥ 5 collapsed junction-table relationships.
2. Generate emits OWL, Cypher, and GraphQL in one pass.
3. The wizard's Log Discovery panel shows LLM-named proposals
   (`:UserAuthFailureRetry` instead of `:Event_42`); engineer-keep
   rate ≥ 70 %.
4. A Prometheus metric appears in the L11 causal DAG as a parent of
   a log-rate-spike node.
5. After 24 h of streaming replay, regime assignments and
   rate-anomaly flags match a batch refit to within tolerance.

---

### Tier 2 — Transformative

The "v3.5 slice." Bigger lifts; each one categorically changes what
the toolkit is. ~6–9 months.

---

#### T2.1 — Logical reasoning plug-in

**Domain:** Cross-cutting. The biggest differentiator vs other tools.
**Problem this fixes.** §2.2 above — no inference.

**Technique.** Pluggable reasoner abstraction (`src/reasoner.py`)
with adapters for HermiT, Pellet, and ELK. Three call sites:
- **Classification** — after Generate, run the reasoner; produce a
  derived class hierarchy and surface "you wrote class X; it's
  actually entailed to be a subclass of Y you didn't intend."
- **Consistency checking** — runs as part of `--phase 2`; fails the
  build if the ontology is inconsistent and shows the minimal
  unsatisfiable axiom set.
- **Entailment in compliance** — compliance bundles can now claim
  *"because the ontology entails Y, regulation §X.Y(z) is
  satisfied"* instead of *"we asserted Y."*

**Acceptance gate.**
- The toolkit detects an injected inconsistency in a test ontology
  (e.g. `Customer ⊓ Robot` declared `owl:disjointWith`) within
  10 s and surfaces the unsat axiom set in the wizard.
- A SHACL constraint that is *redundant given OWL entailment* gets
  flagged for removal.

**Effort.** 6 weeks (HermiT integration is the long pole).

**Risk.** Reasoner JVM startup cost. Mitigation: reasoner runs as a
sidecar process; first call eats the cold-start, subsequent calls
hit a warm process.

---

#### T2.2 — Cross-corpus template library

**Domain:** Log Discovery (federation territory).
**Problem this fixes.** §2.4 above — every corpus starts from zero.

**Technique.** A canonical, signed library of template signatures
shared across corpora.
- Template signature = `(token_set, slot_type_vector,
  embedding_centroid)` — same primitives Drain and L12 already use.
- New corpora bootstrap proposals by matching new templates against
  the library; matches inherit the library's review history and
  ranker priors.

**New module.** `src/template_library.py`. Backs onto SQLite locally;
syncable via the existing federation infra (`federation/`).

**Acceptance gate.**
- Bootstrapping a fresh corpus against a library mined from a
  sibling corpus reduces review-queue size by ≥ 30 %.
- No leakage: per-corpus PII flags do not cross library boundaries.

**Effort.** 6 weeks.

**Risk.** Privacy / compliance — what does the library carry?
Mitigation: signatures are hashed token sets + slot types only; no
raw log lines ever enter the library.

---

#### T2.3 — Policy-based auto-approval

**Domain:** Review surface (Log Discovery + Evolution Review).
**Problem this fixes.** §2.8 above — every proposal needs human eyes.

**Technique.** YAML-defined policies evaluated against the proposal
row:
```yaml
- name: high_confidence_safe
  if:
    confidence: ">= 0.95"
    kind: LOG_EVENT
    pii_risk: 0
    age_hours: ">= 24"   # ranker had time to learn
  then: approve
```
Policies live in `policies/*.yml`. The L9 ranker emits a
`policy_match: <name>` audit trail entry. Engineers spot-check
auto-approvals via a dashboard.

**Acceptance gate.**
- On a curated test set, the policy engine matches engineer
  decisions ≥ 90 % of the time.
- Every auto-approval has a traceable policy match in the audit log.
- Easy override: engineer can revoke an auto-approval and the policy
  is auto-tightened.

**Effort.** 3 weeks.

**Risk.** Premature automation. Mitigation: policies ship disabled by
default; require ≥ 100 historical decisions before enabling.

---

#### T2.4 — Semantic ontology diff + change-impact analysis

**Domain:** Evolution Review.
**Problem this fixes.** §2.9 above — no meaningful diff between
versions.

**Technique.** Compute structural diff (added/removed classes) AND
semantic diff (entailment changes — what was inferable in v1.2 that
is no longer inferable in v1.3, and vice versa). Use the T2.1
reasoner to compute the entailment delta.

**Output.** A `materialised-diff.html` artifact per version pair:
- Added / removed / renamed axioms (structural).
- Lost / gained entailments (semantic) — the more interesting half.
- Downstream impact: list every SPARQL query / SHACL rule / generated
  target that touches a changed axiom.

**Acceptance gate.**
- On a synthetic before/after pair where one disjointness axiom is
  removed, the diff lists the resulting new entailments correctly.
- Change-impact analysis identifies all downstream code that
  references a renamed class.

**Effort.** 4 weeks (depends on T2.1).

**Risk.** Reasoner cost on big ontologies. Mitigation: diff only over
the symmetric-difference axiom set; full reasoning runs only if the
delta exceeds a threshold.

---

#### T2.5 — Interventional causal discovery

**Domain:** Log Discovery + Compliance.
**Problem this fixes.** §2.6 + research-y extension.

**Technique.** When deploy / config-change / incident events are
*labeled* as interventions, use interventional CI tests (PRML §8.4.5)
in addition to observational ones. Much stronger causal claims:
*"deploy A caused outage B"* with statistical backing, not just
correlation.

**Module changes.** `causality_dag.learn_pdag` gains an
`interventions: Dict[node, List[Tuple[int, int]]]` parameter (node →
time-ranges-when-intervened). CI tests partition observations into
"observational" and "interventional" buckets.

**Acceptance gate.**
- On a synthetic corpus where deploy A is a known cause of outage B
  (labeled), interventional PC produces a directed `deploy_A → B`
  edge that observational PC alone cannot.
- v1 acceptance gates from L11 still pass when no interventions are
  labeled (backward-compat).

**Effort.** 8 weeks (research-y).

**Risk.** Label quality. Mitigation: confidence on interventional
edges drops if the label coverage is below a threshold.

---

#### T2.6 — MLOps for the pipeline

**Domain:** Cross-cutting infra.
**Problem this fixes.** §2.11 above.

**Technique.** Per-phase quality metrics emitted to a Prometheus
endpoint:
- L8 — regime stability (Adjusted Rand Index between consecutive
  runs).
- L9 — ranker AUC drift over time.
- L10 — reliability-diagram ECE per release.
- L11 — number of edges added / dropped vs previous run.
- L12 — average merge-candidate distance (corpus drift indicator).
- L13 — false-positive rate sampled by engineers.

A small Grafana dashboard template ships in `ops/`. Calibration drift
alerts trigger when ECE > 0.05 for ≥ 3 consecutive runs.

**Acceptance gate.**
- All six metrics emit to the configured endpoint within 1 s of
  phase completion.
- Drift alert fires on a synthetic corpus that intentionally degrades
  calibration.

**Effort.** 4 weeks.

**Risk.** Metric explosion. Mitigation: tight allow-list of phase
metrics; no per-template cardinality.

---

#### Tier 2 acceptance gate (after T2.1 + T2.2 + T2.3 + T2.4 + T2.5 + T2.6)

A reviewer running the full v3.5 pipeline on a multi-corpus, federated
deployment:

1. Inconsistent ontology fails the build with the unsat-axiom set
   shown (T2.1).
2. Bootstrapping a new corpus against the library reduces review
   queue by ≥ 30 % (T2.2).
3. Policy engine auto-approves high-confidence non-PII proposals;
   engineer reviews only the rest (T2.3).
4. v1.2 → v1.3 ontology diff shows both structural and semantic
   changes (T2.4).
5. Labeled deploy events appear as confirmed interventional causes
   in the DAG (T2.5).
6. Grafana dashboard shows healthy ECE, ranker AUC, and regime
   stability across the last 30 days (T2.6).

---

### Tier 3 — Research / long-horizon

The "v4 territory." Open-ended, exploratory, possibly research papers.

---

#### T3.1 — Hierarchical regime modeling

**Domain:** Log Discovery (L8 extension).
**Problem.** Real systems have nested regimes — cluster-level
(maintenance window across a whole region) inside service-level
(business hours for a single service). v2's L8 only models the
service level.

**Technique.** Two-level switching SSM: global regime `Z_t ∈ {1..K_G}`
gates per-service regime `z_t^(s) ∈ {1..K_S}` whose HMM produces the
template sequence. VB-EM extension is well-known but unstable.

**Effort.** 8–12 weeks. Research-y.

---

#### T3.2 — Sparse GP and FastPC for scale

**Domain:** L13 + L11 performance.
**Problem.** GP at O(n³), PC exponential in cond-set size. Both
capped today; both real ceilings at production scale.

**Technique.** Sparse GP via inducing-point approximation (Snelson &
Ghahramani 2006). Parallel PC-Stable (Colombo & Maathuis 2014).

**Acceptance gate.**
- L13 runs in ≤ 60 s on 1 000 templates × 30 days (currently 60 ×
  7 in 30 s).
- L11 conditioning set cap raised from 3 to 5 without exceeding the
  PC time budget.

**Effort.** 4 weeks total.

---

#### T3.3 — CQ → SPARQL auto-translation

**Domain:** Competency questions.
**Problem.** CQs are free text; never tested against the ontology.

**Technique.** Constrained LLM generation — schema is known, classes
are enumerable. Validate by running the generated SPARQL against
sample data; CQs with zero hits flag as missing concepts.

**Effort.** 4 weeks. Pairs with T1.1's LLM infra.

---

#### T3.4 — Continuous compliance with regulation diffs

**Domain:** Compliance (S4 extension).
**Problem.** Compliance bundles are static snapshots.

**Technique.** Subscribe to regulatory feeds (GDPR, HIPAA, SOX);
detect text changes; map to ontology axioms; trigger re-validation.
When HIPAA §164.312(a)(1) changes, surface the 3 ontology axioms
that no longer satisfy it.

**Effort.** 8 weeks. High product value, high domain expertise
required.

---

#### T3.5 — Neural-with-attention sequence models

**Domain:** L2 / L8 successor.
**Problem.** HMM emission model is bag-of-templates; ignores semantic
similarity between distinct templates.

**Technique.** Small transformer over template-id sequences with
explicit attention visualization as the audit trail. Only adopt if
attention-as-explanation can fully replace the HMM per-step audit
trail — otherwise we lose the toolkit's core value proposition.

**Effort.** 16 weeks. Most research-y item on the list.

---

## 4. Hard "don't go there" list

Each item below was considered and rejected with reasons.

| Anti-pattern | Why we say no |
|---|---|
| **Replace the statistical core with end-to-end neural** | Kills the explainability moat. The whole toolkit's value proposition is *"audit-defensible inference"* — black-box models break that. T3.5 is the *only* permitted neural addition, and only if attention can carry the audit trail. |
| **Add a vector database** | Already rejected in v2 for the same reasons: vector retrieval *outside* ontological constraints is RAG; we're not building generic RAG. The bounded retrieval in S5 *uses* vectors *within* ontology classes — that's different. |
| **Build a custom UI framework** | The Flask wizard is sufficient. Replacing it would burn months on undifferentiated work. Investment goes into the *content* of the wizard (T2.3 policy UI, T2.4 diff UI), not the framework. |
| **Bespoke pipeline orchestrator** | T2.6 emits to standard observability endpoints; Airflow / Temporal / Prefect adapters wrap the CLI when needed. Don't reinvent. |
| **Ontology editor on top of the toolkit** | Protégé exists. We are an *ingestion, mining, and review* tool, not a hand-editor. Approved proposals are the editing surface. |
| **Per-customer LLM fine-tuning** | T1.1 keeps LLMs at the labeling layer with off-the-shelf models. Fine-tuning adds operational cost, retraining cycles, and PII liability without proportional gain. |
| **GraphRAG bolt-on** | Adopters can use the multi-target generation (T1.5) to emit Cypher and integrate with a GraphRAG of their choice. The toolkit is the *source of structure*, not a chat product. |
| **OWL Full reasoning** | Stick to OWL 2 DL. Full undecidable. No reasoner supports it cleanly. T2.1 targets DL only. |

---

## 5. Recommended ordering

| # | Phase | Effort | Why this order |
|---|---|---|---|
| 1 | **T1.1 — LLM naming** | 1.5 w | Lowest-cost wins compound on every other phase that emits proposals. |
| 2 | **T1.4 — Schema import depth** | 3 w | Every customer enters via a database; this is the most common adoption funnel. |
| 3 | **T1.5 — Multi-target generation** | 4 w | Turns the ontology from a deliverable into a generator. Big visible value. |
| 4 | **T1.3 — Streaming mining** | 3 w | Required for any production deployment; un-blocks T2.2 and T2.3. |
| 5 | **T1.2 — Multi-modal causal DAG** | 4 w | Toolkit stops being a "log tool" and becomes an observability RCA platform. |
| 6 | **T2.1 — Reasoner plug-in** | 6 w | The single biggest differentiator vs other toolkits. Enables T2.4. |
| 7 | **T2.6 — MLOps** | 4 w | Required before T2.3 auto-approval is trustworthy. |
| 8 | **T2.3 — Policy auto-approval** | 3 w | Builds on T1.1, T1.3, T2.6. |
| 9 | **T2.2 — Cross-corpus library** | 6 w | Requires T1.3 streaming infra. |
| 10 | **T2.4 — Semantic diff** | 4 w | Requires T2.1 reasoner. |
| 11 | **T2.5 — Interventional causality** | 8 w | Research-y. |
| 12+ | **T3.\*** | varies | Opportunistic. |

**Total to Tier 1 end:** ~16 weeks (4 months).
**Total to Tier 2 end:** ~47 weeks (≈ 12 months).

Smallest shippable slice that is release-note-worthy on its own:
**T1.1 + T1.5** (~6 weeks) — *"LLM-named proposals + multi-target
generation."*

---

## 6. Risks worth naming now

| Risk | Where it surfaces | Mitigation |
|---|---|---|
| **LLM cost at scale** | T1.1, T3.3 | Cache aggressively (proposal → name is idempotent); ship local-model adapter (Llama-3-8B) for cost-sensitive deployments. |
| **Reasoner cold-start** | T2.1 | Reasoner runs as a persistent sidecar; first call eats the JVM start. |
| **Streaming drift** | T1.3 | Periodic batch consolidation pass overwrites streaming state. |
| **Cross-corpus PII leakage** | T2.2 | Signatures are hashed token sets only; no raw log lines cross corpus boundaries. |
| **Policy mis-fires** | T2.3 | Policies disabled by default; require ≥ 100 historical decisions before enabling; engineer can revoke auto-approvals. |
| **Reasoner explosion on big ontologies** | T2.1, T2.4 | Run reasoning incrementally on symmetric-difference axioms; full reasoning only if delta exceeds threshold. |
| **Multi-modal time-bin alignment** | T1.2 | Common resampling layer with Laplace prior for sparse-event adapters. |
| **Multi-target schema churn** | T1.5 | Each adapter is small; output header includes the target-schema version. |
| **Compliance regulation feed reliability** | T3.4 | Manual override path; fallback to last-known-good registry. |

---

## 7. Out of scope (deliberately)

- **End-to-end neural inference.** See §4.
- **Generic vector RAG.** See §4.
- **Per-customer LLM fine-tuning.** See §4.
- **Custom UI framework.** See §4.
- **OWL Full.** Stick to OWL 2 DL.
- **Visual ontology editor.** Protégé exists.
- **Real-time UI updates during mining.** Batch + page-refresh is fine
  for v3; consider SSE / WebSocket only if there's a real product
  request.
- **Chat / conversational interface.** Compelling but adjacent; would
  burn months without lifting the toolkit's core differentiation.

---

## 8. Open questions to resolve before coding Tier 1

1. **LLM provider for T1.1.** Anthropic vs OpenAI vs local. Defaults?
   Cost model? Per-customer override?
2. **Streaming infra for T1.3.** Polling vs Kafka consumer vs OTel
   collector. We probably want all three eventually; which first?
3. **Multi-tenancy timing.** Does v3 ship single-tenant, with
   multi-tenancy deferred to v4? Or do we add tenant scoping to the
   proposal store now to avoid a migration later?
4. **Reasoner default for T2.1.** HermiT (mature, Java), Pellet
   (Pythonic-ish), or ELK (only EL profile, very fast). Defaults
   probably depend on ontology profile detection.
5. **Generation targets for T1.5.** Cypher / GraphQL / Datadog as
   defaults; do we also do Snowflake, BigQuery, Pydantic in v3.0?
6. **Federation maturity for T2.2.** The S3 branch ships a primitive;
   what's its current capability and what gap remains for the cross-
   corpus library?
7. **Compliance feed source for T3.4.** Manual JSON updates? Subscribe
   to a third-party regulatory feed (Thomson Reuters, etc.)?

---

## 9. Files added / extended (preview)

```
# Tier 1
wizard/proposal_namer.py                    T1.1 — LLM naming
src/observability_adapter.py                T1.2 — multi-modal base
src/adapters/{prometheus,otel,deploys}.py   T1.2 — adapters
src/streaming.py                            T1.3 — incremental update wrappers
wizard/importer_semantic.py                 T1.4 — schema import depth
src/targets/{cypher,graphql,detection}.py   T1.5 — generation targets
docs/llm-naming-prompts.md                  T1.1 — prompt library
docs/observability-integration.md           T1.2 — adapter integration guide
docs/streaming-mining.md                    T1.3 — operator guide
docs/schema-import-semantic.md              T1.4 — feature guide
docs/multi-target-generation.md             T1.5 — target reference

# Tier 2
src/reasoner.py + src/reasoners/{hermit,pellet,elk}.py   T2.1
src/template_library.py                                   T2.2
wizard/policy_engine.py + policies/*.yml                  T2.3
src/ontology_diff.py + wizard/templates/diff.html         T2.4
src/causality_interventional.py                           T2.5
ops/grafana/*.json + src/metrics.py                       T2.6
docs/reasoning-guide.md                                   T2.1
docs/template-library.md                                  T2.2
docs/policy-engine.md                                     T2.3
docs/ontology-diff.md                                     T2.4
docs/interventional-causality.md                          T2.5
docs/mlops.md                                             T2.6

# Tier 3 — sketched
src/sequence_learner_hierarchical.py        T3.1
src/sparse_gp.py + src/fast_pc.py           T3.2
wizard/cq_translator.py                     T3.3
src/compliance_feeds.py                     T3.4
src/sequence_learner_neural.py              T3.5
```

---

## 10. Where this leaves us

After Tier 1 (the v3.0 slice) the toolkit becomes:

> *"Point it at any combination of logs, metrics, traces, and a database;
> stream new data in; get LLM-named, audit-defensible ontology proposals
> emitted into OWL, Cypher, GraphQL, and detection rules — all in under
> 4 months from where we are today."*

After Tier 2 (the v3.5 slice) it becomes:

> *"...with logical reasoning over the ontology, cross-corpus template
> reuse, policy-based async review, semantic version diffs, and
> interventional causal claims — defensible to auditors, observable in
> production, federation-ready."*

Tier 3 is research-and-opportunity territory: each phase independently
shippable on top of Tier 2 without dependencies, picked up by whoever
has time.

The dev plan with day-level granularity and acceptance gates per
half-day block will follow in
[`toolkit-v3-dev-plan.md`](toolkit-v3-dev-plan.md) once the open
questions in §8 are resolved.
