# Reasoning Search

!!! note "Flag-gated preview"
    Ontology-grounded **reasoning search** is built and on `main`, gated behind
    the `ONTOFORGE_SEARCH` flag (default-off) — it ships *dark* and is not yet in
    a published release. Enable it locally with `ONTOFORGE_SEARCH=1`. Watch the
    [repository](https://github.com/synaptixs/ontomesh) for the release.

Ask your database a question in plain English and get a **cited, reasoned
answer** — grounded in the ontology Ontoforge generates from your data, executed
**safely** (read-only) against live records, running **locally (Ollama)** or in
the **cloud (OpenAI)**.

## What it does

- **Plans over the ontology, not raw columns** — the model can only reference
  classes and properties that exist, so it can't invent tables or fields.
- **Reasons, not just retrieves** — derives non-obvious facts via Datalog rules,
  each with `prov:wasDerivedFrom` lineage.
- **Multi-hop** across real relationships — foreign-key neighbours are loaded
  automatically so rules can chain across tables.
- **Cites everything** — every claim maps to a source record; the executed
  read-only SQL is always shown.
- **Stays safe** — read-only, allow-listed, sensitivity-tier gated; safe to point
  at a live database.
- **Live SPARQL** — materializes the result subgraph as RDF and lets you query it.

## Try it

```bash
ONTOFORGE_SEARCH=1 ontoforge-wizard --port 5051
# then open http://localhost:5051/ask
```

### 1. Pose a question

Pick a flavor and provider (Ollama / OpenAI), set your sensitivity-tier ceiling,
and optionally build an RDF subgraph for live SPARQL.

![Ask console — ready to reason](../assets/screenshots/ask-01-ready.png)

### 2. Get a cited, reasoned answer

The answer cites its sources, shows the exact read-only SQL that ran, materializes
the result subgraph, and streams the full reasoning trace
(plan → execute → relations → reason → synthesize).

![Ask console — cited, reasoned answer with trace](../assets/screenshots/ask-02-answer.png)

### 3. Interrogate the subgraph with live SPARQL

Query exactly what grounded the answer with a SPARQL `SELECT` over the
materialized RDF triples.

![Ask console — live SPARQL over the result subgraph](../assets/screenshots/ask-03-sparql.png)

## Surfaces

| Surface | How |
|---|---|
| **SDK** | `from runtime.reasoning_search import search` |
| **CLI** | `ontoforge search "…" --flavor network-ops --provider ollama` |
| **HTTP** | `POST /api/search` · streaming `POST /api/search/stream` (SSE) |
| **SPARQL** | `POST /api/sparql` over a materialized subgraph |
| **Console** | the `/ask` page (embedded as a wizard step) |
| **Metrics** | Prometheus `ontomesh_search_*` via `/metrics` (Grafana dashboard in `deploy/monitoring/`) |

```python
from runtime.reasoning_search import search

ans = search("Which alarms have a Critical perceived severity?",
             flavor="network-ops", db_path="db/demo.db",
             providers="ollama", max_tier="Restricted", materialize=True)
print(ans.answer)        # cited, reasoned prose
print(ans.executed_query)  # the read-only SQL that ran
print(ans.subgraph["count"])  # RDF triples in the result subgraph
```

## Examples

> *"Which customers are at risk from the degraded core router crt-07, and why?"*
> → derives the impacted customers by walking `Resource → Service → Customer`,
> cross-checks open alarms, and cites each source.

> *"Which enrolled subjects are now ineligible after their latest labs — and why?"*
> → re-checks each subject's latest results against the trial's eligibility
> criteria, flags violations with audit-grade lineage, and keeps PHI on-host.

---

*Want to shape the design? Open a discussion on the
[repo](https://github.com/synaptixs/ontomesh/discussions).*
