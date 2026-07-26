# Ontology Enhancement Roadmap — Phased Plan

*Analysis date: 2026-07-25 · validated 2026-07-26 · Ontomesh v3.9.0 (`develop`) · all findings independently verified — see [Appendix A](#appendix-a--verification-commands) and [Appendix B](#appendix-b--impact-proofs)*

---

## Executive summary

The pipeline is strong. **The artifact it produces is not.** The generated ontology is RDFS with annotations wearing an OWL 2 label, it asserts falsehoods at scale, and the quality gates report green regardless.

The three findings that drive this plan:

| # | Finding | Verified measurement |
|---|---|---|
| **1** | **No logical content.** Zero class expressions anywhere. | `owl:Restriction` in 0 of 70 `.ttl` files. Reasoner closure = 3,425 triples, of which **2,207 are reflexive tautologies** and **0 are genuine classifications**. |
| **2** | **The ontology asserts falsehoods.** Property IRIs are minted per *column name*, then re-declared per table, and `rdfs:domain` conjoins. | **114 of 671 properties have >1 domain.** `hasCreatedAt` has **46**, meaning anything with a timestamp is inferred to be all 46 classes at once. |
| **3** | **The gate cannot fail.** | **43/43 competency-question tests pass; all 43 return zero rows.** Several of the 35 governance criteria pass a literal score with no computation. |

**Finding 3 is the one to fix first.** Findings 1 and 2 are bugs; finding 3 is why they survived nine releases and got advertised as "1000+ tests." Nothing below is verifiable until the gate can fail.

**Finding 2 is a latent time-bomb.** It is inert today only because there is no instance data. The moment an ABox lands — which is precisely what the Spine integration delivers — every timestamped record classifies into 46 classes and the graph becomes unusable. **Phase 2 is therefore a hard gate on Phase 4.**

### What is *not* broken

Worth stating plainly, because it shapes where the effort goes. `materializer.py` does per-triple `prov:wasDerivedFrom` lineage with a working `explain_triple()`. `ontology_diff.py` diffs *entailments*, not text. The log-mining chain (Drain3 + merge refinement, PMI with an empirically-swept threshold, GP rate anomalies) is real, tested work. 65 of 68 turtle files parse cleanly.

This is a strong pipeline producing a weak artifact, with the scorecard pointed at the pipeline instead of the artifact.

---

## Phase overview

| Phase | Theme | Effort | Gates |
|---|---|---|---|
| **0** | Make failure possible | S | — |
| **1** | Fix the broken artifacts | S | 0 |
| **2** | Soundness — stop asserting falsehoods | M | 1 |
| **3** | Expressivity — become actually OWL 2 | L | 2 |
| **4** | The ABox — instance data + Spine join | M | **2** (hard) |
| **5** | Depth — time, units, participation, identity | L | 3, 4 |
| **6** | Governance maturity | M | 4 |

Phases 0–2 are corrective and should run consecutively. Phases 3 and 4 can run in parallel once Phase 2 lands. Phases 5–6 are ongoing investment.

---

## Phase 0 · Make failure possible ✅ **DELIVERED**

*Branch `phase0/ontology-quality-gates` · 2026-07-26*

**Goal:** make it possible for CI to fail on a defective ontology. Before this, it could not.

| # | Work | Status |
|---|---|---|
| 0.1 | Parse every emitted `.ttl`; fail on error | ✅ [`scripts/ontology_gate.py`](scripts/ontology_gate.py) + `artifact-gate` CI stage |
| 0.2 | Delete the `PASS-STRUCTURAL` branch | ✅ [`sparql_tester.py`](src/sparql_tester.py) — suite now reports **6 pass / 37 fail** (was 43/0) |
| 0.3 | Replace hardcoded score literals with computed scores | ✅ 9 criteria now measure artifacts; **4 of 9 changed** once measured |
| 0.4 | Execute the `sparql_equiv` instead of the SQL twin | ✅ dual reporting: **SQL answers 8/8, ontology answers 1/8** |
| 0.5 | Commit a baseline snapshot | ✅ [`ontology_baseline.json`](ontology_baseline.json) |

**Design decision — a ratchet, not a permanent red build.** The plan originally called for a build that stays red until Phase 2. That trains people to ignore CI. Instead the gate compares against a committed baseline and fails **only on regression**, with each metric tagged to the phase that owns it. Existing debt is recorded, not excused; new debt cannot land silently. Each phase tightens the baseline via `--update-baseline`.

Two hard gates remain unconditional: a Turtle file that does not parse, and a SPARQL query that ERRORs.

**Verified outcomes**

- Gate returns exit 1 on regression and 0 on a clean run — tested in all three metric directions.
- Governance average moved 3.6 → **3.35**, and is now derived from measurements rather than literals.
- Criteria that changed: *Taxonomy vs ontology separation* 4→**0** (the SKOS file does not parse), *Semantic loss detection* 4→**2** (29 unresolved findings), *Explicit key relationships* 4→**3** (17 properties ranged at `owl:Thing`), *Structural constraints* 4→**5** (61 shapes for 59 classes — genuinely better than claimed).
- Five criteria held at their previous value: those assertions were correct, they had simply never been checked.

### ⚠️ What Phase 0 surfaced: 12 regulatory requirements rested on the fake gate

`PASS-STRUCTURAL` was not confined to the test report. Four regulation definitions gated requirements on `status in ('PASS','PASS-STRUCTURAL')`:

| Regulation | Requirements affected |
|---|---|
| EU AI Act | 3 of 6 — incl. `EU-AIA-13-2` (provenance of training/operational data), `EU-AIA-13-3` (confidence & derivation transparency) |
| HIPAA §164.312 | 3 of 7 — incl. `HIPAA-312-B-1` (audit controls, PROV-O attribution) |
| Basel IV / SR 11-7 | 3 of 8 — incl. `SR-11-7-PROV-1` (provenance of every model decision) |
| Ofcom network transparency | 3 of 7 |

Those requirements were being marked satisfied on the strength of competency-question tests that **returned zero rows**, and signed evidence bundles were generated from them (7 committed under `compliance/bundles/`). The dead status has been removed from all four regulation files; because the status can no longer be produced, those requirements now evaluate honestly.

**Measured impact.** The pre-fix behaviour was reproduced on a copy of the output tree (37 `FAIL` rows restored to `PASS-STRUCTURAL`, old `pass_expression` restored) and scored against the same engine:

| Regulation | Reported before | Honest now |
|---|---|---|
| Basel IV / SR 11-7 | **7/7 — 100%** | 4/7 — 57% |
| EU AI Act Art. 13 | **5/5 — 100%** | 2/5 — 40% |
| HIPAA §164.312 | **6/6 — 100%** | 3/6 — 50% |
| Ofcom network transparency | 5/6 — 83% | 2/6 — 33% |
| **Regulations at ≥80% coverage** | **4 of 4** | **0 of 4** |

The toolkit was reporting **100% regulatory coverage**, with three regulations at a perfect score, on the strength of tests that returned no rows. It now reports 33–57%. The governance criterion *Regulatory Evidence Coverage* correspondingly moved to **2/5** — "Only 0/4 regulations at ≥80% coverage — remediation required." Overall governance holds at **3.35/5.0**, still above the 3.0 CI gate.

**Action required beyond this branch:** the previously generated bundles asserted compliance on the old basis. They should be reviewed and, if they were ever shared externally, re-issued. This is a disclosure question, not just a code change.

---

## Phase 1 · Fix the broken artifacts ✅ **DELIVERED**

*Branch `phase0/ontology-quality-gates` · 2026-07-26*

| Metric | Before | After |
|---|---|---|
| `turtle_parse_failures` | 3 | **0** |
| `malformed_iris` | 20 | **0** |
| `alignment_subjects_unbound` | 37 | **1** |
| self-subclass axioms | 1 | **0** |
| `:EventTypeEvent` phantom class | present | **absent** |

All 23 emitted Turtle files parse. 43 of 44 alignment axioms now bind to an entity that actually exists (the one holdout, `refersToResource`, is listed in-file rather than emitted against a dangling IRI).

**Two corrections to the Phase 0 baseline, found while measuring this phase.** Both were flaws in my own gate, not in the toolkit:

1. **The gate counted three independent runs as one corpus.** `output/demo/` and `output/demo-5g/` are separate generations against different databases; folding them in counted each defect up to three times and made the metric depend on which demos happened to be on disk. CI generates exactly one run, so the baseline and CI would have measured different things. The gate now excludes nested run directories (identified by having their own `ontology/` subdir).
2. **The baseline was captured from a database polluted by prior phase runs.** Phases create their own tables (`tmf_*`, `runtime_*`, `log_*`), which later introspection picks up as domain classes — the live DB had 64 tables against 23 in `schema.sql`. The baseline is now taken after rebuilding via `setup_db()`, matching the CI path.

Net effect of both: the corpus is 23 files rather than 68, and the Phase 2/3/4 figures re-based accordingly (`multi_domain_properties` 131 → 105, `worst_domain_count` 48 → 43, `object_properties_ranged_at_thing` 21 → 14). Those are scope corrections, not improvements — the underlying defects are untouched and still owned by Phase 2.

> **Reproducibility note for later phases:** ontology content depends on which phases have previously run against the database, because phases create tables that subsequent introspection picks up. Re-baseline only from a clean `setup_db()` state.

**Goal:** everything the toolkit emits is well-formed and resolves.

| # | Defect | Fix | Where |
|---|---|---|---|
| 1.1 | **3 SKOS files fail to parse** — adjacent Turtle string literals in an f-string | join the strings in Python | [`jsonld_generator.py:240`](src/jsonld_generator.py:240) |
| 1.2 | **Space inside a prefixed name** — `"In Progress"` → `:StatusIn progress` | slugify on all non-alphanumerics before minting | [`jsonld_generator.py:282`](src/jsonld_generator.py:282) |
| 1.3 | **0 of 37 alignment subjects bind** — generator mints into `…/tmf/`, ontology lives in `…/enterprise/` | single source of truth for `BASE_IRI` (there are **seven** hardcoded copies across `alignment_generator`, `db_introspector`, `drift_detector`, `graph_publisher`, `rbac_generator`, `tmf_mapper`, `template_loader` — three different values among them) | [`alignment_generator.py:37`](src/alignment_generator.py:37) |
| 1.4 | **20 malformed alignment IRIs** — `<fhir:MedicinalProduct>`; the YAML prefix map is never read | read `external_alignments:`, expand to absolute IRIs | [`template_loader.py:186`](src/template_loader.py:186) |
| 1.5 | **Self-subclass cycle** — a `domain_events` table shadows the built-in class | namespace-guard built-ins, or detect and skip collisions | [`ontology_generator.py:176`](src/ontology_generator.py:176) |
| 1.6 | **Class minted from a header row** — `event_type = "event_type"` → `:EventTypeEvent` | filter discriminator values against the column name and known sentinels | [`ontology_generator.py:306`](src/ontology_generator.py:306) |

**Exit criteria**

- [ ] 68/68 `.ttl` files parse
- [ ] 37/37 alignment subjects resolve to entities that exist
- [ ] Zero IRIs with unregistered schemes or whitespace
- [ ] No class is its own superclass

**Effort:** small — these are mechanical. 1.3 is the only one needing a design decision (where the canonical namespace constant lives).

---

## Phase 2 · Soundness — stop asserting falsehoods ✅ **DELIVERED**

*Branch `phase0/ontology-quality-gates` · 2026-07-26*

| Metric | Before | After |
|---|---|---|
| `multi_domain_properties` | 105 | **0** |
| `worst_domain_count` | 43 | **0** |
| `object_properties_ranged_at_thing` | 14 | **0** |
| `owl:minCardinality` outside a restriction | 139 | **0** |
| unsound lifecycle `AllDisjointClasses` | present | **removed** |

**The soundness proof, re-run.** The same test that demonstrated the defect now returns the opposite result: loading one instance triple (`:t42 :hasCreatedAt "…"`) into the shipped ontology and running OWL-RL previously inferred **47 `rdf:type` assertions**; it now infers **0 spurious named types**, and correctly infers membership of the anonymous union-domain class — so the domain still constrains, it just no longer lies.

**Decision: union domain, not per-class property IRIs.** The roadmap originally specified minting `:Batch_expiryDate` per `(class, property)`. Measurement changed the answer: of 366 properties only 77 carried multiple domains, and the heaviest were generic audit columns — `hasCreatedAt` (43 classes), `hasName` (22), `hasDescription` (19). Fragmenting those into 43 separate `createdAt` properties would be worse modelling, not better, and would have churned 662 SHACL paths, 653 mapping rows, 372 context terms and the SPARQL suite. `rdfs:domain [ owl:unionOf (…) ]` is the standard OWL idiom for "used on any of these", is logically sound, and left every property IRI stable.

**What the fix actually required.** The root cause was structural: properties were emitted once per `(table, column)`, so each declaration carried its own `rdfs:domain` — and multiple domains conjoin. Emission is now grouped by property IRI in both the schema-driven generator and the industry-template generator, so each property is declared exactly once.

Three further sources surfaced only after the main fix, each found by re-measuring rather than by inspection:

- **Cross-module IRI collisions.** Industry templates declared an `ind:` prefix for their own namespace and never used it, minting every class and property into the shared enterprise namespace — so `expiry_date` from insurance, logistics and pharmaceuticals collided on one IRI carrying three domains. (This was roadmap item 3.5; it belongs here because it was a soundness cause.)
- **Within-module collisions.** The same property name used on several entities of one template, e.g. `product_id` across three pharmaceutical entities.
- **A hardcoded duplicate.** `_prov_patterns()` re-declared `:hasConfidenceScore` with `rdfs:domain :ObservationRecord`, adding a second domain axiom to a property the schema-driven generator already emits — so a confidence score on a `PerformanceIndicator` also made it an `ObservationRecord`.

**Other fixes in this phase.** Object-property naming stripped `_id`, `_org` and `_type` *anywhere* in a column name, collapsing `asset_type_id` and `asset_id` onto one `:assetOf` IRI with two unrelated domains and ranges; only a trailing `_id` is now stripped, giving `:assetType` and `:assetOf`. Unresolvable FK targets were written as `rdfs:range owl:Thing`, which asserts nothing while reading like a constraint — the range is now omitted and the unresolved target recorded in a comment. Lifecycle disjointness is no longer emitted at all: the candidate sibling groups are still computed and listed as comments for review, because asserting `AllDisjointClasses(Placed, Confirmed, Shipped, …)` makes any order that ships unsatisfiable.

Governance holds at **3.32/5.0**. Full suite: 1006 passed, 9 skipped, 1 xfailed.

**Phase 4 is now unblocked** — the hard gate this phase represented is cleared.

**Goal:** the ontology says only true things. **This is the hard gate for Phase 4.**

| # | Defect | Scale | Fix |
|---|---|---|---|
| 2.1 | **Conjunctive multi-domain properties** | **114 properties**; worst case 46 domains | Mint property IRIs **per `(class, property)`** — `:Batch_expiryDate` with a single `rdfs:domain :Batch` — and relate them to a shared abstract property via `rdfs:subPropertyOf`. This is the structural change the whole phase rests on. |
| 2.2 | **Unsound lifecycle disjointness** — `AllDisjointClasses(Placed, Confirmed, Shipped, Delivered, …)` | every event module | Remove. These are phases of one order; unless every transition is reified as a distinct individual, any order that ships is unsatisfiable. Re-introduce only where genuinely disjoint. |
| 2.3 | **Object-property name collapse** — `.replace("_id","")` maps `asset_type_id` and `asset_id` to one `:assetOf` | across modules | Derive the property name from the FK *target*, not the source column string. |
| 2.4 | **17 object properties with `rdfs:range owl:Thing`** | `enterprise.ttl` | Fail loudly when the FK target is outside the introspection set, rather than silently falling through. |
| 2.5 | **Cardinality on properties, not restrictions** | 139 triples | Remove the non-axioms now; the correct form arrives in Phase 3. Do not leave stray RDF in place. |

**Exit criteria**

- [ ] **0 properties with more than one `rdfs:domain`** (from 114)
- [ ] No `owl:AllDisjointClasses` over states of a single lifecycle
- [ ] 0 object properties ranged at `owl:Thing`
- [ ] No `owl:minCardinality` outside an `owl:Restriction`
- [ ] `ontology_diff.py` semantic-closure diff run against the Phase-1 output and reviewed — this change is large and the entailment delta should be inspected, not assumed

**Why this gates Phase 4:** 2.1 is invisible today because there is no instance data. This is not theoretical — it was demonstrated empirically ([Appendix B, Test 1](#appendix-b--impact-proofs)): loading **one** instance triple (`:ticket42 :hasCreatedAt "…"`) into the shipped ontology and running OWL-RL infers **47 `rdf:type` assertions** — the ticket becomes an Agent, an Agreement, an Alarm, an Asset, a CustomerBill, … simultaneously. Sequencing Phase 4 before Phase 2 poisons the joined graph with the very first record.

---

## Phase 3 · Expressivity — become actually OWL 2

**Goal:** a reasoner run produces at least one genuine classification.

| # | Work | Notes |
|---|---|---|
| 3.1 | **Emit real `owl:Restriction` blocks** | `:Agent rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :hasName ; owl:minCardinality 1 ]`. There is currently **no restriction-emitting code path at all** — this is new capability, not a fix. |
| 3.2 | **Populate the axiom metadata** | `ontology_generator.py:221-303` already reads `is_transitive`, `is_symmetric`, `is_inverse_functional`, `inverse_of`, `disjoint_group`, `has_key_columns`. **No shipped DB has those columns.** Infer them from schema shape: unique index → `owl:hasKey`; self-referencing FK → candidate `TransitiveProperty`; reciprocal FK pair → `owl:inverseOf`. |
| 3.3 | **Stop discarding the templates' own richness** | `generate_owl_module` iterates only `entities:`. Silently dropped: `events:` (with `is_event: true`), `relationships:` (with explicit cardinality prose), `values:` enumerations, and properly typed `idmp_alignments:` / `iec_cim_alignments:` with `match: equivalentClass\|closeMatch`. Generated modules have 8 classes and **0 subClassOf edges**. |
| 3.4 | **Close enumerations** | `regulatory_status: [PreClinical, Phase1, …]` currently becomes a bare `xsd:string`. Emit `owl:oneOf` or a SKOS `ConceptScheme`, plus SHACL `sh:in`. |
| 3.5 | **Per-module namespaces** | All five industry modules mint into one flat namespace → **16 measured property IRI collisions**. |
| 3.6 | **Real profile validation** | `_detect_owl_profile` is substring search over file text and always returns EL — itself wrong, since `AllDisjointClasses` is not in EL. Replace with an actual profile checker. |

**Feasibility check:** the exit criterion below needs no new tooling. A single well-formed `owl:Restriction` produces a genuine classification under the **same `owlrl` engine already in the repo's dependency chain** — demonstrated in [Appendix B, Test 2](#appendix-b--impact-proofs).

**Exit criteria**

- [ ] Reasoner closure contains ≥1 genuine classification (currently 0)
- [ ] Reflexive tautologies are no longer the majority of inferred triples (currently 2,207 / 3,425)
- [ ] Profile validator reports a real, correct profile
- [ ] Template modules emit their declared events, relationships, and enumerations
- [ ] 0 cross-module IRI collisions

---

## Phase 4 · The ABox — instance data and the Spine join

**Gated on Phase 2. Do not start earlier.**

**Goal:** the ontology describes actual instances, so the competency questions can return rows.

Ontomesh emits TBox only and has no path from rows to instances — no R2RML/RML/OBDA anywhere. Spine's PKG emits exactly the complement: RDF individuals with `file:line` provenance, in the **same namespace**, via an already-built `facts_to_graph`.

| # | Work | Side |
|---|---|---|
| 4.1 | `POST /api/facts` — accept RDF triples or the SQLite fact projection | Ontomesh |
| 4.2 | Ship generated SHACL shapes to Spine's `GroundingVerifier` — it runs `pyshacl` today but `shapes_path` defaults to `None`, so it returns `[]`. **Shipping shapes turns dead code into a live merge gate with zero Spine-side code.** | Ontomesh |
| 4.3 | Feed axiom signals from PKG structure into 3.2: `IMPLEMENTS` → subclass, reciprocal `REFERENCES` → `inverseOf`, unique constraints → `hasKey` | both |
| 4.4 | Re-point the CQ suite at the populated graph | Ontomesh |

**Exit criteria**

- [ ] CQ tests return **non-zero rows** (currently 43/43 return 0)
- [ ] SHACL validation runs against instances, not just shapes-on-disk
- [ ] `PASS-STRUCTURAL` is not merely deleted but *unnecessary*

**Prerequisite outside this file:** measure the code↔ontology mapping precision before building on the join. Spine maps by token Jaccard at a 0.3 floor and has never measured precision against a real ontology. Ontomesh can improve this materially — it already has 120 `skos:altLabel` synonyms and a `Mapping.resolve()` normalizer solving the same problem.

---

## Phase 5 · Depth — the modeling patterns

**Goal:** a domain model rather than a schema transliteration. These are absent entirely.

| # | Gap | Direction |
|---|---|---|
| 5.1 | **No temporal model.** Zero OWL-Time. No intervals, no Allen relations, no valid time, no transaction time, no bitemporality. | Adopt OWL-Time. Note the existing irony: `runtime/temporal_queries/TQ-03` is a bi-temporal SPARQL template with neither an engine to run it nor a vocabulary to run against. |
| 5.2 | **No units or quantity kinds.** Every measurement is a bare `xsd:decimal`. The only `unitOfMeasure` in the repo is a hardcoded string in a sample payload. | Adopt QUDT (or OM). |
| 5.3 | **No event participation.** One blunt `:hasParticipant (DomainEvent → Agent)`, no role reification. `:DomainEvent rdfs:subClassOf :DomainEntity` — so there is no occurrent/continuant split. | Reify participation; separate occurrents from continuants. |
| 5.4 | **Data-driven TBox.** Event subclasses are generated from `SELECT DISTINCT event_type` against live data, so the class hierarchy mutates when the data does. | Bind the discriminator to a closed SKOS scheme. |
| 5.5 | **No identity semantics.** Zero `owl:hasKey`, zero `InverseFunctionalProperty`. Business identifiers are plain strings. | Follows from 3.2. |

---

## Phase 6 · Governance maturity

**Goal:** the scorecard measures the ontology, and change is managed.

| # | Work |
|---|---|
| 6.1 | **OOPS!-style pitfall detection.** Zero of the 41 pitfalls are checked. P19 (multiple domains) fires 114 times, P11 (missing domain/range), P04 (unconnected elements), P30 (equivalences not explicit) are all directly measurable. |
| 6.2 | **Structural metrics** — depth, breadth, class/property ratio, inheritance richness, attribute richness. Cheap, and they make the scorecard defensible. |
| 6.3 | **Real versioning.** `VERSION = "1.0.0"` is a module constant — every regeneration emits 1.0.0 regardless of content. No `owl:priorVersion`, no `owl:backwardCompatibleWith`. Half the modules have no `versionIRI` at all. Wire `ontology_diff.py` (which already computes the delta) to drive the bump. |
| 6.4 | **Deprecation lifecycle.** The generator never marks anything deprecated and there is no tombstoning. `ontology_diff.py` reports removals; nothing records them in the artifact. |
| 6.5 | **Consistency checking that runs.** `find_unsatisfiable()` shells out to ROBOT, which isn't bundled — the scorecard self-reports 2/5 "ROBOT not found." |

---

## Risks

**Phase 2 is a large, wide-blast-radius change.** Re-minting every property IRI breaks every downstream SPARQL query, SHACL shape, and mapping CSV that references the old IRIs. Mitigation: run `ontology_diff.py`'s change-impact analysis (which already scans downstream SPARQL/SHACL/Cypher/GraphQL for IRI references) *before* the change, and treat its output as the migration checklist.

**Phase 0 turns the build red and it stays red.** This is intended but needs a decision up front: gate as blocking from day one, or report-only until Phase 2 closes.

**Phase 4 depends on an unmeasured join.** See the prerequisite note in Phase 4.

**Templates carry more meaning than the generator reads.** Phase 3.3 is not a bug fix — it will surface modeling decisions (cardinality, event typing, alignment match strength) that were authored in YAML and never reviewed because they never reached an artifact. Budget review time, not just build time.

---

## Appendix A · Verification commands

Every measurement in this document is reproducible from the repo root.

**Class expressions and cardinality form**
```bash
find output examples templates -name "*.ttl" | wc -l
grep -rl "owl:Restriction" output examples templates --include="*.ttl" | wc -l
grep -c "owl:minCardinality" output/ontology/enterprise.ttl
```

**Turtle well-formedness**
```bash
python3 -c "
import glob, rdflib
for f in sorted(glob.glob('output/**/*.ttl', recursive=True)):
    try: rdflib.Graph().parse(f, format='turtle')
    except Exception as e: print('FAIL', f, str(e).splitlines()[0])
"
```

**Reasoner output — tautology ratio**
```bash
python3 -c "
import rdflib
g = rdflib.Graph().parse('output/demo/ontology/enterprise-inferred.ttl', format='turtle')
print('total:', len(g), 'reflexive:', sum(1 for s,p,o in g if s==o))
"
```

**Multi-domain properties**
```bash
python3 -c "
import rdflib, glob
from collections import defaultdict
g = rdflib.Graph()
for f in glob.glob('output/ontology/*.ttl'):
    try: g.parse(f, format='turtle')
    except Exception: pass
d = defaultdict(set)
for s,p,o in g.triples((None, rdflib.RDFS.domain, None)): d[s].add(o)
multi = {k:v for k,v in d.items() if len(v)>1}
print(f'{len(multi)} of {len(d)} properties have >1 domain')
print('worst:', max(len(v) for v in multi.values()))
"
```

**Alignment binding rate**
```bash
python3 -c "
import rdflib
e = rdflib.Graph().parse('output/ontology/enterprise.ttl', format='turtle')
a = rdflib.Graph().parse('output/ontology/alignment.ttl', format='turtle')
es, asub = set(e.subjects()), set(a.subjects())
print('alignment subjects existing in enterprise:', len({s for s in asub if s in es}), 'of', len(asub))
"
```

**Competency-question gate**
```bash
python3 -c "
import csv
from collections import Counter
rows = list(csv.DictReader(open('output/reports/sparql_cq_test_results.csv')))
print(Counter(r['status'] for r in rows))
print('row_counts:', Counter(r['row_count'] for r in rows))
"
```

**Advanced-axiom metadata and resulting axioms**
```bash
python3 -c "
import sqlite3
for db in ['db/enterprise.db','db/demo.db','db/demo_5g.db']:
    cols = [r[1] for r in sqlite3.connect(db).execute('PRAGMA table_info(ontology_metadata)')]
    adv = [c for c in ('is_transitive','inverse_of','disjoint_group','has_key_columns') if c in cols]
    print(db, '->', adv or 'NO advanced axiom columns')
"
for c in owl:inverseOf owl:TransitiveProperty owl:hasKey owl:InverseFunctionalProperty; do
  echo "$c: $(grep -rho "$c" output --include='*.ttl' | wc -l)"
done
```

## Appendix B · Impact proofs

Run 2026-07-26 to validate that the two costliest fixes (Phases 2 and 3) are *impactful*, not merely correct.

**Test 1 — the multi-domain defect poisons the first instance loaded.**

```bash
python3 -c "
import rdflib, owlrl
g = rdflib.Graph().parse('output/ontology/enterprise.ttl', format='turtle')
NS = rdflib.Namespace('https://ontology.example.com/enterprise/')
g.add((NS.ticket42, NS.hasCreatedAt, rdflib.Literal('2026-07-25T10:00:00')))
owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
types = [o for o in g.objects(NS.ticket42, rdflib.RDF.type)
         if isinstance(o, rdflib.URIRef) and 'enterprise' in str(o)]
print(len(types))
"
```

Result: **1 asserted triple → 47 inferred `rdf:type` assertions** (Agent, Agreement, Alarm, Asset, AssetType, Attachment, Characteristic, ConflictEvent, CustomerAccount, CustomerBill, …). Justifies Phase 2 as a hard gate on Phase 4.

**Test 2 — one well-formed restriction yields a genuine classification with the existing toolchain.**

```bash
python3 -c "
import rdflib, owlrl
ttl = '''
@prefix : <https://x.com/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
:HighSeverityAlarm a owl:Class ;
  owl:equivalentClass [ a owl:Restriction ; owl:onProperty :hasSeverity ; owl:hasValue :Critical ] .
:alarm1 :hasSeverity :Critical .
'''
g = rdflib.Graph().parse(data=ttl, format='turtle')
owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
X = rdflib.Namespace('https://x.com/')
print((X.alarm1, rdflib.RDF.type, X.HighSeverityAlarm) in g)
"
```

Result: **`True`** — the classification fires under `owlrl`, which `materializer.py` already uses. Phase 3's exit criterion requires no new reasoner.

### Baseline (2026-07-25, `develop` @ 69d42c2)

| Metric | Value |
|---|---|
| `.ttl` files emitted / parsing | 68 / 65 |
| Files containing `owl:Restriction` | 0 of 70 |
| `owl:minCardinality` outside a restriction | 139 |
| Inferred triples / reflexive tautologies | 3,425 / 2,207 |
| Genuine classifications inferred | 0 |
| Properties with >1 `rdfs:domain` | 114 of 671 (worst: 46) |
| Alignment subjects binding | 0 of 37 |
| CQ tests passing / returning rows | 43 / 0 |
| `owl:inverseOf` · `TransitiveProperty` · `hasKey` · `IFP` | 0 · 0 · 0 · 0 |
