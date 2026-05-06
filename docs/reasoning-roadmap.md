# Rules & Reasoning — Phased Roadmap

Plan to evolve the toolkit from "ontology generator with a reasoner hook" to "ontology generator with first-class rules, materialised inference, and explanations."

> **Status:** plan only — nothing in this document is implemented yet.

---

## Reasoning today — what's actually there

There is one reasoning hook, but it's narrow.

| Capability | Where | What it does |
|---|---|---|
| **OWL 2 classification** | `src/reasoner.py` | Shells out to ROBOT/ELK/HermiT at generation time. Classifies, snapshots the class hierarchy, diffs it across runs, reports unsatisfiable classes. |
| **Profile recommendation** | `output/ontology/profile_recommendation.md` | Says whether you're EL/QL/RL or need full DL — picks ELK vs HermiT accordingly. |
| **SHACL validation** | `src/shacl_generator.py` | Extensive — but only `sh:NodeShape` + `sh:property` constraints. **No `sh:rule`** (no SHACL-based forward chaining). |
| **SPARQL CQs** | `src/cq_tester.py` | SELECT/ASK queries. Test-shaped, not inference-shaped. |
| **Drift detection** | `src/drift_detector.py` | Hierarchy diffs as a reasoning side-effect. |

The reasoner runs, but it has nothing interesting to chew on. Look at what the generator emits today:

```python
# src/ontology_generator.py — every property reduces to:
"  a owl:ObjectProperty ;"
```

No `TransitiveProperty`, `SymmetricProperty`, `FunctionalProperty`, `inverseOf`, `owl:Restriction`, `equivalentClass`, `disjointWith`, `propertyChainAxiom`, `hasKey`. Without those, ROBOT classifies a flat hierarchy and finds nothing to derive.

**Bottom line:** reasoning isn't really baked in. The infrastructure is, the *axioms aren't*, and rules don't exist at all.

---

## Where the gaps are

1. **Thin TBox.** The wizard captures plain "Customer places Orders" relationships → emits a bare `owl:ObjectProperty`. Cardinality, inverses, transitivity, disjointness, keys — all dropped on the floor.
2. **No rules layer.** Nothing for SWRL, SHACL `sh:rule`, or parametrised SPARQL CONSTRUCT.
3. **No materialization phase.** Even if axioms existed, the toolkit reasons over the schema (TBox), not the live data (ABox). No `--phase reason` that produces `materialised.ttl`.
4. **No "why" trace.** When the reasoner derives something, users can't see which axiom/rule fired with what premises.
5. **No rules in Ontology Studio.** Steps 1–6 don't capture them.

---

## Phase A — Richer axiom emission *from existing wizard inputs*

> Smallest change with the biggest reasoning payoff. Most of these signals are already in the session JSON or one checkbox away.

- **`hasKey`** — primary key columns become `owl:hasKey` axioms (already discoverable from `db_introspector.py`).
- **`FunctionalProperty` / `InverseFunctionalProperty`** — derive from `unique` and `cardinality 1` declarations.
- **`inverseOf`** — when a relationship has a "reverse phrase" sibling (e.g. "owns" / "owned by"), pair them.
- **`TransitiveProperty`** — single checkbox on a relationship: "transitive" (e.g. `partOf`, `subRegionOf`).
- **`SymmetricProperty`** — checkbox: "symmetric" (e.g. `colocatedWith`).
- **`disjointWith`** — opt-in marker on the entity row: "exclusive group" → emit `AllDisjointClasses` for the group.
- **Domain / range** — already inferable from relationship endpoints; just emit them.

That's a one-PR change to `src/ontology_generator.py` plus three small UI affordances on the Relationships and Entities steps. Suddenly ELK has something to do.

**Effort:** ~half a day.
**Output:** richer `enterprise.ttl` — measurable by axiom count + reasoner-inferred subclass count.

---

## Phase B — Materialization phase (`--phase reason`)

> A new pipeline step that runs the reasoner over the generated ontology *and the data* and writes derived triples to disk.

```
output/ontology/
├── enterprise.ttl                      # asserted (existing)
├── enterprise-inferred.ttl             # OWL-derived (ROBOT / ELK / HermiT)
├── inferred-shacl.ttl                  # SHACL rules output (pyshacl)
├── inferred-sparql.ttl                 # SPARQL CONSTRUCT output
└── materialised.ttl                    # union with PROV-O lineage on each triple
```

Three engines, picked per ontology profile:

| Engine | Use for | Cost |
|---|---|---|
| **ROBOT / ELK / HermiT** | OWL axioms (hierarchy, restrictions, property chains in EL) | already integrated |
| **pyshacl `--inference advance` + `sh:rule`** | "If shape matches, then assert these triples" | one dependency, ~5 lines of code |
| **rdflib SPARQL CONSTRUCT** | parametrised pattern-based inference | already a transitive dependency |

