# Ontomesh / Ontoforge — Project Overview

*v3.10.0 · 2026-07-26 · `main` @ `c3266b5` · published as `ontoforge` on PyPI*

---

## What this is

A toolkit that turns **the systems you already run** — a relational schema, application
logs — into a **formal, machine-checkable model of what your data means**, and then uses
that model to constrain what an LLM is allowed to say about it.

Two halves, and the second is the point of the first:

1. **Derive an ontology** from evidence rather than from a whiteboard. Tables become OWL
   classes, foreign keys become typed relations, discriminator columns become defined
   classes a reasoner can classify into, `UNIQUE` constraints become identity axioms.
2. **Ground an LLM in it.** The ontology supplies a controlled vocabulary, a sensitivity
   ceiling, a validation gate, and a provenance chain — so an answer either cites real
   records or declines.

An LLM pointed at a database can say anything. An LLM pointed at a database *through an
ontology* can only say things the ontology has terms for, about data it is cleared to
read, in a shape the shapes accept — and it has to show its work.

---

## Install

```bash
pip install ontoforge                 # library + CLI
pip install 'ontoforge[wizard]'       # + the browser wizard
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:3.10.0
```

Python 3.10+. Apache-2.0.

## Sixty-second run

```bash
python toolkit.py --phase all --db db/enterprise.db --out output
python scripts/ontology_gate.py
```

The first builds everything — ontology, shapes, instance data, quality report. The
second tells you whether the result got worse than the last agreed state.

---

## What you get

| Artifact | What it is |
|---|---|
| `ontology/enterprise.ttl` | OWL 2 DL TBox — classes, properties, restrictions, keys |
| `ontology/events.ttl` | Event subclasses as **defined classes** (reasoner-classifiable) |
| `ontology/provenance.ttl` | PROV-O profile — Entity / Activity / Agent roles |
| `ontology/dimensions.ttl` | Time (bitemporal), quantity (QUDT), participation |
| `ontology/instances.ttl` | **ABox** — individuals from your rows, tier-gated |
| `shapes/enterprise-shapes.ttl` | SHACL constraints, one NodeShape per class |
| `shapes/agent-gate.ttl` | The acceptance gate an LLM's output must pass |
| `jsonld/enterprise-context.json` | JSON-LD context — field names → ontology IRIs |
| `jsonld/mcp-tool-definitions.json` | MCP tools carrying `x-ontology-class`, `x-shacl-gate` |
| `mapping/logical_physical_map.csv` | Class→table, property→column. **Editable** — this steers materialisation |
| `reports/ontology_quality.csv` | Pitfalls, structural metrics, consistency |

---

## Capabilities

### Modelling

- **OWL 2 DL** — 244 `owl:Restriction` class expressions; defined classes via
  `owl:equivalentClass` so a reasoner *classifies* rather than merely parses
- **Identity semantics** — `owl:hasKey` derived from `UNIQUE` constraints
- **Bitemporality** — valid time (when a fact was true) kept distinct from transaction
  time (when you recorded it). This is what makes as-of questions answerable.
- **United quantities** — a magnitude and its unit are one object, so `15` is never
  ambiguous between milliseconds and megawatts
- **Reified participation** — *who* took part and *in what role*, not merely that they did
- **Provenance** — `Entity → Activity → Agent` chains that traverse, not flat foreign keys
- **Deprecation lifecycle** — removed terms become `owl:deprecated` tombstones so held
  IRIs still resolve

### Discovery

Drain3 log-template clustering with an EM merge refinement · PMI entity co-occurrence ·
per-service HMM trajectory anomalies · Granger causality and transfer entropy, gated by
a triangulation rule (three independent signals must agree; failures *downgrade* rather
than vanish) · Gaussian-process rate anomalies.

### Governance

- **A CI ratchet** over 15 measurable artifact properties, compared against a committed
  baseline. Fails on *regression*, not on the existence of known debt.
