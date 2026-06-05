# Production hardening

Everything in 3.7.0 (the P3 line) that makes the toolkit production-grade.

| Concern | What's in the box |
|---|---|
| **Application server** | gunicorn with the gthread worker class; 2 workers × 8 threads default; env-var overridable |
| **SSE multi-worker** | Set `ONTOMESH_REDIS_URL` and SSE works across all workers/replicas |
| **Health probes** | `/live` is cheap and dependency-free; `/ready` exercises every dependency and 503s on failure |
| **Logs** | Structured JSON via `python-json-logger`; every request carries a generated or echoed `X-Request-Id`; `/live` and `/ready` excluded from noise |
| **Metrics** | Prometheus `/metrics` endpoint with cardinality-bounded path labels; 5 metric families (HTTP requests counter, request-duration histogram, SSE subscribers gauge, drift events counter, pipeline runs counter) |
| **Image security** | Trivy SARIF scan uploads to GitHub Security; non-root user (`uid 10001`); pinned base image |
| **Supply chain** | cosign keyless OIDC signing; SPDX SBOM + SLSA provenance attached as OCI artefacts |

See the [Production deployment runbook](https://github.com/synaptixs/ontomesh/blob/main/deploy/README.md) for the operational details.
