# Ontomesh

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker pulls](https://img.shields.io/badge/docker-ghcr.io%2Fsynaptixs%2Fontomesh-2496ED?logo=docker)](https://github.com/synaptixs/ontomesh/pkgs/container/ontomesh)
[![Discussions](https://img.shields.io/badge/Discussions-join-1f6feb?logo=github)](https://github.com/synaptixs/ontomesh/discussions)

**The semantic system of record for your enterprise.** Derive a formal model of the systems you already run, govern how it changes, and prove where every answer came from. Built from your schema and your logs — without hand-crafting a single Turtle file.

> **Preview release.** Public API surface is stabilising; expect occasional breaking changes until 1.0.

---

## What's in the image

| | |
|---|---|
| **Image** | `ghcr.io/synaptixs/ontomesh:3.10.1` (and `:latest`) |
| **Size** | ~316 MB compressed |
| **Architectures** | `linux/amd64`, `linux/arm64` (Apple Silicon ready) |
| **Base** | `python:3.12-slim` |
| **Runtime user** | non-root `ontomesh` (uid `10001`) |
| **Process** | single-process Flask via the `ontoforge-wizard` console script |
| **Default port** | `5051` (configurable via `ONTOMESH_PORT`) |
| **Persistent data** | `/data` (mount a volume here) |
| **Healthcheck** | `GET /health` every 30 s |

## Run it

```bash
# Ephemeral run (resets on stop):
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:latest

# Persistent run (saved ontologies survive container restart):
docker volume create ontomesh-data
docker run -d --name ontomesh \
  -p 5051:5051 \
  -v ontomesh-data:/data \
  -e ONTOMESH_DATA_DIR=/data \
  ghcr.io/synaptixs/ontomesh:latest
```

Then open **http://localhost:5051** in your browser.

## Screenshots — a guided tour

A walkthrough from landing page to ontology-grounded **reasoning search**, in order.

**1. Landing** — the marketing entry point.

![Landing page, Twilight theme](docs/assets/screenshots/landing-twilight.png)

**2. Model your domain** — a guided, navy + lime-green **Twilight** wizard that walks
you from a domain to a generated ontology in four phases — Define → Enrich → Build → After.

![Wizard — Domain Identity step, Twilight theme](docs/assets/screenshots/wizard-twilight.png)

**3. Run report** — every run emits a branded HTML report: competency-question
results, governance scorecard, semantic-loss analysis, and orphan-class checks.

![Run report](docs/assets/screenshots/report-branded.png)

**4. Ask — pose a question** — the read-only, ontology-grounded **Ask** console.
Pick a flavor and provider (Ollama / OpenAI), set your sensitivity-tier ceiling,
and optionally build an RDF subgraph for live SPARQL.

![Ask console — ready to reason](docs/assets/screenshots/ask-01-ready.png)

**5. Ask — a cited, reasoned answer** — the answer cites its sources, shows the
exact read-only SQL that ran, materializes the result subgraph, and streams the
full reasoning trace (plan → execute → relations → reason → synthesize).

![Ask console — cited, reasoned answer with trace](docs/assets/screenshots/ask-02-answer.png)

**6. Ask — live SPARQL over the result subgraph** — interrogate exactly what
grounded the answer with a SPARQL `SELECT` against the materialized RDF triples.

![Ask console — live SPARQL over the result subgraph](docs/assets/screenshots/ask-03-sparql.png)

> The wizard ships three themes — **Twilight** (default), **Mono**, and **Light** —
> switchable from the “All steps” drawer.

## What you get

| URL | What it serves |
|---|---|
| `/` | Marketing landing — value prop + install snippet |
| `/wizard` | The 11-step modeling wizard (Domain → Entities → Events → Relationships → Log Discovery → CQs → Rules → Generate → Evolution Review → Compliance → Vector Retrieval) |
| `/projects` | Dashboard of every ontology you've saved — one-click resume |
| `/help` | Per-phase help pages explaining each step |
| `/health` | JSON liveness probe |
| `/api/events/stream` | Server-Sent Events feed (drift + metric updates) |
| `/api/ontologies` | REST endpoint for the saved-ontologies store |
| `/api/templates` | REST endpoint listing available starter templates |

## Configuration (env vars)

| Variable | Default | What it does |
|---|---|---|
| `ONTOMESH_HOST` | `0.0.0.0` | Bind address |
| `ONTOMESH_PORT` | `5051` | Bind port |
| `ONTOMESH_DATA_DIR` | `/data` | Where SQLite + saved ontologies + generated outputs live |
| `ONTOMESH_DB_URL` | _(unset → SQLite at `$ONTOMESH_DATA_DIR/ontologies.db`)_ | Set to `postgresql://user:pass@host:5432/dbname` to use Postgres instead |

## What ships inside

| | |
|---|---|
| **Pipeline phases** | 8 build phases + 8 enrichment phases (log mining L4-L13, schema inference, multi-target generation) |
| **Ontology** | OWL 2 DL — `owl:Restriction` class expressions, defined classes, `owl:hasKey` from UNIQUE constraints, union domains |
| **Instance data** | `--phase abox` materialises individuals from your rows, with reified PROV-O chains and sensitivity-tier gating |
| **Modelling depth** | OWL-Time bitemporal (valid vs transaction time) · QUDT united quantities · reified n-ary participation |
| **Validation** | SHACL 1.1 shapes + materialised inference with `prov:wasDerivedFrom` lineage |
| **Self-checking** | OOPS!-style pitfall detection, structural metrics, in-process consistency (`owlrl`), and a CI regression ratchet |
| **Reasoning** | OWL-RL · SWRL · Datalog (Rulewerk) |
| **Output formats** | OWL/Turtle · SHACL · JSON-LD · SKOS · materialisation report |
| **Wizard surfaces** | 10 starter industries (telecom, healthcare, finance, manufacturing, retail, energy-utilities, government, insurance, logistics, pharmaceuticals) |
| **Discovery** | Drain3 templates · per-service HMMs · Granger / transfer-entropy gating · PMI co-occurrence |
| **Database backends** | SQLite (default) · PostgreSQL · MySQL · MSSQL · Oracle · DB2 |
| **LLM adapters** | Anthropic · OpenAI · Vertex AI · Ollama · OCI |
| **Vector backends** | FAISS · Chroma (scaffolded: Qdrant · pgvector) |

## First-time experience

The first time you load the wizard with an empty session, a welcome modal offers ten starter industries. Pick one to populate the session with a real ontology you can edit, or "Start with a blank session" to build from scratch.

## Persistent SQLite vs. Postgres

The image defaults to SQLite-on-disk. For multi-host or multi-replica deployments, set `ONTOMESH_DB_URL` to a Postgres connection string — the wizard switches transparently. Both backends share the same wire schema.

## Source · documentation · deployment recipes

The full developer documentation, deployment guides (Compose / Fly.io / Render / Cloud Run), and source code live in the repository:

**https://github.com/synaptixs/ontomesh**

Specifically:
- `deploy/README.md` — picking a deployment target
- `docs/integrate.md` — connecting to your own database
- `compose.yml` + `deploy/Caddyfile` — single-host TLS recipe
- `fly.toml` · `render.yaml` · `deploy/cloudrun.yaml` — managed-runtime configs

## Feedback

[**File a tester-feedback issue**](https://github.com/synaptixs/ontomesh/issues/new?template=tester-feedback.yml) — the form has a short three-option dropdown (Bug · Friction · Idea · Docs), optional repro/expected sections, and auto-applies the `tester-feedback` label.  Or message the team directly.

Looking for what changed when?  See [`CHANGELOG.md`](https://github.com/synaptixs/ontomesh/blob/main/CHANGELOG.md).

---

*Ontomesh v3.10.1 · Apache-2.0 · OWL 2 DL · instance data · self-checking output · Reasoning Search · gunicorn · Redis SSE · Prometheus · cosign-signed · OWL 2 · SHACL · PROV-O · SKOS · JSON-LD · 1000+ tests · Docker, Compose, Fly.io, Render, Cloud Run*
