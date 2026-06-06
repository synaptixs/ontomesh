# Ontomesh — UX/UI Uplift Analysis

> Branch: `feat/ux-ui-uplift` · Scope: visual + usability modernization of the
> Flask wizard surfaces. **No functional, route, or data-flow changes.**
> Reference aesthetic: [elevenlabs.io](https://elevenlabs.io). Palette anchor:
> the navy + lime-green brand mark (not exclusive to those two colors).

---

## 1. What we're working with (current state)

The good news: this is **not** a from-scratch redesign. Ontomesh already ships a
genuinely solid, modern foundation:

| Asset | Location | State |
|---|---|---|
| Design tokens (3 themes: light / dark / mono) | `wizard/static/css/tokens.css` | Mature, semantic, well-commented |
| Wizard chrome (sidebar, steps, cards, forms) | `wizard/static/css/wizard.css` (727 ln) | Clean, token-driven |
| Marketing landing | `wizard/static/css/landing.css` (392 ln) + `templates/landing.html` | Good structure, indigo/cyan brand |
| Wizard app shell | `templates/index.html` (6,127 ln) | Single-page, sidebar + step panels |
| Projects dashboard | `templates/projects.html` (528 ln) | Saved-ontology list |
| Brand assets | `wizard/static/brand/*.svg` | Wordmark, mark, OG/Twitter cards |

**Current brand:** indigo `#4f46e5` primary + cyan `#06b6d4` "mesh thread."
**Typography:** Inter (UI) + Inter Tight (display) + JetBrains Mono (code).
**Architecture strength:** every component reads from `--token`s. Re-theming the
entire product = editing **one file** (`tokens.css`). This is the single most
important fact in this analysis — it makes the color uplift low-risk.

### Information architecture (already sound)
The wizard sidebar groups 11 steps into a clear journey:
`Library → **Define** (Domain · Entities · Events · Relationships) → **Enrich**
(Log Discovery · CQs · Rules) → **Build** (Generate) → **After generation**
(Evolution · Compliance · Retrieval) → Settings`. The phase dividers and
"Phase X of 3" hints are strong novice-friendly choices already in place.

---

## 2. Gap analysis vs. the ElevenLabs aesthetic & novice usability

The ElevenLabs look is defined by a few concrete traits. Here's where Ontomesh
stands against each, and what to change.

| ElevenLabs trait | Ontomesh today | Gap → Action |
|---|---|---|
| **Calm, near-monochrome canvas** with one confident accent | Indigo + cyan dual-brand, fairly saturated | Re-anchor to navy ink + a single green accent. Reduce competing hues. |
| **Generous whitespace**, airy sections | `main` padding `36px 40px`; tight-ish card spacing | Increase section rhythm, card padding, and vertical gaps. |
| **Large, tight display type** | Inter Tight present but display sizes modest | Scale hero/H2, tighten letter-spacing, raise line-height contrast. |
| **Soft, large corner radii** (cards ~16–20px) | `--radius: 10px` | Bump radii on cards/buttons/modals for a softer, current feel. |
| **Subtle, layered shadows** (not hard borders) | Borders carry most separation | Lean more on soft shadows + lighter borders. |
| **Pill buttons, high-contrast primary CTA** | Rounded-rect buttons | Increase button radius; make primary CTA the one loud element. |
| **Quiet, confident microcopy** | Already strong & friendly | Keep; extend plain-language pattern to remaining dense panels. |

### Novice-friendliness gaps (functionality stays identical)
1. **First-run orientation** — a novice landing on `/wizard` sees 11 steps at
   once. Already mitigated by phase dividers; strengthen with a one-line
   "You are here / what happens next" banner and clearer "optional" tagging.
2. **Progress legibility** — step state (done/active/locked) relies on subtle
   color. Make completion and "current" states more obviously distinct.
3. **Empty states** — guide novices with a friendly illustration + single next
   action rather than a blank panel.
4. **Primary action clarity** — every step should make "the one thing to do
   next" unmistakable (single high-contrast CTA, secondary actions muted).
5. **Plain-language consistency** — the Domain/Entities/Relationships steps
   already explain themselves in plain English; mirror that tone on the denser
   Rules, Compliance, and Retrieval panels.

---

## 2b. Navigation flow (the journey, not just the layout)

The original analysis covered *information architecture* (how steps are grouped)
but under-covered *navigation flow* (how a user moves through them). Closing that
gap here, since it's the biggest novice lever.

**Today:** a fixed 240px left rail lists all 11 steps + dividers at once, with
free jump-anywhere navigation. Great for power users; **overwhelming for a
first-timer** — everything competes for attention and nothing says "do this now."

Two flow directions are mocked up under `design/mockups/` so you can feel the
difference rather than read it:

| | **Direction A — Refined Rail** (`*-a.html`) | **Direction B — Guided Focus** (`*-b.html`) |
|---|---|---|
| Theme | Light, calm editorial | Dark, premium navy-black |
| Wizard nav | Keep the powerful left rail, but: bolder phase grouping, a slim **top progress bar** (% through the journey), unmistakable done/active/upcoming states, and a sticky **"next action"** footer | Collapse to a horizontal **4-phase stepper**; show **one step at a time** with big Back / Continue; a "▸ All steps" drawer restores jump-anywhere for power users |
| Best for | Mixed audience; minimal behavior change | Novices; a true guided "wizard" feel |
| Migration risk | Low (rail already exists) | Moderate (new focus-mode shell) — still purely presentational |
| Keeps free navigation? | Yes, always visible | Yes, via the drawer |

Both preserve every existing step, route, and capability — they only change how
the path is *presented and paced*.

## 3. Proposed palette (navy + green, ElevenLabs-calm)

> **Direction confirmed (2026-06-05):** brand lime-green (`~#5aa430` / `#7dc242`)
> is the single loud accent; navy is the calm frame. Green stays scarce —
> reserved for CTAs, active step, and the hero mesh threads.


Derived from the brand mark, tuned for WCAG AA contrast. These map **directly**
onto the existing token names — drop-in replacements in `tokens.css`.

### Light theme (default)
| Token | Now | Proposed | Note |
|---|---|---|---|
| `--bg` | `#f6f7f9` | `#f7f9f8` | barely-warm neutral, slight green undertone |
| `--surface` | `#ffffff` | `#ffffff` | keep |
| `--text` | `#0f172a` | `#0f1b2d` | navy-ink, not pure slate |
| `--accent` | `#4f46e5` | `#5aa430` | brand green, AA on white (CTA, active) |
| `--accent-hover` | `#4338ca` | `#4c8c28` | |
| `--accent-soft` | indigo 8% | `rgba(90,164,48,0.10)` | active nav / chips |
| `--accent-2` | `#a855f7` | `#1f3a5f` | navy as secondary node/graph color |
| `--brand` | `#4f46e5` | `#16284a` | **navy** = primary brand ink |
| `--brand-deep` | `#3730a3` | `#0e1b34` | |
| `--brand-mesh` | `#06b6d4` | `#7dc242` | **green** = the "mesh thread" accent |
| `--brand-bg-soft`| `#eef2ff` | `#eef5e7` | soft green wash for marketing bands |
| `--success` | `#16a34a` | `#15803d` | nudge so success ≠ brand green |

> **Why navy as `--brand` and green as the `--accent`/`--brand-mesh`:** navy is
> the stable, trustworthy frame (nav, wordmark, large type); green is the
> energetic "do this" signal (CTAs, active step, the mesh threads in the hero
> art). This matches the mark, and keeps green as a *scarce* color so CTAs pop —
> exactly the ElevenLabs discipline of one loud accent on a calm field.

### Dark theme (navy-black canvas)
| Token | Proposed | Note |
|---|---|---|
| `--bg` | `#0b1220` | deep navy-black (vs current cool `#0a0c10`) |
| `--surface` | `#111a2b` | |
| `--accent` | `#8fd14f` | brighter green for dark-bg contrast |
| `--brand` | `#cbd6e6` | light navy-tint wordmark ink |
| `--brand-mesh` | `#9be35a` | luminous green threads |

> Success/warn/danger semantic colors stay close to current values — they must
> remain distinct from the new brand green to preserve status legibility.

### Shape & elevation tokens
```
--radius:    14px;   /* was 10 — softer cards/inputs   */
--radius-sm: 10px;   /* was 7                          */
--radius-pill: 999px;/* new — primary CTAs & chips      */
/* slightly deeper, softer ambient shadow for the airy feel */
--shadow-2: 0 1px 2px rgba(15,27,45,.04), 0 10px 28px rgba(15,27,45,.07);
```

---

## 4. Recommended changes, grouped by risk (all visual-only)

### Tier A — Pure token swap (zero markup change, instant product-wide reskin)
- Rewrite the three theme blocks in `tokens.css` with the navy+green palette.
- Bump `--radius` / `--radius-sm`, add `--radius-pill`, soften shadows.
- Update the two SVG hero/art fills in `landing.html` (`#4f46e5`/`#06b6d4` →
  navy/green) and the `radialGradient` stop colors.
- **Impact:** entire wizard, landing, projects, and report chrome reskin at once.
- **Risk:** very low. No JS, no routes, no template logic touched.

### Tier B — Typographic & spacing rhythm (CSS-only)
- Scale display type (hero H1, section H2) up; tighten tracking.
- Increase `main` padding and inter-section gaps on the landing page.
- Raise card padding (`22px → 26–28px`) and grid gaps.
- Make primary buttons pill-shaped; ensure exactly one primary CTA per view.
- **Risk:** low. Confined to `landing.css` / `wizard.css`.

### Tier C — Novice-friendly affordances (small, additive markup)
- **"You are here" step banner** at the top of each wizard panel: current phase,
  one-line "what this does," and a muted "optional / required" tag. Reuses the
  existing `nav-hint` copy pattern — purely presentational.
- **Sharper step states** in the sidebar: clearer done (✓ + green), active
  (filled green pill), and upcoming (muted) treatments via existing
  `.step-nav li.done/.active` hooks.
- **Friendlier empty states** for Entities/Events/Relationships before the user
  adds anything: icon + one sentence + the single primary action.
- **Risk:** low–moderate. Additive DOM + CSS only; no handlers, no data changes.
  Each is independently revertible.

### Out of scope (explicitly NOT doing)
- No framework migration (stays Flask + Jinja + vanilla JS).
- No route, API, session, or pipeline changes.
- No copy rewrites that change meaning; only tone-matching on dense panels.
- No build tooling added.

---

## 5. Accessibility guardrails (verify during implementation)
- Green CTA text/background must hit **WCAG AA (4.5:1)** — `#5aa430` on white is
  borderline for small text; use it for fills with white text, and the darker
  `--accent-hover` for green text on light surfaces.
- Don't encode step state in color alone — pair with the ✓ glyph and label
  (already partly done).
- Preserve existing `prefers-reduced-motion` and focus-visible handling.
- Re-check dark-theme wordmark filter (`invert + hue-rotate`) still reads right
  after the navy ink change; may need a dedicated dark wordmark instead of a
  filter.

---

## 6. Suggested implementation order
1. **Tier A** token swap → screenshot every surface (landing, wizard, projects,
   a generated report) light + dark. Confirm nothing breaks, get sign-off on the
   new color feel. *(This alone delivers ~70% of the visual uplift.)*
2. **Tier B** type/spacing polish on landing first (highest-visibility surface),
   then wizard chrome.
3. **Tier C** novice affordances, one at a time, each verified in the browser.
4. Regenerate brand SVGs / OG cards in the new palette (separate, low-priority).

Every tier is shippable on its own and fully revertible. Recommend landing
Tier A as the first PR so the color direction can be reviewed before investing
in B and C.

---

## 7. Files that will change (for reviewers)
| File | Tier | Nature |
|---|---|---|
| `wizard/static/css/tokens.css` | A | palette + radius + shadow tokens |
| `wizard/templates/landing.html` | A | inline SVG art fill colors only |
| `wizard/static/css/landing.css` | B | type scale, spacing, pill CTAs |
| `wizard/static/css/wizard.css` | B/C | spacing, step-state, empty-state styles |
| `wizard/templates/index.html` | C | additive "you are here" banners, empty states |
| `wizard/static/brand/*.svg` | A (later) | recolor wordmark/mark/cards |

No `.py`, route, or test files are touched.
