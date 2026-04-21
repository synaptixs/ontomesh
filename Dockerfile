# Ontology Engineering Toolkit — multi-stage Docker image
# Stage 1: build deps; Stage 2: slim runtime

FROM python:3.12-slim AS base

LABEL maintainer="Ontology Toolkit Team"
LABEL description="Domain-Agnostic Ontology Engineering Toolkit v2.0 (Phase 3)"

WORKDIR /app

# System deps for optional DB drivers and NLP
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install core Python deps (skip heavy optional drivers unless needed)
RUN pip install --no-cache-dir \
    rdflib>=7.0.0 \
    pyshacl>=0.26.0 \
    sparqlwrapper>=2.0.0 \
    requests>=2.32.3 \
    pyyaml>=6.0.2 \
    flask>=3.0.3 \
    flask-cors>=4.0.1 \
    spacy>=3.7.4 \
    && python -m spacy download en_core_web_sm \
    && pip install --no-cache-dir anthropic>=0.34.0 openai>=1.40.0

# Copy project source
COPY . .

# Create output directory
RUN mkdir -p output/ontology output/shapes output/vocab output/jsonld \
             output/mapping output/reports output/security db

# Pre-seed database
RUN python toolkit.py --phase 1 || true

EXPOSE 5000

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

CMD ["python", "toolkit.py"]
