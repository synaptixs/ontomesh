# Log mining

The L4–L13 enrichment phases turn raw application logs into ontology-evolution signals.

| Phase | Algorithm | What it surfaces |
|---|---|---|
| L4 | Drain3 template clustering | Frequent log templates |
| L5 | Per-service HMM | Anomalous state sequences |
| L6 | Granger causality + transfer entropy | Which services drive which |
| L7 | PMI co-occurrence | Implicit entity co-mentions |
| L8 | Switching state-space models | Regime-aware anomaly detection |
| L9 | Active-learning ranker | Surfaces the highest-signal templates first |
| L10 | Variational Bayes | Calibrated confidence on inferred entities |
| L11 | PC algorithm + FastPC | Causal DAG over services |
| L12 | Probabilistic PCA | Visualises template clusters |
| L13 | Gaussian Process | Rate anomalies in event streams |

Output is a stream of JSON-LD ObservationRecords that the **Evolution review** step (build phase 7) reads.

The design rationale is in [`docs/log-rca-roadmap.md`](https://github.com/synaptixs/ontomesh/blob/main/docs/log-rca-roadmap.md).
