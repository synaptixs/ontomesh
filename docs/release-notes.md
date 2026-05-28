# Release Notes

## v3.2 — Log-Driven Root-Cause Analysis

> **Theme:** turn a folder of logs into a reviewed, materialised, queryable RCA ontology — without leaving the toolkit.

This release implements the entire roadmap in [docs/log-rca-roadmap.md](log-rca-roadmap.md) and the development plan in [docs/log-rca-dev-plan.md](log-rca-dev-plan.md) — Phases L1 through L7, all seven shipped.

**263 tests, all green.** No breaking changes; the new pipeline lives alongside the existing one.

---

### What's new

The new pipeline closes a loop: logs → reviewed candidates → ontology → materialised graph → grounded RCA query.

```
   logs/ folder
        │
        ▼  --phase mine + --phase sequence
   templates · slot types · PMI graph · HMM anomalies · Granger causality
        │
        ▼  Studio Step 2.5 — Log Discovery
   engineer approve / reject / edit / merge candidates
        │
        ▼  --phase 2 + --phase reason
   enterprise.ttl  +  materialised.ttl  +  materialised-lineage.ttl
        │
        ▼  Insights → RCA preset
   "what caused {event}?" with prov:wasDerivedFrom premise tree
```

#### L1 — Log mining (`--phase mine`)

Three-layer pipeline over a folder pointer:

