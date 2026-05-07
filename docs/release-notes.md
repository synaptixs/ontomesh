# Release Notes

## v3.1 — Rules & Reasoning

> **Theme:** turn the toolkit's narrow "ontology generator with a reasoner hook" into "ontology generator with first-class rules, materialised inference, explanations, and grounded LLM Insights."

This release implements the entire roadmap in [docs/reasoning-roadmap.md](reasoning-roadmap.md) — Phases A through E — plus a follow-up suite of authoring affordances (slot-fill builder, test-fire preview, premise tree, NL drafting, rule-impact heat map, conversational drawer).

**171 tests, all green.** No breaking changes to the existing pipeline; every addition is opt-in.

---

### What's new

#### A. Richer OWL axioms from existing wizard inputs

The generator now emits axioms the reasoner can actually chew on:

- **`owl:hasKey`** — opt-in via the `has_key_columns` metadata column.
- **`owl:FunctionalProperty`** — auto-emitted for every FK-backed object property (one row references at most one parent).
- **`owl:TransitiveProperty` / `owl:SymmetricProperty` / `owl:InverseFunctionalProperty`** — flagged via the new `is_transitive` / `is_symmetric` / `is_inverse_functional` metadata columns.
- **`owl:inverseOf`** — pair object properties via the new `inverse_of` metadata column.
- **`owl:AllDisjointClasses`** — opt-in via the new `disjoint_group` metadata column, plus auto-emitted for sibling event subclasses (mutually exclusive by `event_type`).
- **Profile detector escalation** — `inverseOf` / `SymmetricProperty` / `InverseFunctionalProperty` now correctly bump the recommendation to OWL 2 DL with a clear rationale.

Existing `ontology_metadata` rows continue to work unchanged — the new columns are tolerated as `NULL` on legacy databases.

#### B. Materialisation phase — `python toolkit.py --phase reason`

A new pipeline step that runs three pure-Python inference engines and writes their output to disk:

- **OWL-RL closure** — rdflib + owlrl
- **SHACL `sh:rule`** — pyshacl in advanced mode
- **SPARQL CONSTRUCT** — `output/sparql_rules/*.rq`

Outputs land under `output/ontology/`:

```
enterprise-inferred.ttl       # OWL-RL derivations
inferred-shacl.ttl            # SHACL sh:rule outputs
inferred-sparql.ttl           # SPARQL CONSTRUCT outputs
materialised.ttl              # union of asserted ⊕ derived
materialised-lineage.ttl      # per-triple prov:wasDerivedFrom (Phase D)
materialisation_report.md     # triple counts, blow-up ratio, sensitivity audit
```

ROBOT is **not** required — Phase 2's existing ROBOT integration is untouched, and Phase B falls back to pure Python so the toolkit always produces materialised triples regardless of host setup.

#### C. Rules step in Ontology Studio (Step 5.5)

A new wizard step between CQs and Generate. Authors edit rules in three flavours:

- **SHACL** rules with a friendly slot-fill builder *(new in v3.1)* — target class, conditions, assertion. The textarea is optional ("Source" tab).
- **SPARQL CONSTRUCT** for users who already write SPARQL.
- **OWL axioms** for raw Turtle fragments.

Every rule is **validated before save** — broken rules cannot be persisted. Each rule round-trips as `session.rules[]` and is exported to disk before `--phase reason` runs (`output/shapes/rules.ttl`, `output/sparql_rules/<id>.rq`).

A starter library ships for **telecom**, **healthcare**, and **finance** at [templates/rules/](../templates/rules/).

#### D. Explain / why-trace

Every derived triple carries `prov:wasDerivedFrom` lineage in `materialised-lineage.ttl`:

