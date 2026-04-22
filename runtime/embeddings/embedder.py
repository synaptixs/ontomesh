"""
runtime.embeddings.embedder — Workstream 5
============================================
Embedding-model abstraction with zero-install defaults.

The production-friendly path is ``sentence-transformers/all-MiniLM-L6-v2``
(local) or ``text-embedding-3-small`` (OpenAI), both of which require
third-party dependencies.  To keep the toolkit runnable with the Python
standard library alone, we ship a deterministic 384-dim hash-bucket
embedder that preserves the semantic distance ordering of bag-of-words
overlap.  That is enough to unit-test the full ontology-bounded
retrieval pipeline end-to-end without network access or extra wheels.

Model IDs:

  * ``hash-local-384`` — default; stdlib SHA-256 bucketed bag-of-words.
  * ``sentence-transformers/all-MiniLM-L6-v2`` — if the library is
    installed, we delegate; otherwise we fall back to ``hash-local-384``.
  * ``text-embedding-3-small`` — OpenAI; requires ``OPENAI_API_KEY``.
  * Any model whose ID starts with ``allenai/`` — treated as a
    sentence-transformers model.

The fall-back is deliberate: benchmark numbers in the toolkit report are
reproducible on a fresh checkout.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Callable, Dict, List, Optional


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_DEFAULT_DIM = 384


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _hash_embed(text: str, dim: int = _DEFAULT_DIM) -> List[float]:
    """Deterministic hash-bucket embedding.

    For each token we derive two bucket indices from SHA-256 and
    accumulate ±1 weights.  The result is L2-normalised so that dot
    product == cosine similarity.  This captures token overlap and
    roughly preserves the ranking order of two documents relative to
    a third — enough for retrieval benchmarks against small corpora.
    """
    vec = [0.0] * dim
    for tok in _tokenize(text):
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        # 4 buckets per token for higher coverage
        for j in range(4):
            idx = int.from_bytes(h[j * 2: j * 2 + 2], "little") % dim
            sign = 1.0 if (h[j * 2 + 1] & 1) == 0 else -1.0
            vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0.0:
        vec = [v / norm for v in vec]
    return vec


def _openai_embed(text: str, model: str) -> List[float]:  # pragma: no cover
    """Delegate to OpenAI if installed and ``OPENAI_API_KEY`` is set;
    otherwise fall back to the local hash embedder so the toolkit
    remains runnable in offline CI."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return _hash_embed(text)
    if not os.environ.get("OPENAI_API_KEY"):
        return _hash_embed(text)
    client = OpenAI()
    resp = client.embeddings.create(model=model, input=text)
    return list(resp.data[0].embedding)


def _sentence_transformers_embed(text: str, model: str) -> List[float]:  # pragma: no cover
    """Delegate to sentence-transformers if installed; otherwise fall
    back to the local hash embedder."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        return _hash_embed(text)
    mdl = SentenceTransformer(model)
    return [float(x) for x in mdl.encode(text, normalize_embeddings=True)]


# Model registry: id → (dim, embed_fn).  Callable signature: (text) -> list[float]
MODEL_REGISTRY: Dict[str, Dict] = {
    "hash-local-384": {
        "dim": _DEFAULT_DIM,
        "fn":  lambda txt: _hash_embed(txt, _DEFAULT_DIM),
        "description": "Deterministic local SHA-256 bucketed bag-of-words embedder.",
    },
    "sentence-transformers/all-MiniLM-L6-v2": {
        "dim": 384,
        "fn":  lambda txt: _sentence_transformers_embed(
                   txt, "sentence-transformers/all-MiniLM-L6-v2"),
        "description": "Sentence-Transformers local encoder (auto-fallback if uninstalled).",
    },
    "text-embedding-3-small": {
        "dim": 1536,
        "fn":  lambda txt: _openai_embed(txt, "text-embedding-3-small"),
        "description": "OpenAI small embedding (auto-fallback if uninstalled).",
    },
    "allenai/scibert_scivocab_uncased": {
        "dim": 768,
        "fn":  lambda txt: _sentence_transformers_embed(
                   txt, "allenai/scibert_scivocab_uncased"),
        "description": "Pharma/biomed domain embedder (auto-fallback).",
    },
}


def resolve_model(model_id: Optional[str]) -> Dict:
    """Return the registry entry for a model ID.

    Unknown models are treated as sentence-transformers paths and
    transparently fall back to ``hash-local-384`` if the library is
    not installed — the returned ``dim`` is still ``_DEFAULT_DIM`` in
    that case so that downstream shape checks remain consistent.
    """
    if not model_id:
        return MODEL_REGISTRY["hash-local-384"]
    if model_id in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_id]
    # Unknown model — treat as sentence-transformers and fall back to hash
    return {
        "dim": _DEFAULT_DIM,
        "fn":  lambda txt: _sentence_transformers_embed(txt, model_id),
        "description": f"Unknown model '{model_id}' — auto-fallback to local hash embedder.",
    }


def embed_text(text: str, model_id: Optional[str] = None) -> List[float]:
    """Embed *text* using *model_id* (or the default hash embedder)."""
    entry = resolve_model(model_id)
    return entry["fn"](text)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity of two equal-length vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    num  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return num / (na * nb)
