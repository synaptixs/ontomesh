# Ontomesh — Deployment guide

This directory holds the deployment artifacts for the four production
paths Ontomesh supports. Pick the one that matches your team's
existing infrastructure.

| Target | File | Best for | Setup |
|---|---|---|---|
| **Single container** | `/Dockerfile` | Quick demo · local trial · CI smoke | `docker build . && docker run` |
| **Docker Compose** | `/compose.yml` + `Caddyfile` | Internal tool on one host · self-hosted with TLS | `docker compose up -d` |
| **Fly.io** | `/fly.toml` | Global Anycast · scales to zero · cheapest production hosted | `flyctl deploy` |
| **Render** | `/render.yaml` | Easiest "git push to deploy" · managed Postgres on-tap | Blueprint Sync via dashboard |
| **Cloud Run** | `deploy/cloudrun.yaml` | GCP shops · scales to zero · pair with Cloud SQL | `gcloud run services replace` |

All five wrap the **same** P2.1 `Dockerfile`. The image is built
once and then deployed wherever; nothing is re-engineered per target.

## Picking a target

### "I want to try it" → Single container

```bash
docker build -t ontomesh:3.6.0-dev .
docker run --rm -p 5051:5051 ontomesh:3.6.0-dev
# open http://localhost:5051
```

### "I want my team to use it" → Compose

```bash
docker compose up -d
# wizard at http://localhost (Caddy auto-TLS for real domains)
```

Add Postgres later with `docker compose --profile pg up -d`.

### "I want a URL my customer can hit" → managed runtime

Three flavours, all good. Pick by ergonomic preference:

- **Fly.io** — purest "Docker image on global Anycast" model. Best
  SSE behaviour. Has its own Postgres offering. CLI-driven.
- **Render** — dashboard-driven, "git push to deploy". Blueprint Sync
  reads `render.yaml` and creates everything for you. Slightly more
  expensive than Fly at the entry tier.
- **Cloud Run** — if you're already on GCP. Scales to zero. Stateless
  by default — pair with Cloud SQL Postgres or every restart loses
  the SQLite data.

### "I want to deploy to our k8s cluster" → not in this directory

That's P2.5 (Helm chart) — landing in a future branch. For now, take
the Dockerfile, write your own Deployment + Service + Ingress, and
plumb `ONTOMESH_DB_URL` to your existing Postgres.

## Database backend

All four targets default to **SQLite-on-volume**. This works fine for
single-replica deployments. For anything multi-replica or where you
need centralised backups, set `ONTOMESH_DB_URL`:

```bash
# Local Postgres:
ONTOMESH_DB_URL=postgresql://ontomesh:secret@localhost:5432/ontomesh

# Cloud-managed (Fly Postgres example):
ONTOMESH_DB_URL=postgres://ontomesh:secret@ontomesh-db.flycast:5432/ontomesh
```

Each target's config file has comments showing where to plug this in.

## SSE notes

Ontomesh's `/api/events/stream` is a Server-Sent Events endpoint.
All four targets handle SSE correctly in their default config:

- **Fly.io** — Anycast proxy doesn't buffer streaming responses.
- **Render** — same.
- **Cloud Run** — streaming HTTP works; `timeoutSeconds: 300` in
  the manifest gives 5 minutes of keep-alive headroom.
- **Caddy** — `read_timeout 24h` in `deploy/Caddyfile` keeps
  long-lived connections open.

If you're putting an additional reverse proxy in front (CDN,
hardware LB, nginx ingress), check that streaming responses aren't
buffered — the most common cause of "the wizard never shows live
drift events" in production.

## Health endpoint

Every target's healthcheck hits `GET /health`, which returns a
200 with `{ ok: true, timestamp: ... }`. Don't put auth on this
path.
