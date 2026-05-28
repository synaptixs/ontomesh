# Log Discovery (v2) — Roadmap

> **Status:** plan only. Nothing in this document is implemented yet. Builds on the v1 pipeline that shipped in PR #21 (Phases L1–L7) and the wizard Step 5 Log Discovery UI that landed with the database-import work in PR #22.

> **Companion docs:** [log-rca-roadmap.md](log-rca-roadmap.md) — the v1 plan. [log-rca-dev-plan.md](log-rca-dev-plan.md) — the v1 dev plan with day-level granularity. This document follows the same structure for v2.

---

## 1. What we have today

Six layers, all shipped in v1:

| Layer | Today's implementation | PRML mapping | Module |
|---|---|---|---|
| Template clustering | Drain3 at `sim_th=0.4` + EM merge | Ch. 9 (mixture / EM) | `src/log_templates.py` |
| Slot typing | Regex ladder + entropy | — | `src/log_miner.py` |
| Entity graph | PMI + temporal lead ratio | Ch. 8 (graphical models) | `src/log_miner.py` |
| Trajectory model | Per-service `CategoricalHMM` with BIC | Ch. 13 (sequential data) | `src/sequence_learner.py` |
| Anomaly score | HMM log-likelihood + cluster-bag novelty (heuristic floor) | — (ad-hoc) | `src/sequence_learner.py` |
| Causality gate | Granger + transfer-entropy triangulation | Ch. 11 + Ch. 14 | `src/causality_miner.py` |
| Review surface | `confidence × consequence` sort | Ch. 1 (decision theory) | `wizard/log_review.py` |

**The v1 demo against `examples/log-rca/large/` (6,836 lines):** 52 templates · 101 slots · 1,843 PMI edges · 98 triangulation-gated causal edges · 1 HMM anomaly. End-to-end in ~0.5 s.

---

## 2. Where v1 is shallow

Honest inventory of what's currently weak — each motivates one v2 phase below.

1. **Single regime per service.** A single HMM averages over business hours, maintenance windows, and incident response. A "weekend-maintenance" pattern surfaces as an anomaly during weekdays not because anything is wrong, just because the model averaged over both regimes. **The biggest source of review-queue false positives.**

2. **Heuristic confidence.** The dev-plan acceptance gate (≥ 0.6 on injected outliers) is met by a hand-tuned confidence floor, not a calibrated probability. Engineers can't compare confidence across kinds (event vs causal edge); review-queue sort order is debatable.

3. **Pairwise causality only.** Granger and TE test pairs in isolation. A real RCA needs a *structural* graph that exposes shared causes — three pairwise edges `A→B`, `A→C`, `B→C` may collapse to a single `A → {B, C}` once you condition on `A`.

4. **Review queue doesn't learn across runs.** Engineers reject the same noise template every session. The ordering is static; rejected patterns don't get suppressed in future runs.

5. **Template clustering is hard-thresholded.** Drain's `sim_th=0.4` is one knob. Over-merge (lose information) or over-split (review fatigue) depending on corpus noise — no posterior over template count.

6. **No rate-shape anomalies.** The HMM sees template *identity*, not template *rate*. A burst of normal templates (e.g., 10× the usual log rate for "User logged in") is invisible to v1 but is the canonical "something broke" signal.

---

## 3. Six PRML-mapped enhancements

Ranked by impact-per-effort for the RCA use case, not by mathematical elegance.

### Phase L8 — Switching State-Space Models for regime detection

**Bishop reference:** Ch. 13.3.3 (switching state-space models) and Ch. 9 (mixture models for the regime distribution).

**The problem this fixes.** §2.1 above — the single-HMM averaging.

**Technique.** Two-level latent model:
- Top level: discrete regime `z_t ∈ {1..K}` with its own transition matrix.
- Per regime: a CategoricalHMM over template ids (what v1 already has).
- Inference via VB-EM (mean-field over regime indicator + emission + transition params).