- **SPARQL** — full bindings + WHERE-clause premises captured per match.
- **SHACL** — per-shape attribution with focusNode binding.
- **OWL-RL** — coarse engine-level attribution (the closure doesn't expose per-triple premises; ROBOT-explain integration is a future refinement).

The wizard's **Ontology Viewer → Materialised tab** lets users:

- Filter triples by engine / rule.
- Click any derived triple to see its derivation chain.
- **Premise tree** *(new in v3.1)* — `<details>`-driven recursive view: click a premise to drill into *its* lineage (lazy fetch, max depth 4, per-triple cache).

#### E. Provider-agnostic LLM Insights

A new layer wires the ontology to the LLM you already trust:

- **Provider catalogue** at [runtime/llm_providers.json](../runtime/llm_providers.json) — OpenAI, OCI Generative AI, Anthropic, Vertex AI, Local (Ollama). Default model + **residency hint** per provider (us-cloud / tenant-region / gcp-region / air-gapped).
- **Settings → Providers panel** shows ✓ / ⚠ status with a clear "key not set" / "SDK not installed" reason per provider.
- **Ask Insights** — question grounded in the asserted ontology by default; toggle on to include materialised triples (Phase B). Residency warning surfaces before sending materialised triples to a public-cloud provider.
- **Hallucinated-IRI filter** — every response is checked against the ontology vocabulary; unknown IRIs are flagged in the UI.

Adapters are unchanged from v3.0 — Insights wraps them so the same call works regardless of which provider is active.

---

### Authoring affordances (graphical / NL)

Building on Phase E, v3.1 also ships a suite of features that make rule authoring feel like the rest of the wizard:

| # | Feature | What it does |
|---|---|---|
| F1 | `GET /api/ontology/vocabulary` | mtime-cached classes + properties from `enterprise.ttl` — fuel for every UI feature below. |
| #3 | **Slot-fill SHACL builder** | When [class] [matches condition] → assert [property] [value]. Eight operators (`=`, `!=`, `>=`, `<`, `regex`, `in`, `exists`, `not_null`). Generated source visible in a "Show source" disclosure. |
| F2 | `POST /api/rules/preview` | Single-rule preview engine — compiles, runs against a synthetic ABox, returns derived triples + lineage. |
| #6 | **Test-fire button** | Every rule row has Test fire; results panel shows count, table of derived triples (subject / predicate / object / bindings) + premises, with an empty-state hint when the rule fires but produces nothing. |
| #5 | **Premise tree** | Recursive `<details>` viewer on the Materialised tab. |
| #1 | **Draft from English** | Per-rule modal: NL textarea → LLM → SHACL/SPARQL/OWL body, with grounded/unknown IRI breakdown. Standard vocabularies (`sh:`, `owl:`, `xsd:`) are not flagged as hallucinations. |
| #7 | **Rule-impact heat overlay** | The Relationships graph tints classes by how many rules touch them (cool → hot). Click a node → popover lists the rules with a one-click jump to the Rules editor. Legend shows `N/M classes covered`. |
| #2 | **NL summary on every rule** | One-sentence English summary persisted on the rule, shown as the primary label in the rule list. ↻ summarise re-runs at any time. |
| #8 | **Conversational drawer** | A single "Build from English" surface that drafts (#1), test-fires (#6), and highlights the touched classes on a mini graph (#7) in one round trip. Accept lands the rule and auto-summarises (#2). |

The corresponding canvas-style node-graph rule editor (suggestion #4 in our roadmap discussion) was deliberately deferred — the slot-fill builder and the conversational drawer cover the same authoring use cases without the maintenance cost of a full graph editor.

---

### Migration notes

- **Schema:** running this release against an old `ontology_metadata` table just works. New columns default to `NULL` and the introspector tolerates their absence. To enable the Phase A signals on an existing database, run the schema DDL in [db/schema.sql](../db/schema.sql) — the new columns are `is_transitive`, `is_symmetric`, `is_functional`, `is_inverse_functional`, `inverse_of`, `disjoint_group`, `has_key_columns`.
- **Pipeline:** `--phase all` now includes `reason` after `shacl`. Existing `--phase 2` invocations are unchanged.
- **Wizard sessions:** old sessions load fine; `rules` defaults to `[]` and `nl_summary` to `""`.
- **Adapters:** no signature change. Existing OpenAI / OCI / Anthropic / Vertex / Ollama adapters are wrapped, not modified.

---

### Files added or substantially extended

```
src/materializer.py                 # Phase B + D
src/vocabulary.py                   # F1
runtime/insights.py                 # Phase E + #1 + #2 + #8
runtime/llm_providers.json          # Phase E
wizard/rules.py                     # Phase C + #3 + F2 + #7
wizard/templates/index.html         # all UI surfaces above
templates/preview_abox.ttl          # F2 / #6
templates/rules/{telecom,healthcare,finance}.yaml  # Phase C starter library
docs/reasoning-roadmap.md           # plan
docs/release-notes.md               # this file
tests/test_phase_a_axioms.py        # 8 tests
tests/test_phase_b_materializer.py  # 7 tests
tests/test_phase_c_rules.py         # 16 tests
tests/test_phase_d_explain.py       # 6 tests
tests/test_phase_e_insights.py      # 10 tests
tests/test_vocabulary_and_slots.py  # 18 tests (F1 + #3)
tests/test_rule_preview.py          # 7 tests (F2 + #6)
tests/test_nl_rule_drafter.py       # 10 tests (#1)
tests/test_rule_coverage.py         # 8 tests (#7)
tests/test_nl_summary.py            # 7 tests (#2)
tests/test_convo_rule.py            # 5 tests (#8)
```

---

### Limits / known gaps

- **OWL-RL premises are empty** in lineage — owlrl runs as a single closure pass and doesn't expose which axiom produced each triple. Phase D records engine-level attribution; per-triple premises arrive when ROBOT-explain integration ships.
- **SPARQL premise extraction is best-effort** — only basic graph patterns are captured. FILTERs, OPTIONALs, and sub-SELECTs are not reflected as premises (lineage shows engine + bindings instead).
- **Test-fire tempdirs are not auto-cleaned** — each preview leaves ~50 KB under `$TMPDIR`. macOS auto-cleans these; Linux users may want to wrap the helper in `tempfile.TemporaryDirectory` if it matters.
- **OWL slot-fill builder is not yet implemented** — slot-fill currently covers SHACL only. SPARQL and OWL kinds use the source textarea (with NL drafting available).
- **Mini-graph in the conversational drawer is a snapshot** — editing Step 2 entities while the drawer is open won't auto-refresh the graph; reopen to see the new state.

---

### Documentation

- [docs/reasoning-roadmap.md](reasoning-roadmap.md) — the original plan.
- [docs/runtime.md](runtime.md) — runtime layer + adapter contracts.
- [docs/integrate.md](integrate.md) — 5-minute path; no changes required.
