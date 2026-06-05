# Path to a public Ontomesh release

Canonical plan for taking Ontomesh from a private repository to a publicly available open-source project.  Living document — edit as the work progresses or scope shifts.

## Objective

Make the toolkit publicly available so a developer anywhere can:

1. Visit `github.com/synaptixs/ontomesh` and read the code.
2. Run `docker run ghcr.io/synaptixs/ontomesh:<tag>` with no authentication.
3. (Optional) `pip install ontomesh` from PyPI.

## Non-goals

- ❌ Multi-tenant hosted SaaS.
- ❌ Public demo URL we operate (costs $, attracts abuse).
- ❌ A defined SLA for security fixes or feature requests.

## Snapshot of where we are

| Surface | State |
|---|---|
| Repository | Private at `github.com/synaptixs/ontomesh` |
| Container image | Private at `ghcr.io/synaptixs/ontomesh:3.7.1-dev` (signed + SBOM-attached + SLSA-attested) |
| License | Apache-2.0 declared in `pyproject.toml`; full text at `LICENSE` |
| Attribution | `NOTICE` ships at repo root |
| Security policy | `SECURITY.md` ships at repo root |
| CONTRIBUTING + CHANGELOG + issue templates | Present and groomed for public audience |
| Identity (personal account) | De-linked: `pyproject.toml` author is `Synaptixs`; CONTRIBUTING points at `SECURITY.md` instead of a personal handle |
| Test suite | 296 SQLite-only + Postgres/Redis-when-sidecar-up tests pass |

## Stages

The work is divided into five stages.  Stages 1–3 take you to "publicly available."  Stages 4–5 amplify discoverability and are optional.

### Stage 1 — Pre-flight cleanup ✅ Done

All committed in the `chore/public-release-prep` branch.

- ✅ License swapped to Apache-2.0; `LICENSE` + `NOTICE` files added.
- ✅ Dependency license audit: every runtime and extra dep is compatible.  psycopg (LGPL-3.0) is documented in `NOTICE` with usage boundaries.
- ✅ Full git-history secret scan via gitleaks: 0 findings across 132 commits.
- ✅ Bundled-data audit: only synthetic demo data ships (`db/enterprise.db`); the dev wizard store and active session are gitignored.
- ✅ "Internal preview" wording replaced; identity de-link complete; `SECURITY.md` added.
- ✅ Examples verified to run end-to-end from a fresh clone.

### Stage 2 — Repo grooming (~1 hour)

| Item | Owner |
|---|---|
| `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1 verbatim | Engineering |
| `.github/PULL_REQUEST_TEMPLATE.md` — checklist for incoming PRs | Engineering |
| Version bump (see decision below) | Engineering |
| CHANGELOG entry for the public release | Engineering |
| README + sidebar pill version refresh | Engineering |
| Test assertions for the new version pin | Engineering |

**Decision: version strategy.**

| Option | What it says to a user | Recommended? |
|---|---|---|
| **A. `0.1.0`** | "This is an early-days OSS release." `pip install ontomesh==0.1.0` reads like Day 1. | ✅ Default choice |
| **B. `3.7.0`** | "This has been worked on for years, here's the real version number." Honest about maturity; risk: newcomers miss the pre-1.0 caveats. | If you don't want to "reset the clock." |

Both work.  When in doubt, pick **A** — it's the convention 95% of OSS-from-private-repo projects follow.

### Stage 3 — Flip the visibility switches (~1 minute, irreversible-ish)

⚠️ Do not run Stage 3 until Stages 1 and 2 are merged and you've sanity-checked the repo state.

```text
A. Repo public:
   https://github.com/synaptixs/ontomesh/settings
   → Danger Zone → Change visibility → Public
   → Type the repo name to confirm

B. Container package public:
   https://github.com/synaptixs/ontomesh/pkgs/container/ontomesh
   → Package settings → Danger Zone → Change visibility → Public
