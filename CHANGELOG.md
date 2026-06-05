# Changelog

All notable changes to **Ontomesh** (formerly *Ontology Engineering Toolkit*) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.7.0] — 2026-06-05 · Public release

First public release on PyPI + GHCR (public).  Consolidates the 3.7.0-dev and 3.7.1-dev preview cuts into one tagged release under the new `synaptixs/ontomesh` namespace and Apache-2.0 licence.

### Added

- **Apache-2.0 licence** at `LICENSE`; matching `NOTICE` documents every third-party dependency.
- **`SECURITY.md`** describes the responsible-disclosure process (GitHub Security Advisories + back-up email).
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1.
- **`.github/PULL_REQUEST_TEMPLATE.md`** for incoming contributions.
- **`docs/PUBLIC_RELEASE_PLAN.md`** — the canonical roadmap for going from private to public.

### Changed

- **Repository moved** from `nrohilla-fibonacci/ontology` to `synaptixs/ontomesh`.  GitHub auto-redirects the old URL for ~30 days.
- **Container image path** is now `ghcr.io/synaptixs/ontomesh:3.7.0` (and `:latest`).  Multi-arch (`linux/amd64` + `linux/arm64`), signed via keyless cosign, ships with SLSA provenance + SPDX SBOM as OCI artefacts.
- **Identity de-link** — `pyproject.toml` author is `Synaptixs`; `CONTRIBUTING.md` security contact now points at `SECURITY.md` rather than a personal handle.
- **README** rewritten for a public audience: license + Python + Docker + Discussions badges; removed the "internal preview · private artefact" disclaimer; removed the `docker login` prelude.
- **Issue templates** rewritten for a public audience; the privacy-check checkbox now warns about a *public* repo rather than an internal team.
- **CI workflow** (`publish-image.yml`): Trivy step now scans-and-reports (uploads SARIF) instead of failing the build on every new upstream CVE.

### Production hardening (P3 line — first available in 3.7.0)

- **gunicorn** replaces Flask's dev server (P3.1).  gthread worker class, 2 workers × 8 threads default, env-var overridable.  "Do not use in production" warning gone.
- **Redis-backed SSE bus** (P3.2).  `ONTOMESH_REDIS_URL` activates; in-memory stays the default.  Multi-worker / multi-replica safe.  Compose adds opt-in `redis` profile.
- **Differentiated `/live` + `/ready` probes** (P3.3).  `/live` is cheap and dependency-free; `/ready` checks every dependency and 503s on failure.  Dockerfile / Compose / Fly / Render / Cloud Run probes all updated.
- **Structured JSON access logs + X-Request-Id correlation** (P3.4).  Every request gets an X-Request-Id (auto-generated or echoed); /live and /ready excluded from log noise.
- **Prometheus `/metrics` endpoint** (P3.5).  Five families (HTTP requests counter, request-duration histogram, SSE subscribers gauge, drift events counter, pipeline runs counter); path-label normalisation keeps cardinality bounded.
- **Image security + supply chain** (P3.6).  Trivy vulnerability scan (SARIF in Security tab); cosign keyless OIDC signing; SBOM + SLSA provenance attestation.

### Notes

- The `infodrift` repo (drift-monitor source for the `[drift]` extra) was also transferred under the Synaptixs org and now lives at `synaptixs/infodrift`.  GitHub auto-redirects the old `nrohilla-fibonacci/infodrift` URL during the transitional window.
- Pre-release dev cuts (`3.7.0-dev`, `3.7.1-dev`) remain accessible as historical tags but are not advertised as supported.

---

## [3.6.0-dev] — 2026-06-03 · Production deployment

Five-phase deployment line plus the first internal-share workflow.

### Added