**New module:** `src/sequence_learner_regimes.py` (keep v1's `sequence_learner.py` for backward compatibility).

**Persistence.** New SQLite tables:
- `log_regime_models(service, n_regimes, model_blob, fit_at)`
- `log_trajectory_regimes(trajectory_id, regime_id, posterior)` — per-trajectory regime assignment.

**What lands in the UI.** Each LOG_EVENT proposal carries an extra tag: *"Appears in Regime 2 (4 sessions/hour, Saturdays 02:00–06:00) but not Regime 1 (weekday business hours)."*

**Acceptance gate.** On a synthetic corpus with two engineered regimes (business hours + maintenance) plus one regime-specific anomaly:
- ≥ 2 regimes discovered per service.
- The synthetic anomaly surfaces *only* under its own regime.
- A normal-but-rare pattern in Regime 2 does **not** flag (the v1 single-HMM falsely flags it).

**Effort.** 3 days.

---

### Phase L9 — Active-learning review-queue ranker

**Bishop reference:** Ch. 1.5 (decision theory + loss functions) and Ch. 4.3 (logistic regression).

**The problem this fixes.** §2.4 above — engineers re-rejecting the same noise.

**Technique.** A small logistic classifier trained on `(features, decision)` pairs across all past runs:
- **Features (per proposal):** kind, confidence, severity, evidence_volume, slot-PII flag, template-token-count, n-services-touched, hits, time-since-first-seen, regime tag if L8 is in.
- **Target:** `approved=1` / `rejected=0` from `ontology_evolution_proposals.status`.
- **Refit:** on demand (button on Step 5) and nightly.

**New module:** `wizard/review_ranker.py`. Exposes `score(proposal_dict) -> float` and `rerank(candidates) -> candidates`.

**Wiring.** `wizard/log_review.list_candidates` calls the ranker if a fitted model is present on disk; falls back to `confidence × consequence` otherwise. Failure mode is graceful — a ranker that's never been trained is just a no-op.

**Persistence.** Single pickle at `db/review_ranker.pkl` (committed to gitignore; reference in `wizard/ontologies_store.py`).

**What lands in the UI.** A new "↻ Re-rank with feedback" button in Step 5. When clicked: refits the model on the current proposal-store decisions and re-sorts the queue. A small "model trained on N decisions" badge under the count.

**Acceptance gate.** On a corpus with 200 mined proposals, simulate 50 alternating approve/reject decisions on a clearly-noisy slice:
- Re-rank pushes the simulated noise-class proposals from the top half of the queue to the bottom half.
- Cross-validated AUC ≥ 0.75 reported in the test log.

**Effort.** 1 day.

---

### Phase L10 — Calibrated confidence via Variational Bayes

**Bishop reference:** Ch. 10.1 (variational inference) and Ch. 10.2.4 (VB for mixture models).

**The problem this fixes.** §2.2 above — the heuristic confidence floor.

**Technique.** Replace the BIC-selected point estimate of the HMM with a variational Bayesian posterior:
- Variational lower bound (ELBO) for each candidate `n_components`.
- Marginalise over model size by Bayesian model averaging across the top-K.
- Confidence becomes "posterior probability that this trajectory's per-step log-likelihood is below the 5th percentile of the variational predictive."

**Module changes.** Drop-in replacement inside `src/sequence_learner.py:fit_hmm_for_service`. Add `vb` as an alternative inference path; keep the EM path for fallback / A/B comparison.

**Acceptance gate.**
- Reliability diagram (10-bin) shows ECE < 0.05 on a held-out synthetic corpus.
- Confidence floor in the test suite (currently 0.6 hand-tuned) becomes a proven posterior probability — no `max(confidence, 0.6)` in the new code path.
- Existing tests (`tests/test_sequence_learner.py`) still pass under the new path.

**Effort.** 1.5 days.

---

### Phase L11 — Bayesian causal structure learning (PC algorithm)

**Bishop reference:** Ch. 8.2 (conditional independence) and Ch. 8.4.5 (causality, d-separation).

**The problem this fixes.** §2.3 above — pairwise causality only.

**Technique.** **PC algorithm** running on the time-binned rate series the Granger code already produces:
1. Skeleton phase: pairwise conditional-independence tests over expanding conditioning sets.
2. v-structure orientation.
3. Meek rule propagation.

Output: a **partially-directed graph** (PDAG) over template ids. Causal edges from this graph supersede the pairwise list when present.

**New module:** `src/causality_dag.py`. Reuses `src/causality_miner.build_rate_series`.

**Wiring.** `wizard.log_review.seed_from_mining` consults the PDAG first; falls back to the v1 pairwise list when conditioning sets aren't significant. Each `LOG_CAUSAL_EDGE` proposal carries its parent set as evidence text.

**What lands in the UI.** The causal-edge card shows the edge plus a small "shared causes" line: *"Shared upstream cause: NetworkPartition (confounds A→B and A→C)"*.

**Acceptance gate.** On a synthetic 3-node corpus where `A` causes both `B` and `C` (no `B→C` edge):
- v1 Granger gives `A→B`, `A→C`, `B↔C` (the spurious one).
- v2 PC gives `A→B`, `A→C` only — the `B↔C` edge is removed once conditioned on `A`.

**Effort.** 2 days.

---

### Phase L12 — Probabilistic PCA over template-feature vectors

**Bishop reference:** Ch. 12.2 (probabilistic PCA).

**The problem this fixes.** §2.5 above (over-/under-clustering) **plus** the demo screenshot story.

**Technique.** Each template's bag-of-tokens (after stop-token + numeric-slot removal) → sparse vector. Run pPCA to 2 components for visualisation, 8–16 for merge candidacy.

**Module:** `src/log_templates_embed.py`. Surfaces `embed(template_id) -> np.ndarray` and `suggest_merges(threshold)`.

**Wiring.** Drain-merge step now consults pPCA-distance as a secondary check before merging.

**What lands in the UI.** The Step 5 cluster card gets a small 2D scatter (PCA projection). Templates within distance `δ` are circled as merge candidates; engineer clicks to confirm/dismiss.

**Acceptance gate.**
- On the bundled `large/` corpus: cluster count drops by ≥ 10 % vs Drain alone with no measurable loss of unique-pattern coverage (manual review).
- Top-5 nearest-neighbour pairs for one held-out template all "obviously" relate to it (judged by an engineer reading the templates).

**Effort.** 1.5 days.

---

### Phase L13 — Rate-shape anomalies via Gaussian Processes

**Bishop reference:** Ch. 6.4 (Gaussian processes), Ch. 3.3 (Bayesian linear regression).

**The problem this fixes.** §2.6 above — burst-of-normal-templates anomalies.

**Technique.** Per template, fit a GP over time-of-day with a **periodic kernel** (24h period) + an RBF kernel for local smoothness. Anomalies = points outside the 99% posterior predictive interval.

**Module:** `src/log_rate_anomalies.py`. Uses `sklearn.gaussian_process` for prototype; consider `gpytorch` if scale becomes an issue.

**Wiring.** New `detection_strategy='GP_RATE_DEVIATION'` proposals into the same store as L2 anomalies. Step 5 Log Discovery list shows a small sparkline per such proposal.

**Acceptance gate.**
- On a synthetic 1-week corpus with one injected rate-spike at 3 am:
  - The spike falls outside the 99% posterior interval.
  - Normal weekend rate dips (a different shape, not anomalies) do **not** flag.
- GP fit time on 7 days × 60 templates ≤ 30 s.

**Effort.** 1.5 days.

---

## 4. Recommended ordering

| # | Phase | Effort | Why this order |
|---|---|---|---|
| 1 | **L9 — Active-learning ranker** | 1 d | Lowest effort, highest cumulative payoff. Every approval/rejection improves the next run. Ship first. |
| 2 | **L8 — Switching SSM regimes** | 3 d | Largest single drop in false-positive rate. Adds the regime tag that downstream phases (L11 / L13) can condition on. |
| 3 | **L10 — VB calibrated confidence** | 1.5 d | Cleans up the heuristic confidence floor. Drop-in inside `sequence_learner.py`. |
| 4 | **L11 — PC algorithm causal DAG** | 2 d | Replaces pairwise Granger with structural causality. Publishable architecture story. |
| 5 | **L12 — pPCA template viz** | 1.5 d | Demo screenshot. Modest merge improvement. |
| 6 | **L13 — GP rate anomalies** | 1.5 d | Catches a different anomaly *kind*. Complement, not replacement. |

**Total: ~10.5 person-days.** Smallest shippable slice is **L9 + L8** (4 days) — already a major perceptual upgrade: "the queue learns from your decisions" and "regime-aware anomalies" are both release-note-worthy bullets.

---

## 5. v2 acceptance gate (after L8 + L9 + L10)

A reviewer running on `examples/log-rca/large/`:

1. First mine + sequence pass → review queue ordered by `confidence × consequence` (v1 behaviour). Approves 5 useful events, rejects 5 obvious noise.
2. Click **↻ Re-rank with feedback** → the 5 rejected categories drop below the fold.
3. Each `LOG_EVENT` proposal carries a regime tag (e.g. *"Regime 2 of 3"*); some show only in Regime 2.
4. Confidence values are real posterior probabilities (no `max(c, 0.6)` clamps in the code).
5. Reliability diagram in `output/reports/anomaly_calibration.png` shows ECE < 0.05.
6. Full pipeline runs in ≤ 5 s on the 6,836-line corpus (vs v1 ~0.5 s — VB inference is the dominant new cost; that's tolerable).

---

## 6. Risks worth naming now

| Risk | Where it surfaces | Mitigation |
|---|---|---|
| **Regime overfitting** | L8 on small corpora — 2 regimes get picked when there's really 1 | Per-service minimum corpus size (24 h); VB ELBO threshold to admit `K>1`. |
| **Cold-start ranker** | L9 — first run has no decisions yet | Falls back to `confidence × consequence` until ≥ 20 decisions in the store. |
| **PC algorithm cost on big graphs** | L11 — conditional-independence tests are exponential in conditioning-set size | Cap conditioning-set size at 3 (standard practical limit); skip CI tests when `n_samples < 30`. |
| **VB local minima** | L10 — variational posterior can land on a poor local mode | Multi-restart (3 seeds) + ELBO maximisation; warn in the report if ELBO variance > 5% across restarts. |
| **GP scaling** | L13 — `O(n³)` in observations | Subsample to 5,000 points per template for fit; use posterior on the full series. Sparse GP (Ch. 6.4.6) if needed at production scale. |
| **Ranker drift** | L9 — model trained on old decisions stays in place when org's review style changes | Refit on every Step 5 page load (it's small — ~1k samples, < 50 ms). |
| **Increased opaqueness** | L8–L13 as a set — engineers may distrust "Bayesian" labels | Every UI surface that uses a v2 signal also shows the v1 signal in a tooltip ("v1 said: …; v2 says: …"). |

---

## 7. Out of scope (deliberately)

- **Neural log embedding (BERT-style).** Original v1 roadmap deferred this; the reasoning stands. Embedding-distance candidates are *harder* for an engineer to review than rule-based ones, not easier. Stick to the principle: if an engineer can't read the rule, they won't approve it.
- **Online learning during a mining run.** The ranker (L9) refits between runs, not during. Adds operational complexity, low payoff.
- **Reinforcement-learning queue agents.** Logistic regression on `(features, decision)` does the job. RL is overkill.
- **Anomaly explanation via attention / SHAP.** Worth doing eventually but PRML-adjacent rather than core PRML. Park until v3.
- **GP scaling beyond ~10 k points.** If a customer corpus needs it we can revisit with sparse GPs (Ch. 6.4.6) or stochastic VB.

---

## 8. Open questions to resolve before coding L8

1. **Regime count K — fixed or learned?** Lean toward "learned via ELBO, capped at K=5". Defaults need agreeing.
2. **Regime tag persistence.** Store per-trajectory regime in the proposal? Or only show it transiently in the UI? Persistence matters if downstream Insights queries want to filter by regime.
3. **Cross-service regimes.** Do we fit a *global* regime that gates multiple services' HMMs, or independent regimes per service? Cross-service captures the "whole site under maintenance" case but is computationally heavier.
4. **Ranker feature set.** The list in §3.L9 is a starting point. Whether to include the regime tag as a feature depends on whether L8 ships first (it should, per the ordering above).
5. **VB stopping criterion.** ELBO change threshold + max iterations. Defaults need pinning per the dev plan that follows.

---

## 9. Files added / extended (preview)

```
src/sequence_learner_regimes.py        L8 — switching SSM + VB-EM
src/log_templates_embed.py             L12 — pPCA + KNN merge candidates
src/causality_dag.py                   L11 — PC algorithm
src/log_rate_anomalies.py              L13 — GP per-template rate model
src/sequence_learner.py                L10 — VB inference path (additive)
wizard/review_ranker.py                L9 — logistic ranker
wizard/log_review.py                   L9, L11 wiring
wizard/templates/index.html            L9 re-rank button, L8 regime tag,
                                        L12 2D scatter
db/migrations/log_discovery_v2.py      new tables: log_regime_models,
                                        log_trajectory_regimes, ranker pickle ref
docs/log-discovery-enhancements-dev-plan.md   half-day breakdown (next doc)
```

---

## 10. Where this leaves us

After L8 + L9 + L10 (the v2.0 slice), the Log Discovery review experience becomes:

> "The queue is sorted by what *you* tend to approve, anomalies come with a regime tag so you know what's normal-for-context, and the confidence score is a real probability we can defend in an audit."

That's the pitch. The remaining phases (L11–L13) are each independently shippable on top and don't depend on each other — they can be picked up opportunistically by whoever has time, in any order, without blocking the v2.0 slice from going to production.

The dev plan with day-level granularity and acceptance gates per half-day block will follow in [`log-discovery-enhancements-dev-plan.md`](log-discovery-enhancements-dev-plan.md) once the open questions in §8 are resolved.
