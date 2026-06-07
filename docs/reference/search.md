# Reasoning search

!!! info "Coming soon"
    Ontology-grounded **reasoning search** is in active development and not yet
    part of a released version. The API and CLI below are a preview of what's
    coming — they may change before launch. Watch the
    [repository](https://github.com/synaptixs/ontomesh) for the release.

Ask your database a question in plain English and get a **cited, reasoned
answer** — grounded in the ontology Ontoforge generates from your data, executed
**safely** (read-only) against live records, and runs **locally (Ollama)** or in
the **cloud (OpenAI)**.

## What it will do

- **Plan over the ontology, not raw columns** — the model can only reference
  classes and properties that exist, so it can't invent tables or fields.
- **Reason, not just retrieve** — derive non-obvious facts (impact, eligibility,
  classification) via OWL-RL/Datalog rules, each with `prov:wasDerivedFrom` lineage.
- **Multi-hop** across real relationships in your model.
- **Cite everything** — every claim maps to a source record; the executed query
  is always shown.
- **Stay safe** — read-only, allow-listed, sensitivity-tier gated; safe to point
  at a live database.

## A taste

> *"Which customers are at risk from the degraded core router crt-07, and why?"*
> → derives the impacted customers by walking `Resource → Service → Customer`,
> cross-checks open alarms, and cites each source.

> *"Which enrolled subjects are now ineligible after their latest labs — and why?"*
> → re-checks each subject's latest results against the trial's eligibility
> criteria, flags violations with audit-grade lineage, and keeps PHI on-host.

---

*Want early access or to shape the design? Open a discussion on the
[repo](https://github.com/synaptixs/ontomesh/discussions).*
