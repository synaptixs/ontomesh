"""
runtime.embeddings — Workstream 5 (Gen2): Ontology-Bounded Vector Retrieval
===========================================================================

The OWL class hierarchy becomes a hard semantic filter on vector similarity
search.  Where RAG retrieves whatever is numerically closest in embedding
space, ontology-bounded retrieval first constrains the search population
by OWL class expression, then ranks within it by vector similarity.

Public entry points:

  * :mod:`runtime.embeddings.pipeline`     — index ontology-typed records
  * :mod:`runtime.embeddings.class_filter` — translate SPARQL class
                                             expressions into metadata filters
  * :mod:`runtime.embeddings.embedder`     — deterministic + pluggable
                                             embedding model registry
  * :mod:`runtime.embeddings.adapters`     — vector-store adapters
                                             (Qdrant · Chroma · Weaviate · pgvector · in-memory)
  * :mod:`runtime.embeddings.benchmark`    — precision/recall/latency suite

CLI:
    python3 toolkit.py --phase embed --flavor network-ops
    python3 toolkit.py --phase retrieve --flavor network-ops \\
        --question "Which NFs are degraded?" --top-k 5
    python3 toolkit.py --phase retrieve --benchmark
"""

from __future__ import annotations

from .pipeline     import index_flavor, reindex_all  # noqa: F401
from .class_filter import (                           # noqa: F401
    resolve_class_hierarchy, build_metadata_filter,
)
from .embedder     import embed_text, MODEL_REGISTRY  # noqa: F401
from .adapters     import get_adapter                 # noqa: F401

__all__ = [
    "index_flavor", "reindex_all",
    "resolve_class_hierarchy", "build_metadata_filter",
    "embed_text", "MODEL_REGISTRY",
    "get_adapter",
]
