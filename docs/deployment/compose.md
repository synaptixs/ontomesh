# Docker Compose

The [`compose.yml`](https://github.com/synaptixs/ontomesh/blob/main/compose.yml) at the repo root brings up the wizard behind Caddy with automatic TLS.

```bash
curl -O https://raw.githubusercontent.com/synaptixs/ontomesh/main/compose.yml
docker compose up -d
```

What you get:

- **Caddy** terminating TLS with auto-issued Let's Encrypt certs
- **Ontoforge** wizard on the `ontomesh` service
- **Redis** (opt-in `--profile redis`) for multi-worker SSE
- **Postgres** (opt-in `--profile postgres`) for the saved-ontologies store

The SSE proxy is configured with `read_timeout 24h` so live drift / metrics streams survive.

See [`deploy/Caddyfile`](https://github.com/synaptixs/ontomesh/blob/main/deploy/Caddyfile) for the proxy config.
