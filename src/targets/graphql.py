"""
src/targets/graphql.py — T1.5
─────────────────────────────
GraphQL SDL target.

Each entity / table becomes a GraphQL ``type``. Properties map to
fields with their inferred GraphQL scalar (``String``, ``Int``,
``Float``, ``Boolean``, ``ID``, ``DateTime``). Cardinality from the
T1.4 enhancements drives nullability and list arity:

- ``minCount = 1``  →  field is non-null (``!``)
- ``maxCount = 1``  →  scalar / single object reference
- ``maxCount`` absent or > 1 → list type (``[Type!]!``)

Foreign-key columns / wizard relationships become object-reference
fields. Junction-table relationships with ``via`` become a many-to-
many list on each endpoint.

We also emit a placeholder ``Query`` root with one ``allXxx``
resolver per entity — enough to compile, easy to extend.

Output: ``graphql/schema.graphql``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import GenerationContext, Target, TargetResult


# Map common SQL / OWL types → GraphQL scalars.
_SCALAR_MAP = {
    "string":   "String",
    "text":     "String",
    "varchar":  "String",
    "char":     "String",
    "integer":  "Int",
    "int":      "Int",
    "bigint":   "Int",
    "smallint": "Int",
    "tinyint":  "Int",
    "decimal":  "Float",
    "numeric":  "Float",
    "real":     "Float",
    "double":   "Float",
    "float":    "Float",
    "boolean":  "Boolean",
    "bool":     "Boolean",
    "date":     "String",
    "datetime": "String",
    "timestamp": "String",
    "time":     "String",
    "uuid":     "ID",
    "uuid4":    "ID",
    "json":     "JSON",
    "jsonb":    "JSON",
}


def _type_name(name: str) -> str:
    parts = re.split(r"[\s_\-]+", (name or "").strip())
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _field_name(name: str) -> str:
    parts = re.split(r"[\s_\-]+", (name or "").strip())
    if not parts:
        return "field"
    head = parts[0].lower()
    tail = "".join(p[:1].upper() + p[1:] for p in parts[1:])
    return head + tail


def _scalar_for(sql_type: str) -> str:
    base = re.sub(r"\(.*\)", "", (sql_type or "").strip()).lower()
    return _SCALAR_MAP.get(base, "String")


def _cardinality_render(scalar: str, *,
                        min_count: Optional[int],
                        max_count: Optional[int]) -> str:
    """Turn cardinality bounds into a GraphQL type literal."""
    is_list = max_count is None or max_count > 1
    if is_list:
        inner_required = min_count is not None and min_count >= 1
        outer_required = min_count is not None and min_count >= 1
        return ("[" + scalar + ("!" if inner_required else "") + "]"
                + ("!" if outer_required else ""))
    # Single-valued.
    return scalar + ("!" if (min_count or 0) >= 1 else "")


@dataclass
class GraphQLTarget:
    name: str = "graphql"

    def generate(self, ctx: GenerationContext) -> TargetResult:
        result = TargetResult(target=self.name)
        lines: List[str] = []
        lines.append(f'"""Auto-generated GraphQL SDL for {ctx.domain_name}.')
        lines.append('Edit at approval time — base IRI: '
                     f'<{ctx.base_iri}>"""')
        lines.append("")

        type_names: List[str] = []
        n_types = 0
        n_fields = 0
        seen_types: set = set()

        # ── Types from introspected tables ──────────────────────────
        for table in ctx.tables:
            tname = getattr(table, "name", None)
            if not tname:
                continue
            type_name = _type_name(tname)
            if type_name in seen_types:
                continue
            seen_types.add(type_name)
            type_names.append(type_name)
            n_types += 1
            label = getattr(table, "label", None) or type_name
            description = getattr(table, "description", "") or ""
            lines.append(f'"""{label}'
                         + (f'\n\n{description}' if description else "")
                         + '"""')
            lines.append(f"type {type_name} {{")
            for col in getattr(table, "columns", []) or []:
                cname = getattr(col, "name", None)
                if not cname:
                    continue
                ctype = _scalar_for(getattr(col, "sqlite_type", "")
                                    or getattr(col, "data_type", ""))
                required = (
                    bool(getattr(col, "not_null", False))
                    or bool(getattr(col, "is_pk", False))
                )
                if getattr(col, "is_pk", False):
                    ctype = "ID"
                lines.append(f"  {_field_name(cname)}: {ctype}"
                             + ("!" if required else ""))
                n_fields += 1
            # FK references → object-reference fields.
            for col in getattr(table, "columns", []) or []:
                if not getattr(col, "is_fk", False):
                    continue
                ref = getattr(col, "fk_references", "")
                if not ref:
                    continue
                ref_name = _type_name(ref)
                lines.append(f"  {_field_name(ref)}: {ref_name}")
                n_fields += 1
            lines.append("}")
            lines.append("")

        # ── Types from wizard entities (when there are no tables) ───
        if not seen_types:
            for ent in (ctx.session.get("entities") or []):
                ename = ent.get("name") or ent.get("label")
                if not ename:
                    continue
                type_name = _type_name(ename)
                if type_name in seen_types:
                    continue
                seen_types.add(type_name)
                type_names.append(type_name)
                n_types += 1
                lines.append(f'"""{ent.get("label") or type_name}"""')
                lines.append(f"type {type_name} {{")
                for prop in (ent.get("properties") or []):
                    pname = prop.get("name")
                    if not pname:
                        continue
                    scalar = _scalar_for(prop.get("type") or "string")
                    card = prop.get("cardinality") or {}
                    typ = _cardinality_render(
                        scalar,
                        min_count=card.get("minCount"),
                        max_count=card.get("maxCount"),
                    )
                    lines.append(f"  {_field_name(pname)}: {typ}")
                    n_fields += 1
                lines.append("}")
                lines.append("")

        # ── Many-to-many fields from junction-aware relationships ───
        rel_lookup: Dict[str, List[str]] = {}
        for rel in (ctx.session.get("relationships") or []):
            src = _type_name(rel.get("from_entity") or "")
            dst = _type_name(rel.get("to_entity") or "")
            if not (src and dst):
                continue
            rel_lookup.setdefault(src, []).append(dst)
            if rel.get("via"):                           # symmetric for M-N
                rel_lookup.setdefault(dst, []).append(src)
        if rel_lookup:
            lines.append("# Relationship-derived fields (auto-suggested)")
            for src, dsts in rel_lookup.items():
                for dst in set(dsts):
                    lines.append(
                        f"# extend type {src} {{ {_field_name(dst + 's')}: [{dst}!]! }}"
                    )
            lines.append("")

        # ── Query root ─────────────────────────────────────────────
        lines.append("type Query {")
        for tn in sorted(set(type_names)):
            field = _field_name(f"all_{tn}s")
            lines.append(f"  {field}: [{tn}!]!")
            n_fields += 1
        lines.append("}")
        lines.append("")
        lines.append("scalar JSON")
        lines.append("")

        result.files["graphql/schema.graphql"] = "\n".join(lines)
        result.stats = {"types": n_types, "fields": n_fields}
        return result


__all__ = ["GraphQLTarget"]
