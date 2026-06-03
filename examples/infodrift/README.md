# infodrift × ontology-toolkit — integration demo

This example shows how to integrate **[`drift_monitor`](https://github.com/nrohilla-fibonacci/infodrift) (the package formerly known as *infodrift*)** with the ontology-toolkit, where the toolkit's OWL ontology is the *source of truth* for production drift monitoring — not a separate hand-written config.

## Why this matters (the real-world case)

Most ML drift tooling treats "what to monitor" as a separate config concern: a YAML listing entities, baselines, thresholds. That config drifts away from your real data model the moment the schema changes.

In a toolkit-driven setup the ontology already *describes* every monitorable thing — Order, Customer, Invoice, Shipment, AMF/SMF/UPF, etc. — with proper class hierarchy, cardinalities, and SHACL constraints. Reusing that as the registry means:

- **No duplicate entity lists.** Add a class to the ontology → it's eligible for monitoring automatically.
- **Schema enforcement comes free.** The same SHACL shapes that gate API payloads gate production frames before drift sees them.
- **Drift events join the lineage graph.** Each alert becomes a JSON-LD/PROV-O `ObservationRecord` keyed back to the OWL individual — the same observation store as the rest of the toolkit's outputs. SPARQLable alongside provenance.
- **Escalation follows the model.** When `Order/1` drifts, the OWL class graph tells you that `Invoice/1` is a sibling of the same parent class and likely needs eyes on it too.

## What the demo does

The script `scripts/demo_infodrift.py` runs end-to-end against the retail seed data:

| Phase | What runs | What it shows |
|-------|-----------|---------------|
| 1 | `OntologyDriftMonitor` reads `output/demo/ontology/enterprise.ttl` | Every OWL individual under the retail namespace becomes a `drift_monitor` entity — no separate registry |
| 2 | `SHACLGate` against `output/demo/shapes/enterprise-shapes.ttl` | A malformed production frame is rejected *before* drift sees it |
| 3 | Two production windows: `W1_stable` and `W2_black_friday` | Stable window → no/few alerts. Black Friday window inflates `amount` 3-4× and adds category `D` → PSI fires, alerts emitted |
| 4 | `DriftEnricher` | Each alert wrapped in JSON-LD + PROV-O using the toolkit's context, appended to `output/infodrift/observations.jsonl` |
| 5 | `OWLPropagator` | When `Order::1` drifts, sibling individuals (e.g. `Invoice::1`) are surfaced for escalation |

## Run it

From the repo root:

```bash
./examples/infodrift/demo_infodrift.sh           # idempotent
./examples/infodrift/demo_infodrift.sh --fresh   # rebuild ontology + observations
```

The script will:
1. build `db/demo.db` (if absent),
2. run `toolkit.py` to produce `output/demo/` (if absent),
3. run `examples/infodrift/scripts/demo_infodrift.py`.

Direct Python invocation also works once the toolkit has run once:

```bash
python3 examples/infodrift/scripts/demo_infodrift.py
```

## Prerequisites

```bash
pip install -r requirements.txt
```

This installs `drift_monitor` (the renamed infodrift package), `rdflib`, `pyshacl`, `pandas`, `numpy`, and the rest of the toolkit deps.

Quick sanity check:

```bash
python3 -c "from drift_monitor import DriftOrchestrator; print('drift_monitor ok')"
python3 -c "from runtime.drift import OntologyDriftMonitor; print('toolkit-side ok')"
```

## Expected output (abbreviated)

```
▸ 1/5  Ontology-driven entity discovery (P2)
  ontology                 output/demo/ontology/enterprise.ttl
  namespace                https://ontology.example.com/retail#
  individuals found        12
    · Customer::1
    · Customer::2
    · Order::1
    · Order::2
    · …
  registered               4

▸ 2/5  SHACL input gate (P3) — reject malformed prod frames
  shapes                   output/demo/shapes/enterprise-shapes.ttl
  malformed frame          REJECTED: SHACLValidationError

▸ 3/5  Two production windows: stable vs. Black Friday surge

  ── window=W1_stable  (stable) ──
    Customer::1           alerts=0   psi=0.014    level=ok
    Order::1              alerts=0   psi=0.022    level=ok
    …

  ── window=W2_black_friday  (Black Friday surge) ──
    Customer::1           alerts=2   psi=0.487    level=critical
    Order::1              alerts=2   psi=0.512    level=critical
    …

▸ 4/5  OWL propagation (P5) — siblings to escalate
  Order::1 drifted → propagator surfaces 3 dependent(s):
    → Invoice::1
    → Invoice::2
    → Customer::1

▸ 5/5  Summary
  observations written     output/infodrift/observations.jsonl
  records                  8
```

## Where to look afterwards

- `output/infodrift/observations.jsonl` — every drift alert as a JSON-LD record. Each `@id` is an IRI under the retail namespace; `@type` is the OWL class; `prov:wasGeneratedBy` ties it to a specific monitoring run.
- `output/demo/ontology/enterprise.ttl` — the OWL graph that drove discovery.
- `output/demo/shapes/enterprise-shapes.ttl` — the same shapes the runtime `OutputGate` uses for LLM responses now also gate production drift inputs.

## Integrating in your own pipeline

Minimal pattern (after `toolkit.py` has produced `output/<flavor>/`):

```python
from runtime.drift import (
    OntologyDriftMonitor, SHACLGate, DriftEnricher, OWLPropagator,
)

mon = OntologyDriftMonitor(
    ontology_path="output/<flavor>/ontology/enterprise.ttl",
    namespace="https://ontology.example.com/<flavor>#",
)
mon.register_all(baseline_features=your_baselines,
                 numeric_features=[...], categorical_features=[...])

gate = SHACLGate(shapes_path="output/<flavor>/shapes/enterprise-shapes.ttl",
                 namespace="https://ontology.example.com/<flavor>#")
enricher = DriftEnricher(
    context_path="output/<flavor>/jsonld/enterprise-context.json",
    obs_db_path="output/<flavor>/observations.jsonl",
    entity_namespace="https://ontology.example.com/<flavor>#",
)
propagator = OWLPropagator(
    ontology_path="output/<flavor>/ontology/enterprise.ttl",
    namespace="https://ontology.example.com/<flavor>#",
)

# In your serving loop:
prod_df = gate.validate(prod_df, entity_key)            # P3
alerts  = mon.run(entity_key, prod_df=prod_df, window_id="2026W18")  # P2
for a in alerts:
    enricher.enrich_and_store(                          # P4
        {"entity_key": entity_key, "psi_score": a.value,
         "drift_level": a.severity},
        baseline_id="2026Q1", window_id="2026W18",
    )
    for d in propagator.propagate(a):                   # P5
        watchlist.add(d)
```

That's it — the ontology you already generated drives every step.
