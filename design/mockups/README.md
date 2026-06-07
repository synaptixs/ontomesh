# Ontomesh — design direction mockups

Self-contained, openable HTML mockups (no backend, no build). Double-click any
file or open it in the Launch preview panel. **These are visual prototypes with
mock data — not wired to the real app.** Real functionality is unchanged.

| File | Surface | Direction |
|---|---|---|
| [`landing-a.html`](landing-a.html) | Landing | **A — Calm Editorial** (light, navy ink, scarce green CTA, airy ElevenLabs-style) |
| [`wizard-a.html`](wizard-a.html) | Wizard | **A — Refined Rail** (keeps the left rail; adds top progress bar + sticky "next action" footer) |
| [`landing-b.html`](landing-b.html) | Landing | **B — Guided Focus** (dark navy-black, green glow, centred hero + product preview) |
| [`wizard-b.html`](wizard-b.html) | Wizard | **B — Guided Focus** (4-phase stepper, one-step-at-a-time focus mode, "All steps" drawer) |

## The navigation-flow difference (the key contrast you asked about)

**Direction A — evolution.** The familiar left rail stays (power users keep
jump-anywhere navigation always visible), but it's made legible for novices:
- a slim **progress bar** ("4 / 11 steps") at the top of the rail
- unmistakable **done (navy ✓) / active (green) / upcoming (muted)** states
- a **"you are here" banner** + a sticky **"Continue to Events →"** footer so the
  single next action is never ambiguous.

**Direction B — reinvention.** The 11-item rail collapses into a horizontal
**4-phase stepper** (Define · Enrich · Build · After). The user sees **one step
at a time** with big Back / Continue / Skip — a true guided wizard. Power users
click **"▸ All steps"** to open a drawer that restores full jump-anywhere
navigation. Most novice-friendly; bigger change to the shell.

Both keep every existing step, route, and capability — only the *pacing and
presentation* of the path changes.

---

## If you'd rather iterate in Claude (claude.ai) — ready-to-paste prompts

### Prompt — Landing page
```
Design a modern marketing landing page for "Ontomesh — the ontology mesh for
GraphRAG", a developer tool that mines ontologies from logs, validates with
SHACL, and ships a hybrid retriever. Build it as a single self-contained
responsive HTML file with inline CSS (no frameworks).

Aesthetic: clean and calm like elevenlabs.io — generous whitespace, large tight
display type, soft large corner radii (~16px), subtle layered shadows, pill
buttons. Brand palette from the logo: deep navy (#14284a) as the calm ink/frame,
lime-green (#7dc242 / #8fd14f) as a single SCARCE accent used only for the
primary CTA and the active/mesh-thread elements. Fonts: Inter + Inter Tight for
display, JetBrains Mono for code.

Sections, in order: sticky nav (wordmark + Product/Docs/Projects/GitHub + a green
"Open the wizard →" CTA); a hero (kicker pill, big "The ontology mesh for
GraphRAG." headline with "GraphRAG" in green, one-line subhead, primary CTA + a
`pip install ontoforge` code pill, and an abstract mesh-graph SVG illustration in
navy with green threads); an open-standards trust strip (OWL 2, SHACL, SPARQL,
JSON-LD, SKOS, Datalog); a 3-card "What you can build" grid; a 3-step "How it
works" flow (Discover → Model & validate → Generate & ship); and a navy final
CTA band. Keep copy confident and quiet. WCAG AA contrast.
```

### Prompt — Wizard
```
Design a guided multi-step wizard UI for "Ontomesh" as a single self-contained
responsive HTML file with inline CSS + minimal vanilla JS (no frameworks).

The wizard has 11 steps grouped into 4 phases: Define (Domain Identity, Entities,
Events, Relationships), Enrich (Log Discovery, Competency Questions, Rules &
Reasoning), Build (Generate), and After generation (Evolution Review, Compliance,
Vector Retrieval). Plus a Library entry and Settings.

Goal: make it effortless for a NOVICE while preserving power-user free
navigation. Use a GUIDED FOCUS layout: a top bar with the wordmark and an
"▸ All steps" button; a horizontal 4-phase stepper showing done/active/upcoming;
ONE step shown at a time in a centred focus area with a friendly "you are here"
banner (current phase, one-line explanation, optional/required tag); and a sticky
bottom action bar with Back / Skip / a prominent green "Continue →" plus a "next:
<step name>" hint. The "All steps" button opens a slide-in drawer listing all 11
steps grouped by phase for jump-anywhere navigation.

Aesthetic: dark, premium navy-black canvas (#0b1220) with soft green glow,
lime-green (#8fd14f) as the single accent for CTAs/active state, navy ink.
Generous whitespace, ~16-18px radii, soft shadows, pill buttons. Fonts: Inter +
Inter Tight, JetBrains Mono for code. Mock the "Entities" step as the live
example (name + plural + description inputs, an "Add entity" button, and a list
of 3 entity chips). WCAG AA contrast; don't rely on color alone for step state.
```

> Tip: paste each prompt into a fresh Claude conversation and ask for an HTML
> artifact. Then say "now make a light, calm-editorial variant" to get the
> Direction A counterpart, or vice-versa.
