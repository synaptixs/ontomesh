# Docker

The published image at `ghcr.io/synaptixs/ontomesh:3.10.2` is the standard delivery vehicle.

```bash
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:3.10.2
```

## Persistent run

```bash
docker volume create ontomesh-data
docker run -d --name ontomesh \
  -p 5051:5051 \
  -v ontomesh-data:/data \
  -e ONTOMESH_DATA_DIR=/data \
  ghcr.io/synaptixs/ontomesh:3.10.2
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ONTOMESH_HOST` | `0.0.0.0` | Bind address |
| `ONTOMESH_PORT` | `5051` | Bind port |
| `ONTOMESH_DATA_DIR` | `/data` | Where SQLite + saved ontologies live |
| `ONTOMESH_DB_URL` | unset → SQLite | Postgres URL to switch backend |
| `ONTOMESH_REDIS_URL` | unset → in-memory | Redis URL for the SSE bus |

## Image facts

| | |
|---|---|
| Tag | `3.7.0`, `latest` |
| Size | ~316 MB compressed |
| Architectures | `linux/amd64`, `linux/arm64` |
| Base | `python:3.12-slim` |
| Runtime user | `ontomesh` (uid `10001`, non-root) |
| Healthcheck | `GET /health` every 30 s |
| Signed | cosign keyless OIDC |
| SBOM | SPDX attached as OCI artefact |
| Provenance | SLSA attestation attached |

## Verify the image

```bash
cosign verify ghcr.io/synaptixs/ontomesh:3.10.2 \
  --certificate-identity-regexp='^https://github.com/synaptixs/ontomesh' \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```
