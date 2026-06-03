# Ontomesh — the ontology mesh for GraphRAG

**v3.6 · Mine ontologies from your logs · Validate with SHACL · Ship a hybrid retriever**

Ontomesh (formerly *Ontology Engineering Toolkit*) is the production toolkit for data and ML engineers building GraphRAG. Point it at a relational schema or a folder of logs; get back a production-ready OWL 2 ontology, SHACL validation shapes, JSON-LD agent payloads, SKOS vocabulary, materialised inference + lineage, and a scored governance report — for any domain, any industry, any major relational database.

> **Internal preview.** This repo is private. The container image below is published to GitHub Container Registry under the same visibility — pulling requires a GitHub token. Do **not** share image URLs or test data outside the team.

---

## Try it in 30 seconds (Docker — recommended)

If you have Docker Desktop installed, this is the whole on-ramp:

```bash
# 1. Make a GitHub Personal Access Token with `read:packages` scope (one time):
#    https://github.com/settings/tokens/new?scopes=read:packages
#    Copy the token — you'll only see it once.

# 2. Log Docker into the private registry (one time per machine):
echo $TOKEN | docker login ghcr.io -u YOUR_GH_USER --password-stdin

# 3. Run the wizard:
docker run --rm -p 5051:5051 ghcr.io/nrohilla-fibonacci/ontomesh:latest

# 4. Open http://localhost:5051 in your browser.
```

A welcome modal offers ten starter industries (telecom, healthcare, finance, manufacturing, retail, energy, government, insurance, logistics, pharma). Pick one to populate the session with a real ontology you can edit; or "Start with a blank session" to build from scratch.

**Everything is local.** Your data never leaves your laptop. The container is ephemeral — stop it and the session resets unless you mount a volume:

```bash
# Persistent session + saved ontologies:
docker volume create ontomesh-data
docker run --rm -p 5051:5051 \
  -v ontomesh-data:/data \
  -e ONTOMESH_DATA_DIR=/data \
  ghcr.io/nrohilla-fibonacci/ontomesh:latest
```

## What's at each URL

Once running, four surfaces are useful:

| URL | What it is |
|---|---|
| `http://localhost:5051/` | Marketing landing — value prop, install snippet, capabilities |
| `http://localhost:5051/wizard` | The 11-step modeling wizard (Domain → Entities → … → Vector Retrieval) |
| `http://localhost:5051/projects` | Dashboard of every ontology you've saved — one-click resume |
| `http://localhost:5051/help` | Per-phase help pages (what each step does, why it matters, how) |
| `http://localhost:5051/health` | Liveness probe — used by Docker's `HEALTHCHECK` |

## Deploying it on real infrastructure

Five deployment shapes ship in this repo. See [`deploy/README.md`](deploy/README.md) for the picking guide.

- **Single host with TLS** — `docker compose up -d` brings up the wizard behind Caddy with auto-issued certs.
- **Fly.io** — `flyctl deploy` reads [`fly.toml`](fly.toml). Anycast + scale-to-zero.
- **Render** — Blueprint Sync reads [`render.yaml`](render.yaml).
- **Cloud Run** — `gcloud run services replace deploy/cloudrun.yaml`.
- **Postgres backend** — set `ONTOMESH_DB_URL=postgresql://...` on any of the above. SQLite is the zero-config default.

---

## For contributors (source install)

If you're modifying the code rather than testing the product:

```bash
git clone https://github.com/nrohilla-fibonacci/ontology.git
cd ontology
pip install -e ".[wizard]"

# Run tests
python -m pytest tests/ -q

# Run the wizard from source
ontomesh-wizard --port 5051
```

The full CLI is also exposed as a console script after `pip install -e .`:

```bash
ontomesh --db db/demo.db --out output/         # full pipeline
ontomesh --phase log --db db/demo.db --out output/   # log discovery only
ontomesh-onboard --industry telecom            # interactive REPL wizard
```

To point at your own database (PostgreSQL, MySQL, Oracle, MSSQL, DB2, SQLite) follow [docs/integrate.md](docs/integrate.md).

---

## Examples

Four runnable demos under [`examples/`](examples/) — each ~5 seconds, no API keys.

| Demo | What it shows | Runner |
|---|---|---|
| [Wizard](examples/wizard/) | Smart Building Operations end-to-end | `./examples/wizard/demo_wizard.sh` |
| [Retail](examples/retail/) | Ontology-vs-baseline LLM comparison | `./examples/retail/demo.sh` |
| [5G Core NFs](examples/5g/) | 3GPP semantic issues | `./examples/5g/demo_5g.sh` |
| [Drift monitoring](examples/infodrift/) | OWL-driven `drift_monitor` integration | `./examples/infodrift/demo_infodrift.sh` |

---

## Documentation

| File | When to read |
|---|---|
| **[deploy/README.md](deploy/README.md)** | Picking a deployment target — Docker / Compose / Fly / Render / Cloud Run |
| **[docs/integrate.md](docs/integrate.md)** | Five-minute SQLite path, 30-minute existing-DB path |
| **[install.md](install.md)** | Database driver issues, connection-string formats, full CLI reference |
| **[features.md](features.md)** | What every phase, artifact, and runtime component does |
| **[docs/sdk.md](docs/sdk.md)** | Python SDK — `RuntimeClient`, `Grounder`, `InputGate`, `OutputGate` |
| [examples/README.md](examples/README.md) | Index of runnable demos |

Companion documents (architects, leadership, governance):

- [docs/framework-whitepaper.md](docs/framework-whitepaper.md) — full framework specification v1.1
- [docs/executive-summary.md](docs/executive-summary.md) — non-technical overview
- [docs/technical-blueprint.md](docs/technical-blueprint.md) — phase-by-phase implementation guide
- [tests/test-plan.md](tests/test-plan.md) — first-contact test plans

---

## Feedback

Internal evaluators — please file issues with the `tester-feedback` label so we can triage:

- 🐞 **Bug** — something doesn't work
- 💭 **Friction** — something works but is harder than it should be
- 💡 **Idea** — something you wish it did

Or just drop a message in the team channel; we're collecting everything.

---

*Framework v1.1 · Toolkit v3.6.0-dev · OWL 2 · SHACL · PROV-O · SKOS · JSON-LD · TM Forum SID v23.0 · 6 database backends · SQLite or Postgres · Docker / Compose / Fly / Render / Cloud Run · 200+ tests*
