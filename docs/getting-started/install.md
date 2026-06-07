# Install

Three supported installation paths, in order from "least effort" to "most customisable".

## 1. Docker (fastest path to running)

The published image at `ghcr.io/synaptixs/ontomesh:3.7.0` is multi-arch (`linux/amd64` + `linux/arm64`), runs as a non-root user, and bundles every default extra needed to open the wizard.

```bash
# Ephemeral (resets when the container stops):
docker run --rm -p 5051:5051 ghcr.io/synaptixs/ontomesh:latest

# Persistent (saved ontologies survive restarts):
docker volume create ontomesh-data
docker run -d --name ontomesh \
  -p 5051:5051 \
  -v ontomesh-data:/data \
  -e ONTOMESH_DATA_DIR=/data \
  ghcr.io/synaptixs/ontomesh:latest
```

Then open **http://localhost:5051**.

### Verify what you pulled

The image is cosign-signed by GitHub Actions OIDC — anyone can verify, offline:

```bash
cosign verify ghcr.io/synaptixs/ontomesh:3.7.0 \
  --certificate-identity-regexp='^https://github.com/synaptixs/ontomesh' \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

The image also ships an SPDX SBOM and SLSA provenance attestation as OCI artefacts:

```bash
docker buildx imagetools inspect ghcr.io/synaptixs/ontomesh:3.7.0 \
  --format '{{ json .SBOM }}'
```

## 2. From PyPI (when published)

!!! info "Coming soon"

    PyPI publish lands in 3.7.1.  Track at [issue #44](https://github.com/synaptixs/ontomesh/issues).

```bash
pip install ontoforge                 # core only — small footprint
pip install 'ontoforge[wizard]'       # adds Flask + the wizard UI
pip install 'ontoforge[wizard,postgres,runtime]'   # production-ish
ontoforge-wizard                       # launches the wizard
```

## 3. From source (for contributors)

```bash
git clone https://github.com/synaptixs/ontomesh.git
cd ontomesh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[wizard,test]"
pytest tests/ -q              # 297+ tests should pass
ontoforge-wizard               # starts the wizard at :5051
```

## Optional extras

The package ships with a set of optional extras you can compose:

| Extra | Adds | When you need it |
|---|---|---|
| `wizard` | Flask, flask-cors, gunicorn, jsonschema, prometheus-client, python-json-logger | Running the wizard UI |
| `postgres` | psycopg2-binary + psycopg3 | Postgres backend for the saved-ontologies store |
| `mysql`, `mssql`, `oracle`, `db2` | Respective drivers | Schema introspection against those engines |
| `runtime` | anthropic, openai, google-cloud-aiplatform, requests, oci | LLM adapters used at runtime |
| `mining` | drain3, hmmlearn, statsmodels, scikit-learn | Log mining phases (L4–L13) |
| `drift` | drain3 (plus a follow-on `pip install git+https://github.com/synaptixs/infodrift.git` for `drift-monitor` itself) | Production drift monitoring |
| `discover` | spaCy | Log-entity discovery |
| `neptune` | boto3 | AWS Neptune graph backend |
| `redis` | redis-py | Multi-worker SSE bus |
| `test` | pytest | Running the test suite |
| `all` | every runtime/drift/wizard/db extra | Convenience aggregate |

For the full list see [`pyproject.toml`](https://github.com/synaptixs/ontomesh/blob/main/pyproject.toml).
