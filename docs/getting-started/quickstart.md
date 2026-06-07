# Quickstart

Five minutes from `docker run` to an exported, SHACL-validated ontology you can drop into a GraphRAG retriever.

## 0 · Run the wizard

```bash
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:latest
```

Open **http://localhost:5051**.

## 1 · Pick a starter

On first launch, the welcome modal offers ten starter industries. Pick **Telecom**.

The session is now seeded with a real TMF-aligned ontology — ~280 classes, ~1,400 properties, ~150 SHACL shapes. You can edit any of them; the wizard guides you through 11 steps to produce a validated output bundle.

## 2 · Walk the eleven steps

| Step | What it does |
|---|---|
| 1 — Domain | Pin scope, sensitivity tier, regulatory frame |
| 2 — Entities | Inspect / extend the seed entity catalogue |
| 3 — Events | Define lifecycle, state-change, and metric events |
| 4 — Relationships | Wire entities and events via OWL object properties |
| 5 — Log discovery | (Optional) Mine entity hints from sample log lines |
| 6 — Competency questions | Capture the questions the ontology must answer |
| 7 — Rules | SWRL / Datalog enrichment rules |
| 8 — Generate | Materialise OWL, SHACL, JSON-LD, SKOS, report |
| 9 — Evolution | Drift signals + proposed evolutions |
| 10 — Compliance | Map to GDPR / HIPAA / DORA / ISO 27001 / TMF |
| 11 — Vector retrieval | Build a hybrid (BM25 + dense) retriever over the ontology |

## 3 · Inspect the output

Click **Generate** at step 8 — the wizard writes to `/data/output/`:

```
output/
├── ontology/
│   ├── enterprise.ttl              # OWL Turtle
│   ├── enterprise-inferred.ttl     # OWL-RL materialised
│   └── materialisation_report.md
├── shapes/
│   ├── enterprise.shacl
│   └── _combined.ttl
├── jsonld/
│   └── enterprise.jsonld
├── skos/
│   └── enterprise-vocab.ttl
└── reports/
    ├── cq_enterprise.csv           # Competency questions
    └── compliance_map.md
```

## 4 · Verify SHACL passes

```bash
docker exec ontomesh ontoforge --phase 3
# →  ✓ SHACL validation passed.  0 violations, 0 warnings.
```

## 5 · Use it from your retriever

```python
from rdflib import Graph
g = Graph().parse("/data/output/ontology/enterprise.ttl", format="turtle")

# Find every class with sensitivity tier ≥ 3:
sensitive = g.query("""
    PREFIX : <https://ontology.example.com/enterprise/>
    SELECT ?cls ?label WHERE {
        ?cls a owl:Class ;
             :sensitivityTier ?tier ;
             rdfs:label       ?label .
        FILTER (?tier >= 3)
    }
""")
```

Or wire it into the SDK:

```python
from runtime import HybridRetriever

r = HybridRetriever(flavor="retail", db_path="/data/db/enterprise.db")
r.retrieve("active service order in retention period")
```

!!! tip "Reasoning Search"
    For ontology-grounded reasoning over a connected database — cited answers,
    derived facts, and a live SPARQL subgraph — see
    [Reasoning Search](../reference/search.md).

## Next steps

- [Concepts → Pipeline phases](../concepts/pipeline.md) — understand what each phase actually does.
- [Deployment → Docker Compose](../deployment/compose.md) — bring up the wizard behind Caddy with auto-TLS.
- [Reference → SDK](../sdk.md) — embed the toolkit in a larger Python app.
