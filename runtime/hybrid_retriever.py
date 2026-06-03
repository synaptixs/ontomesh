"""
runtime.hybrid_retriever — Workstream 5, Component 3
=====================================================
Hybrid query executor that combines ontology-bounded vector search
with SPARQL-shaped record retrieval.

Execution path for one call::

    question → class_expression → metadata_filter
             → question_embedding
             → adapter.search(embedding, filter, k*over_fetch)
             → graph enrichment (pull full JSON-LD per result)
             → composite ranking  (vector × confidence × recency)
             → top-k JSON-LD payload

``RuntimeClient.ask(..., retrieval="hybrid", class_expression=...)``
delegates here; the hybrid retriever can also be driven standalone
for evaluation and benchmarking.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flavor_registry import FlavorRegistry
from embeddings.adapters     import get_adapter
from embeddings.class_filter import (
    build_metadata_filter, passes_filter,
)
from embeddings.embedder     import embed_text


_DEFAULT_DB = os.path.join(_ROOT, "db", "enterprise.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────
# Composite scoring
# ─────────────────────────────────────────────────────────────────────


def _recency_weight(indexed_at: Optional[str], now: float) -> float:
    """30-day half-life recency weight — identical to memory layer."""
    if not indexed_at:
        return 1.0
    try:
        t = datetime.fromisoformat(indexed_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 1.0
    age_days = max(0.0, (now - t) / 86400.0)
    return 0.5 ** (age_days / 30.0)


def _confidence_weight(confidence: Optional[float]) -> float:
    if confidence is None:
        return 1.0
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return 1.0
    return max(0.1, min(1.0, c))


def _composite_score(
    similarity: float,
    *,
    confidence: Optional[float],
    indexed_at: Optional[str],
    now_ts: Optional[float] = None,
) -> float:
    now_ts = now_ts or time.time()
    return (
        similarity
        * _confidence_weight(confidence)
        * _recency_weight(indexed_at, now_ts)
    )


# ─────────────────────────────────────────────────────────────────────
# Graph enrichment — pull full JSON-LD for a record
# ─────────────────────────────────────────────────────────────────────


def _enrich_from_graph(
    record_iri: str,
    source_table: Optional[str],
    primary_key: Optional[str],
    db_path: str,
) -> Dict[str, Any]:
    """Fetch the full row from the source table and return a JSON-LD dict."""
    if not (source_table and primary_key):
        return {"@id": record_iri}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                f"SELECT * FROM {source_table} WHERE id = ?",
                (primary_key,),
            ).fetchone()
        except sqlite3.OperationalError:
            return {"@id": record_iri}
    if not row:
        return {"@id": record_iri}
    d: Dict[str, Any] = {"@id": record_iri}
    for k in row.keys():
        d[k] = row[k]
    return d


def _log_query(
    db_path: str,
    *,
    query_id: str,
    index_name: str,
    flavor: str,
    question: str,
    class_filter: Optional[str],
    resolved_classes: List[str],
    k_requested: int,
    k_returned: int,
    latency_ms: int,
    strategy: str,
) -> None:
    import json as _json
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                INSERT INTO vector_query_log (
                    query_id, index_name, flavor, question,
                    class_filter, resolved_classes, k_requested,
                    k_returned, latency_ms, strategy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query_id, index_name, flavor, question,
                class_filter, _json.dumps(resolved_classes[:32]),
                k_requested, k_returned, latency_ms, strategy,
            ))
    except sqlite3.OperationalError:
        # Schema not installed yet — best effort logging only
        pass


# ─────────────────────────────────────────────────────────────────────
# Hybrid retriever
# ─────────────────────────────────────────────────────────────────────


class HybridRetriever:
    """Ontology-bounded vector retrieval + graph enrichment."""

    def __init__(
        self,
        *,
        flavor: str,
        db_path: str = _DEFAULT_DB,
        flavors_dir: Optional[str] = None,
        connection_string: Optional[str] = None,
        model_id: Optional[str] = None,
        ontology_path: Optional[str] = None,
    ):
        self.flavor = flavor
        self.db_path = db_path
        self.ontology_path = ontology_path

        self._registry = FlavorRegistry(flavors_dir=flavors_dir)
        flavor_cfg = self._registry.load(flavor)
        embed_cfg = flavor_cfg.get("embedding") or {}
        self._model_id = model_id or embed_cfg.get("model") or "hash-local-384"
        self._connection = (
            connection_string
            or embed_cfg.get("vector_store")
            or f"memory://{flavor}"
        )
        self._tier = flavor_cfg.get("sensitivity_tier", "Internal")
        self._adapter = get_adapter(
            self._connection, index_name=flavor, db_path=db_path,
        )

    # ---------- primary API ---------------------------------------

    def retrieve(
        self,
        question: str,
        *,
        class_expression: Optional[str] = None,
        k: int = 5,
        over_fetch: int = 3,
        strategy: str = "ONTOLOGY_BOUNDED",
        min_score: float = 0.0,
    ) -> Dict[str, Any]:
        """Retrieve top-*k* ontology-bounded results for *question*.

        Strategies:
          * ``UNFILTERED_VECTOR`` — baseline RAG (no class filter, no tier gate)
          * ``ONTOLOGY_BOUNDED``  — OWL class filter + tier gate (default)
          * ``PURE_SPARQL``       — recency-ordered scan, no vector ranking
        """
        t0 = time.time()
        query_id = str(uuid.uuid4())

        if strategy == "UNFILTERED_VECTOR":
            metadata_filter = {
                "owl_classes_in":  [],
                "owl_classes_all": [],
                "max_tier":        "Restricted",
                "resolved_from":   "none",
            }
        else:
            metadata_filter = build_metadata_filter(
                class_expression=class_expression,
                flavor=self.flavor if strategy != "PURE_SPARQL" else None,
                ontology_path=self.ontology_path,
                requesting_tier=self._tier,
            )

        vec = embed_text(question, model_id=self._model_id)
        fetch_k = k if strategy == "PURE_SPARQL" else max(k, k * over_fetch)

        raw = self._adapter.search(vec, metadata_filter, k=fetch_k)

        # Enrich + rescore
        now_ts = time.time()
        enriched: List[Dict[str, Any]] = []
        for hit in raw:
            meta = hit.get("metadata") or {}
            jsonld = _enrich_from_graph(
                meta.get("record_iri"),
                meta.get("source_table"),
                meta.get("primary_key"),
                self.db_path,
            )
            confidence = jsonld.get("confidence_score") if isinstance(jsonld, dict) else None
            sim = hit.get("score", 0.0)
            if strategy == "PURE_SPARQL":
                composite = _recency_weight(meta.get("indexed_at"), now_ts)
            else:
                composite = _composite_score(
                    sim, confidence=confidence,
                    indexed_at=meta.get("indexed_at"),
                    now_ts=now_ts,
                )
            if composite < min_score:
                continue
            enriched.append({
                "record_iri":        meta.get("record_iri"),
                "owl_class":         meta.get("owl_class"),
                "flavor":            meta.get("flavor"),
                "sensitivity_tier":  meta.get("sensitivity_tier"),
                "similarity":        sim,
                "composite_score":   composite,
                "source_table":      meta.get("source_table"),
                "primary_key":       meta.get("primary_key"),
                "indexed_at":        meta.get("indexed_at"),
                "text_repr":         meta.get("text_repr"),
                "jsonld":            jsonld,
            })

        enriched.sort(key=lambda r: r["composite_score"], reverse=True)
        top = enriched[:k]

        latency_ms = int((time.time() - t0) * 1000)
        _log_query(
            self.db_path,
            query_id=query_id,
            index_name=self.flavor,
            flavor=self.flavor,
            question=question,
            class_filter=class_expression,
            resolved_classes=metadata_filter.get("owl_classes_in") or [],
            k_requested=k,
            k_returned=len(top),
            latency_ms=latency_ms,
            strategy=strategy,
        )

        return {
            "query_id":        query_id,
            "flavor":          self.flavor,
            "strategy":        strategy,
            "class_expression": class_expression,
            "resolved_classes": metadata_filter.get("owl_classes_in") or [],
            "max_tier":        metadata_filter.get("max_tier"),
            "k":               k,
            "result_count":    len(top),
            "latency_ms":      latency_ms,
            "timestamp":       _now_iso(),
            "results":         top,
        }

    # ---------- convenience ---------------------------------------

    @property
    def adapter(self):
        return self._adapter

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def connection(self) -> str:
        return self._connection
