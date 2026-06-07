# Pipeline phases

Ontoforge's pipeline is a linear sequence of phases. Each is independently runnable from the CLI and emits artefacts the next phase reads.

```
Build phases (1–8):

   1. Domain          ──┐
   2. Entities          │
   3. Events            │ produce  ontology/<domain>.ttl
   4. Relationships     │
   5. SHACL             │
   6. Generation        │ + shapes/<domain>.shacl
   7. Evolution         │ + jsonld/<domain>.jsonld
   8. Compliance      ──┘ + reports/*.md, csv


Enrichment phases (L4–L13):

   L4   Log discovery (Drain3)
   L5   Sequence learning (HMM per service)
   L6   Causality (Granger / transfer-entropy)
   L7   Co-occurrence (PMI)
   L8   Switching state-space models
   L9   Active-learning ranker
   L10  Calibrated confidence (Variational Bayes)
   L11  Causal DAG (PC algorithm, FastPC)
   L12  Template visualisation (probabilistic PCA)
   L13  Rate anomalies (Gaussian Process)
```

## Build phases (1–8)

| # | Phase | Reads | Writes |
|---|---|---|---|
| 1 | Domain | template YAML or wizard session | `domain_meta.json` |
| 2 | Entities | `domain_meta.json` + edits | `entities.json`, `entity_props.json` |
| 3 | Events | `entities.json` + edits | `events.json` |
| 4 | Relationships | `entities.json`, `events.json` | `relationships.json` |
| 5 | SHACL | all of the above | `shapes/<domain>.shacl` |
| 6 | Generation | `entities.json`, `events.json`, `relationships.json`, `shapes/` | `ontology/<domain>.ttl`, `jsonld/`, `skos/` |
| 7 | Evolution | current + previous TTL | `reports/evolution.md`, `proposals/*.json` |
| 8 | Compliance | TTL + selected frame | `reports/compliance_map.md` |

CLI:

```bash
ontoforge --phase 1            # Domain
ontoforge --phase all          # Run 1–8 end to end
ontoforge --phase 3            # Just regenerate SHACL
```

## Enrichment phases (L4–L13)

Optional. Only relevant when you have log data.

```bash
ontoforge --phase mine         # L4 (Drain3)
ontoforge --phase sequence     # L5 (HMM)
ontoforge --phase causality    # L6 (Granger)
ontoforge --phase all-mining   # L4 through L13
```

Each enrichment phase emits a JSON-LD ObservationRecord that the wizard's Evolution phase consumes to propose ontology changes.

## Composability

Every phase reads a stable on-disk format. You can:

- Re-run a single phase after tweaking inputs.
- Swap a phase for your own implementation (read the same JSON, write the same JSON-LD).
- Skip enrichment entirely if you don't have logs.
- Pipe artefacts to a downstream system (e.g. send `output/jsonld/*.jsonld` to a GraphQL gateway).

The phases are described in detail in [extending.md](../extending.md).
