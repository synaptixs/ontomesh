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

_SQL_OPS = {"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=", "like": "LIKE"}


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
) -> tuple[str, list]:
    """Compile a single-hop plan to ``(sql, params)``.

    Raises:
        CompileError: unmapped class, table not allow-listed, or bad identifier.
    """
    cls = plan.primary_class
    table = mapping.table_for(cls)
    if not table:
        raise CompileError(f"no physical table mapped for class {cls!r}")
    if allowed_tables and table not in allowed_tables:
        raise CompileError(f"table {table!r} is not allow-listed for this flavor")
    table = _safe_ident(table)

    # Project the class's mapped columns (fall back to * if none mapped).
    cols = sorted(
        _safe_ident(col)
        for (c, _prop), (_t, col) in mapping.prop_col.items()
        if c == cls and _t == table
    )
    select_list = ", ".join(cols) if cols else "*"

    where_parts: list[str] = []
    params: list = []
    for f in plan.filters:
        loc = mapping.column_for(cls, f.prop)
        if not loc:
            raise CompileError(f"no column mapped for {cls}.{f.prop}")
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