- **OOPS!-style pitfall detection** — 10 checks computed from the graph
- **Consistency** — unsatisfiable-class detection via `owlrl`, in-process, no external binary
- **36 governance criteria**, none hardcoded — each reads the artifact it makes a claim about

### Integration

6 database backends (SQLite, Postgres, MySQL, MSSQL, Oracle, DB2) · 5 LLM adapters
(Anthropic, OpenAI, Vertex, Ollama, OCI) · FAISS and Chroma vector stores · Fuseki,
Stardog, Oxigraph, Neptune, GraphDB publishing · 10 industry starter templates.

---

## Grounding an LLM in the ontology

This is the part that matters. Four mechanisms, each closing a different failure mode.

### 1. The vocabulary is a fence, not a suggestion

A *flavor* (`runtime/flavors/*.json`) is a declarative domain slice: which OWL classes
are in scope, which JSON-LD terms name them, **which database tables may be touched**,
and the sensitivity ceiling.

The planner is given only that vocabulary. A question it cannot express in those terms
does not become a creative SQL query — it returns `status: "ungrounded"`.

```python
from runtime.reasoning_search import search

answer = search("Which assets have low-confidence observations?",
                flavor="network-ops", db="db/enterprise.db",
                max_tier="Internal")
```

### 2. Sensitivity tiers gate what the model can see

Every class and property carries `:sensitivityTier` — `Public`, `Internal`,
`Confidential`, `Restricted` — and so does every materialised individual. The ceiling is
enforced in three places:

- **At materialisation** — the ABox is a *copy* of your data in a portable file, so
  columns above `--max-tier` are never written. `Restricted` is excluded by default.
- **At query compile** — columns above the caller's ceiling are dropped from the
  projection; a *filter* on one is refused outright.
- **Fail-closed** — an unknown or missing tier ranks most restrictive.

The model never sees the withheld column, so it cannot leak it, quote it, or infer from it.

### 3. SHACL gates run on both sides

Input is validated before it reaches the prompt; output is validated before it reaches
your system. `agent-gate.ttl` is the acceptance shape — an LLM response that fails it is
marked invalid rather than acted on.

### 4. Citations point at real records, and lineage is traversable

A grounded answer is not prose. It is a `ReasonedAnswer`:

```
answer           the text
plan             what it decided to look at, in ontology terms
executed_query   the exact read-only SQL that ran
results          the rows that came back
citations        IRIs of the records used
inferred         facts derived by the reasoner, each with the rule and its inputs
confidence       a score
trace            plan → execute → relations → reason → synthesize
status           ok | blocked | ungrounded | empty
```

Because the ABox carries PROV-O chains, a citation is not a dead reference — you can walk
it:

```sparql
SELECT ?obs ?agent WHERE {
  ?obs a :ObservationRecord ; prov:wasGeneratedBy ?activity .
  ?activity prov:wasAssociatedWith ?agent .
}
```

*Who* produced the fact the model cited, and *when*, is a query rather than a guess.

### What this actually prevents

| Failure mode | What stops it |
|---|---|
| Inventing an entity or attribute | The planner is confined to the flavor's controlled vocabulary |
| Reading data it shouldn't | Tier gating at materialisation and at compile, fail-closed |
| Writing anything | Read-only SQL: allow-listed tables, parameterised values, `PRAGMA query_only` |
| Confident nonsense on no data | `status: empty` / `ungrounded` instead of prose |
| Unverifiable claims | Citations name records; inferred facts name the rule that derived them |
| Silent schema drift | The evolution/drift loop proposes ontology changes for human review |
| Malformed output | SHACL acceptance gate |

### Why the ontology has to be *correct* for this to mean anything

This is the lesson of the v3.10.0 work. Grounding an LLM in a broken ontology is worse
than not grounding it, because the output looks rigorous.

Before this release, loading **one** instance triple and running a reasoner inferred
**47 `rdf:type` assertions** — a trouble ticket was simultaneously an Agent, an Alarm, an
Asset and 44 other things, because 114 properties carried conjunctive multi-domain
axioms. Any LLM grounded in that would have cited its way to nonsense with perfect
provenance.

