# Drift monitoring

Ontomesh integrates with [`drift-monitor`](https://github.com/synaptixs/infodrift) for production drift surveillance.

## How it composes

```
production data  ──►  drift-monitor  ──►  ObservationRecord
                                            │
                                            ▼
                                       Ontomesh L10
                                            │
                                            ▼
                                       Evolution proposal
                                            │
                                            ▼
                                       Wizard step 9 (Evolution review)
```

- **drift-monitor** computes PSI / KL / Wasserstein on each feature in your production pipeline.
- It emits `ObservationRecord` JSON-LD objects whose IRI references the corresponding OWL class.
- The Evolution phase reads those records and proposes ontology evolutions — new class, widened range, retired property.

## Install the integration

```bash
pip install 'ontomesh[drift]'
```

This pulls `drift-monitor` from the `synaptixs/infodrift` GitHub repository.

See [`examples/infodrift/`](https://github.com/synaptixs/ontomesh/tree/main/examples/infodrift) for a complete example.
