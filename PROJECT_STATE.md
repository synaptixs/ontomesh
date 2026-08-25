# Ontomesh / Ontoforge — Project Overview

*v3.10.1 · 2026-07-26 · `main` @ `342e209` · published as `ontoforge` on PyPI*

> **For the team:** start with [What this is](#what-this-is) and
> [What this gives an engineering team](#what-this-gives-an-engineering-team). The rest is
> reference.

---

## What this is

A toolkit that turns **the systems you already run** — a database schema, application
logs — into a **formal model of what your data means**, and then uses that model to
control what an LLM is allowed to say about it.

Two halves, and the second is the point of the first:

1. **Build an ontology from evidence**, not from a whiteboard. Tables become classes,
   foreign keys become typed relationships, status columns become categories a reasoner
   can sort records into, `UNIQUE` constraints become "this identifies the thing".
2. **Ground an LLM in it.** The ontology gives the model a fixed vocabulary, a limit on
   what data it may read, a validation gate on its output, and a citation trail — so an
   answer either points at real records or admits it can't answer.

The one-line version:

> An LLM pointed at a database can say anything. An LLM pointed at a database *through an
> ontology* can only say things the ontology has words for, about data it's cleared to
> read — and it has to show its sources.

### What it is not

Not a vector database, not an agent framework, not a replacement for your LLM stack. It's
the **semantic layer underneath** them — the thing that says what your fields mean, who
may see them, and how to prove where an answer came from.

---

## What this gives an engineering team

If several teams are building different AI features on the same data, these are the
problems this solves. Each one is a real failure mode, not a hypothetical.

### "Every team invents its own field meanings"

Team A's chatbot thinks `status` means order state. Team B's ops assistant thinks it
means device health. Both are querying the same column. Nobody notices until the answers
disagree in front of a customer.

**What you get:** one generated JSON-LD context (`jsonld/enterprise-context.json`) that
maps field names to shared IRIs. Any service that loads it interprets `status` the same
way. The vocabulary is generated from the schema, so it stays in step with the database
rather than drifting in a wiki.

### "What stops the model reading data it shouldn't?"

The usual answer is a prompt instruction, which is not a control.

**What you get:** every class and field carries a sensitivity tier — `Public`,
`Internal`, `Confidential`, `Restricted`. The ceiling is enforced in three places: when
instance data is written, when a query is compiled, and when related records are pulled
in. Unknown tier means most-restrictive. The model never receives the withheld column, so
it can't quote or infer from it.

You can show an auditor a table instead of writing a memo.

### "Why did it say that?"

**What you get:** a grounded answer isn't just text. It carries the plan, the exact
read-only SQL that ran, the rows returned, citations pointing at specific records, and any
derived facts with the rule that produced each. Because instance data carries PROV-O
chains, *who* produced a cited fact and *when* is a query:

```sparql
SELECT ?obs ?agent WHERE {
  ?obs a :ObservationRecord ; prov:wasGeneratedBy ?activity .
  ?activity prov:wasAssociatedWith ?agent .
}
```

That turns "why did the AI say that" from an investigation into a lookup.

### "Our agents can't agree on a tool contract"

**What you get:** MCP tool definitions that carry `x-ontology-class` and `x-shacl-gate`.
A tool contract stops being a bare JSON schema and starts saying what the fields *mean*
and what a valid response looks like. Two agents built by two teams interpret the same
tool identically.

### "The schema changed and the AI quietly started being wrong"

**What you get:** drift detection over both schema and logs, surfacing changes as
*proposals for human review* rather than silently reshaping the model. New log templates,
changed distributions and new entity candidates all land in a review queue.

### "We can't tell if our ontology is any good"

**What you get:** a quality report — pitfall checks, structural metrics, consistency —
plus a CI gate that fails when the artifact gets *worse* than an agreed baseline. It does
not fail merely because known debt exists; that would train everyone to ignore it.

```bash
python scripts/ontology_gate.py
```

### "We're spread across several AI projects and want them to interoperate"

This is the compounding one. A retrieval service, a support assistant and an anomaly
triage bot built independently will each build their own idea of the domain. Point them at
one ontology and they share meaning by construction — the same classes, the same field
IRIs, the same sensitivity rules, the same citation format. Integration stops being a
mapping exercise.

### Where it fits in a stack

```
   your AI features        chatbot · agent · RAG service · triage bot
          │
   ── grounding ──         vocabulary · tier ceiling · SHACL gate · citations
          │
   Ontomesh ontology       classes · relationships · shapes · provenance
          │
   your systems            database · application logs
```

---

## Install

```bash
pip install ontoforge                 # library + CLI
pip install 'ontoforge[wizard]'       # + the browser wizard
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:3.10.1
```

Python 3.10+. Apache-2.0.

## Sixty-second run

```bash
python toolkit.py --phase all --db db/enterprise.db --out output
python scripts/ontology_gate.py
```

The first builds everything — ontology, shapes, instance data, quality report. The second
tells you whether the result got worse than the last agreed state.

---

## What you get

| Artifact | What it is |
|---|---|
| `ontology/enterprise.ttl` | The schema of meaning — classes, properties, constraints, keys |
| `ontology/events.ttl` | Event types a reasoner can sort records into |
| `ontology/provenance.ttl` | Who-did-what-when structure (PROV-O) |
| `ontology/dimensions.ttl` | Time, units, participation roles |
| `ontology/instances.ttl` | Your actual rows as data the model can cite — tier-gated |
| `shapes/enterprise-shapes.ttl` | Validation rules, one per class (SHACL) |
| `shapes/agent-gate.ttl` | The gate an LLM's output must pass before you act on it |
| `jsonld/enterprise-context.json` | Shared field-name → meaning map for services |
| `jsonld/mcp-tool-definitions.json` | Agent tools carrying their ontology class and gate |
| `mapping/logical_physical_map.csv` | Class→table, field→column. **Editable** — this is how you steer it |
| `reports/ontology_quality.csv` | Pitfalls, structural metrics, consistency |

---

## Capabilities

### Modelling

- **OWL 2 DL** — 244 real class expressions, so a reasoner *classifies* records rather
  than just parsing a file
- **Identity** — `owl:hasKey` from `UNIQUE` constraints: "these two records are the same thing"
- **Time, done properly** — when a fact was *true* kept separate from when you *recorded*
  it, which is what makes "what did we believe last March?" answerable
- **Units attached to numbers** — `15` is never ambiguous between milliseconds and megawatts
- **Roles in relationships** — *who* took part and *in what capacity*, not just that they did
- **Provenance you can walk** — Entity → Activity → Agent, not a flat foreign key
- **Deprecation** — removed terms become tombstones, so old IRIs still resolve

### Discovery — machine learning over your logs

See [Finding the model in your logs](#finding-the-model-in-your-logs) below for how this
works and what you're asked to decide.

### Governance

- **CI ratchet** over 15 measurable properties against a committed baseline
- **10 pitfall checks** (OOPS!-style) computed from the graph
- **Consistency checking** in-process via `owlrl` — no external reasoner binary needed
- **36 governance criteria**, none hardcoded — each reads the artifact it judges

### Integration

6 databases (SQLite, Postgres, MySQL, MSSQL, Oracle, DB2) · 5 LLM adapters (Anthropic,
OpenAI, Vertex, Ollama, OCI) · FAISS and Chroma · publishing to Fuseki, Stardog, Oxigraph,
Neptune, GraphDB · 10 industry starter templates.

---

## Finding the model in your logs

A database schema tells you what your system *stores*. Your logs tell you what it
actually *does* — which things exist, how they relate, and what happens to them. That
information is real but unlabelled, so this uses statistics to propose candidates and
then asks a human to decide.

**Nothing here writes to your ontology automatically.** Every finding becomes a
*proposal* in a review queue. You approve, reject or merge it. That is the design: the
maths is good at spotting patterns and bad at knowing which ones mean something.

### Step 1 — Turn log lines into templates

Millions of lines collapse into a few hundred shapes. `Order 4821 shipped to LON` and
`Order 9134 shipped to NYC` are the same event with different values.

Drain3 does the clustering, then a refinement pass merges near-duplicate templates that
differ only slightly (edit distance), so you don't review the same thing five times.

**Output:** a template catalogue with hit counts.

### Step 2 — Work out what the variable parts *are*

Each varying slot in a template gets classified by looking at the values it takes. A
majority vote (≥80% agreement) across a regex ladder assigns one of:

`IRI` · `IP` · `UUID` · `ENUM` · `NUMERIC` · `HEX` · `FREETEXT`

This is what separates an **entity reference** from an **attribute**. A slot full of
UUIDs is a thing that exists elsewhere in your system; a slot full of free text is a
description. That distinction becomes object-property vs data-property in the ontology.

Slots are also flagged for **PII risk**, which feeds the sensitivity tier.

**Output:** candidate entities, typed, with a risk flag.

### Step 3 — Find which entities belong together

Two entities are related if they co-occur more than chance explains. The measure is
**pointwise mutual information**:

```
PMI(x,y) = log₂  p(x,y) / (p(x)·p(y))
```

Co-occurrence means sharing a trace ID, or appearing inside the same short time window.
The threshold (τ = 2.0) was chosen from a sweep recorded in the source, not picked by
feel — the table shows edges found and noise admitted at each candidate value.

**Output:** candidate relationships, scored.

### Step 4 — Work out direction, and admit when you can't

If A reliably appears before B, the relationship probably points A → B. The lead-ratio
test has **three** outcomes, not two:

- **Directed** — A consistently leads B
- **Flipped** — the reverse holds
- **Ambiguous** — neither dominates, so the edge is left **undirected and flagged for
  review**

That third case matters. Guessing a direction produces a confident wrong model; leaving
it undirected produces an honest question.

### Step 5 — Separate correlation from causation

Two independent statistical tests, run separately:

- **Granger causality** — does knowing A's past improve prediction of B, beyond B's own past?
- **Transfer entropy** — how much information flows A → B, validated against a permutation
  null (100 shuffles) so a z-score says whether it beats chance

Then a **triangulation rule**: an edge is proposed as *causal* only if co-occurrence,
timing and at least one causality test all agree. An edge that fails is **not deleted** —
it is downgraded to a plain relationship. You still see it; it just doesn't claim more
than the evidence supports.

**Output:** candidate causal rules, with the statistics attached.

### Step 6 — Learn normal behaviour, so abnormal stands out

- **Per-service hidden Markov models** learn the usual sequence of states. The number of
  states is chosen by BIC rather than guessed. Trajectories that fall below a likelihood
  threshold are flagged, and the least likely transition is recorded as the **root-cause
  anchor** — the point where things went wrong.
- **A variational Bayesian HMM** produces *calibrated* confidence from the posterior
  rather than a fixed floor, so "80% confident" is a claim you can act on.
- **Gaussian-process rate models** learn each template's normal volume, including its
  daily cycle, and flag deviations outside a 99% interval — in **both** directions, so a
  process that goes suspiciously quiet surfaces alongside one that floods.

**Output:** anomalies with a time, a confidence, and a root-cause anchor.

### Step 7 — You decide

Everything above lands in a review queue as one of three proposal kinds:

| Kind | What it's claiming |
|---|---|
| `LOG_ENTITY` | "This looks like a thing in your domain" |
| `LOG_EVENT` | "This looks like something that happens" |
| `LOG_RELATIONSHIP` | "These two look connected" (with direction, or flagged ambiguous) |

Each carries its evidence — hit counts, PMI score, causality statistics, sample lines —
so you're judging a case, not a verdict. In the wizard's Log Discovery step, or via the
API:

```
GET  /api/log-discovery/candidates          # what was found, ranked
POST /api/log-discovery/<id>/approve        # becomes part of the ontology
POST /api/log-discovery/<id>/reject
POST /api/log-discovery/<id>/merge          # same thing under two names
```

Approved proposals become classes, relationships and event types in the generated
ontology, and from there they constrain what an LLM can say — which closes the loop from
raw log line to grounded answer.

### Try it — a five-minute demo

Real commands, real output. Everything below was run against a 400-line sample log.

**1. Point it at a log folder.** JSONL, syslog, CEF and OTLP are auto-detected; a folder,
a glob or a single file all work.

```bash
python toolkit.py --phase mine \
  --db db/enterprise.db --out output \
  --log-path ./demo-logs
```

```
  Phase L1: Log Mining — Templates · Slot Typing · PMI Graph
  ──────────────────────────────────────────────────────────
  ↪ corpus: 1 file(s) under ./demo-logs
  ✓ records ingested         400
  ✓ templates                  4  (after EM merge: 4, merges: 0)
  ✓ slots profiled             8
  ✓ entity edges              15
  ✓ proposals seeded          24  (event=4 entity=5 rel=15 causal=0)
  ✓ summary               → output/reports/log_mining_summary.json
```

**2. See the templates it found.** 400 lines collapsed to 4 shapes, with the variable
parts marked `<*>`:

```
   200x  [ran /WARN ]  PRB utilisation high on <*> <*> at 91 percent
   200x  [ran /ERROR]  Throughput degraded on <*> <*> to 12 Mbps
   200x  [oss /ERROR]  Alarm raised <*> for <*> severity MAJOR
   200x  [oss /INFO ]  Ticket <*> opened for <*>
```

**3. See how it classified the variable parts:**

```
  ENUM        5 slots   pii_risk=0
  FREETEXT    3 slots   pii_risk=0
```

`ENUM` slots become entity candidates; `FREETEXT` becomes attributes. A `pii_risk` count
above zero would raise the sensitivity tier on whatever those slots produce.

**4. See the relationships, and where it declined to guess:**

```
  cell-C3    — gnb-042    pmi=3.82  n=241  lead=0.53
  cell-B2    — gnb-041    pmi=3.79  n=316  lead=0.51
  cell-B2    — gnb-043    pmi=3.79  n=310  lead=0.49
  gnb-041    — gnb-042    pmi=3.78  n=413  lead=0.50
```

Strong co-occurrence (PMI ≈ 3.8 over hundreds of observations), but every lead ratio sits
at ~0.50 — neither side reliably precedes the other. So every edge came back **undirected**
(`—` rather than `→`) and goes to review as an open question rather than an invented
direction. This is step 4 doing its job on data that genuinely has no ordering.

**5. Learn normal behaviour and flag what isn't:**

```bash
python toolkit.py --phase sequence \
  --db db/enterprise.db --out output \
  --log-path ./demo-logs
```

```
  Phase L2: Sequence Learning — Trajectories · HMM · Anomalies
  ──────────────────────────────────────────────────────────
  ✓ trajectories          2
  ✓ services fit          2
  ✓ anomalies             1
  ✓ proposals             1
```

**6. Look at what you're being asked to decide:**

```
  type                conf  title
  LOG_EVENT           1.00  Event template #1: PRB utilisation high on <*> <*> a…
  LOG_EVENT           1.00  Event template #2: Throughput degraded on <*> <*> to…
  LOG_EVENT           1.00  Event template #3: Alarm raised <*> for <*> severity…
  LOG_ENTITY          1.00  Entity candidate :PRBCode (ENUM)
  LOG_ENTITY          1.00  Entity candidate :ThroughputCode (ENUM)
```

All 24 sit at `status = PENDING` until somebody rules on them:

```
  LOG_RELATIONSHIP     PENDING    15
  LOG_ENTITY           PENDING     5
  LOG_EVENT            PENDING     4
```

**7. Review and decide** — in the wizard's Log Discovery step, or over the API:

```bash
curl localhost:5051/api/log-discovery/candidates            # ranked, with evidence
curl -X POST localhost:5051/api/log-discovery/<id>/approve  # into the ontology
curl -X POST localhost:5051/api/log-discovery/<id>/reject
curl -X POST localhost:5051/api/log-discovery/<id>/merge    # same thing, two names
```

Approved proposals become classes, relationships and event types the next time you
generate — and from there they constrain what an LLM may say.

### Useful flags

| Flag | What it does |
|---|---|
| `--log-path` | File, glob or folder. **Required** for `mine`, `sequence`, `log`. |
| `--log-format` | `auto` (default), `jsonl`, `syslog`, `cef`, `otlp`, `regex` |
| `--log-regex` | Named-group regex, when `--log-format regex` |
| `--dry-run` | Parse and report without writing to the database |
| `--min-freq` | Minimum co-occurrence for `--phase discover` (default 3) |

Related phases: `--phase log` (structured ingest only), `--phase drift-templates` (flag
log shapes that never appeared before), `--phase discover` (the separate TF-IDF/spaCy
entity path).

### What this is honest about

- **Proposals are candidates, not findings.** A high PMI score means two things co-occur,
  which is not the same as them being related in your domain. The review step is the
  product, not a formality.
- **A small corpus produces confident-looking scores.** The demo above shows
  `confidence 1.00` on 400 synthetic lines. Confidence reflects consistency within what
  it saw, not how representative that sample was.
- **The causal DAG check is currently advisory.** A PC-algorithm pass runs and *enriches*
  proposals with likely shared causes, but it doesn't yet veto edges it believes are
  confounded. Treat causal proposals as strong hints needing domain judgement.
- **`entity_discoverer` (TF-IDF + spaCy) is a weaker, separate path** from the slot-typing
  above. If both are enabled you'll see overlapping candidates.

---

## How the grounding actually works

Four mechanisms, each closing a specific failure mode.

**1. The vocabulary is a fence.** A *flavor* (`runtime/flavors/*.json`) declares which
classes are in scope, which tables may be touched, and the tier ceiling. The planner only
sees that vocabulary. A question it can't express in those terms returns
`status: "ungrounded"` instead of becoming a creative SQL query.

```python
from runtime.reasoning_search import search

answer = search("Which assets have low-confidence observations?",
                flavor="network-ops", db="db/enterprise.db",
                max_tier="Internal")
```

**2. Tiers gate what the model sees** — enforced when data is materialised, when a query
is compiled, and when related records are fetched. Fail-closed on unknown tiers.

**3. SHACL gates run on both sides** — input validated before it reaches the prompt,
output validated before it reaches your system.

**4. Answers carry their evidence.** A `ReasonedAnswer` returns:

```
answer           the text
plan             what it decided to look at, in ontology terms
executed_query   the exact read-only SQL that ran
results          the rows that came back
citations        IRIs of the records used
inferred         derived facts, each with the rule and its inputs
confidence       a score
trace            plan → execute → relations → reason → synthesize
status           ok | blocked | ungrounded | empty
```

### What this prevents

| Failure mode | What stops it |
|---|---|
| Inventing an entity or field | Planner confined to the flavor's vocabulary |
| Reading data it shouldn't | Tier gating in three places, fail-closed |
| Writing anything | Read-only SQL — allow-listed tables, bound parameters, `query_only` |
| Confident nonsense on no data | `status: empty` / `ungrounded` instead of prose |
| Unverifiable claims | Citations name records; derived facts name their rule |
| Silent schema drift | Drift loop raises proposals for review |
| Malformed output | SHACL acceptance gate |

### Why the ontology has to be correct

Grounding an LLM in a broken ontology is **worse** than not grounding it, because the
output looks rigorous.

Before v3.10.0, loading **one** record and running a reasoner inferred **47 type
assertions** — a trouble ticket was simultaneously an Agent, an Alarm, an Asset and 44
other things, because 114 fields had contradictory domain declarations. An LLM grounded in
that would have cited its way to nonsense with perfect provenance.

The same test now infers **zero** spurious types. That's the difference between a citation
that means something and one that merely exists.

---

## How to use it, in the order that works

**1. Point it at a database.**

```bash
python toolkit.py --phase all --db db/enterprise.db --out output
```

**2. Read the mapping workbook.** `output/mapping/logical_physical_map.csv` is the
contract between your schema and the ontology. It's generated, and it's **editable** —
editing it is how you steer what gets modelled.

**3. Check the semantic-loss report.** `output/mapping/semantic_loss_report.csv` flags
where the database flattened meaning — a status column that's really an event, a missing
actor, an overloaded type column. These are the decisions worth a human's time.

**4. Look at the quality report.** `output/reports/ontology_quality.csv`. Depth of 1 means
a flat list; 0 restrictions means nothing can be reasoned over.

**5. Wire an LLM.** Pick or write a flavor, set the ceiling, enable search:

```bash
export ONTOFORGE_SEARCH=1
ontoforge search "which assets are degraded?" --flavor network-ops --max-tier Internal
```

**6. Put the gate in CI.** `python scripts/ontology_gate.py` fails on regression. Update
the baseline in the same commit as the change that justifies it — never to turn a red
build green.

---

## Honest limitations

Stated plainly, because a grounding layer that oversells itself is the thing it exists to
prevent.

- **Reasoning Search is default-off** (`ONTOFORGE_SEARCH`) and is a linear
  plan→execute→answer pipeline, not an agent loop. SQL is single-table; multi-hop is
  approximated by one hop of foreign-key neighbours.
- **The rule engine is SDK-only.** Neither the CLI nor the HTTP route passes rules, so on
  those surfaces "reasoning" means gated SQL plus an LLM summary.
- **No route-level authentication.** Tier gating assumes an authenticated gateway in
  front. Don't expose the search endpoints directly.
- **Qdrant, Weaviate and pgvector adapters are filter translators, not clients.** The
  default embedder is a bag-of-words hash, not a semantic model — check your flavor's
  `embedding.model` before trusting similarity scores.
- **17 of 58 demo tables are empty**, so most competency questions can't pass in the demo.
  That's a fixture gap, not a modelling one, but it understates what the pipeline does on
  real data.
- The ontology is **OWL 2 DL**, so ELK won't fully classify it — use HermiT, or the
  bundled `owlrl`.

---

## Recent releases

| Version | What changed |
|---|---|
| **3.10.1** | Security patch. Related-record lookups bypassed the sensitivity ceiling and table allow-list; they now go through the same controls. Affects 3.10.0 and earlier **only with Reasoning Search enabled**. |
| **3.10.0** | Ontology correctness. Real class expressions (0 → 244), instance data, PROV chains, bitemporal modelling, self-checking output. **Breaking:** relationship field names changed (`:assetOf` → `:asset`), and compliance figures corrected — see CHANGELOG. |

---

## Where to look next

| Question | File |
|---|---|
| What does the ontology contain? | [`docs/concepts/ontology-model.md`](docs/concepts/ontology-model.md) |
| How do the quality gates work? | [`docs/reference/quality-gates.md`](docs/reference/quality-gates.md) |
| What is each output file for? | [`docs/artifacts.md`](docs/artifacts.md) |
| Which phase does what? | [`docs/concepts/pipeline.md`](docs/concepts/pipeline.md) |
| How did we get here? | [`ONTOLOGY_ROADMAP.md`](ONTOLOGY_ROADMAP.md) |
| What changed in a release? | [`CHANGELOG.md`](CHANGELOG.md) |

---

## Outstanding — not a code task

Twelve regulatory requirements across the EU AI Act, HIPAA §164.312, Basel IV/SR 11-7 and
the Ofcom transparency code were previously marked satisfied by tests that returned **zero
rows**. Reported coverage was 100%; honest figures are 33–57%. Seven signed evidence
bundles under `compliance/bundles/` were generated on the old basis.

The correction is published in the CHANGELOG and the `v3.10.0` tag. **Whether any of those
bundles reached a third party still needs confirming.**
