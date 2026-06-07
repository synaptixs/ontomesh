# Implementation Plan — Direction B (Twilight Navy) + Mono theme

> Branch: `feat/ux-ui-uplift`
> Goal: ship the **Guided Focus** wizard (Direction B) with **Twilight Navy** as
> the default theme and a working **Mono** switch — modern, novice-friendly,
> **functionality unchanged**.
> Reference mockups: `design/mockups/wizard-b-twilight.html`, `landing-b.html`.

## Confirmed decisions (locked)
1. **Themes:** keep a **3-way picker** — **Twilight Navy (default)** + **Mono** +
   **Light**. `THEMES = ['twilight','mono','light']`; Twilight is the default and
   the flash-free first-paint theme. Light is re-skinned to the navy+green
   palette (the calm "Direction A" light treatment), not the old indigo/cyan.
2. **Generated HTML reports:** recolor to the new brand **in this pass** (new
   Phase 6). CSS strings only in the three report generators — no report logic.
3. **Cadence:** plan approved as written; implementation begins on your go.

## Guiding constraints (must hold for every step)
- **No behavior change.** Step IDs (`#step-domain` …), `data-step` values, form
  field names, `/api/*` calls, and the generate pipeline are untouched.
- **Reuse the existing engine.** `goStep(name)` (index.html:1734) stays the single
  navigation entry point; `setTheme(name)` (:1649) stays the theme entry point.
  New chrome *calls* these — it never replaces them.
- **Token-only recolor.** All components read CSS custom properties; the palette
  lives entirely in `tokens.css`.
- **Each phase is independently revertible** and shippable.

## What changes vs. what doesn't
| Changes | Stays exactly as-is |
|---|---|
| `wizard/static/css/tokens.css` (palette/3 themes) | All `.step-panel` content blocks in index.html |
| `wizard/templates/index.html` (chrome + small JS additions) | `goStep()` core, all `/api` handlers, every form |
| `wizard/static/css/wizard.css` (new chrome styles) | Routes, tests, pipeline, session, generate logic |
| `wizard/templates/landing.html` + `landing.css` | The data each report computes/renders |
| `src/reporter.py`, `compliance/dashboard.py`, `runtime/embeddings/dashboard.py` — **inline CSS strings only** | All report *logic* (queries, scoring, table building) |

---

## Phase 0 — Baseline & safety net  *(~15 min)*
1. Confirm branch: `git branch --show-current` → `feat/ux-ui-uplift`. Working tree
   clean except the `design/` mockups.
2. Run the wizard locally to capture a **before** baseline:
   `python wizard/app.py --port 5051` (or `ontoforge-wizard --port 5051`).