```

**After Stage 3 is done, Ontomesh is publicly available.**

Verification (run from a fresh shell, no docker login):

```bash
docker logout ghcr.io
docker pull ghcr.io/synaptixs/ontomesh:<version>
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:<version>
curl -fsS http://localhost:5051/live
open https://github.com/synaptixs/ontomesh   # works in incognito
```

### Stage 4 — Polish (optional, ~1 week of focused work)

Each item is independent.  Tackle any subset, in any order.

| Item | Description | Effort | Notes |
|---|---|---|---|
| **4a · PyPI publish** | `pip install ontomesh` from PyPI. Requires PyPI account + Trusted Publishing config + a verified-clean wheel build. | 1 day | The largest single polish item. |
| **4b · Documentation site** | mkdocs-material at `docs.<domain>` or GitHub Pages, populated from `docs/` + the `help_content.py` content. | 1 day | Pairs well with PyPI launch. |
| **4c · Domain registration** | `ontomesh.dev` ~$15/yr, `synaptixs.dev` ~$15/yr, `ontomesh.io` ~$40/yr. | 30 min | Not blocking. |
| **4d · Static landing site** | Standalone marketing landing at the domain (the wizard's `/` becomes the *app* landing). | 1 day | Requires 4c first. |
| **4e · PNG social cards** | Twitter, LinkedIn, Slack scrape PNG more reliably than SVG. Render OG + Twitter cards once. | 1 hour | Improves link previews. |
| **4f · Docker Hub mirror** | Publish to `ontomesh/ontomesh` on Docker Hub for discoverability. Docker Desktop searches Hub by default. | 30 min | Worth it for adoption. |
| **4g · Changelog automation** | `release-please` to auto-generate CHANGELOG entries from Conventional Commits. | 2 hours | Nice-to-have. |

### Stage 5 — Launch announcement (optional, ~1–2 days)

| Item | Purpose |
|---|---|
| Draft ~300-word "Show HN" post | Show HN works for dev tools; ML-heavy posts can go to `r/MachineLearning` instead. |
| Pick at most two channels | HN + one of LinkedIn/Twitter/dev.to. Don't spread thin. |
| Watch first 24 hours actively | Respond to comments within an hour on launch day. |
| Capture FAQ items from real questions | Update README / docs / FAQ as themes emerge. |

## What to *not* do during the public release

- ❌ Rewrite git history. Breaks every SHA, every signed tag, every workflow reference. The gitleaks scan came up clean; there's no benefit.
- ❌ Promise an SLA.  "Best-effort, no SLA" is the honest disclosure.
- ❌ Set up a public hosted demo URL.  Costs money, attracts abuse, creates support load.  People can spin up their own via the deploy configs.
- ❌ Accept hostile PRs.  "We're selective about what we merge" is fine to put in `CONTRIBUTING.md`.

## Privacy of the personal account

To prevent your personal GitHub identity from being visible on the public repo, complete these clicks (one-time, ~5 minutes):

| # | URL | Setting |
|---|---|---|
| 1 | https://github.com/settings/emails | ☑ Keep my email addresses private + ☑ Block command line pushes that expose my email |
| 2 | https://github.com/settings/admin | ☐ Uncheck "Include private contributions on my profile" |
| 3 | https://github.com/orgs/synaptixs/people | Find your row → dropdown → Visibility: Private |
| 4 | https://github.com/organizations/synaptixs/settings/member_privacy | Set member privacy default to Private |
| 5 | https://github.com/organizations/synaptixs/settings/profile | Fill in display name "Synaptixs" + description + optional logo |

After these, the public repo will:
- Show commits authored by `<noreply>@users.noreply.github.com`, not your personal email.
- Not advertise the connection between the personal account and the org.
- Not list you as an org member on the public people page.

Historical commits in `git log` will keep whatever author info they were originally created with — rewriting them is not worth the cost.

## Decision log

| Date | Decision | Made by |
|---|---|---|
| 2026-06-04 | Apache-2.0 license (over MIT, BSL) | Engineering |
| 2026-06-04 | Org name: `synaptixs`; repo name: `ontomesh` | Engineering |
| pending | Version strategy: A (`0.1.0`) vs B (`3.7.0`) | TBD |
| pending | Domain to register, or skip for v1.0 | TBD |
| pending | Launch channel(s) | TBD |
| pending | Documentation site host (Pages / readthedocs / netlify) | TBD |

## Reference links

- This repo: https://github.com/synaptixs/ontomesh
- This package: https://github.com/synaptixs/ontomesh/pkgs/container/ontomesh
- Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0
- Contributor Covenant 2.1: https://www.contributor-covenant.org/version/2/1/code_of_conduct/
- Trusted publishing on PyPI: https://docs.pypi.org/trusted-publishers/
- gitleaks: https://github.com/gitleaks/gitleaks
- Keep a Changelog: https://keepachangelog.com/en/1.1.0/
- Semantic Versioning: https://semver.org/spec/v2.0.0.html
