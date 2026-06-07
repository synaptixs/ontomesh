"""Query compiler: validated Plan → read-only SQL (§11 #7).

Single-hop (Phase 0). Compiles the plan's primary class to its physical table via
the logical↔physical `Mapping`, projecting the class's mapped columns and applying
the plan's filters as **parameterized** predicates.

Safety is structural here — the compiler can only ever emit a single ``SELECT``
with a ``LIMIT`` against an **allow-listed** table, and all values are bound
parameters (never interpolated). The fuller safety layer (tier gating, timeouts,
multi-statement rejection) lands in Phase 1 §11 #10–#11.
"""

from __future__ import annotations

from ._loaders import Mapping
from .planner import Plan
from .safety import tier_ok

_SQL_OPS = {"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=", "like": "LIKE"}


def _gated(element_tier: str | None, max_tier: str) -> bool:
    """True if an explicitly-classified element exceeds ``max_tier``.

    Missing tier info → not gated (only *declared* sensitive data is withheld).
    """
    return element_tier is not None and not tier_ok(element_tier, max_tier)


class CompileError(ValueError):
    """The plan could not be compiled to a safe query."""


def _safe_ident(name: str) -> str:
    """Permit only plain SQL identifiers (defense-in-depth; values are params)."""
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise CompileError(f"unsafe identifier: {name!r}")
    return name


def compile_sql(
    plan: Plan,
    *,
    mapping: Mapping,
    allowed_tables: set[str],
    limit: int = 200,
    max_tier: str = "Restricted",
) -> tuple[str, list]:
    """Compile a single-hop plan to ``(sql, params)``.

    Columns/filters whose declared sensitivity tier exceeds ``max_tier`` are
    excluded (columns) or rejected (filters).

    Raises:
        CompileError: unmapped class, table not allow-listed, bad identifier, or
            a filter on a column above the tier ceiling.
    """
    cls = plan.primary_class
    table = mapping.table_for(cls)
    if not table:
        raise CompileError(f"no physical table mapped for class {cls!r}")
    if allowed_tables and table not in allowed_tables:
        raise CompileError(f"table {table!r} is not allow-listed for this flavor")
    table = _safe_ident(table)

    # Project the class's mapped columns, excluding any above the tier ceiling.
    cols = sorted(
        _safe_ident(col)
        for (c, prop), (_t, col) in mapping.prop_col.items()
        if c == cls and _t == table and not _gated(mapping.tier.get(f"{cls}.{prop}"), max_tier)
    )
    select_list = ", ".join(cols) if cols else "*"

    where_parts: list[str] = []
    params: list = []
    for f in plan.filters:
        loc = mapping.column_for(cls, f.prop)
        if not loc:
            raise CompileError(f"no column mapped for {cls}.{f.prop}")
        if _gated(mapping.tier.get(f"{cls}.{f.prop}"), max_tier):
            raise CompileError(f"filter on {cls}.{f.prop} exceeds tier ceiling {max_tier!r}")
        _t, col = loc
        op = _SQL_OPS.get(f.op)
        if not op:
            raise CompileError(f"unsupported op {f.op!r}")
        where_parts.append(f"{_safe_ident(col)} {op} ?")
        params.append(f.value)

    sql = f"SELECT {select_list} FROM {table}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += f" LIMIT {int(limit)}"
    return sql, params
