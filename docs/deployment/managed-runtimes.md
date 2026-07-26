# Managed runtimes

Configs for the three managed runtimes ship at the repo root:

| Runtime | Config file | When |
|---|---|---|
| Fly.io | [`fly.toml`](https://github.com/synaptixs/ontomesh/blob/main/fly.toml) | You want the same machine close to your users |
| Render | [`render.yaml`](https://github.com/synaptixs/ontomesh/blob/main/render.yaml) | You want a one-click deploy with managed Postgres |
| Cloud Run | [`deploy/cloudrun.yaml`](https://github.com/synaptixs/ontomesh/blob/main/deploy/cloudrun.yaml) | You're already on GCP |

All three wrap the same `ghcr.io/synaptixs/ontomesh:3.10.0` image and configure `/live` + `/ready` probes correctly.

The full guide is at [`deploy/README.md`](https://github.com/synaptixs/ontomesh/blob/main/deploy/README.md).
