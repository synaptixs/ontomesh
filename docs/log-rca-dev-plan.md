# Log-Driven RCA — Development Plan

> Operational companion to [docs/log-rca-roadmap.md](log-rca-roadmap.md).
>
> The roadmap is **what + why**. This document is **how, when, in what order, with what gates**. Sized in **half-day units (0.5 d)**; total budget **25 half-days (12.5 person-days)** for the full loop, **15 half-days (7.5 person-days)** for the v1 minimum-shippable slice (L1 + L4 + L5).

---

## 0. Pre-flight (0.5 d) — do once before L1

| # | Item | Owner sign-off |
|---|---|---|
| 0.1 | Open questions 1–5 in roadmap §9 resolved in writing (defaults: SQLite storage, per-service HMM, `--since=auto`, shared tokeniser, defer NN). | Tech lead |
| 0.2 | New deps pinned in `pyproject.toml` extras: `[mining]` group with `drain3>=0.9.11`, `hmmlearn>=0.3.0`, `statsmodels>=0.14.0`, `scikit-learn>=1.3` (Drain / HMM / Granger / PMI math). All ≤ 30 MB combined. | Tech lead |
| 0.3 | Schema migration drafted (SQLite `ALTER TABLE ontology_evolution_proposals ADD COLUMN source_log_path TEXT`; plus four new proposal_type CHECK values: `LOG_ENTITY`, `LOG_RELATIONSHIP`, `LOG_EVENT`, `LOG_CAUSAL_EDGE`). Committed in the same branch as L1 day 1 so future migrations don't fork. | Tech lead |
| 0.4 | Branch: `feature/log-rca`. Sub-branches per phase. PRs land into `feature/log-rca`; that branch merges into `develop` only when the v1 slice (L1+L4+L5) is green. | Tech lead |
| 0.5 | Decide demo corpus: bundled `examples/log-rca/sample/*.jsonl` (~10k synthetic 5G logs) + a real-customer corpus path documented but kept out of the repo. | Tech lead |

**Gate to start L1:** all five items checked. None require external review — they're a 30-minute meeting + 90-minute setup.

---

## 1. Phase L1 — Log Mining (3 d / 6 half-days)

### Files to create

```
src/log_miner.py                 # template clustering + PMI graph
src/log_templates.py             # Drain wrapper + EM refinement helper
src/log_corpus.py                # corpus iterator, shared with sequence_learner
tests/test_log_miner.py
tests/test_log_templates.py
tests/fixtures/sample-logs/      # 6–10 synthetic .jsonl files, 50 lines each
templates/log-rca/               # reserved — populated in L6
```

### Implementation order

| Block | Effort | What you ship |
|---|---|---|
| 1.1 | 0.5 d | `LogCorpus` iterator over a folder/glob, reusing `src/log_connector.py` parsers. Pure read path — no DB writes yet. Unit test: ingest 6 sample files, assert N lines back. |
| 1.2 | 1.0 d | `LogTemplateMiner` wrapping `drain3`. Persists templates to a new SQLite table `log_templates(id, template, regex, sample_line, hits, first_seen, last_seen)`. EM refinement merges templates with edit-distance ≤ 2 once `hits ≥ 10`. |
| 1.3 | 0.5 d | Variable-slot typing. For each `<*>` slot in a template, classify the value distribution: `IRI` (matches an `ontology_metadata` class IRI), `IP`, `UUID`, `enum` (≤ 8 distinct values), `numeric`, `freetext`. Writes to `log_template_slots(template_id, slot_idx, type, distinct_count, top_values)`. |
| 1.4 | 0.5 d | PMI entity graph. For every pair `(slot_value_x, slot_value_y)` appearing in the same trace-id or within Δt=60s, compute PMI from the cached `log_templates` counts. Threshold τ_PMI=2.0 by default. Writes `log_entity_edges(src, dst, pmi, count, temporal_lead_ratio)`. |
| 1.5 | 0.5 d | Temporal ordering. For each surviving edge, count `x → y` vs `y → x` within Δt. Edge direction set when `lead_ratio > 0.7`. |
| 1.6 | 0.5 d | CLI integration. New `toolkit.py` phase: `--phase mine --log-path <folder>`. Idempotent — re-runs append to `log_templates`, never delete. |
| 1.7 | 0.5 d | Tests: template clustering produces stable ids on a fixed corpus, EM merges near-duplicates, PMI thresholds work, temporal direction inferred when expected. |
| 1.8 | 1.0 d | Buffer: real-corpus tuning. Run against demo 5G corpus + one real customer corpus; tune τ_PMI and the edit-distance threshold. Document chosen defaults in module docstring. |

