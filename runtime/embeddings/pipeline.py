"""
runtime.embeddings.pipeline — Workstream 5, Component 1
========================================================
Indexes ontology-typed records as vector embeddings.

For each flavor we:

  1. Load the flavor's embedding configuration (model, vector store,
     OWL classes to index, text template) — sensible defaults are
     supplied if the flavor has no ``embedding`` block.
  2. Walk the flavor's ``db_tables`` and pull every row.
  3. Serialise each row into a text representation that mentions the
     OWL class name, the record IRI, and every non-null column as
     ``<term>: <value>``.  Column names appear as their JSON-LD
     ontology labels where possible, so the embedder learns the
     semantic vocabulary, not opaque SQL identifiers.
  4. Embed the text with the configured model.
  5. Upsert into the vector store adapter.
  6. Register the index in the ``embedding_indexes`` table so the
     toolkit report can show coverage.

Incremental indexing is supported via the ``content_hash`` column on
``embedding_records`` — rows whose hash matches the current text
representation are skipped unless ``force=True``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .adapters import get_adapter, MemoryAdapter
from .embedder import embed_text, resolve_model

_HERE     = os.path.dirname(os.path.abspath(__file__))
_RUNTIME  = os.path.dirname(_HERE)
_ROOT     = os.path.dirname(_RUNTIME)
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from flavor_registry import FlavorRegistry  # noqa: E402

_TMF_BASE = "https://ontology.example.com/tmf/"
_DEFAULT_DB = os.path.join(_ROOT, "db", "enterprise.db")


# ─────────────────────────────────────────────────────────────────────
# Default embedding configuration per flavor
# ─────────────────────────────────────────────────────────────────────


_DEFAULT_EMBEDDING_CFG: Dict[str, Any] = {
    "model":             "hash-local-384",
    "vector_store":      None,                 # filled at runtime
    "text_template":     None,                 # None → generic serialiser
    "owl_classes":       None,                 # None → all flavor classes
    "chunk_size":        1,                    # one embedding per record
}


def _embedding_config(flavor_name: str, flavor: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(_DEFAULT_EMBEDDING_CFG)
    cfg.update(flavor.get("embedding") or {})
    cfg["vector_store"] = cfg["vector_store"] or f"memory://{flavor_name}"
    return cfg


# ─────────────────────────────────────────────────────────────────────
# Text serialisation
# ─────────────────────────────────────────────────────────────────────


def _db_class_for_table(table: str, flavor: Dict[str, Any]) -> str:
    """Pick the best OWL class for a table from the flavor's class list.

    Heuristic: strip underscores and lowercase both sides, then pick
    the class whose normalised name is a substring of the normalised
    table name — preferring longer (more specific) matches.  Falls
    back to the first class in the flavor.
    """
    norm_table = (table or "").lower().replace("_", "")
    candidates = [
        cls for cls in flavor.get("owl_classes", [])
        if cls.lower().replace("_", "") in norm_table
    ]
    if candidates:
        candidates.sort(key=lambda c: len(c), reverse=True)
        return candidates[0]
    classes = flavor.get("owl_classes") or []
    return classes[0] if classes else "Resource"


_TYPE_COLUMN_MAP = (
    "resource_type",
    "event_type",
    "alarm_type",
    "ticket_type",
    "agreement_type",
    "party_type",
    "observation_type",
    "conflict_type",
    "policy_type",
    "kpi_type",
    "report_type",
    "asset_type",
    "service_type",
    "product_type",
)


def _refine_class_from_row(
    row: Dict[str, Any],
    default_cls: str,
    flavor: Dict[str, Any],
) -> str:
    """Upgrade the default class assignment based on typed columns.

    Tables like ``tmf_resource`` store mixed instances (NetworkFunction,
    NetworkSlice, Antenna, …) distinguished by a ``resource_type``
    column.  When that column value maps to a declared flavor class,
    use it — otherwise keep the table default.
    """
    flavor_classes = flavor.get("owl_classes") or []
    # normalise for comparison: strip underscores, lowercase
    norm_map = {cls.lower().replace("_", ""): cls for cls in flavor_classes}
    for col in _TYPE_COLUMN_MAP:
        val = row.get(col)
        if not val:
            continue
        key = str(val).lower().replace("_", "").replace("-", "")
        if key in norm_map:
            return norm_map[key]
        # Try suffix-based matching for values like NETWORK_FUNCTION
        for cls_norm, cls in norm_map.items():
            if cls_norm and (cls_norm in key or key in cls_norm):
                return cls
    return default_cls


def _class_iri(cls_name: str, flavor: Dict[str, Any]) -> str:
    terms = flavor.get("context_terms", {}) or {}
    if cls_name in terms:
        return terms[cls_name]
    return _TMF_BASE + cls_name


def _row_to_text(row: Dict[str, Any], cls_name: str) -> str:
    """Build a bag-of-words text representation from a row.

    Uses the OWL class name plus every non-null column as
    ``<column>: <value>``.  No filtering on datatype — short strings
    carry the semantic weight.
    """
    parts: List[str] = [f"class: {cls_name}"]
    for k, v in row.items():
        if v is None:
            continue
        text = str(v).strip()
        if not text or text == "None":
            continue
        parts.append(f"{k}: {text}")
    return " | ".join(parts)


def _record_iri(table: str, pk: Any) -> str:
    return f"https://ontology.example.com/enterprise/{table}/{pk}"


# ─────────────────────────────────────────────────────────────────────
# Index registration
# ─────────────────────────────────────────────────────────────────────


def _register_index(
    db_path: str,
    *,
    index_name: str,
    flavor: str,
    connection_string: str,
    model_id: str,
    dim: int,
    owl_classes: List[str],
    record_count: int,
    max_sensitivity: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO embedding_indexes (
                index_name, flavor, vector_store, connection_string,
                model_id, dimensions, owl_classes, record_count,
                max_sensitivity, last_indexed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(index_name) DO UPDATE SET
                flavor            = excluded.flavor,
                vector_store      = excluded.vector_store,
                connection_string = excluded.connection_string,
                model_id          = excluded.model_id,
                dimensions        = excluded.dimensions,
                owl_classes       = excluded.owl_classes,
                record_count      = excluded.record_count,
                max_sensitivity   = excluded.max_sensitivity,
                last_indexed_at   = datetime('now'),
                updated_at        = datetime('now')
        """, (
            index_name, flavor, connection_string.split("://", 1)[0],
            connection_string, model_id, dim,
            json.dumps(owl_classes), record_count, max_sensitivity,
        ))


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def index_flavor(
    flavor_name: str,
    *,
    db_path: str = _DEFAULT_DB,
    flavors_dir: Optional[str] = None,
    connection_string: Optional[str] = None,
    model_id: Optional[str] = None,
    force: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Index every row from the flavor's DB tables as an embedding.

    Returns a summary dict::

        {
          "flavor": ..., "index_name": ..., "model": ..., "dim": ...,
          "indexed": <n>, "skipped_unchanged": <n>, "owl_classes": [...],
          "connection": "memory://network-ops",
        }
    """
    reg = FlavorRegistry(flavors_dir=flavors_dir)
    flavor = reg.load(flavor_name)

    cfg = _embedding_config(flavor_name, flavor)
    if connection_string:
        cfg["vector_store"] = connection_string
    if model_id:
        cfg["model"] = model_id

    model_entry = resolve_model(cfg["model"])
    dim = model_entry["dim"]

    adapter = get_adapter(cfg["vector_store"], flavor_name, db_path=db_path)
    adapter.ensure_index(dim=dim, metadata_fields=[
        "owl_class", "flavor", "sensitivity_tier", "primary_key", "source_table"
    ])

    # Build list of (table, class_name)
    tables = flavor.get("db_tables") or []
    tier   = flavor.get("sensitivity_tier", "Internal")

    # Cache existing content hashes for incremental re-indexing
    existing_hashes = _existing_hashes(db_path, flavor_name)

    indexed = 0
    skipped = 0
    seen_classes: List[str] = []
    upsert_buffer: List[Dict[str, Any]] = []
    BATCH = 256

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for tbl in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            except sqlite3.OperationalError:
                # Table doesn't exist in this DB profile — skip quietly
                continue
            if not rows:
                continue
            default_cls = _db_class_for_table(tbl, flavor)

            for idx, row in enumerate(rows):
                if limit is not None and indexed >= limit:
                    break
                rec = dict(row)
                cls_name = _refine_class_from_row(rec, default_cls, flavor)
                cls_iri  = _class_iri(cls_name, flavor)
                if cls_iri not in seen_classes:
                    seen_classes.append(cls_iri)
                pk  = rec.get("id") or rec.get("observation_iri") or idx
                record_iri = _record_iri(tbl, pk)
                text = _row_to_text(rec, cls_name)
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if not force and existing_hashes.get(record_iri) == content_hash:
                    skipped += 1
                    continue
                vec = embed_text(text, model_id=cfg["model"])
                upsert_buffer.append({
                    "id": record_iri,
                    "vector": vec,
                    "metadata": {
                        "record_iri":       record_iri,
                        "owl_class":        cls_iri,
                        "flavor":           flavor_name,
                        "sensitivity_tier": tier,
                        "primary_key":      str(pk),
                        "source_table":     tbl,
                        "text_repr":        text,
                        "indexed_at":       datetime.now(timezone.utc).isoformat(),
                    },
                })
                if len(upsert_buffer) >= BATCH:
                    indexed += adapter.upsert(upsert_buffer)
                    upsert_buffer.clear()

    if upsert_buffer:
        indexed += adapter.upsert(upsert_buffer)

    # Register index (uses aggregated count including skipped rows)
    total_rows = adapter.count()
    _register_index(
        db_path,
        index_name=flavor_name,
        flavor=flavor_name,
        connection_string=cfg["vector_store"],
        model_id=cfg["model"],
        dim=dim,
        owl_classes=seen_classes,
        record_count=total_rows,
        max_sensitivity=tier,
    )

    return {
        "flavor":             flavor_name,
        "index_name":         flavor_name,
        "model":              cfg["model"],
        "dim":                dim,
        "connection":         cfg["vector_store"],
        "indexed":            indexed,
        "skipped_unchanged":  skipped,
        "total_records":      total_rows,
        "owl_classes":        seen_classes,
        "max_sensitivity":    tier,
    }


def _existing_hashes(db_path: str, index_name: str) -> Dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT record_iri, content_hash FROM embedding_records "
                "WHERE index_name = ?",
                (index_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    return {r["record_iri"]: r["content_hash"] for r in rows}


def reindex_all(
    *,
    db_path: str = _DEFAULT_DB,
    flavors_dir: Optional[str] = None,
    force: bool = False,
) -> List[Dict[str, Any]]:
    """Reindex every registered flavor.  Returns one summary per flavor."""
    reg = FlavorRegistry(flavors_dir=flavors_dir)
    out: List[Dict[str, Any]] = []
    for name in reg.list_flavors():
        try:
            out.append(index_flavor(
                name, db_path=db_path, flavors_dir=flavors_dir, force=force,
            ))
        except Exception as exc:  # pragma: no cover
            out.append({"flavor": name, "error": str(exc)})
    return out


def list_indexes(db_path: str = _DEFAULT_DB) -> List[Dict[str, Any]]:
    """Return every registered embedding index with record counts."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT index_name, flavor, vector_store, model_id, "
                "dimensions, owl_classes, record_count, max_sensitivity, "
                "last_indexed_at FROM embedding_indexes ORDER BY flavor"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["owl_classes"] = json.loads(d["owl_classes"] or "[]")
        except json.JSONDecodeError:
            d["owl_classes"] = []
        out.append(d)
    return out