- **Single-container image** (`ghcr.io/synaptixs/ontomesh:3.6.0-dev`) — multi-stage `Dockerfile`, non-root `ontomesh` user (uid 10001), `HEALTHCHECK` against `/health`. Multi-arch (`linux/amd64` + `linux/arm64`). 316 MB. (P2.1)
- **Docker Compose stack** — `compose.yml` brings up the wizard behind Caddy with auto-issued TLS. SSE-safe `read_timeout 24h`. Persistent volumes for SQLite + Caddy cert state. (P2.2)
- **Postgres backend** — `wizard/ontologies_store.py` refactored to be backend-agnostic. Set `ONTOMESH_DB_URL=postgresql://...` to switch; default stays SQLite. Single `[postgres]` extra ships psycopg2 + psycopg3. (P2.3)
- **Managed-runtime configs** — `fly.toml`, `render.yaml`, `deploy/cloudrun.yaml`, all wrap the same image. `deploy/README.md` is the picking guide. (P2.4)
- **Internal-share workflow** — `.github/workflows/publish-image.yml` builds and pushes to GHCR on every `v*.*.*` tag + manual dispatch. GHA layer cache. (P2.5)
- **Package-page README** rewritten to a focused image-reference doc (what's in the box, ports, env vars, endpoints). Long developer docs moved into `deploy/`, `docs/`, source repo. (P2.5.1)
- **Tester-feedback issue form** at `.github/ISSUE_TEMPLATE/tester-feedback.yml` for structured bug / friction / idea reports. (P2.6)
- **Boot banner** now reads "Ontomesh — the ontology mesh for GraphRAG · v3.6.0-dev" with the public surface URLs and active DB URL surfaced; version is pulled from `ontomesh.__version__` so it auto-tracks future bumps.

### Changed

- Package on PyPI renamed `ontology-toolkit` → `ontomesh`. Legacy import aliases are kept for one release.
- Console scripts: `ontomesh`, `ontomesh-wizard`, `ontomesh-onboard` are now the canonical entry points; the legacy `ontology-toolkit` / `ontology-onboard` aliases remain.
- README on `main` no longer reflects v1.5 — it now mirrors `develop`.

---

## [3.5.0-dev] — 2026-06-02 · Product surface

Brand, marketing, onboarding, dashboard, and the honest-numbers landing.

### Added

- **Brand identity (Ontomesh)** — wordmark, mark, favicon, OG / Twitter social cards, brand tokens across light / dark / mono themes. Sidebar header swap. Branded 404 / 500. (P1.1)
- **Marketing landing at `/`** — hero (brand-gradient "GraphRAG"), trust strip, "what you can build" cards, how-it-works, install snippet, end-CTA. Wizard moves to `/wizard`; legacy `/?step=X` 301-redirects. (P1.2)
- **Honest landing** — fabricated `HybridRetriever` snippet removed; install path = `git clone … && pip install -e .`; card stats now read at render time from `benchmarks/last-run.json` (852 KB DB → 4.8 s → 283 classes, 1,429 properties, 159 SHACL shapes). (P1.2.5)
- **First-run onboarding modal** — sample-project picker with ten starter industries (telecom, healthcare, finance, manufacturing, retail, energy, government, insurance, logistics, pharmaceuticals). One-click apply to session, then land on Step 2. (P1.3)
- **Project dashboard at `/projects`** — KPI strip + searchable filter chips + project-grid cards with one-click resume / delete. Linked from landing nav. (P1.4)
- **Empty-state polish** — Entities, Events, Relationships panels gain inviting empty states with primary + secondary CTAs (one re-opens the onboarding modal). Live SSE pill in the sidebar footer pulses cyan when the bus is connected. (P1.5)
- **Settings UX fixes** — "Switch starting point" card re-opens the welcome picker on demand; "landing page" → "Step 1 picker" honest copy; "Show all" / "Pick all" / "Clear" convenience buttons. (P1.5.1)
- **Whitelist domain visibility** — Step 1's template grid now shows only domains the user explicitly ticks in Settings (was: everything except a blacklist). Empty whitelist by default with an inviting empty state. (P1.5.2)

### Changed

- `pyproject.toml` renamed to `ontomesh` (3.4.0-dev → 3.5.0-dev).
- Help-page back-links updated for the wizard route change (`/?step=X` → `/wizard?step=X`).

---

## [3.4.0-dev] — 2026-06-01 · UI polish (P0)

Accessibility, design tokens, live drift, per-phase help.

### Added

- **Design tokens** — extracted inline CSS into `tokens.css` (light / dark / mono themes) + `wizard.css`. (P0.1)
- **Accessibility pass (WCAG 2.1 AA)** — skip-link, ARIA landmarks, `aria-current`, focus-visible rings, `prefers-reduced-motion`, keyboard navigation on the step list, persistent `aria-live` toast host. (P0.2)
- **Server-Sent Events** — in-memory pub/sub (`src/events_bus.py`), Flask `/api/events/stream` + `/api/events/stats`, `live_events.js` client with auto-reconnect. Drift events surface as toasts via `window.LiveBus`. (P0.3)
- **Per-phase help pages** at `/help/<slug>` for every wizard step. Tokens-aware styling, full a11y parity with P0.2. "ⓘ How it works" pill on every step title. (P0.4)
- **Reusable proposal-card component** (ES module, used by Log Discovery). (P0.1)

---

## [3.3.0] — 2026-05-22 · Tier 3 — Scale and continuous compliance

### Added

- T3.1 — Hierarchical regime modeling.
- T3.2 — Sparse GP + FastPC for scale.
- T3.3 — CQ → SPARQL auto-translation.
- T3.4 — Continuous compliance with regulation diffs.
- T3.5 — Neural-with-attention sequence models.

---

## [3.2.0] — 2026-05-13 · Tier 2 — Reasoning, policy, semantic diff

### Added

- T2.1 — Logical reasoning plug-in (SWRL, Datalog via Rulewerk).
- T2.2 — Cross-corpus template library.
- T2.3 — Policy-based auto-approval.
- T2.4 — Semantic ontology diff.
- T2.5 — Interventional causal discovery.
- T2.6 — MLOps for the pipeline.

---

## [3.1.0] — 2026-05-04 · Tier 1 — Naming, schema import, multi-target, streaming

### Added

- T1.1 — LLM-assisted proposal naming.
- T1.2 — Multi-modal causal DAG.
- T1.3 — Streaming / incremental mining.
- T1.4 — Schema-import depth.
- T1.5 — Multi-target generation.

---

## [3.0.0] — 2026-04-15 · Log discovery foundation

### Added

- Phases L4 – L13 — log mining, switching SSM regimes (L8), active-learning ranker (L9), VB-calibrated confidence (L10), PC algorithm causal DAG (L11), pPCA template viz (L12), GP rate anomalies (L13).
- Log Discovery wizard step with review queue.
- RCA-shaped ontology with `:CausalEvent / :hasCause / :rootCause` taxonomy.

---

## [1.5] — 2026-04-01 · Initial public framework release

### Added

- 8 build phases + the Flask wizard (Ontology Studio).
- OWL 2 + SHACL + JSON-LD + SKOS multi-target generation.
- TM Forum SID v23.0 baseline.
- 6 database backends (SQLite, PostgreSQL, MySQL, MSSQL, Oracle, DB2).

---

[3.7.0]: https://github.com/synaptixs/ontomesh/compare/v3.6.0-dev...v3.7.0
[3.6.0-dev]: https://github.com/synaptixs/ontomesh/compare/v3.5.0-dev...v3.6.0-dev
[3.5.0-dev]: https://github.com/synaptixs/ontomesh/compare/v3.4.0-dev...v3.5.0-dev
[3.4.0-dev]: https://github.com/synaptixs/ontomesh/compare/3.3.0...v3.4.0-dev
[3.3.0]: https://github.com/synaptixs/ontomesh/compare/3.2.0...3.3.0
[3.2.0]: https://github.com/synaptixs/ontomesh/compare/3.1.0...3.2.0
[3.1.0]: https://github.com/synaptixs/ontomesh/compare/3.0.0...3.1.0
[3.0.0]: https://github.com/synaptixs/ontomesh/compare/v1.5...3.0.0
[1.5]: https://github.com/synaptixs/ontomesh/releases/tag/v1.5