3. Screenshot the current wizard (each of the 4 phases' first step), landing, and
   `/projects` in the existing light + dark themes. These are the regression
   reference.
4. Tag the pre-uplift state: `git tag pre-ux-uplift` (easy rollback point).

**Exit check:** wizard boots, a sample domain generates successfully (proves the
pipeline works before we touch anything).

---

## Phase 1 — Token layer: Twilight default + Mono  *(~1–2 h)*
File: `wizard/static/css/tokens.css`

1. Add a named **`[data-theme="twilight"]`** block with the Twilight Navy palette,
   mapped onto the existing semantic token names so no component CSS changes:
   ```
   --bg:#16213d; --surface:#1f2d50; --surface-2:#273a63;
   --text:#eef2f9; --text-2:#b6c4da; --muted:#7d8cab;
   --border:rgba(255,255,255,.09); --border-strong:rgba(255,255,255,.18);
   --accent:#8fd14f; --accent-hover:#a7e06b; --accent-soft:rgba(143,209,79,.15);
   --success:#5fd07a; --warn:#fbbf24; --danger:#f87171;
   --brand:#eef2f9; --brand-mesh:#8fd14f; --brand-bg-soft:#1f2d50; --on-brand:#15203a;
   --on-accent:#15203a;
   ```
2. Add the shared shape/elevation tokens (used by both themes):
   `--radius:18px; --radius-sm:12px; --radius-pill:999px;` and a softer
   `--shadow-2` tuned for the dark canvas.
3. Keep the existing **`[data-theme="mono"]`** block (already high-contrast,
   print-friendly); only bump its radii via the shared tokens and verify the
   green accent isn't introduced there (mono stays monochrome by design).
4. **Light theme (kept — 3-way):** re-skin the existing `:root`/light block to the
   navy+green calm palette (navy ink `#14284a`, scarce green accent `#5aa430`,
   warm-neutral `--bg #f7f9f8`) — i.e. the "Direction A" light treatment, so all
   three themes share one brand. Verify green CTA text hits AA on white (use
   `--accent-hover #4c8c28` for green-on-light text, the brighter green for fills).

**Exit check:** load the existing pages with `<html data-theme="twilight">` —
everything recolors, nothing breaks layout. This alone delivers ~60% of the look.

---

## Phase 2 — Wizard chrome restructure (the core)  *(~4–6 h)*
File: `wizard/templates/index.html` (chrome markup) + `wizard/static/css/wizard.css`

**2a. Markup — replace the left rail, keep the content.** Swap the outer
`<aside class="sidebar">` (index.html:94–150) for the Direction B shell:
- A **top bar**: brand + `▸ All steps` button + save state (`#save-status` keeps
  its id) + Exit. Move the theme picker here or into the drawer.
- A **horizontal 4-phase stepper** (Define · Enrich · Build · After) + a sub-step
  line ("Define · step 2 of 4 — Entities").
- A **slide-in drawer** that contains the **existing `<ul class="step-nav">`
  markup moved verbatim** (same `data-step`, same classes). This is the key move:
  `goStep()` already targets `.step-nav li` and `[data-step]`, so drawer
  highlighting keeps working with **no JS change**.
- A **sticky action bar**: `← Back`, `Skip for now`, `Continue →`.
- `<main class="main">` and **all `.step-panel` blocks stay exactly where they
  are** (index.html:152–1300ish). Only their wrapper chrome changed.

**2b. CSS — add chrome styles to `wizard.css`:** `.top`, `.phases/.ph/.pdot`,
`.drawer/.scrim`, `.actionbar`, `.stage` focus layout, and the per-step
"you-are-here" banner. Port directly from the mockup; all token-driven so Mono
inherits automatically. Keep existing `.card`, `.tabs`, input, and form styles.

**Exit check:** clicking drawer items still drives `goStep()`; all 11 panels show.

---

## Phase 3 — Navigation wiring (small, additive JS)  *(~2–3 h)*
File: `wizard/templates/index.html` `<script>`

1. Define the linear journey + phase map (Library/Settings stay out-of-band,
   reached only via the drawer):
   ```js
   const FLOW = ['domain','entities','events','relationships',
                 'log-discovery','cqs','rules','generate','evolve','comply','retrieve'];
   const PHASE_OF = { /* domain..relationships:'Define', log-discovery..rules:'Enrich',
                         generate:'Build', evolve..retrieve:'After' */ };
   ```
2. Add **`_syncChromeB(name)`**: sets the active phase dot + done states, the
   sub-step counter, the drawer item (already handled by goStep), and the action
   bar's Back/Continue targets + "Up next: …" hint. Disable Back on the first
   step; turn Continue into "⚡ Generate" context on `generate` if desired.
3. **Call `_syncChromeB(currentStep)`** once at the **end of `goStep()`** (one
   line) and once in `init()`. goStep keeps all its existing side-effects
   (`renderSummary`, `refreshLibrary`, preflight, etc.) — we only append.
4. Back/Continue/Skip buttons → `goStep(FLOW[i±1])`. Drawer toggle function.
5. Keyboard/a11y: stepper dots and drawer items keep `role`/`tabindex`; Esc
   closes the drawer; focus moves to `<main>` on step change (preserve existing
   `tabindex="-1"` on main).

**Exit check:** Back/Continue walk the 11-step flow in order; drawer jumps
anywhere; phase stepper tracks correctly; generate still runs.

---

## Phase 4 — Theme switch: Twilight ⇄ Mono  *(~1 h)*
File: `wizard/templates/index.html`

1. `const THEMES = ['twilight','mono','light'];` (3-way, per decision).
2. `_initTheme()` default → `setTheme('twilight')` when nothing is stored. Keep
   reading `localStorage('wizard-theme')` so a returning user's Light/Mono choice
   sticks. (System `prefers-color-scheme` no longer forces a theme; Twilight is
   the deliberate default — note this in a code comment.)
3. Update the theme-picker buttons (index.html:137–145) to **Twilight · Mono ·
   Light** with correct `data-theme-name` (and matching icons/labels).
4. Set `<html data-theme="twilight">` in the template so first paint is correct
   before JS runs (no flash).
5. Verify the brand wordmark reads in Mono (existing `grayscale(1)` filter) and in
   Twilight (may need the light wordmark variant instead of a filter — see Phase 6).

**Exit check:** toggling Twilight/Mono restyles the entire chrome (stepper,
drawer, action bar, cards) via tokens; choice persists across reload; the
relationship graph re-reads vars and recolors (goStep/setTheme already handle it).

---

## Phase 5 — Landing page (Direction B)  *(~2–3 h)*
Files: `wizard/templates/landing.html`, `wizard/static/css/landing.css`
1. Set landing to `data-theme="twilight"`; restyle to the centred dark hero +
   product-preview + 3-phase "how it works" stepper from `landing-b.html`.
2. Recolor the inline hero SVG (indigo/cyan → navy lines + green threads/glow).
3. Keep all copy, links, routes, and the copy-install button behavior.

**Exit check:** landing matches the wizard's Twilight palette; nav links resolve.

---

## Phase 5b — Generated report theming  *(~2–3 h)*
Files: `src/reporter.py`, `compliance/dashboard.py`, `runtime/embeddings/dashboard.py`
> Reports are **standalone, single-palette HTML** (opened directly from
> `output/reports/`), not theme-switchable like the wizard. Re-skin their inline
> CSS to the navy+green brand. **CSS strings only — zero report logic, no change
> to what data is rendered.**
1. Replace the gradient headers, badge colors, and score-bar fills in each
   generator's inline `<style>` block with the brand palette (navy headers, green
   accents/score bars; keep PASS/FAIL/severity colors semantically distinct from
   brand green — green must not read as "success" on a status badge).
