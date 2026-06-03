# syntax=docker/dockerfile:1.6
#
# Ontomesh — single-container production image (P2.1).
#
# Multi-stage build:
#   • builder  installs build-time deps + the project in editable mode,
#                producing a populated /opt/venv we can copy to runtime.
#   • runtime  is python:3.12-slim with only the runtime venv, the
#                application source, and a non-root user.  The image
#                runs `ontomesh-wizard` and serves on $ONTOMESH_PORT
#                (default 5051).
#
# Build:
#   docker build -t ontomesh:3.6.0-dev .
#
# Run (development — SQLite in an anonymous volume):
#   docker run --rm -p 5051:5051 ontomesh:3.6.0-dev
#
# Run (production — persistent named volume for session + outputs):
#   docker volume create ontomesh-data
#   docker run -d --name ontomesh \
#     -p 5051:5051 \
#     -v ontomesh-data:/data \
#     -e ONTOMESH_DATA_DIR=/data \
#     ontomesh:3.6.0-dev
#
# Healthcheck:
#   The image declares a HEALTHCHECK that hits /health every 30 s.
#   Docker, Compose, and most orchestrators read it directly.


# ── Stage 1: builder ───────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for any wheels that need to compile.  Most of our wheels
# (rdflib, flask, etc.) are pure-Python; this is here so optional DB
# extras (psycopg2-binary, mysql-connector-python) work without rebuild.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Create the runtime virtualenv at a stable path so the runtime stage
# can copy it as-is.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy the full source.  We don't pre-split metadata-only because the
# project's pyproject.toml needs README + the ontomesh/ package present
# during `pip install`.
COPY . .

# Install core + wizard extra in one shot.  Editable so console scripts
# (ontomesh, ontomesh-wizard, ontomesh-onboard) land on PATH and the
# python files stay readable for debugging.
RUN pip install --upgrade pip \
 && pip install -e ".[wizard]"


# ── Stage 2: runtime ───────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ONTOMESH_HOST=0.0.0.0 \
    ONTOMESH_PORT=5051 \
    ONTOMESH_DATA_DIR=/data

# curl powers the HEALTHCHECK; everything else ships in the venv.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root runtime user.  uid 10001 is well above any LDAP-mapped range
# and matches the common k8s securityContext convention.
RUN groupadd --system --gid 10001 ontomesh \
 && useradd  --system --uid 10001 --gid ontomesh \
             --home-dir /app --no-create-home ontomesh

WORKDIR /app

# Pull in the populated venv + the application source from the builder.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app      /app

# Persistent data dir.  Mount a volume here in production.
RUN mkdir -p "${ONTOMESH_DATA_DIR}" \
 && chown -R ontomesh:ontomesh /app "${ONTOMESH_DATA_DIR}"

USER ontomesh

EXPOSE 5051

# Hit /health every 30 s; consider the container unhealthy after 3
# consecutive failures.  start-period gives Flask room to boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://localhost:${ONTOMESH_PORT}/health" || exit 1

# Single-process entrypoint.  Wizard's main() reads --host / --port;
# we pass them via env-var-expanded args so `docker run -e
# ONTOMESH_PORT=8080` works without rebuilding.
ENTRYPOINT ["sh", "-c", "exec ontomesh-wizard --host \"${ONTOMESH_HOST}\" --port \"${ONTOMESH_PORT}\""]
