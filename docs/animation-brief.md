# Animation brief — two explainer animations for Ontomesh

A self-contained specification. Everything needed is in this document; no repo access
required. Hand it to a motion designer, or paste it into a generative video/animation tool.

**Deliverables:** two animations, 60–90 seconds each, sharing one visual language.

| # | Title | Answers |
|---|---|---|
| **1** | *How Ontomesh is built* | What is this thing, what goes in, what comes out |
| **2** | *What it does for your AI* | Why an AI team should care |

**Audience:** software engineers and data/ML engineers. Technically literate, sceptical,
have seen a lot of AI marketing. They will disengage instantly at hand-waving.

**Tone:** calm, precise, quietly confident. No hype, no rocket ships, no glowing brains.
The product's whole argument is *"we don't overstate"* — the animation must sound like
that too.

---

## Shared visual language

Both animations must feel like one system.

**Palette** — dark-native, navy base with lime-green accent (the product's existing theme):

| Role | Colour | Used for |
|---|---|---|
| Background | `#0B1220` deep navy | canvas |
| Surface | `#121C2E` | panels, cards |
| Primary accent | `#A3E635` lime | the ontology, anything "governed" |
| Secondary | `#38BDF8` sky | data in motion, queries |
| Warning | `#FBBF24` amber | withheld / needs review |
| Danger | `#F87171` red | blocked, rejected, ungrounded |
| Text | `#E2E8F0` / muted `#94A3B8` | |

**Shapes carry meaning — keep consistent across both:**

- **Cylinder** = a data source (database, log file)
- **Rounded rectangle** = a generated artifact (a file)
- **Hexagon** = an ontology class
- **Line between hexagons** = a relationship; *dashed* = unconfirmed/ambiguous
- **Shield outline** = a gate or control
- **Small circle** = an individual record

**Typography:** one geometric sans (Inter, Söhne). Code and identifiers in a mono face
(JetBrains Mono). Never render code in a proportional font — this audience notices.

**Motion:** ease-in-out, 300–500 ms per beat. Things *assemble*, they don't fly in.
No bounce, no spin. Camera moves are slow pans and scale, never rotation.

**Rule:** every number on screen must be real (they're supplied below). Do not invent
metrics. If a figure isn't in this brief, don't show one.

---

# Animation 1 — *How Ontomesh is built*

**Length:** 75–90 s. **Goal:** a viewer can explain, afterwards, what goes in and what
comes out.

### Scene 1 — The problem (0:00–0:10)

Two sources sit apart on a dark canvas: a **database cylinder** labelled `schema` and a
**stack of log lines** labelled `logs`.

Between them, a faint question mark, or a dotted outline of a shape that doesn't resolve.

> **Caption:** "Your systems know what your data *is*. Nothing knows what it *means*."

*Motion:* both sources pulse gently, out of sync. They are unconnected — emphasise that.

### Scene 2 — Reading the schema (0:10–0:25)

A beam sweeps the database cylinder. Rows of table names lift out and transform:

```
assets          →  ⬡ Asset
domain_events   →  ⬡ DomainEvent
agents          →  ⬡ Agent
```

Then the relationships draw themselves between hexagons as solid lines, labelled with
real property names:

```
:asset      :recordedBy      :hasEventType
```

> **Caption:** "Tables become classes. Foreign keys become typed relationships."

*Motion:* hexagons snap to a light grid. Lines draw from source to target over ~400 ms.

### Scene 3 — Mining the logs (0:25–0:45) — **the most important scene**

This is where the machine learning lives. Four beats, tight.

**Beat A — Templates.** Hundreds of log lines scroll fast, then collapse into four
template cards. Show the real templates:

```
 200×   PRB utilisation high on <*> <*> at 91 percent
 200×   Throughput degraded on <*> <*> to 12 Mbps
 200×   Alarm raised <*> for <*> severity MAJOR
 200×   Ticket <*> opened for <*>
```

> **Caption:** "400 lines → 4 shapes."

**Beat B — Typing the variables.** The `<*>` placeholders light up and get labelled:

```
ENUM        →  becomes an entity
FREETEXT    →  becomes an attribute
```

> **Caption:** "What varies tells you what exists."

**Beat C — Finding relationships.** Entity hexagons appear and lines form between them,
each carrying a score. Use the real values:

```
cell-C3  ── gnb-042    pmi 3.82   n 241   lead 0.53
cell-B2  ── gnb-041    pmi 3.79   n 316   lead 0.51
gnb-041  ── gnb-042    pmi 3.78   n 413   lead 0.50
```

**Critical detail:** these lines must be **dashed and undirected**. No arrowheads.

> **Caption:** "Strongly connected — but nothing says which came first. So it doesn't guess."

*This beat is the emotional core of animation 1.* The system declining to invent a
direction is the trust-building moment. Give it a full 4 seconds and let it breathe.

**Beat D — Proposals.** The findings slide into a review panel as cards:

```
LOG_EVENT         Event template #1: PRB utilisation high…      PENDING
LOG_EVENT         Event template #2: Throughput degraded…       PENDING
LOG_ENTITY        Entity candidate :PRBCode (ENUM)              PENDING
LOG_RELATIONSHIP  cell-C3 — gnb-042                             PENDING
```

A human cursor approves two, rejects one, merges two into one.

> **Caption:** "Nothing enters the model automatically. You decide."

### Scene 4 — The artifacts (0:45–1:05)

The approved hexagon graph condenses into a stack of labelled file cards:

| Card | Sub-label |
|---|---|
| `enterprise.ttl` | classes, properties, constraints |
| `events.ttl` | event types |
| `provenance.ttl` | who did what, when |
| `dimensions.ttl` | time, units, roles |
| `instances.ttl` | your actual records |
| `enterprise-shapes.ttl` | validation rules |
| `enterprise-context.json` | shared field meanings |

> **Caption:** "One command."
> **Mono overlay:** `python toolkit.py --phase all`

### Scene 5 — Checking itself (1:05–1:20)

A shield outline forms over the artifact stack. Metrics tick up beside it — use these
real values:

```
turtle files parsing        23 / 23
class expressions              244
pitfall checks                  10
consistency              consistent
```

Then a small red bar labelled *regression* rises and is stopped by the shield.

> **Caption:** "It fails when the model gets worse — not when it's merely imperfect."

### Scene 6 — Close (1:20–1:30)

Pull back to the full stack, quiet.

> **Ontomesh — the semantic system of record for your enterprise.**

---

# Animation 2 — *What it does for your AI*

**Length:** 60–75 s. **Goal:** an AI engineer thinks *"that's the thing my chatbot is
missing."*

### Scene 1 — Ungrounded (0:00–0:15)

A chat bubble sits beside a database cylinder, connected by a thin sky-blue line.

Question appears: **"Which customers are at risk?"**

The answer types out — confident, fluent, and **wrong**. As it finishes, three red flags
pop beside it:

```
✗  invented a field that doesn't exist
✗  read a column it shouldn't have
✗  no way to check any of it
```

> **Caption:** "An LLM pointed at a database can say anything."

*Motion:* the answer types at a believable speed. Let it look good before the flags land —
the point is that plausibility is the problem.

### Scene 2 — Inserting the ontology (0:15–0:25)

The hexagon graph from animation 1 slides in **between** the chat bubble and the database.
The connection now routes *through* it.

> **Caption:** "Put the model in between."

### Scene 3 — The four gates (0:25–0:55) — **the core**

Same question re-asked. Follow it through four checkpoints. Each is a shield; each does
something visible.

**Gate 1 — Vocabulary.** The question meets a panel of allowed terms. Two of its words
turn lime (matched); one turns red and is **rejected**.

```
✓ Customer   ✓ hasRiskScore   ✗ churnLikelihood
```

> **Caption:** "It can only use words the ontology has."

**Gate 2 — Sensitivity.** The query reaches the database. Columns light up:

```
name              Internal        ✓ passes
region            Internal        ✓ passes
credential_expiry Confidential    ✗ withheld
ssn               Restricted      ✗ withheld
```

Withheld columns go amber and **do not travel onward**. Show them stopping at the shield.

> **Caption:** "The model never receives what it isn't cleared to read."

**Gate 3 — Query.** A mono panel shows the actual SQL, with the read-only nature marked:

```sql
SELECT name, region, has_risk_score
FROM   customers
WHERE  has_risk_score > ?
LIMIT  50
```

> **Caption:** "Read-only. Allow-listed tables. Bound parameters."

**Gate 4 — Output.** The generated answer meets a SHACL shield before reaching the user.

> **Caption:** "Validated before you act on it."

### Scene 4 — The answer, with receipts (0:55–1:10)

The answer appears — and this time it arrives with structure attached. Show these fields
as a small panel, mono:

```
answer          "Three customers show elevated risk…"
citations       Customer/41 · Customer/88 · Customer/103
executed_query  SELECT name, region … LIMIT 50
confidence      0.85
status          ok
```

Then a citation is clicked and a chain unfolds:

```
Customer/41  ←  generated by  ←  DerivationActivity/7  ←  associated with  ←  Agent/3
```

> **Caption:** "Every claim points at a record. Every record points at who produced it."

### Scene 5 — When it can't answer (1:10–1:20)

Briefly, a second question arrives that the data can't support. Instead of prose:

```
status: ungrounded
```

> **Caption:** "And when it doesn't know, it says so."

*This scene is short but non-negotiable.* It's the credibility beat.

### Scene 6 — Many teams, one meaning (1:20–1:35)

Zoom out. Three AI features appear around the single hexagon graph:

```
support assistant   ·   anomaly triage   ·   retrieval service
```

Each connects to the same ontology. Field names flow between them **matching** —
show `status` meaning the same thing in all three.

> **Caption:** "Three teams. One vocabulary. No drift."

### Scene 7 — Close (1:35–1:45)

> **Your AI can only say what your data supports — and it has to show its sources.**

---

## Accuracy notes — get these right

1. **The direction thing matters.** In animation 1 Beat C, the lines must be **dashed
   with no arrowheads**. Adding arrows inverts the message.
2. **Withheld data must visibly stop.** Don't fade it out — show it hitting the shield and
   not continuing. Fading reads as "hidden"; stopping reads as "never sent".
3. **`status: ungrounded` is a feature, not an error.** Style it neutral or amber, never
   red-alarm.
4. **The human approves proposals.** Never show the system writing to the ontology by
   itself.
5. **Real strings only.** All log templates, PMI scores, field names and metrics above are
   taken from an actual run. Don't substitute plausible-looking alternatives.
6. **Tier names are exactly:** `Public`, `Internal`, `Confidential`, `Restricted`.

## Avoid

- Glowing brains, neural-network node clouds, robot imagery
- "AI" as a floating orb or assistant character
- Binary rain, matrix effects, generic "data" particles
- Speed-ramping or aggressive transitions — this is a governance product
- Any claim of accuracy, correctness, or intelligence. The claim is **traceability**.

## Optional third short (if budget allows)

15 seconds, terminal only. Real recorded output:

```
$ python toolkit.py --phase mine --log-path ./logs

  ✓ records ingested         400
  ✓ templates                  4
  ✓ entity edges              15
  ✓ proposals seeded          24  (event=4 entity=5 rel=15)
```

Cut to the review UI. Cut to a cited answer. No narration. Good for social.