2. Pick **one** report surface to make the canonical light brand treatment
   (`toolkit_report.html`) and mirror it to the compliance + retrieval reports so
   all three match.
3. Regenerate the demo reports under `output/demo/` to refresh the committed
   examples.

**Exit check:** a fresh `generate` produces reports in the new brand; status
badges remain unambiguous (no green/success collision).

---

## Phase 6 — Brand assets, accessibility & polish  *(~2–3 h)*
1. **Brand SVGs** (`static/brand/`): recolor wordmark/mark to navy + green; add a
   light-ink wordmark for Twilight if the CSS filter looks off. OG/Twitter cards:
   regenerate later (low priority, non-blocking).
2. **Accessibility pass:**
   - Green (`#8fd14f`) on Twilight bg + as button text on `--on-accent #15203a`
     must hit **WCAG AA 4.5:1** — verify with a contrast checker; nudge if short.
   - Step/phase state never color-only: keep ✓ glyph + visible labels.
   - Preserve `prefers-reduced-motion` (drawer/stepper transitions off) and
     `:focus-visible` rings.
   - Drawer: focus trap while open, Esc to close, `aria-expanded` on the toggle.
3. **Other surfaces:** check `projects.html`, `error.html`, `phase_help.html`,
   `log_discovery_help.html` inherit the new tokens cleanly (they should — all
   token-driven). Patch any hard-coded indigo/cyan hex.

---

## Phase 7 — Verification  *(~1–2 h)*
1. Boot the wizard; click through **all 11 steps** via both the stepper/Continue
   and the drawer. Confirm each panel renders and its actions work.
2. Run a **full generate** on a sample domain (telecom/healthcare); open the
   generated `toolkit_report.html`, compliance, and retrieval reports — confirm
   they render acceptably (report CSS is separate/inline; recolor is optional and
   can be a follow-up).
3. Toggle **Twilight ⇄ Mono** on every surface; reload to confirm persistence.
4. Responsive check (≤860px): stepper stacks, drawer overlays, action bar wraps.
5. Run the existing test suite (`pytest`) — should pass untouched since no `.py`
   changed.
6. Capture **after** screenshots; diff against the Phase 0 baseline.

---

## Phase 8 — Commit & PR  *(~30 min)*
Commit in reviewable slices on `feat/ux-ui-uplift`:
1. `feat(ui): navy+green Twilight/Mono/Light design tokens` (Phase 1)
2. `feat(wizard): Direction B guided-focus chrome (stepper + drawer + action bar)` (Phases 2–3)
3. `feat(wizard): default to Twilight theme, 3-way picker` (Phase 4)
4. `feat(landing): Direction B Twilight landing` (Phase 5)
5. `style(reports): recolor generated HTML reports to brand (CSS only)` (Phase 5b)
6. `chore(brand): recolor wordmark/mark + a11y polish` (Phase 6)

Open a PR with before/after screenshots and an explicit "no functional changes;
the only `.py` edits are inline report CSS strings (no logic)" note. Keep the
`design/` mockups + analysis in the PR as the design rationale.

---

## Effort & risk summary
| Phase | Effort | Risk | Revertible alone |
|---|---|---|---|
| 0 Baseline | 15 min | none | n/a |
| 1 Tokens | 1–2 h | very low | ✅ |
| 2 Chrome | 4–6 h | moderate (markup) | ✅ |
| 3 Wiring | 2–3 h | moderate (JS) | ✅ |
| 4 Theme switch | 1 h | low | ✅ |
| 5 Landing | 2–3 h | low | ✅ |
| 5b Reports | 2–3 h | low | ✅ |
| 6 Brand/a11y | 2–3 h | low | ✅ |
| 7 Verify | 1–2 h | — | — |
| **Total** | **~3 focused days** | — | — |

**Biggest risk:** the index.html chrome swap (Phase 2) — `index.html` is 6.1k
lines, so the edit must surgically replace only the `<aside class="sidebar">`
block and add the new shell, leaving all `.step-panel`s intact. Mitigated by the
fact that `goStep`/`setTheme` are untouched and the drawer reuses existing markup.

## Status
All scoping decisions resolved (see **Confirmed decisions** at top). Plan is
approved-as-written; **awaiting go to start Phase 0**.
