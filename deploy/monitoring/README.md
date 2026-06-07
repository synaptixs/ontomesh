# Monitoring — Reasoning Search

The wizard already exposes Prometheus metrics at **`GET /metrics`** (wired by
`wizard/metrics_exporter.py`). When `ONTOFORGE_SEARCH` is enabled, reasoning-search
metrics are exported alongside the existing HTTP/pipeline metrics.

## Metrics

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `ontomesh_search_requests_total` | counter | `status`, `provider`, `cached` | Searches by outcome (`ok`/`empty`/`blocked`/`ungrounded`/`error`), LLM provider, and cache hit/miss |
| `ontomesh_search_duration_seconds` | histogram | `provider` | End-to-end search latency (cache misses only) |
| `ontomesh_search_result_rows_total` | counter | — | Rows returned across searches |
| `ontomesh_search_derived_facts_total` | counter | — | Facts derived by the reasoner |
| `ontomesh_search_subgraph_triples_total` | counter | — | Subgraph triples materialized |

These require `prometheus_client` (installed with `ontoforge[wizard]`). Without it,
`/metrics` degrades gracefully and search still works.

## Quick start

1. **Run the wizard** with search on:
   ```bash
   ONTOFORGE_SEARCH=1 ontoforge-wizard --port 5000
   ```
2. **Scrape it** with Prometheus:
   ```bash
   prometheus --config.file=deploy/monitoring/prometheus.yml
   ```
3. **Visualize** in Grafana: add the Prometheus data source, then
   *Dashboards → Import* and upload
   `deploy/monitoring/grafana-reasoning-search.json` (select your Prometheus
   data source when prompted).

The dashboard shows total searches, cache-hit ratio, error rate, p95 latency,
request rate by status, latency quantiles by provider, and reasoning output
(rows / derived facts / subgraph triples).
