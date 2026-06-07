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

Two steps — `drift-monitor` itself isn't on PyPI yet (it's installed straight from the [`synaptixs/infodrift`](https://github.com/synaptixs/infodrift) repository), and PyPI policy bans `pip install` from pulling git+VCS URLs through a published package, so we keep the two halves separate:

```bash
pip install 'ontoforge[drift]'                                            # the PyPI half: drain3 + glue
pip install git+https://github.com/synaptixs/infodrift.git@develop       # drift-monitor itself
```

When `drift-monitor` ships to PyPI we'll fold this into a single install.

See [`examples/infodrift/`](https://github.com/synaptixs/ontomesh/tree/main/examples/infodrift) for a complete example.
