# Quality gates

How the toolkit checks its own output, what each signal means, and what to do
when one goes red.

There are three layers, and they answer different questions:

| Layer | Question | Command | Blocks CI? |
|---|---|---|---|
| **Artifact gate** | Did the ontology get *worse*? | `python scripts/ontology_gate.py` | Yes, on regression |
| **Quality report** | What is wrong with it *now*? | `python toolkit.py --phase quality` | No — it informs |
| **Governance scorecard** | How mature is it overall? | `python toolkit.py --phase test` | Yes, below 3.0 |

---

## 1. The artifact gate — a ratchet

```bash
python scripts/ontology_gate.py
```

```
    metric                                  baseline   current   owner
    -------------------------------------- --------- ---------   --------
    turtle_parse_failures                          0         0   Phase 1
    multi_domain_properties                        0         0   Phase 2
    owl_restrictions                             244       244   Phase 3
    cq_tests_returning_rows                        5         5   Phase 4
    temporal_extents                              22        22   Phase 5
    pitfalls_firing                                3         3   Phase 6

  ✓ Ontology gate passed — no regression against baseline.
```

The gate measures the emitted graph and compares it against
`ontology_baseline.json`. Each metric declares a direction — some should go down
(parse failures, unsound axioms), some should go up (restrictions, instance data).

**It fails only on regression.** It does not fail merely because debt exists.
A build held permanently red by known problems trains everyone to ignore CI,
which recreates the problem it was meant to solve.

### When it fails

```
  ✗ Ontology gate FAILED — the artifact regressed:

      • turtle_parse_failures: 0 -> 3 (regressed; lower is better)
      • owl_restrictions: 244 -> 190 (regressed; higher is better)
```

Read it as *"your change made this worse than the last agreed state."* Two valid
responses:

1. **Fix the regression.** Usually the right answer.
2. **Accept it deliberately** — if the change is intended and understood, update
   the baseline **in the same commit** so a reviewer sees both:

```bash
python scripts/ontology_gate.py --update-baseline
```

!!! warning "Never raise a `lower_is_better` number to go green"

    Updating the baseline to hide a regression is the one thing this tool cannot
    protect you from. The baseline is committed precisely so that loosening it
    shows up in review.

### Two failures are unconditional

Regardless of baseline, these always fail:

- **A Turtle file that does not parse.** An unusable artifact is never acceptable.
- **A SPARQL query that ERRORs.** It is malformed or targets vocabulary that does
  not exist.

A query that *FAILs* — returns no rows — is ratcheted rather than hard-blocked,
because how many questions your data can answer depends on how much data you have.

### Machine-readable output

```bash
python scripts/ontology_gate.py --json > metrics.json
```

`stdout` is JSON only; the human verdict goes to `stderr`, so both are usable in
a pipeline.

---

## 2. The quality report

```bash
python toolkit.py --phase quality --db db/enterprise.db --out output
```

```
  ✓ Ontology quality      → output/reports/ontology_quality.csv
    Pitfalls checked: 10  |  firing: 3  |  critical: 0
      MEDIUM   P04 Unconnected ontology elements: 1
      HIGH     P11 Missing domain or range: 17
      MEDIUM   P41 No licence declared: 5
    Depth 3  |  inheritance richness 1.0  |  attribute richness 4.77
    Consistency (owlrl): consistent
```

### Pitfalls

Ten checks from the [OOPS!](https://oops.linkeddata.es/) catalogue, restricted to
those computable from the graph alone — no external service.

| ID | Title | Severity | What it means |
|---|---|---|---|
| `P04` | Unconnected ontology elements | MEDIUM | A class nothing references and that sits in no hierarchy |
| `P07` | Distinct classes sharing one label | MEDIUM | Two classes probably modelling one concept |
| `P08` | Missing annotations | LOW | No `rdfs:label` — unusable in a picker or a report |
| `P11` | Missing domain or range | HIGH | A property that constrains nothing |
| `P13` | No inverse declared | LOW | Relations only traversable one way |
| `P19` | Multiple domains (conjunctive) | **CRITICAL** | Domains intersect, so instances classify into everything at once |
| `P24` | Recursive definition | **CRITICAL** | A class that is its own superclass |
| `P30` | Identical signatures, no equivalence | LOW | Probably the same concept, not declared so |
| `P35` | Untyped class as domain or range | MEDIUM | Referenced but never declared |
| `P41` | No licence declared | MEDIUM | Consumers cannot tell what they may do with it |

**A firing pitfall is not automatically a bug.** `P11` fires on properties that
deliberately carry no domain — semantic aliases must not add a second
`rdfs:domain`, because domains conjoin. Read the offenders before acting.

### Structural metrics

| Metric | Reading it |
|---|---|
| `max_depth` | 1 means a flat list. 3+ is a real taxonomy. |
| `inheritance_richness` | Mean subclass edges per class. Below ~1 is flat. |
| `attribute_richness` | Mean data properties per class. |
| `restrictions` | Class expressions. **0 means nothing can be reasoned over.** |
| `defined_classes` | Classes with `owl:equivalentClass` — the ones a reasoner can classify *into*. |

### Consistency

Unsatisfiable classes, computed with `owlrl` in-process. A class is unsatisfiable
when the closure makes it a subclass of `owl:Nothing` — nothing can ever be an
instance of it, which usually means contradictory axioms.

No external binary is needed. (`--phase reasoner` still shells out to ROBOT for a
fuller DL check if you have it installed.)

---

## 3. The governance scorecard

```bash
python toolkit.py --phase test --db db/enterprise.db --out output
```

Writes `output/reports/governance_scorecard.csv` — 36 criteria, each scored 0–5
with a rationale naming the evidence.

CI enforces a floor of **3.0** and warns below **4.0**.

!!! note "Every criterion is computed"

    Criteria used to include score literals that returned 4/5 on every run
    regardless of output. They now read the artifact they make a claim about: a
    criterion asserting SKOS separation parses the SKOS file, and scores 0 if it
    does not parse.

---

## Competency questions

```bash
python toolkit.py --phase sparql --db db/enterprise.db --out output
```

Runs `tests/sparql/CQ-*.sparql` against the generated graph and writes
`output/reports/sparql_cq_test_results.csv`.

!!! warning "A question that returns nothing has not been answered"

    A zero-row result used to be scored as a pass whenever the ontology was
    TBox-only, so all 43 tests passed while every one returned nothing. That
    verdict is gone. If a question returns no rows, either your data does not
    contain the answer or the query targets vocabulary that is not there — both
    worth knowing.

Most remaining failures are **missing data**, not modelling defects: a question
about federation cannot pass if no federation rows exist. Run `--phase abox`
first, or the suite has only a schema to query.

---

## Putting it together in CI

The bundled workflow (`.github/workflows/ontology.yml`) runs, in order:

1. **generate** — phases 1–5, TMF, **abox**, **quality**
2. **artifact-gate** — the ratchet (blocking)
3. **reasoner** — ROBOT consistency, if available
4. **sparql-cq** — errors block; failures are ratcheted
5. **governance** — scorecard threshold (blocking)
6. **report** — the HTML summary

A minimal local equivalent before you push:

```bash
python toolkit.py --phase all --db db/enterprise.db --out output
python scripts/ontology_gate.py
```
