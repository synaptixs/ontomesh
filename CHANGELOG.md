# Changelog

All notable changes to **Ontomesh** (formerly *Ontology Engineering Toolkit*) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.10.2] — 2026-08-25 · Repositioning

No functional change. The package description, the boot banner and the wizard
UI carry a new tagline; the code is identical to 3.10.1.

### Changed

- **Repositioned away from "GraphRAG".** `The ontology mesh for GraphRAG` named
  a component rather than the product: GraphRAG is a retrieval technique, and
  retrieval is roughly one of eleven wizard steps — discovery, causal mining,
  drift, evolution governance, compliance evidence and federation all sit
  outside it. "for GraphRAG" also positioned the product as an input to a
  pipeline we do not own.

  Now: **Ontomesh — the semantic system of record for your enterprise.** Derive
  a formal model of the systems you already run, govern how it changes, and
  prove where every answer came from.

  Applied across the landing hero and footer, the wizard page, the CLI boot
  banner and argparse description, the package docstring, the pyproject and
  mkdocs descriptions, the README and docs subheads, the OCI image label, and
  both social-card SVGs. Subheads that still led with "ship a hybrid retriever"
  were rewritten to match.

- Corrected two stale `v3.7` version strings on the landing page, left behind by
  earlier releases.

### Added (repository only, not shipped in the wheel)

- `scripts/confluence_sync.py` — publishes the documentation to Confluence as a
  generated, one-directional mirror; the repository stays the source of truth.
- `docs/diagrams/` — four SVG architecture diagrams, three animated with SMIL.
- `PROJECT_STATE.md` — expanded with what the toolkit gives an engineering team,
  how the log-mining ML works, and a runnable five-minute demo.

---

## [3.10.1] — 2026-07-26 · Security patch

### Security

- **FK-neighbour reads bypassed the sensitivity ceiling and the table
  allow-list.** Reasoning Search has two paths that read the database.
  `compile_sql()` enforces the flavor's table allow-list and drops columns
  above the caller's `max_tier`; `_fk_neighbors()` enforced neither. It issued
  `SELECT *` against tables discovered from `PRAGMA foreign_key_list` — the
  schema, not the allow-list — and returned every column regardless of tier.
  De-identification ran before neighbours were fetched, so it never masked them.

  The values were not confined to the process: every neighbour column became a
  triple in the materialised subgraph, and `POST /api/sparql` runs the
  *caller's* SPARQL over that subgraph and returns the results. The ceiling was
  advisory on that path.

  Demonstrated on the shipped demo database — a fetch seeded from
  `observations` returned `agents.credential_expiry`, classified
  `Confidential`, with no ceiling applied.

  The neighbour read now goes through the same controls: allow-list checked,
  projected to mapped columns within the ceiling, de-identified on the same
  pass, and failing closed without a mapping. Dropped edges are reported in the
  trace rather than silently omitted.

  **Affected:** 3.10.0 and earlier, when Reasoning Search is enabled
  (`ONTOFORGE_SEARCH=1`, default-off). Installations that never enabled it were
  not exposed. **Upgrade to 3.10.1** if you enabled it.

---

## [3.10.0] — 2026-07-26 · Ontology correctness, instance data, self-checking output

A correctness release for the generated ontology itself. The pipeline was
sound; the artifact it produced was not. Six phases of work, each measured
against a committed baseline.

### ⚠ Breaking

- **Object-property IRIs changed.** The `Of` suffix is gone and only a
  trailing `_id` is stripped, so `asset_id` yields `:asset` (was `:assetOf`)
  and `asset_type_id` yields `:assetType` (was also `:assetOf` — the two
  collapsed onto one IRI with contradictory domains). Saved SPARQL queries
  against the old names need updating. The mapping workbook, the ontology
  and the ABox now share one naming function, so they cannot drift apart.
- **`PASS-STRUCTURAL` is removed.** A competency question returning zero rows
  is no longer scored as a pass. Suites that relied on it will now report
  real failures — that is the point.
- **Compliance outcomes change.** Twelve requirements across the EU AI Act,
  HIPAA §164.312, Basel IV/SR 11-7 and the Ofcom transparency code were
  gated on `PASS-STRUCTURAL`, so they were satisfied by tests returning no
  rows. Reported coverage was 100% with three regulations at a perfect
  score; honest figures are 33–57%. **Previously generated evidence bundles
  asserted compliance on the old basis and should be reviewed.**
- Property-level `owl:minCardinality` triples (139 of them) are gone. A
  cardinality outside an `owl:Restriction` is not an axiom; the same
  information is now emitted as restrictions.

### Added

- **`--phase abox`** — materialises instance data from your rows via the
  mapping workbook. `instances.ttl` carries individuals, reified PROV-O
  chains, validity periods, united quantities and reified participation.
  Sensitivity-tier gated, `Restricted` excluded by default.