- **Template clustering** via Drain3 + EM refinement (close-by templates merge once they're each ≥ 10 hits).
- **Slot typing** — every `<*>` placeholder is classified as `IRI / IP / UUID / ENUM / NUMERIC / HEX / FREETEXT` with a PII heuristic (`imsi|msisdn|email|…`) that defaults to a higher sensitivity tier.
- **PMI-weighted entity graph + temporal ordering** — directed edges only when `lead_ratio > 0.7` over a Δt window.

New SQLite tables: `log_templates`, `log_template_slots`, `log_entity_edges`.

#### L2 — Sequence learning (`--phase sequence`)

Per-service `CategoricalHMM` over Drain cluster-id trajectories with BIC-selected state count. Anomaly scoring uses a **combined HMM-likelihood + cluster-bag-novelty** signal — the bag-novelty term catches structurally-simpler outliers that pure likelihood would miss. Confidence floor scales with cluster rarity so the dev-plan acceptance gate (≥ 0.6 on injected outliers) is met.

#### L3 — Causality gate (no new phase; runs inside `--phase mine`)

Strict triangulation before an edge becomes `LOG_CAUSAL_EDGE`:

1. PMI ≥ 2.0 (from L1).
2. `temporal_lead_ratio ≥ 0.7` (from L1).
3. **Granger p < 0.05 OR transfer-entropy z > 2.**

Edges that fail #3 demote to `LOG_RELATIONSHIP` — still visible to the reviewer, just without the causal claim. On the sample corpus 210 → 130 causal candidates (80 demoted).

#### L4 — Step 2.5 Log Discovery in Ontology Studio

A new wizard sidebar entry between Entities and Events. Engineers see candidates of four kinds (`LOG_EVENT`, `LOG_ENTITY`, `LOG_RELATIONSHIP`, `LOG_CAUSAL_EDGE`) sorted by **confidence × consequence** (PRML Ch. 1 decision theory). Per-row actions: ✓ approve · ✕ reject · ✎ edit · 🔀 merge. For relationship / causal candidates, a click-to-toggle mini-graph shows the two endpoint classes with the edge tagged by confidence and lag.

New endpoints: `GET /api/log-discovery/{summary, candidates}`, `POST /api/log-discovery/{seed, <pid>/{approve, reject, merge}}`.

Schema extension (idempotent migration in [db/migrations/log_rca_proposals.py](../db/migrations/log_rca_proposals.py)) adds four new `proposal_type` values and five new `detection_strategy` values to the existing `ontology_evolution_proposals` table.

#### L5 — RCA-shaped ontology

When the active session contains any `source=log-discovery`, `ontology_generator` emits:

- The static **causal taxonomy** (`:CausalEvent`, `:hasCause`, `:triggers`, `:precededBy`, `:rootCause`) — see [src/rca_taxonomy.py](../src/rca_taxonomy.py).
- One class per approved log-derived event, as `rdfs:subClassOf :CausalEvent`.
- Time-interval data properties (`:startedAt`, `:endedAt`, `:duration`).
- Severity tier mapping: `DEBUG/INFO → Public`, `WARN → Internal`, `ERROR → Confidential`, `CRITICAL → Restricted`.

`wizard.rules.compile_causal_rule` turns each approved `LOG_CAUSAL_EDGE` into a SPARQL CONSTRUCT that Phase B materialises into derived `:hasCause` + `:triggers` triples with full `prov:wasDerivedFrom` lineage.

#### L6 — RCA starter library + Insights presets

[templates/rules/rca.yaml](../templates/rules/rca.yaml) — 5 starter rules:

- `rca-rootcause-onehop`, `rca-rootcause-twohop` — walk the closure of `:hasCause` and assert `:rootCause` on terminal nodes.
- `rca-multiple-causes` — flag effects with > 1 `:hasCause` edge (anti-tunnel-vision).
- `rca-derivation-inferred`, `rca-derivation-measured` — split `:NfDeregister` between heartbeat-inferred and explicit (the 3GPP R4 ambiguity from the 5G demo).

Two Insights presets: **root-cause** ("walk the :hasCause chain") and **similar-incidents** ("show past incidents with shared causes/severity"). Available via `GET /api/insights/rca-presets` and `POST /api/insights/rca`.

#### L7 — Drift-template loop (`--phase drift-templates`)

A closed-loop hook: re-runs Drain3 (with a stricter `sim_th=0.7`) against incoming logs, aggregating any new cluster ids that don't match the approved catalogue. Templates that clear the hit floor become `LOG_EVENT` proposals with `detection_strategy='DRIFT_ON_NEW_TEMPLATE'` — they land in the same Step 2.5 queue engineers already use for bootstrap candidates. No new UI surface needed.

---

### Files added or substantially extended

```
docs/log-rca-roadmap.md                   plan
docs/log-rca-dev-plan.md                  build-out
docs/release-notes.md                     this entry

src/log_corpus.py                         L1.1 folder iterator
src/log_templates.py                      L1.2 Drain wrapper + EM refine
src/log_miner.py                          L1.3–1.5 orchestrator
src/sequence_learner.py                   L2 HMM + anomalies
src/causality_miner.py                    L3 Granger + transfer entropy
src/rca_taxonomy.py                       L5.1 causal taxonomy
src/ontology_generator.py                 L5.2 log-derived classes (modified)

runtime/drift/log_template_drift.py       L7 drift hook

wizard/log_review.py                      L4 review logic
wizard/rules.py                           L5.3 compile_causal_rule (modified)
wizard/app.py                             6 + 2 + 1 new endpoints
wizard/templates/index.html               Step 2.5 Log Discovery panel

db/schema.sql                             new proposal_type / strategy values
db/migrations/log_rca_proposals.py        idempotent rebuild migration

templates/rules/rca.yaml                  L6.1 RCA starter library
templates/log-rca/                        reserved namespace

examples/log-rca/sample/                  215-line synthetic 5G corpus
examples/log-rca/sample/generate.py       reproducibility script

tests/test_log_corpus.py                  7 tests
tests/test_log_templates.py              11 tests
tests/test_log_miner.py                  15 tests
tests/test_sequence_learner.py           10 tests
tests/test_log_review.py                 12 tests
tests/test_causality_miner.py            10 tests
tests/test_rca_ontology.py               13 tests
tests/test_rca_starter_library.py         8 tests
tests/test_drift_template_loop.py         5 tests
                                  ─────
                                    91 new tests
```

---

### CLI surface added

| Phase | What it does |
|---|---|
| `--phase mine --log-path …` | L1 — template clustering + slot typing + PMI graph + Granger-gated causality; reseeds the proposal store. |
| `--phase sequence --log-path …` | L2 — per-service HMM + anomaly proposals. |
| `--phase drift-templates --log-path …` | L7 — find new templates not in the approved catalogue, queue them for review. |

The existing `--phase reason` automatically picks up approved causal rules from `session.causal_rules` via `wizard.rules.export_causal_rules`.

---

### Migration notes

- **Schema:** safe to run on an existing DB. The new `ontology_evolution_proposals` columns + CHECK constraint relaxations apply via `db/migrations/log_rca_proposals.py` — a SAVEPOINT probe detects whether the rebuild is needed and, when it is, performs the standard SQLite rename-create-copy-drop dance without losing existing rows.
- **Wizard sessions:** old sessions load fine. New keys `causal_rules` default to `[]`. Approvals from Step 2.5 add entries with `source="log-discovery"` so the L5 ontology generator can pick them out.
- **Adapter contract:** unchanged. The existing OpenAI / OCI / Anthropic / Vertex / Ollama adapters are wrapped, not modified.
- **Demo DB / artefacts:** unchanged. Phase 2 generation omits the RCA taxonomy when the session has no `source=log-discovery`, so projects that don't use log mining see identical output to v3.1.

---

### Known gaps / explicit limits

- **OWL-RL premises remain coarse.** owlrl doesn't expose per-triple premises; Phase D lineage attributes those triples to the engine only. ROBOT-explain integration is a future refinement.
- **SPARQL time-window filter dropped from compiled causal rules.** rdflib's SPARQL engine can't reliably do `xsd:dateTime - xsd:dateTime` arithmetic against `xsd:duration` literals. The window value (set by L3) is preserved as an audit comment, and the directional filter (`?et > ?ct`) carries the temporal semantic. Switching to a graph store with full SPARQL 1.1 duration support (Stardog, Fuseki) would lift this restriction.
- **Drain at `sim_th=0.4` is permissive.** The L1 miner can over-merge templates on diverse corpora. Tightening to 0.5 in `LogTemplateMiner.__init__` is a one-flag change for projects with noisier logs.
- **Drift detector uses stricter `sim_th=0.7`.** That's intentional — false positives in the review queue are cheaper to dismiss than false negatives (real drift hidden behind a permissive match).

---

### Closed-loop demo (5 minutes against the bundled sample corpus)

```bash
python toolkit.py --phase mine     --log-path examples/log-rca/sample/
python toolkit.py --phase sequence --log-path examples/log-rca/sample/
python wizard/app.py
# → browser: Step 2.5 → approve a LOG_EVENT + a LOG_CAUSAL_EDGE
python toolkit.py --phase 2
python toolkit.py --phase reason
# → output/ontology/materialised.ttl carries derived :hasCause
# → output/ontology/materialised-lineage.ttl shows prov:wasDerivedFrom
```

Optional steady state — drop a new `.jsonl` with a never-seen pattern into the watched folder:

```bash
python toolkit.py --phase drift-templates --log-path examples/log-rca/sample/
# → 1 new template detected → 1 LOG_EVENT proposal queued
```

The Viewer's Materialised tab (from v3.1) renders the derivation premise tree end-to-end. The Insights panel's RCA presets answer **"what caused {event}?"** with the materialised graph as context.

---

## v3.1 — Rules & Reasoning

> **Theme:** turn the toolkit's narrow "ontology generator with a reasoner hook" into "ontology generator with first-class rules, materialised inference, explanations, and grounded LLM Insights."

This release implements the entire roadmap in [docs/reasoning-roadmap.md](reasoning-roadmap.md) — Phases A through E — plus a follow-up suite of authoring affordances (slot-fill builder, test-fire preview, premise tree, NL drafting, rule-impact heat map, conversational drawer).

**171 tests, all green.** No breaking changes to the existing pipeline; every addition is opt-in.

---

### What's new

#### A. Richer OWL axioms from existing wizard inputs

The generator now emits axioms the reasoner can actually chew on:

- **`owl:hasKey`** — opt-in via the `has_key_columns` metadata column.
- **`owl:FunctionalProperty`** — auto-emitted for every FK-backed object property (one row references at most one parent).
- **`owl:TransitiveProperty` / `owl:SymmetricProperty` / `owl:InverseFunctionalProperty`** — flagged via the new `is_transitive` / `is_symmetric` / `is_inverse_functional` metadata columns.
- **`owl:inverseOf`** — pair object properties via the new `inverse_of` metadata column.
- **`owl:AllDisjointClasses`** — opt-in via the new `disjoint_group` metadata column, plus auto-emitted for sibling event subclasses (mutually exclusive by `event_type`).
- **Profile detector escalation** — `inverseOf` / `SymmetricProperty` / `InverseFunctionalProperty` now correctly bump the recommendation to OWL 2 DL with a clear rationale.

Existing `ontology_metadata` rows continue to work unchanged — the new columns are tolerated as `NULL` on legacy databases.

#### B. Materialisation phase — `python toolkit.py --phase reason`

A new pipeline step that runs three pure-Python inference engines and writes their output to disk:

- **OWL-RL closure** — rdflib + owlrl
- **SHACL `sh:rule`** — pyshacl in advanced mode
- **SPARQL CONSTRUCT** — `output/sparql_rules/*.rq`

Outputs land under `output/ontology/`:

```
enterprise-inferred.ttl       # OWL-RL derivations
inferred-shacl.ttl            # SHACL sh:rule outputs
inferred-sparql.ttl           # SPARQL CONSTRUCT outputs
materialised.ttl              # union of asserted ⊕ derived
materialised-lineage.ttl      # per-triple prov:wasDerivedFrom (Phase D)
materialisation_report.md     # triple counts, blow-up ratio, sensitivity audit
```

ROBOT is **not** required — Phase 2's existing ROBOT integration is untouched, and Phase B falls back to pure Python so the toolkit always produces materialised triples regardless of host setup.

#### C. Rules step in Ontology Studio (Step 5.5)

A new wizard step between CQs and Generate. Authors edit rules in three flavours:

- **SHACL** rules with a friendly slot-fill builder *(new in v3.1)* — target class, conditions, assertion. The textarea is optional ("Source" tab).
- **SPARQL CONSTRUCT** for users who already write SPARQL.
- **OWL axioms** for raw Turtle fragments.

Every rule is **validated before save** — broken rules cannot be persisted. Each rule round-trips as `session.rules[]` and is exported to disk before `--phase reason` runs (`output/shapes/rules.ttl`, `output/sparql_rules/<id>.rq`).

A starter library ships for **telecom**, **healthcare**, and **finance** at [templates/rules/](../templates/rules/).

#### D. Explain / why-trace

Every derived triple carries `prov:wasDerivedFrom` lineage in `materialised-lineage.ttl`:

- **SPARQL** — full bindings + WHERE-clause premises captured per match.
- **SHACL** — per-shape attribution with focusNode binding.
- **OWL-RL** — coarse engine-level attribution (the closure doesn't expose per-triple premises; ROBOT-explain integration is a future refinement).

The wizard's **Ontology Viewer → Materialised tab** lets users:

- Filter triples by engine / rule.
- Click any derived triple to see its derivation chain.
- **Premise tree** *(new in v3.1)* — `<details>`-driven recursive view: click a premise to drill into *its* lineage (lazy fetch, max depth 4, per-triple cache).

#### E. Provider-agnostic LLM Insights

A new layer wires the ontology to the LLM you already trust:

- **Provider catalogue** at [runtime/llm_providers.json](../runtime/llm_providers.json) — OpenAI, OCI Generative AI, Anthropic, Vertex AI, Local (Ollama). Default model + **residency hint** per provider (us-cloud / tenant-region / gcp-region / air-gapped).
- **Settings → Providers panel** shows ✓ / ⚠ status with a clear "key not set" / "SDK not installed" reason per provider.
- **Ask Insights** — question grounded in the asserted ontology by default; toggle on to include materialised triples (Phase B). Residency warning surfaces before sending materialised triples to a public-cloud provider.
- **Hallucinated-IRI filter** — every response is checked against the ontology vocabulary; unknown IRIs are flagged in the UI.

Adapters are unchanged from v3.0 — Insights wraps them so the same call works regardless of which provider is active.

---

### Authoring affordances (graphical / NL)

Building on Phase E, v3.1 also ships a suite of features that make rule authoring feel like the rest of the wizard:

| # | Feature | What it does |
|---|---|---|
| F1 | `GET /api/ontology/vocabulary` | mtime-cached classes + properties from `enterprise.ttl` — fuel for every UI feature below. |
| #3 | **Slot-fill SHACL builder** | When [class] [matches condition] → assert [property] [value]. Eight operators (`=`, `!=`, `>=`, `<`, `regex`, `in`, `exists`, `not_null`). Generated source visible in a "Show source" disclosure. |
| F2 | `POST /api/rules/preview` | Single-rule preview engine — compiles, runs against a synthetic ABox, returns derived triples + lineage. |
| #6 | **Test-fire button** | Every rule row has Test fire; results panel shows count, table of derived triples (subject / predicate / object / bindings) + premises, with an empty-state hint when the rule fires but produces nothing. |
| #5 | **Premise tree** | Recursive `<details>` viewer on the Materialised tab. |
| #1 | **Draft from English** | Per-rule modal: NL textarea → LLM → SHACL/SPARQL/OWL body, with grounded/unknown IRI breakdown. Standard vocabularies (`sh:`, `owl:`, `xsd:`) are not flagged as hallucinations. |
| #7 | **Rule-impact heat overlay** | The Relationships graph tints classes by how many rules touch them (cool → hot). Click a node → popover lists the rules with a one-click jump to the Rules editor. Legend shows `N/M classes covered`. |
| #2 | **NL summary on every rule** | One-sentence English summary persisted on the rule, shown as the primary label in the rule list. ↻ summarise re-runs at any time. |
| #8 | **Conversational drawer** | A single "Build from English" surface that drafts (#1), test-fires (#6), and highlights the touched classes on a mini graph (#7) in one round trip. Accept lands the rule and auto-summarises (#2). |

The corresponding canvas-style node-graph rule editor (suggestion #4 in our roadmap discussion) was deliberately deferred — the slot-fill builder and the conversational drawer cover the same authoring use cases without the maintenance cost of a full graph editor.

---

### Migration notes

- **Schema:** running this release against an old `ontology_metadata` table just works. New columns default to `NULL` and the introspector tolerates their absence. To enable the Phase A signals on an existing database, run the schema DDL in [db/schema.sql](../db/schema.sql) — the new columns are `is_transitive`, `is_symmetric`, `is_functional`, `is_inverse_functional`, `inverse_of`, `disjoint_group`, `has_key_columns`.
- **Pipeline:** `--phase all` now includes `reason` after `shacl`. Existing `--phase 2` invocations are unchanged.
- **Wizard sessions:** old sessions load fine; `rules` defaults to `[]` and `nl_summary` to `""`.
- **Adapters:** no signature change. Existing OpenAI / OCI / Anthropic / Vertex / Ollama adapters are wrapped, not modified.

---

### Files added or substantially extended

```
src/materializer.py                 # Phase B + D
src/vocabulary.py                   # F1
runtime/insights.py                 # Phase E + #1 + #2 + #8
runtime/llm_providers.json          # Phase E
wizard/rules.py                     # Phase C + #3 + F2 + #7
wizard/templates/index.html         # all UI surfaces above
templates/preview_abox.ttl          # F2 / #6
templates/rules/{telecom,healthcare,finance}.yaml  # Phase C starter library
docs/reasoning-roadmap.md           # plan
docs/release-notes.md               # this file
tests/test_phase_a_axioms.py        # 8 tests
tests/test_phase_b_materializer.py  # 7 tests
tests/test_phase_c_rules.py         # 16 tests
tests/test_phase_d_explain.py       # 6 tests
tests/test_phase_e_insights.py      # 10 tests
tests/test_vocabulary_and_slots.py  # 18 tests (F1 + #3)
tests/test_rule_preview.py          # 7 tests (F2 + #6)
tests/test_nl_rule_drafter.py       # 10 tests (#1)
tests/test_rule_coverage.py         # 8 tests (#7)
tests/test_nl_summary.py            # 7 tests (#2)
tests/test_convo_rule.py            # 5 tests (#8)
```

---

### Limits / known gaps

- **OWL-RL premises are empty** in lineage — owlrl runs as a single closure pass and doesn't expose which axiom produced each triple. Phase D records engine-level attribution; per-triple premises arrive when ROBOT-explain integration ships.
- **SPARQL premise extraction is best-effort** — only basic graph patterns are captured. FILTERs, OPTIONALs, and sub-SELECTs are not reflected as premises (lineage shows engine + bindings instead).
- **Test-fire tempdirs are not auto-cleaned** — each preview leaves ~50 KB under `$TMPDIR`. macOS auto-cleans these; Linux users may want to wrap the helper in `tempfile.TemporaryDirectory` if it matters.
- **OWL slot-fill builder is not yet implemented** — slot-fill currently covers SHACL only. SPARQL and OWL kinds use the source textarea (with NL drafting available).
- **Mini-graph in the conversational drawer is a snapshot** — editing Step 2 entities while the drawer is open won't auto-refresh the graph; reopen to see the new state.

---

### Documentation

- [docs/reasoning-roadmap.md](reasoning-roadmap.md) — the original plan.
- [docs/runtime.md](runtime.md) — runtime layer + adapter contracts.
- [docs/integrate.md](integrate.md) — 5-minute path; no changes required.
