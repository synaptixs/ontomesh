"""
src/targets/cypher.py — T1.5
────────────────────────────
Neo4j Cypher schema + migration target.

Emits two files:
- ``cypher/schema.cypher``    — CREATE CONSTRAINT statements + node-
  label declarations. Idempotent — every statement uses ``IF NOT EXISTS``.
- ``cypher/migration.cypher`` — a sketch of the data-load pattern
  (LOAD CSV / MERGE) the reviewer customises with their own data
  source. We don't try to be a full ETL — that's not our job.

Mapping rules
-------------
- Each ``TableModel`` whose name doesn't look like a junction →
  ``(:LabelName)`` node with constraints on its PK columns.
- Each foreign-key column → ``(:Source)-[:HAS_TARGET]->(:Target)``
  relationship.
- Each junction-table relationship from the wizard session
  (carrying a ``via`` marker, set by ``importer_semantic``) →
  ``(:A)-[:VIA_TABLE_LABEL {extra_cols}]->(:B)`` with the original
  scalar columns as edge properties.

Output is plain Cypher — no Neo4j SDK calls, no driver
dependency. The reviewer runs it through ``cypher-shell`` or the
Neo4j desktop client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from .base import GenerationContext, Target, TargetResult


_KEYWORDS_RESERVED = {"and", "or", "not", "match", "create", "return"}


def _label(name: str) -> str:
    """Snake/kebab → PascalCase. ``order_items`` → ``OrderItems``."""
    parts = re.split(r"[\s_\-]+", (name or "").strip())
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _rel_type(name: str) -> str:
    """Snake/kebab → SCREAMING_SNAKE for Cypher relationship type."""
    parts = re.split(r"[\s_\-]+", (name or "").strip().lower())
    return "_".join(p.upper() for p in parts if p) or "RELATES_TO"


def _cypher_safe(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float, bool)):
        return str(value).lower() if isinstance(value, bool) else str(value)
    s = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


@dataclass
class CypherTarget:
    name: str = "cypher"

    def generate(self, ctx: GenerationContext) -> TargetResult:
        result = TargetResult(target=self.name)
        schema_lines: List[str] = []
        migration_lines: List[str] = []

        schema_lines.append(
            f"// Cypher schema for `{ctx.domain_name}`\n"
            f"// Generated from ontology — re-runnable; uses IF NOT EXISTS.\n"
            f"// Base IRI: <{ctx.base_iri}>\n"
        )
        migration_lines.append(
            f"// Migration sketch for `{ctx.domain_name}`\n"
            f"// Replace LOAD CSV paths with your data source.\n"
        )

        n_nodes = 0
        n_constraints = 0
        n_rels = 0

        # 1. Node labels + uniqueness constraints from tables / entities.
        seen_labels: set = set()
        for table in ctx.tables:
            tname = getattr(table, "name", None)
            if not tname:
                continue
            label = _label(tname)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            n_nodes += 1
            pk_cols = list(getattr(table, "pk_columns", []) or [])
            schema_lines.append(f"// :: {label}")
            for pk in pk_cols:
                schema_lines.append(
                    f"CREATE CONSTRAINT {label}_{pk}_unique IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{pk} IS UNIQUE;"
                )
                n_constraints += 1
            schema_lines.append("")

        # 1b. If we have no introspector tables but wizard entities exist,
        # fall back to those (covers the wizard-only flow).
        if not seen_labels:
            for ent in (ctx.session.get("entities") or []):
                ename = ent.get("name") or ent.get("label")
                if not ename:
                    continue
                label = _label(ename)
                if label in seen_labels:
                    continue
                seen_labels.add(label)
                n_nodes += 1
                schema_lines.append(f"// :: {label}")
                for prop in (ent.get("properties") or []):
                    if (prop.get("cardinality") or {}).get("maxCount") == 1 \
                            and (prop.get("cardinality") or {}).get("minCount") == 1:
                        schema_lines.append(
                            f"CREATE CONSTRAINT "
                            f"{label}_{prop['name']}_unique IF NOT EXISTS "
                            f"FOR (n:{label}) REQUIRE n.{prop['name']} IS UNIQUE;"
                        )
                        n_constraints += 1
                schema_lines.append("")

        # 2. Relationships from wizard session.
        for rel in (ctx.session.get("relationships") or []):
            src_label = _label(rel.get("from_entity") or "")
            dst_label = _label(rel.get("to_entity")   or "")
            if not (src_label and dst_label):
                continue
            rtype = _rel_type(rel.get("label") or "relates_to")
            extras = list(rel.get("extra_cols") or [])
            via = rel.get("via")
            n_rels += 1
            comment_via = f"  // via {via}" if via else ""
            if extras:
                migration_lines.append(
                    f"// {src_label} -[:{rtype} {{ {', '.join(extras)} }}]-> {dst_label}{comment_via}\n"
                    f"// MATCH (a:{src_label}), (b:{dst_label}) "
                    f"WHERE … MERGE (a)-[r:{rtype}]->(b) SET r += $extras;"
                )
            else:
                migration_lines.append(
                    f"// {src_label} -[:{rtype}]-> {dst_label}{comment_via}\n"
                    f"// MATCH (a:{src_label}), (b:{dst_label}) "
                    f"WHERE … MERGE (a)-[r:{rtype}]->(b);"
                )

        # 3. Relationships from introspected FKs (the structural path).
        for table in ctx.tables:
            for col in getattr(table, "columns", []) or []:
                if not getattr(col, "is_fk", False):
                    continue
                src_label = _label(getattr(table, "name", "") or "")
                dst_label = _label(getattr(col, "fk_references", "") or "")
                if not (src_label and dst_label):
                    continue
                n_rels += 1
                migration_lines.append(
                    f"// FK {src_label}.{col.name} → {dst_label}\n"
                    f"// MATCH (a:{src_label}), (b:{dst_label}) "
                    f"WHERE a.{col.name} = b.{dst_label.lower()}_id "
                    f"MERGE (a)-[:HAS_{_rel_type(dst_label)}]->(b);"
                )

        result.files["cypher/schema.cypher"] = "\n".join(schema_lines)
        result.files["cypher/migration.cypher"] = "\n".join(migration_lines)
        result.stats = {
            "nodes": n_nodes, "constraints": n_constraints,
            "relationships": n_rels,
        }
        return result


__all__ = ["CypherTarget"]