- **`--phase quality`** — OOPS!-style pitfall detection (10 checks),
  structural metrics, and in-process consistency checking with `owlrl`. No
  external reasoner binary required.
- **`scripts/ontology_gate.py`** — a CI ratchet over 16 measurable artifact
  properties, compared against a committed `ontology_baseline.json`. Fails
  on regression rather than on the existence of known debt.
- **`dimensions.ttl`** — OWL-Time bitemporal modelling (valid time kept
  distinct from transaction time), QUDT-aligned quantities, and reified
  n-ary participation.
- **Real class expressions.** Event subclasses are now defined classes with
  `owl:equivalentClass` restrictions, so a reasoner classifies into them.
  244 `owl:Restriction` blocks where there were none.
- **`owl:hasKey`** derived from UNIQUE constraints — 39 axioms where the
  feature had never emitted one, because it read metadata columns no shipped
  database populates.
- **Versioning and deprecation** — `owl:priorVersion`,
  `owl:backwardCompatibleWith`, `dcterms:license`, and `owl:deprecated`
  tombstones so retired IRIs still resolve.
- Industry templates now emit their declared `events:`, `values:`
  enumerations (as closed `owl:oneOf` dataranges) and required-property
  restrictions, all of which the generator previously read and discarded.

### Fixed

- **Every generated SKOS vocabulary failed to parse.** Two adjacent Turtle
  string literals in an f-string produced an unterminated object.
- **114 properties carried conjunctive multi-domain axioms.** `:hasCreatedAt`
  had 43 domains, so one instance triple inferred 47 `rdf:type` assertions.
  Properties are now declared once with a union domain.
- **All 45 upper-ontology alignments were dangling** — minted under the TMF
  namespace while describing enterprise classes. Subjects are now resolved
  against the ontologies actually generated; 44 of 44 bind.
- **20 malformed alignment IRIs** (`<fhir:MedicinalProduct>`) — the
  templates' `external_alignments:` prefix map was never read.
- Unsound `owl:AllDisjointClasses` over lifecycle phases, which made any
  order that shipped unsatisfiable.
- A self-referential `:DomainEvent rdfs:subClassOf :DomainEvent`, and an
  `:EventTypeEvent` class minted from a CSV header row.
- Object properties ranged at `owl:Thing`, which asserts nothing while
  reading like a constraint.
- `:wasProducedBy` was a subproperty of `prov:wasGeneratedBy` with an Agent
  range, which inferred every agent was an Activity.

### Changed

- The governance scorecard has 36 criteria and **none are hardcoded**. Nine
  passed a score literal on every run regardless of output; each now reads
  the artifact it makes a claim about. The average moved 3.6 → 3.4, and the
  lower number is the honest one.
- Consistency checking no longer requires the ROBOT binary.
- `--phase all` includes `abox` and `quality`.

---

## [3.9.0] — 2026-06-22 · Liquid Glass theme

### Added

- **Liquid Glass theme** — an opt-in, dark-native UI theme: translucent frosted surfaces (`backdrop-filter`) over a live gradient backdrop, with specular edge highlights. Selectable from the wizard's theme picker (Twilight · Mono · Light · **Glass**) and a toggle on the marketing landing; the choice persists across the wizard, landing, Ask console, and Projects via the shared `wizard-theme` key. Built on the existing `[data-theme]` token system, so it's fully reversible.
- **Accessibility fallbacks for glass** — `@supports`-guarded opaque surfaces where `backdrop-filter` is unsupported; `prefers-reduced-transparency` drops the frost to opaque navy and hides the animated backdrop; `prefers-reduced-motion` stops the backdrop animation. Light/Mono themes intentionally stay flat (glass is dark-only).

### Changed

- **Distribution surface is pip + Docker** — removed GitHub/`git clone` from the live UI and user-facing docs in favour of `pip install 'ontoforge[wizard]'` and the published `ghcr.io/synaptixs/ontomesh` image. Contributor/security/changelog references to the repo are kept.
- **Wizard navigation** — connected **Build → After-generation** into one continuous linear flow: the Generate step now leads to Evolution Review, and the three post-generation steps gained standard Back/Continue navigation. Log Discovery's "Pipeline at a glance" cards were tokenised (fixes a latent Twilight contrast bug and lets the category colours survive under glass).

### Fixed

- **Report phase crash** — `generate_report()` now creates `output/reports/` before writing, fixing a `FileNotFoundError` when the report phase ran before a phase that created the directory.
- Migrated all `datetime.utcnow()` calls to timezone-aware `datetime.now(timezone.utc)` (the deprecated API is scheduled for removal).

### Internal

