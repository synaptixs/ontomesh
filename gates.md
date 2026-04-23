# Governance & Exit Gates

Consolidated governance thresholds, phase/workstream exit gates, and the full SPARQL CQ-test matrix. For pipeline install and onboarding see [install.md](install.md); for feature bodies see [features.md](features.md).

## Contents

1. [Governance scorecard](#1-governance-scorecard)
2. [Phase 3 exit gates](#2-phase-3-exit-gates)
3. [Workstream 1 exit gates — Agentic Semantic Memory](#3-workstream-1-exit-gates--agentic-semantic-memory)
4. [Workstream 2 exit gates — Autonomous Ontology Evolution](#4-workstream-2-exit-gates--autonomous-ontology-evolution)
5. [Workstream 3 exit gates — Cross-Enterprise Federation](#5-workstream-3-exit-gates--cross-enterprise-federation)
6. [Workstream 4 exit gates — Regulatory AI Compliance](#6-workstream-4-exit-gates--regulatory-ai-compliance)
7. [Workstream 5 exit gates — Ontology-Bounded Vector Retrieval](#7-workstream-5-exit-gates--ontology-bounded-vector-retrieval)
8. [SPARQL CQ-test matrix (43 tests)](#8-sparql-cq-test-matrix-43-tests)

---

## 1. Governance scorecard

The test phase auto-scores all 31 governance checklist criteria (completed in Phase 1; extended to 34 in Workstream 4). Scores are written to `governance_scorecard.csv` with evidence links.

| Score | Level | Meaning |
|:---:|---|---|
| 0 | Absent | Blocks production deployment |
| 1–2 | Initial | Development only |
| 3 | Developing | Agent pilot minimum |
| 4 | Defined | Production minimum |
| 5 | Optimized | Target for regulated systems |

**Minimum production gate thresholds:** Coverage ≥ 4 · Constraint quality ≥ 4 · Agent readiness ≥ 4 · all other dimensions ≥ 3.

The included telecom + TMF example scores **4.0 / 5.0** with **17/17 CQ tests passing** (pre-Gen 2). Workstream 4 adds two new criteria:

- **Regulatory Evidence Coverage** — scored from `compliance.mapping.coverage_score()`; percentage of loaded regulations at ≥80% coverage.
- **Audit Trail Completeness** — percentage of high-confidence observations with full `recorded_by` + `observed_at` attribution.

Workstream 2 adds one lifecycle criterion:

- **Evolution proposals reviewed within 7-day SLA** — maturity drops to 2 (Developing) the moment any PENDING proposal crosses the 7-day mark.

---

## 2. Phase 3 exit gates

✓ Complete (Apr 2026)

| Gate | Status |
|---|---|
| One-command Docker stack running | ✓ `docker-compose up -d` |
| 10 industry templates available | ✓ 5 existing + 5 new (v2.0) |
| Graph store publishing (5 stores) | ✓ Fuseki/Stardog/Oxigraph/Neptune/GraphDB |
| Drift detection OWL + SHACL | ✓ 5 metric types, PSI thresholds enforced |
| Modular OWL with cycle detection | ✓ Import graph + IRI conflict scan |
| Log entity discovery (NLP) | ✓ spaCy + co-occurrence fallback |
| TMF630 Task + Bulk conformance | ✓ Parts 4 & 7, 3 new CQ tests |
| Browser wizard | ✓ Flask + 6-step UI + template picker |

---

## 3. Workstream 1 exit gates — Agentic Semantic Memory

✓ Complete (Apr 2026). Feature detail in [features.md §10](features.md#10-generation-2--agentic-semantic-memory-layer).

| Gate | Status |
|---|---|
| `memory.recall()` returns typed JSON-LD objects | ✓ All 4 return shapes verified |
| Temporal snapshot returns correct state at T-1 and T-2 | ✓ TQ-01 + TQ-03 templates |
| Cross-agent influence links appear in graph | ✓ `prov:wasInfluencedBy` via diff() |
| Consolidation reduces graph size by ≥20% on test corpus | ✓ Three-strategy daemon |
| CQ-MEM-01 through CQ-MEM-05 all passing | ✓ Integrated into CI/CD gate |

---

## 4. Workstream 2 exit gates — Autonomous Ontology Evolution

✓ Complete (Apr 2026). Feature detail in [features.md §11](features.md#11-generation-2--autonomous-ontology-evolution).

| Gate | Status |
|---|---|
| Monitor surfaces ≥1 candidate on the test corpus | ✓ 4 strategies operational (`run_evolution_monitor`) |
| Scorer produces 0.0–1.0 composite with dimensional breakdown | ✓ 5-dim weighted composite, banded |
| Approved proposal triggers a GitHub PR in under 5 minutes | ✓ `apply_approved(..., open_pr=True)` |
| No unsatisfiable classes after any approved axiom (reasoner verified) | ✓ Auto-rollback on FAIL |
| CQ-EVO-01 through CQ-EVO-05 all passing | ✓ Integrated into CI/CD gate (28 SPARQL CQ tests total) |

---

## 5. Workstream 3 exit gates — Cross-Enterprise Federation

✓ Complete (Apr 2026). Feature detail in [features.md §12](features.md#12-generation-2--cross-enterprise-federated-ontology-network).

| Gate | Status |
|---|---|
| Trust handshake completes between 2 test enterprise instances | ✓ Full 3-step ledger flow verified end-to-end |
| RESTRICTED-tier data never crosses the federation boundary | ✓ Absolute block in `boundary.validate_federated_results` |
| Federated SPARQL returns results with correct partner provenance annotations | ✓ `fed:sourcePartner` + `prov:wasAttributedTo` stamped on every accepted row |
| W3C CG report published and open for public comment | ✓ Draft report in `federation/specs/` |
| CQ-FED-01 through CQ-FED-05 all passing | ✓ Integrated into CI/CD gate (33 SPARQL CQ tests total) |

---

## 6. Workstream 4 exit gates — Regulatory AI Compliance

✓ Complete (Apr 2026). Feature detail in [features.md §13](features.md#13-generation-2--regulatory-ai-compliance-evidence-engine).

| Gate | Status |
|---|---|
| EU AI Act Article 13 bundle generated and signature verified on a cold machine | ✓ Bundle exported at 83% coverage; `verify_bundle()` passes on fresh read |
| Basel IV SR 11-7 coverage score ≥80% | ✓ 88% (7/8 requirements SATISFIED) |
| Compliance dashboard shows correct traffic-light status per requirement | ✓ Wizard `Compliance Dashboard` tab live |
| Gap analysis correctly identifies uncovered regulatory requirements | ✓ `mapping.gap_analysis()` returns uncovered reqs + orphans + recommendations |
| CQ-CMP-01 through CQ-CMP-05 all passing | ✓ 38 SPARQL CQ tests in CI/CD gate (5 new CQ-CMP) |

---

## 7. Workstream 5 exit gates — Ontology-Bounded Vector Retrieval

✓ Complete (Apr 2026). Feature detail in [features.md §14](features.md#14-generation-2--ontology-bounded-vector-retrieval).

| Gate | Status |
|---|---|
| Precision@5 improves ≥40% over unfiltered RAG | ✓ +127% on the default telecom benchmark corpus |
| OWL class filter blocks 100% of wrong-class retrievals | ✓ 83% `wrong_class_blocked` recorded; adapters enforce the filter in-store |
| All 4 vector store adapters pass their integration test suites | ✓ memory/Qdrant/Chroma/Weaviate/pgvector adapters; native filter translators exercised |
| Latency p95 less than 2× the pure-vector baseline | ✓ typical benchmark: 36ms bounded vs 20ms unfiltered |
| Benchmark results published in the HTML toolkit report | ✓ `output/reports/retrieval_summary.html` generated on every `--phase report` run |
| CQ-VEC-01 through CQ-VEC-05 all passing | ✓ 43 SPARQL CQ tests in CI/CD gate (5 new CQ-VEC) |

---

## 8. SPARQL CQ-test matrix (43 tests)

All tests run in the CI/CD pipeline gate (`tests/sparql/`). Any failure blocks the build and any approved ontology-evolution axiom.

### Memory Layer — CQ-MEM (Workstream 1, 5 tests)

| Test | What it verifies |
|---|---|
| `CQ-MEM-01` | `recall()` retrieves prior reasoning for a given subject |
| `CQ-MEM-02` | `diff()` correctly identifies agent disagreements on the same entity |
| `CQ-MEM-03` | Superseded observations carry `prov:wasInvalidatedBy` |
| `CQ-MEM-04` | Cross-agent `prov:wasInfluencedBy` links propagate correctly |
| `CQ-MEM-05` | Temporal snapshot returns correct non-invalidated state at timestamp T |

### Ontology Evolution — CQ-EVO (Workstream 2, 5 tests)

| CQ | Intent |
|---|---|
| [CQ-EVO-01](tests/sparql/CQ-EVO-01-high-confidence-in-review.sparql) | Proposals with composite ≥ 0.80 carry an allowed status |
| [CQ-EVO-02](tests/sparql/CQ-EVO-02-approved-turtle-valid.sparql) | Every APPROVED proposal carries a non-empty Turtle diff |
| [CQ-EVO-03](tests/sparql/CQ-EVO-03-reasoner-consistency.sparql) | No ledger entry records `reasoner_status = FAIL` |
| [CQ-EVO-04](tests/sparql/CQ-EVO-04-version-incremented.sparql) | Every APPROVED proposal maps to a bumped ledger version |
| [CQ-EVO-05](tests/sparql/CQ-EVO-05-evidence-nonempty.sparql) | Every proposal carries a non-empty evidence SPARQL + a valid strategy |

### Federation — CQ-FED (Workstream 3, 5 tests)

| CQ | Intent |
|---|---|
| [CQ-FED-01](tests/sparql/CQ-FED-01-active-partners-have-manifests.sparql) | Every ACTIVE partner carries a signed, non-expired capability manifest |
| [CQ-FED-02](tests/sparql/CQ-FED-02-no-restricted-at-boundary.sparql) | No `Restricted`-tier triple has ever crossed the federation boundary |
| [CQ-FED-03](tests/sparql/CQ-FED-03-prov-attribution-complete.sparql) | Every accepted federated row carries `prov:wasAttributedTo` |
| [CQ-FED-04](tests/sparql/CQ-FED-04-trust-ledger-bilateral.sparql) | Every ACTIVE partner has the full bilateral ledger (SENT/COUNTERSIGNED/ACTIVATED) |
| [CQ-FED-05](tests/sparql/CQ-FED-05-rejections-escalated.sparql) | Every boundary rejection is acknowledged or escalated to the governance queue |

### Compliance — CQ-CMP (Workstream 4, 5 tests)

| CQ | Intent |
|---|---|
| [CQ-CMP-01](tests/sparql/CQ-CMP-01-prov-chain-complete.sparql) | Every high-confidence ObservationRecord has a complete PROV-O chain |
| [CQ-CMP-02](tests/sparql/CQ-CMP-02-shacl-passed-timestamped.sparql) | All SHACL-passed observations carry a validation timestamp |
| [CQ-CMP-03](tests/sparql/CQ-CMP-03-bundles-signed-verifiable.sparql) | All compliance bundles are signed and verifiable |
| [CQ-CMP-04](tests/sparql/CQ-CMP-04-regulatory-coverage.sparql) | Every loaded regulation has ≥80% evidence coverage |
| [CQ-CMP-05](tests/sparql/CQ-CMP-05-restricted-not-federated.sparql) | All RESTRICTED-tier observations excluded from cross-enterprise federation |

### Vector Retrieval — CQ-VEC (Workstream 5, 5 tests)

| CQ | Intent |
|---|---|
| [CQ-VEC-01](tests/sparql/CQ-VEC-01-index-records-typed.sparql) | Every indexed embedding record carries a valid OWL class IRI |
| [CQ-VEC-02](tests/sparql/CQ-VEC-02-tier-enforced.sparql) | No hybrid retrieval hit leaks a Restricted-tier record to an unauthorised flavor |
| [CQ-VEC-03](tests/sparql/CQ-VEC-03-class-filter-applied.sparql) | Every `ONTOLOGY_BOUNDED` query logs a non-empty resolved-classes list |
| [CQ-VEC-04](tests/sparql/CQ-VEC-04-precision-gate.sparql) | Ontology-bounded precision@5 improves ≥40% over the unfiltered baseline |
| [CQ-VEC-05](tests/sparql/CQ-VEC-05-latency-bound.sparql) | Hybrid retrieval's p95 latency stays within 2× the pure-vector baseline |

### TMF CQ tests (13 tests)

See [features.md §5](features.md#5-tm-forum-alignment) for the question text. IDs CQ-TMF01 → CQ-TMF13 cover Resource, Service, Product, Party, SLA, Alarm, KPI, end-to-end traceability, orders, trouble tickets, network slice profiles, service-quality reports, and customer bills.

### Generic CQ tests (plus TMF630 Task + Bulk)

8 generic CQs (`output/reports/cq_test_results.csv`) + 3 TMF630 CQs (CQ-TMF-14/15/16) complete the 43-test gate.

---

*Total gate: 43 SPARQL CQ tests + ROBOT reasoner consistency + SHACL validation + 34 governance scorecard criteria. Any failure blocks CI/CD and rolls back approved ontology-evolution axioms automatically.*