The same test now infers **zero** spurious types. That is the difference between a
citation that means something and a citation that merely exists.

---

## How to use it, in the order that works

**1. Point it at a database.**

```bash
python toolkit.py --phase all --db db/enterprise.db --out output
```

**2. Read the mapping workbook.** `output/mapping/logical_physical_map.csv` is the
contract between your schema and the ontology — class→table, property→column, sensitivity
tier. It is generated, and it is **editable**. Editing it is the supported way to steer
what gets modelled and materialised.

**3. Check the semantic-loss report.** `output/mapping/semantic_loss_report.csv` names
places where the physical schema flattened meaning — a status column that is really an
event, an implicit actor, an overloaded type column. These are the highest-value modelling
decisions and they need a human.

**4. Look at the quality report.** `output/reports/ontology_quality.csv` — pitfalls,
depth, richness, consistency. Depth of 1 means a flat list; 0 restrictions means nothing
can be reasoned over.

**5. Wire an LLM.** Pick or write a flavor, set the tier ceiling, enable search:

```bash
export ONTOFORGE_SEARCH=1
ontoforge search "which assets are degraded?" --flavor network-ops --max-tier Internal
```

**6. Put the gate in CI.** `python scripts/ontology_gate.py` fails when the artifact
regresses. Update the baseline in the same commit as any change that justifies it —
never to make a red build green.

---

## Honest limitations

Stated plainly, because a grounding layer that oversells itself is the thing it was built
to prevent.

- **Reasoning Search ships behind `ONTOFORGE_SEARCH` (default-off)** and is a linear
  plan→execute→synthesize pipeline, not an agent loop. SQL is single-table; multi-hop is
  approximated by one hop of foreign-key neighbours.
- **The Datalog reasoner takes caller-supplied rules and is reachable only from the
  Python SDK.** Neither the CLI nor the HTTP route passes `rules=`, so in those surfaces
  "reasoning" is gated SQL plus an LLM summary.
- **No route-level authentication.** Tier gating assumes an authenticated gateway in front.
  This is the remaining reason not to expose the search endpoints directly.
- **Qdrant, Weaviate and pgvector adapters are filter translators, not clients.** The
  default embedder is a bag-of-words hash, not a semantic model — check your flavor's
  `embedding.model` before trusting similarity.
- **17 of 58 demo tables are empty**, so 33 of 43 competency questions cannot pass. That
  is a fixture gap, not a modelling one, but it means the demo understates what the
  pipeline does on populated data.
- The ontology is **OWL 2 DL** (union domains put it outside EL), so ELK will not fully
  classify it — use HermiT, or the bundled `owlrl` for the RL profile.

---

## Where to look next

| Question | File |
|---|---|
| What does the ontology actually contain? | [`docs/concepts/ontology-model.md`](docs/concepts/ontology-model.md) |
| How do the quality gates work? | [`docs/reference/quality-gates.md`](docs/reference/quality-gates.md) |
| What is each output file for? | [`docs/artifacts.md`](docs/artifacts.md) |
| Which phase does what? | [`docs/concepts/pipeline.md`](docs/concepts/pipeline.md) |
| How was the current state reached? | [`ONTOLOGY_ROADMAP.md`](ONTOLOGY_ROADMAP.md) |
| What changed in this release? | [`CHANGELOG.md`](CHANGELOG.md) |

---

## Outstanding, non-code

Twelve regulatory requirements across the EU AI Act, HIPAA §164.312, Basel IV/SR 11-7 and
the Ofcom transparency code were previously marked satisfied by competency-question tests
that returned **zero rows**. Reported coverage was 100%; honest figures are 33–57%. Seven
signed evidence bundles under `compliance/bundles/` were generated on the old basis. The
correction is published in the CHANGELOG and the `v3.10.0` tag. **Whether any of those
bundles reached a third party remains to be confirmed.**