- Stopped tracking generated artifacts already covered by `.gitignore` (`db/enterprise.db`, `output/reports/*`, `**/__pycache__/*.pyc`).
- Fixed two stale test assertions (template-registration key, GHCR login-step count) for a clean CI gate — full suite at 1006 passing.

---

## [3.8.0] — 2026-06-07 · Reasoning Search + Ontoforge

First PyPI release under the **`ontoforge`** package name (`pip install ontoforge`). The GitHub repo (`synaptixs/ontomesh`) and GHCR image path (`ghcr.io/synaptixs/ontomesh`) are unchanged; only the pip/console-script name and the docs-site brand move to Ontoforge.

### Added

- **Reasoning Search** — ontology-grounded, LLM-powered search over a connected database. Plans over the ontology vocabulary, executes safe **read-only** SQL (allow-listed, sensitivity-tier gated), derives facts via a forward-chaining Datalog reasoner with `prov:wasDerivedFrom` lineage, auto-loads foreign-key neighbours for multi-hop reasoning, and returns **cited** answers. Surfaces: SDK (`from runtime.reasoning_search import search`), CLI (`ontoforge search`), HTTP (`POST /api/search` + SSE `/api/search/stream`), and the `/ask` console (embedded as a wizard step). Local (Ollama) or cloud (OpenAI). **Flag-gated behind `ONTOFORGE_SEARCH` (default-off).**
- **Live SPARQL subgraph** — materializes the result subgraph as RDF (Turtle + nodes/edges view) and runs a dependency-free minimal SPARQL `SELECT` over it; `POST /api/sparql` + an Ask-console "Build RDF subgraph" toggle.
- **Search observability** — `ontomesh_search_*` Prometheus metrics (requests, latency, rows, derived facts, triples) on the existing `/metrics`; a bundled Grafana dashboard + Prometheus scrape config in `deploy/monitoring/`.
- **Persistent search memory** + a TTL response cache for `/api/search`.

### Changed

- **Package + console scripts renamed** `ontomesh` → `ontoforge` (`ontoforge`, `ontoforge-wizard`, `ontoforge-onboard`). Repo slug and GHCR image name unchanged.
- **Docs site** rebranded to Ontoforge (URL `synaptixs.github.io/ontomesh/` unchanged).

### Fixed

- Property resolution is now naming-convention tolerant: a planner term like `alarmState` resolves to the mapping's `hasAlarmState`, so real-LLM queries ground reliably (`Mapping.resolve()`).

## [3.7.0] — 2026-06-05 · Public release

First public release on PyPI + GHCR (public).  Consolidates the 3.7.0-dev and 3.7.1-dev preview cuts into one tagged release under the new `synaptixs/ontomesh` namespace and Apache-2.0 licence.

### Added

- **Apache-2.0 licence** at `LICENSE`; matching `NOTICE` documents every third-party dependency.
- **`SECURITY.md`** describes the responsible-disclosure process (GitHub Security Advisories + back-up email).
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1.
- **`.github/PULL_REQUEST_TEMPLATE.md`** for incoming contributions.

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
- **Boot banner** now reads "Ontomesh — the ontology mesh for GraphRAG · v3.6.0-dev" with the public surface URLs and active DB URL surfaced; version is pulled from `ontoforge.__version__` so it auto-tracks future bumps.

### Changed

- Package on PyPI renamed `ontology-toolkit` → `ontomesh`. Legacy import aliases are kept for one release.
- Console scripts: `ontomesh`, `ontoforge-wizard`, `ontoforge-onboard` are now the canonical entry points; the legacy `ontology-toolkit` / `ontology-onboard` aliases remain.
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

[3.9.0]: https://github.com/synaptixs/ontomesh/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/synaptixs/ontomesh/compare/v3.7.1...v3.8.0
[3.7.0]: https://github.com/synaptixs/ontomesh/compare/v3.6.0-dev...v3.7.0
[3.6.0-dev]: https://github.com/synaptixs/ontomesh/compare/v3.5.0-dev...v3.6.0-dev
[3.5.0-dev]: https://github.com/synaptixs/ontomesh/compare/v3.4.0-dev...v3.5.0-dev
[3.4.0-dev]: https://github.com/synaptixs/ontomesh/compare/3.3.0...v3.4.0-dev
[3.3.0]: https://github.com/synaptixs/ontomesh/compare/3.2.0...3.3.0
[3.2.0]: https://github.com/synaptixs/ontomesh/compare/3.1.0...3.2.0
[3.1.0]: https://github.com/synaptixs/ontomesh/compare/3.0.0...3.1.0
[3.0.0]: https://github.com/synaptixs/ontomesh/compare/v1.5...3.0.0
[1.5]: https://github.com/synaptixs/ontomesh/releases/tag/v1.5