### Acceptance gate L1

- `python toolkit.py --phase mine --log-path examples/log-rca/sample/` on the bundled corpus produces ≥ 20 templates and ≥ 30 entity edges in under 60 seconds.
- `pytest tests/test_log_miner.py tests/test_log_templates.py -q` passes.
- `log_templates` and `log_entity_edges` rows are readable from sqlite3 cli; counts match the run summary printed by the phase.

---

## 2. Phase L2 — Sequence + Anomaly Learning (2 d / 4 half-days)

### Files to create

```
src/sequence_learner.py
tests/test_sequence_learner.py
```

### Implementation order

| Block | Effort | What you ship |
|---|---|---|
| 2.1 | 0.5 d | `TrajectoryBuilder` — groups `domain_events` rows by `(service, host)` ordered by timestamp, encoded as sequences of `log_templates.id`. Configurable downsample: dedupe consecutive identical ids. |
| 2.2 | 0.5 d | HMM fitter using `hmmlearn`. Per-trajectory state count selected via BIC over `n=4..16`. Persists trained model + likelihood threshold to `log_hmm_models(service, host, model_blob, threshold, fit_at)`. |
| 2.3 | 0.5 d | Per-sequence anomaly scoring. Sequences below the 5th-percentile likelihood produce **candidate root-cause events** anchored at the change-point template id. Writes to `ontology_evolution_proposals` with `proposal_type='LOG_EVENT'`, `dim_consistency_risk` populated from the likelihood gap. |
| 2.4 | 0.5 d | CLI: `--phase sequence` runs L2 after L1. Tests: synthetic sequence with one anomaly → exactly that template id flagged. |

### Acceptance gate L2

- On a synthetic corpus with one injected anomalous trajectory, the proposal store has at least one `LOG_EVENT` candidate pointing at the injected template id with `confidence_score ≥ 0.6`.
- HMM fit time ≤ 30 s on the demo corpus.
- BIC selection produces ≤ 16 states for every service in the demo corpus.

---

## 3. Phase L3 — Causality Candidates (1.5 d / 3 half-days)

### Files to create

```
src/causality_miner.py
tests/test_causality_miner.py
```

### Implementation order

| Block | Effort | What you ship |
|---|---|---|
| 3.1 | 0.5 d | Rate-series builder. For each `log_templates.id`, bucket events into minute bins over the corpus window. Output is a sparse matrix `n_templates × n_minutes`. |
| 3.2 | 0.5 d | Granger via `statsmodels.tsa.stattools.grangercausalitytests`. For every PMI edge from L1 with `count ≥ 30`, test at lags 1–5 minutes. Records `(cause, effect, lag, p_value, n_samples)`. |
| 3.3 | 0.25 d | Transfer-entropy fallback (custom implementation, ≤ 60 lines) for series that fail Granger's stationarity check. |
| 3.4 | 0.25 d | Triangulation rule: candidate is emitted only when **all three** of PMI > τ_PMI, temporal_lead_ratio > 0.7, and (Granger p < 0.05 OR TE z > 2). Writes `proposal_type='LOG_CAUSAL_EDGE'` to the proposal store. |

### Acceptance gate L3