Each derived triple gets a `prov:wasDerivedFrom` triple naming the rule/axiom — that's the foundation for Phase D (explain).

**Persisted output:** `materialised.ttl` is what the runtime layer (Insights, retrieval) reads when it needs "the full picture", not just asserted data.

**Effort:** ~2 days.
**Output:** new pipeline phase, `materialised.ttl`, dependency on `pyshacl`.

---

## Phase C — Rules step in Ontology Studio

> A new Step 5.5 between CQs and Generate, structured like Relationships.

Three rule kinds in a single tabbed editor:

- **SHACL rules** — friendly form: `When [class] [matches condition] → assert [property] [value]`.
- **SPARQL CONSTRUCT** — for users who already write SPARQL.
- **OWL axioms** — checkboxes for the simpler shapes (transitive, equivalent class) so users don't write Turtle.

A **starter rules library** per industry, same shape as the YAML templates:

- Telecom: "if NetworkElement is parent of failed element, mark as impacted".
- Healthcare: "if encounter has terminal-illness diagnosis, flag as palliative".
- Finance: "if transaction amount > threshold AND counterparty unknown, flag for review".

**Validation** — every rule must parse and execute against the empty ontology plus a synthetic ABox before it's saved. No saving broken rules.

Stored in `session.rules[]`, picked up by Phase B at generation time.

**Effort:** ~2 days. Starter library matters — budget time for telecom and healthcare templates.
**Output:** new Step 5.5, `session.rules[]` shape, starter library YAMLs.

---

## Phase D — Explain / "why?" trace

> Highest-trust feature. Auditors and domain experts won't accept inferences they can't trace.

For each triple in `materialised.ttl`:

```turtle
:UnitA :impactedBy :OutageEvent42 ;
       prov:wasDerivedFrom [
         :rule "rule-impact-via-hierarchy" ;
         :premises ( :UnitA  :childOf  :SiteA )
                     ( :SiteA :affectedBy :OutageEvent42 ) ;
       ] .
```

In Ontology Studio's Viewer, add a sixth tab — **Materialised** — that lets the user click any inferred triple and see its premises tree.

- ROBOT has `explain` for OWL axioms.
- For SHACL / SPARQL rules, capture the rule-id at execution time and the binding set that satisfied the rule.

**Effort:** ~2 days.
**Output:** new Viewer tab, `prov:wasDerivedFrom` chains in `materialised.ttl`, ROBOT `explain` integration.

---

## Phase E — Wire to Insights (the LLM feature)

> Closing-the-loop step. Insights itself is described in a separate plan; this is the integration point.

### Provider-agnostic by design

Insights must support multiple LLM providers — **OpenAI** and **OCI Generative AI** are the two primary targets, with **Anthropic, Azure OpenAI, AWS Bedrock, Google Vertex, and self-hosted (vLLM / Ollama)** following the same adapter pattern.

```python
class LLMClient(Protocol):
    def chat(self, system: str, user: str,
             schema: dict | None = None,
             model: str | None = None) -> dict: ...
```

Adapters under `runtime/adapters/`:

| Adapter | Auth | Hosting model | Why include |
|---|---|---|---|
| `openai_client.py` | `OPENAI_API_KEY` | OpenAI cloud | Most common starting point; widest model selection. |
| `oci_client.py` | OCI config / instance principal | Customer's own OCI tenancy | Telecom + regulated industries — data residency. Primary alongside OpenAI. |
| `anthropic_client.py` | `ANTHROPIC_API_KEY` | Anthropic cloud | Strong tool-use + structured output; cheap to plug in. |
| `azure_openai_client.py` | Azure AD / API key | Azure tenant | Enterprise customers already on Azure governance. |
| `bedrock_client.py` | AWS SigV4 | AWS account | Same model catalog under AWS data-residency. |
| `vertex_client.py` | GCP service account | GCP project | Same, Google side. |
| `local_client.py` | none | self-hosted (vLLM, Ollama, llama.cpp) | Air-gapped deployments. |

All adapters implement the same `chat()` signature, return the same response shape, and surface the same telemetry (tokens, latency, cost where available). Provider + model are picked **per call** in the UI, not fixed at install time.

### Provider configuration

- Keys live in **environment variables** (or OCI config file / instance principal). Never persisted to the SQLite library, never sent to the browser.
- A `runtime/llm_providers.json` declares which adapters are *available*, their default models, and a per-provider data-residency hint shown in the UI:
  ```json
  {
    "openai":   {"model": "gpt-4o",          "residency": "us-cloud"},
    "oci":      {"model": "cohere.command-r","residency": "tenant-region"},
    "anthropic":{"model": "claude-3-7-sonnet","residency": "us-cloud"}
  }
  ```
