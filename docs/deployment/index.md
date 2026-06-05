# Deployment

Five supported targets. They all wrap the same `ghcr.io/synaptixs/ontomesh` image.

| Target | When | Time to first request |
|---|---|---|
| [Docker (single container)](docker.md) | Local dev, evaluation | 30 s |
| [Docker Compose](compose.md) | Single-host with TLS | 2 min |
| [Postgres backend](postgres.md) | Multi-replica + persistent state | Adds to any target above |
| [Managed runtimes](managed-runtimes.md) | Fly.io, Render, Cloud Run | 10 min |
| [Production hardening](production.md) | Anywhere — gunicorn, Redis SSE, metrics, structured logs, image security | Layered on top |