- On a synthetic 2-cause / 1-effect corpus, both causes surface as `LOG_CAUSAL_EDGE` candidates with `p_value < 0.05`.
- Triangulation: setting any one of the three signals to fail removes the candidate from the queue (3 unit tests for the three knock-out cases).
- Total L3 runtime on the demo corpus ≤ 60 s.

---

## 4. Phase L4 — Engineer Review Step (3 d / 6 half-days)

This is the most user-visible step. Largest UX surface; reuses existing wizard patterns.

### Files to create / modify

```
wizard/log_review.py             # new — review logic, persistence
wizard/templates/index.html      # modify — new step panel + cluster card + mini-graph
wizard/app.py                    # modify — new endpoints
tests/test_log_review.py
```

### Implementation order

| Block | Effort | What you ship |
|---|---|---|
| 4.1 | 0.5 d | Schema migration: extend `ontology_evolution_proposals.proposal_type` CHECK to allow the four new values. Add columns `evidence_template_id INTEGER`, `evidence_sample TEXT`. Backfill defaults for existing rows. |
| 4.2 | 0.5 d | `wizard/log_review.py` — `list_candidates(kind, status, limit)`, `approve(id, edits=None)`, `reject(id, note)`, `merge(id, into_existing)`. Approval routes the candidate into `session.entities` / `events` / `relationships` / `causal_rules`. |
| 4.3 | 0.5 d | API endpoints: `GET /api/log-discovery/candidates`, `POST /api/log-discovery/<id>/approve`, `…/reject`, `…/merge`, `…/edit`. All write to the existing session save path so the rest of the wizard sees the new entities immediately. |
| 4.4 | 1.0 d | UI: new sidebar entry **"2.5 Log Discovery"** between Entities and Events. List view sortable by `confidence × consequence` (decision-theory ordering from PRML Ch. 1). Each row: ✓ ✕ ✎ 🔀 buttons; expandable cluster card with template + sample lines + variable slots. |
| 4.5 | 0.5 d | Mini graph (reuse `_renderConvoGraph` from Phase #8) for relationship / causal-edge candidates. Endpoint classes lit up, edge tagged with confidence + lag. |
| 4.6 | 0.5 d | PCA / t-SNE 2D plot of template clusters (read-only, scikit-learn t-SNE on top-200 templates). Embedded as a small canvas above the list. |
| 4.7 | 0.5 d | LLM-assist (optional, behind Insights provider availability): "Suggest a class name for this cluster" + "Summarise these log lines." Re-uses `runtime/insights.py` adapter pipeline. Output goes into editable fields, never auto-saved. |
| 4.8 | 1.0 d | Tests: candidate listing, approve writes to session, reject doesn't, merge unions sample arrays, schema migration is idempotent, endpoint smoke. |

### Acceptance gate L4

- A reviewer can: open the new step, see candidates from L1–L3, approve one entity + one relationship + one event-template + one causal edge, and refresh — the four newly-approved items are visible on the existing Entities / Events / Relationships / Rules steps.
- Mini-graph correctly highlights the involved classes on approval-preview.
- 6+ unit tests in `test_log_review.py` pass; one end-to-end test using a Flask test client posts an approval and asserts session update.

---

## 5. Phase L5 — RCA Ontology Generation (1.5 d / 3 half-days)

### Files to create / modify

```
src/ontology_generator.py        # modify — add causal taxonomy emitter
src/rca_taxonomy.py              # new — static causal-taxonomy fragment
wizard/rules.py                  # modify — compile_causal_rule for session.causal_rules
tests/test_rca_ontology.py
```

### Implementation order

| Block | Effort | What you ship |
|---|---|---|
| 5.1 | 0.25 d | `src/rca_taxonomy.py` — emits the static causal taxonomy block (`:CausalEvent`, `:hasCause`, `:triggers`, `:precededBy`, `:rootCause`). Imported from `ontology_generator` and rendered before the domain classes. |
| 5.2 | 0.5 d | Auto-add time-interval data properties to every log-derived class: `:startedAt`, `:endedAt`, `:duration`. Driven off a new `is_log_derived` marker in `ontology_metadata`. |
| 5.3 | 0.25 d | Severity tier mapping. `DEBUG/INFO → Public`, `WARN → Internal`, `ERROR → Confidential`, `CRITICAL → Restricted`. Reuses existing `:sensitivityTier` pattern. |
| 5.4 | 0.5 d | `wizard/rules.py:compile_causal_rule(causal_edge_dict)` — converts an approved `LOG_CAUSAL_EDGE` candidate into a SPARQL CONSTRUCT rule body. Plugs into the existing `export_rules` path so Phase B materialisation picks it up automatically. |
| 5.5 | 0.5 d | Tests: generated ontology contains the causal taxonomy; an approved causal edge round-trips through `compile_causal_rule` → validates → produces the expected `:hasCause` derivation when materialised. |

### Acceptance gate L5

- After running phases `mine → review (approve ≥ 5) → 2 → reason`, the materialised graph contains ≥ 1 derived `:hasCause` triple with a `prov:wasDerivedFrom` block that names the rule.
- The Materialised tab in the Viewer renders the premise tree for that triple back to its source log-template id.

---

## 6. Phase L6 — RCA Templates + Insights (0.5 d / 1 half-day)

### Files to create

```
templates/rules/rca.yaml         # cause-chain, concurrent-cause, heartbeat-inference
runtime/insights.py              # modify — two RCA-shaped prompt presets
tests/test_rca_starter_library.py
```

### Acceptance gate L6

- Loading `rca.yaml` via the wizard's library dropdown surfaces three rules.
- Each rule validates and test-fires on the synthetic preview ABox.
- The Insights "What caused {event}?" preset is selectable from the Ask Insights panel; ungrounded fallback ("not enough context") is the response when materialised triples aren't present.

---

## 7. Phase L7 — Closed-Loop Drift Hook (1 d / 2 half-days, optional)

### Files to modify

```
runtime/drift/monitor.py
runtime/drift/enricher.py
```

### Implementation order

| Block | Effort | What you ship |
|---|---|---|
| 7.1 | 0.5 d | Drift monitor consumes new log lines not matching any approved template. Pushes them into `ontology_evolution_proposals` with `proposal_type='LOG_EVENT'`, `detection_strategy='DRIFT_ON_NEW_TEMPLATE'`. |
| 7.2 | 0.5 d | Wizard's Step 2.5 already paginates by status; new drift-detected candidates simply appear in the review queue alongside bootstrap ones. No new UI. |

### Acceptance gate L7

- Injecting one new template (a log line no existing template matches) at runtime causes one new `LOG_EVENT` proposal to land in the review queue within 60 seconds.

---

## 8. Timeline view (12.5-day path)

```
   Days   1 2 3 4 5 6 7 8 9 10 11 12
Pre-flight ▓
Phase L1   ▓▓▓ (Drain + PMI + temporal)
Phase L2     ▓▓ (HMM)
Phase L3       ▓ (causality)
Phase L4         ▓▓▓ (review UI)
Phase L5             ▓ (RCA ontology)
Phase L6              .5 (templates)
Phase L7                ▓ (drift loop, optional)
Buffer                   ▓ (regression + docs)
```

**v1 minimum-shippable slice** (the "story works end-to-end" milestone):
- Pre-flight + L1 + L4 + L5 = **7.5 days**.
- v1 demonstrates: logs in → reviewed candidates → ontology generated → materialised graph carries derived `:hasCause` triples with PROV-O lineage.

**v2 adds depth**:
- L2 + L3 + L6 + L7 = additional **5 days**.
- v2 turns "engineers approve everything Drain suggests" into "engineers approve what HMM/Granger triangulate as causally meaningful."

---

## 9. Branch & PR strategy

```
develop                              (protected)
  └── feature/log-rca                 (integration branch — merge target for all sub-PRs)
        ├── feature/log-rca/L1-mining
        ├── feature/log-rca/L2-sequence
        ├── feature/log-rca/L3-causality
        ├── feature/log-rca/L4-review-ui
        ├── feature/log-rca/L5-rca-gen
        ├── feature/log-rca/L6-templates
        └── feature/log-rca/L7-drift-loop
```

- Each sub-PR lands into `feature/log-rca` only.
- `feature/log-rca` → `develop` is **one big PR** at the v1 milestone, with the v2 phases riding the same PR if they land in time, or a follow-up PR if not.
- Every sub-PR must include its phase's acceptance gate as a passing test and a one-line line entry in `docs/release-notes.md`.

---

## 10. Test inventory targets

| Phase | New test files | Min new tests |
|---|---|---|
| L1 | `test_log_miner.py`, `test_log_templates.py` | 12 |
| L2 | `test_sequence_learner.py` | 6 |
| L3 | `test_causality_miner.py` | 5 |
| L4 | `test_log_review.py` | 8 |
| L5 | `test_rca_ontology.py` | 6 |
| L6 | `test_rca_starter_library.py` | 3 |
| L7 | extend `test_drift_integration.py` | 2 |
| **Total** | 7 new files | **42 new tests** |

Aim for full-suite count to land near **215 tests passing** post-L7 (173 today + 42 new).

---

## 11. Demo plan (per-phase, visible to stakeholders)

| Phase | Demo (≤ 5 min) |
|---|---|
| L1 | `python toolkit.py --phase mine --log-path examples/log-rca/sample/` → show template table + entity edges in sqlite browser. |
| L2 | Inject one anomalous trajectory into the corpus, rerun mine + sequence, show the new `LOG_EVENT` candidate. |
| L3 | Two `LOG_CAUSAL_EDGE` candidates appear with `p_value < 0.05` and visible lag. |
| L4 | Launch wizard → Step 2.5 → approve five candidates → Step 2/3/4 show them as proper entities/events/relationships. |
| L5 | Run `--phase 2 --phase reason` → open Viewer → Materialised tab → click a derived `:hasCause` → premise tree drills to source log template. |
| L6 | Load `rca.yaml` from the rules library → test-fire on synthetic ABox → see `:rootCause` derivations. |
| L7 | Tail a new log file into the watched folder with a never-seen template → new candidate appears in the review queue within 60 s. |

The "screenshot of step 2.5 with five candidates pending review" is the single best deck slide for the v1 milestone.

---

## 12. Risk-tracked checkpoints (recap)

These are the existing risks from roadmap §8 — listed here with the exact checkpoint where each gets validated.

| Risk | Validated at | Mitigation in plan |
|---|---|---|
| Pattern false-positives | L1.8 buffer | Tune τ_PMI + EM threshold against real corpus before L2 builds on top. |
| Causation ≠ correlation | L3 acceptance gate | UI labels Granger candidates as "statistically dependent." |
| PII in log values | L1.3 slot typing | Sensitivity tier defaults to Confidential for slot kinds matching the PII regex set. |
| Review-queue fatigue | L4.4 | Top-50 cap, sort by `confidence × consequence`, "batch approve cluster" action. |
| Generated ontology bloat | L5 acceptance gate | OWL profile detector emits warning when log-derived classes > 2× hand-authored count. |

---

## 13. Hand-off / next step

Pick one of:

- **Start L1 now.** Open `feature/log-rca/L1-mining`, copy roadmap §5 Phase L1 acceptance gate into the PR description, run the day-1 checklist (sample corpus + dep pin + schema migration).
- **Validate the open questions first.** Have a 30-minute meeting per roadmap §9 to lock in the five defaults, then start L1.
- **Build a thinner prototype.** Skip the wizard work and ship a CLI-only `--phase mine + --phase generate-from-mine` path in 3 days to validate the algorithmic core before committing the L4 UX budget.

The third option is the lowest-risk path if you have any doubt about Drain + PMI working on your real-world corpora. If the algorithms hold up, jump straight to L4–L5; if they don't, L1's parameters get retuned cheaply before any UI work locks in.