- Wizard Settings panel gains a "Providers" section that lists each adapter, its current configuration status (✓ key found / ⚠ not configured), and the residency hint.

### What changes for materialisation

When the LLM gets called:

- **Default grounding** → asserted ontology + 2 KB class summary.
- **Toggle on** → asserted **+ materialised** triples.

The LLM now sees derived knowledge it could never compute itself — transitive impact chains, inferred hierarchy, rule-fired flags. Telecom RCA scenarios in particular get dramatically better here.

The grounding payload is **provider-independent** — same JSON-LD context + class sheet + (optional) materialised triples regardless of which adapter executes the call. This is what makes provider switching cheap.

### Effort + output

**Effort:** ~half a day for the materialisation toggle, on top of the Insights base which ships with the **OpenAI + OCI** adapters as MVP. Anthropic + Azure + Bedrock + Vertex + local each add ~half a day, mostly auth plumbing.
**Output:** `LLMClient` protocol, two-adapter MVP (OpenAI, OCI), provider/model picker in the Insights panel, "include materialised triples" toggle, providers section in Settings.

---

## Recommended ordering

| # | Phase | Effort | Why this order |
|---|---|---|---|
| 1 | **A — Richer axioms** | 0.5 d | Immediate value; the existing reasoner becomes useful overnight. |
| 2 | **B — Materialization** | 2 d | Prerequisite for everything that consumes derived knowledge. |
| 3 | **C — Rules step in Studio** | 2 d | User-facing authoring; needs B to be useful. |
| 4 | **E — Wire to Insights** | 0.5 d | After Insights itself ships. |
| 5 | **D — Explain / why-trace** | 2 d | Hardest; defer until users ask "why did it infer this?". |

---

## What to skip or down-rank

- **SWRL** — fading standard, poor SHACL / SPARQL interop. Stick to SHACL rules + SPARQL CONSTRUCT.
- **Real-time forward chaining** — materialise on a schedule (after each pipeline run, or nightly). Live inference at query time gets expensive fast and most use cases don't need it.
- **Custom rule DSL** — don't invent one. SHACL + SPARQL is enough.
- **Backward-chaining / Datalog engines** — overkill for this toolkit's audience.

---

## Risks worth flagging now

- **OWL 2 EL is what most domains stay in.** It's the cheap profile. Adding `propertyChainAxiom` keeps you in EL; `inverseOf` does **not** — it bumps you to DL. The wizard should tell users when their checkboxes have just changed the profile.
- **Rule explosions.** A bad transitive + symmetric + cardinality combination can blow up materialization time. Add a "size of materialised graph" report as a sanity check after Phase B runs.
- **Sensitivity tiers.** Inferred triples need to inherit the highest sensitivity of their premises — otherwise a Public conclusion can leak Confidential evidence. Add this rule in the materialisation step.
- **LLM data residency.** Sending materialised triples to OpenAI or another public-cloud provider exits the customer's tenancy. The Insights UI must show the active provider's residency hint (`us-cloud`, `tenant-region`, `air-gapped`, etc.) before every call so users aren't surprised. For regulated workloads, OCI Generative AI (in-tenancy) or a local model is the safer default.
- **Hallucinated IRIs.** LLMs invent class and property names that aren't in the ontology. Every Insights response runs through a post-step that validates IRIs against the ontology and either strips or flags unknowns. This applies to every provider — same validator, different adapter.

---

## Out of scope (for now)

- Probabilistic reasoning (Markov logic, Bayesian networks).
- Description Logic learning (concept lattice mining).
- Closed-world reasoning across federated graphs.
- Rule conflict resolution beyond rule-priority ordering.

These are interesting but large undertakings. Revisit once Phases A–E are in production for a quarter.

---

## Open questions to resolve before coding

1. **Materialization storage** — keep `materialised.ttl` as a flat file, or persist into the graph store (Oxigraph / Fuseki) on every pipeline run?
2. **Rule scoping** — are rules per-ontology (saved in the Library row) or global to the toolkit instance?
3. **Hot reload** — should editing a rule in the Studio re-run materialisation immediately, or wait for the next `--phase reason` invocation?
4. **Profile escalation UX** — surface a banner ("This rule changes your profile from EL → DL — slower reasoner") at rule-save time, or only at generation time?
5. **LLM provider defaults** — should new installs default to OpenAI (broadest reach) or OCI (in-tenancy by default)? Affects the Insights onboarding flow and the residency-hint wording.
6. **Adapter ordering for MVP** — OpenAI + OCI are agreed. Which is the third adapter to ship: Anthropic (cheap to integrate), local (self-hosted, demo-friendly), or Azure OpenAI (enterprise governance)?

These are small calls but worth aligning before Phase A starts.
