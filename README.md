# Ontomesh

**The ontology mesh for GraphRAG.** Mine ontologies from your logs, validate with SHACL, ship a hybrid retriever — without hand-crafting a single Turtle file.

> **Internal preview · private artefact.** This image is published from a private repository to a private container registry. Do **not** share image URLs, screenshots of session data, or test data outside the team.

---

## What's in the image

| | |
|---|---|
| **Image** | `ghcr.io/nrohilla-fibonacci/ontomesh:3.6.0-dev` (and `:latest`) |
| **Size** | ~316 MB compressed |
| **Architectures** | `linux/amd64`, `linux/arm64` (Apple Silicon ready) |
| **Base** | `python:3.12-slim` |
| **Runtime user** | non-root `ontomesh` (uid `10001`) |
| **Process** | single-process Flask via the `ontomesh-wizard` console script |
| **Default port** | `5051` (configurable via `ONTOMESH_PORT`) |
| **Persistent data** | `/data` (mount a volume here) |
| **Healthcheck** | `GET /health` every 30 s |

## Run it

```bash
# One-time per machine: log Docker into the private registry.
# (Token needs `read:packages` scope — make one at
#  https://github.com/settings/tokens/new?scopes=read:packages )
echo $TOKEN | docker login ghcr.io -u YOUR_GH_USER --password-stdin

# Ephemeral run (resets on stop):
docker run --rm -p 5051:5051 ghcr.io/nrohilla-fibonacci/ontomesh:latest

# Persistent run (saved ontologies survive container restart):
docker volume create ontomesh-data
docker run -d --name ontomesh \
  -p 5051:5051 \
  -v ontomesh-data:/data \
  -e ONTOMESH_DATA_DIR=/data \
  ghcr.io/nrohilla-fibonacci/ontomesh:latest
```

Then open **http://localhost:5051** in your browser.

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
| **Validation** | SHACL 1.1 shapes + materialised inference with `prov:wasDerivedFrom` lineage |
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

**https://github.com/nrohilla-fibonacci/ontology**

Specifically:
- `deploy/README.md` — picking a deployment target
- `docs/integrate.md` — connecting to your own database
- `compose.yml` + `deploy/Caddyfile` — single-host TLS recipe
- `fly.toml` · `render.yaml` · `deploy/cloudrun.yaml` — managed-runtime configs

## Feedback

File issues against the source repo with the `tester-feedback` label, or message the team directly.

---

*Ontomesh v3.6.0-dev · OWL 2 · SHACL · PROV-O · SKOS · JSON-LD · 217+ tests · Docker, Compose, Fly.io, Render, Cloud Run*
