"""
wizard/importer_semantic.py — T1.4
──────────────────────────────────
Schema-import depth enhancements that layer on top of the structural
``_norm_schema`` pass in :mod:`wizard.importer`.

Why this exists
───────────────
Structural import treats a relational schema as a flat list of tables,
columns, and foreign keys. Most enterprise databases encode business
meaning in *exactly* the places that structural import drops:

- Foreign-key chains (orders → customers → segments) carry implicit
  property paths that the engineer never has to spell out manually.
- Junction tables (M-N: ``order_items(order_id, product_id, qty)``)
  are *one* relationship, not two — collapsing them halves the noise
  in the review queue.
- ``NOT NULL`` constraints map to ``sh:minCount 1`` cardinality.
  Column-statistics derived from ``information_schema`` map to
  ``sh:maxCount``.
- View definitions (``CREATE VIEW v AS SELECT …``) carry derived
  classes plus the SHACL/SPARQL rule that defines them — a free
  semantic enrichment if we parse the SELECT.

Each enhancement is independently toggleable so the engineer can
adopt them incrementally and the ``_norm_schema`` invariant
(idempotent + diff-friendly) is preserved.

Public API
──────────
    out = enhance_schema(session, schema, *,
                         detect_fk_chains=True,
                         detect_junctions=True,
                         null_to_cardinality=True,
                         views_to_classes=True)

``session`` is the wizard-shaped dict produced by
``importer._norm_schema``; ``schema`` is the original ``{tables: …}``
input (we still need the raw FK lists and column-flags). Returns a
new session dict with:

- ``relationships`` augmented with collapsed junction edges
  (``via`` metadata identifies the original junction table).
- A new top-level ``property_paths`` list — multi-step FK chains
  surfaced as candidate ``sh:path`` sequences.
- ``properties[*].cardinality`` populated with
  ``{minCount, maxCount}`` where derivable from NULL semantics.
- ``derived_classes`` — new list, one entry per view, carrying the
  view's SELECT (parsed via sqlglot) as a SPARQL CONSTRUCT skeleton.

No data is mutated in place; the enhancer returns a deep-copied
session so callers can diff against the input.
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# Heuristic threshold for "this table is a junction." A pure junction
# has 2 columns that are both PK + FK, plus optionally 1-3 lightweight
# scalar columns (qty, created_at). Anything heavier is a real entity.
_JUNCTION_MAX_NON_FK_COLS = 3


# ── Helpers ──────────────────────────────────────────────────────────────


def _table_columns(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(table.get("columns") or [])


def _table_fks(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(table.get("foreign_keys") or [])


def _col_is_pk(col: Dict[str, Any]) -> bool:
    return bool(col.get("is_pk") or col.get("primary_key")
                or col.get("pk"))


def _col_is_required(col: Dict[str, Any]) -> bool:
    """A NOT NULL column. Mirrors ``_norm_schema``'s convention —
    both ``required`` and ``not_null`` are accepted."""
    if col.get("is_nullable") is False:
        return True
    return bool(col.get("required") or col.get("not_null"))


def _fk_column_names(table: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for fk in _table_fks(table):
        col = fk.get("column") or fk.get("from_column")
        if isinstance(col, str):
            out.add(col)
        elif isinstance(col, list):
            out.update(col)
    return out


def _label_from_snake(s: str) -> str:
    return " ".join(p.capitalize() for p in s.replace("-", "_").split("_") if p)


# ── Junction-table detection ─────────────────────────────────────────────


@dataclass
class JunctionInfo:
    """A table whose role is to relate two other tables M-N."""
    table:       str
    endpoint_a:  str               # referenced table A
    endpoint_b:  str               # referenced table B
    label:       str               # proposed relationship label
    extra_cols:  List[str] = field(default_factory=list)
    # When extra_cols is non-empty (e.g. 'qty' or 'price'), the engineer
    # can choose to keep the junction as a relationship-class instead
    # of collapsing it; we surface the hint either way.


def detect_junction_tables(schema: Dict[str, Any]) -> List[JunctionInfo]:
    """Return one JunctionInfo per detected M-N table.

    Heuristic (intentionally conservative — false negatives are cheaper
    than false positives at this stage):
    1. Exactly 2 distinct foreign keys to different tables.
    2. Both FK columns are part of the primary key (composite PK).
    3. Remaining non-FK columns ≤ ``_JUNCTION_MAX_NON_FK_COLS``.
    """
    out: List[JunctionInfo] = []
    for table in (schema.get("tables") or []):
        tname = table.get("name") or ""
        if not tname:
            continue
        fks = _table_fks(table)
        if len(fks) != 2:
            continue
        targets = [fk.get("references_table") or fk.get("ref_table")
                   or fk.get("references") for fk in fks]
        if not all(targets) or targets[0] == targets[1]:
            continue
        fk_cols = _fk_column_names(table)
        all_cols = {c.get("name") for c in _table_columns(table)
                    if c.get("name")}
        non_fk_cols = sorted(all_cols - fk_cols)
        # PK constraint: each FK column must be marked PK (composite PK
        # over both FKs is the hallmark of a junction).
        pk_cols = {c.get("name") for c in _table_columns(table)
                   if c.get("name") and _col_is_pk(c)}
        if not fk_cols.issubset(pk_cols):
            continue
        if len(non_fk_cols) > _JUNCTION_MAX_NON_FK_COLS:
            continue
        label = _label_from_snake(tname)
        out.append(JunctionInfo(
            table=tname,
            endpoint_a=str(targets[0]),
            endpoint_b=str(targets[1]),
            label=label,
            extra_cols=non_fk_cols,
        ))
    return out


# ── Foreign-key chain detection ──────────────────────────────────────────


@dataclass
class FkChainInfo:
    """A multi-step FK path through 2+ intermediate tables."""
    start_table: str
    end_table:   str
    steps:       List[Tuple[str, str, str]]   # (from_tbl, fk_col, to_tbl)

    def as_property_path(self) -> str:
        """SPARQL-ish ``sh:path`` rendering — for the proposal turtle."""
        return " / ".join(f":has{_label_from_snake(s[2])}"
                          for s in self.steps)


def detect_fk_chains(schema: Dict[str, Any], *,
                     min_length: int = 2,
                     max_length: int = 4,
                     exclude_junctions: bool = True,
                     ) -> List[FkChainInfo]:
    """Return one FkChainInfo per discovered FK chain of length
    ``min_length`` (default 2 — i.e. orders → customer → segment).

    Cycles are skipped. Chains that pass *through* a junction table
    are skipped by default (the junction collapse already covers
    them more cleanly).
    """
    tables = {t.get("name"): t for t in (schema.get("tables") or [])
              if t.get("name")}
    junction_names: Set[str] = set()
    if exclude_junctions:
        junction_names = {j.table for j in detect_junction_tables(schema)}

    # Build forward adjacency: from_table -> [(fk_col, to_table)]
    forward: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for tname, t in tables.items():
        for fk in _table_fks(t):
            target = (fk.get("references_table") or fk.get("ref_table")
                      or fk.get("references"))
            col = fk.get("column") or fk.get("from_column") or ""
            if target and isinstance(col, str):
                forward[tname].append((col, target))

    out: List[FkChainInfo] = []

    def walk(start: str, current: str, depth: int,
             visited: Tuple[str, ...],
             steps: List[Tuple[str, str, str]]) -> None:
        if depth >= max_length:
            return
        for col, nxt in forward.get(current, []):
            if nxt in visited or nxt in junction_names:
                continue
            new_steps = steps + [(current, col, nxt)]
            if len(new_steps) >= min_length:
                out.append(FkChainInfo(
                    start_table=start, end_table=nxt, steps=list(new_steps),
                ))
            walk(start, nxt, depth + 1, visited + (nxt,), new_steps)

    for tname in tables:
        if tname in junction_names:
            continue
        walk(tname, tname, 0, (tname,), [])

    return out


# ── NULL semantics → cardinality ─────────────────────────────────────────


def derive_cardinality(col: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a column's NULL / uniqueness / PK metadata into a
    SHACL-style cardinality block.

    Rules
    -----
    - ``NOT NULL`` (or ``is_nullable=False``)        ⇒  ``minCount = 1``
    - Has a column-level ``DEFAULT``                 ⇒  override
      ``minCount = 0`` (the value is generated, not required of the user).
    - Primary key or column marked ``unique=True``   ⇒  ``maxCount = 1``
    - Otherwise both bounds are absent (``None``) — i.e. the property
      is single-valued by default at the OWL level and SHACL is silent.
    """
    block: Dict[str, Any] = {"minCount": None, "maxCount": None}
    has_default = col.get("default") is not None or col.get("column_default") is not None
    if _col_is_required(col) and not has_default:
        block["minCount"] = 1
    elif has_default:
        block["minCount"] = 0
    if _col_is_pk(col) or bool(col.get("unique")):
        block["maxCount"] = 1
    return block


# ── Views → derived classes ──────────────────────────────────────────────


@dataclass
class DerivedClassInfo:
    name:           str
    label:          str
    base_tables:    List[str]
    select_columns: List[str]
    raw_sql:        str = ""
    sparql_skeleton: str = ""


def detect_views(schema: Dict[str, Any]) -> List[DerivedClassInfo]:
    """Parse each ``views`` entry in the schema input into a
    DerivedClassInfo. Schema input shape (extension to the existing
    structural import):

        {"views": [{"name": "high_value_customers",
                    "sql": "CREATE VIEW high_value_customers AS
                            SELECT id, name FROM customers WHERE …"}]}

    We use sqlglot to lift the FROM clauses and SELECT columns. On any
    parse failure we still emit a DerivedClassInfo with the raw SQL,
    so downstream UI can render *something* the engineer can edit.
    """
    out: List[DerivedClassInfo] = []
    views = schema.get("views") or []
    for v in views:
        name = v.get("name") or ""
        if not name:
            continue
        sql = v.get("sql") or v.get("definition") or ""
        base_tables, columns, sparql = _parse_view_sql(name, sql)
        out.append(DerivedClassInfo(
            name=name,
            label=_label_from_snake(name),
            base_tables=base_tables,
            select_columns=columns,
            raw_sql=sql,
            sparql_skeleton=sparql,
        ))
    return out


def _parse_view_sql(name: str, sql: str) -> Tuple[List[str], List[str], str]:
    """Best-effort parse of a CREATE VIEW into (base tables, select
    columns, SPARQL CONSTRUCT skeleton). Returns empty lists on
    failure — we never raise out of the importer."""
    if not sql:
        return [], [], ""
    try:
        import sqlglot
        import sqlglot.expressions as exp
    except ImportError:
        return _regex_parse_view(name, sql)
    try:
        # sqlglot needs a SELECT; strip the CREATE VIEW prefix if
        # present so we can parse the inner query in isolation.
        body = re.sub(
            r"^\s*CREATE(\s+OR\s+REPLACE)?\s+VIEW\s+\S+\s+AS\s+",
            "", sql, flags=re.IGNORECASE | re.DOTALL,
        )
        tree = sqlglot.parse_one(body, read="postgres")
    except Exception:                                  # noqa: BLE001
        return _regex_parse_view(name, sql)
    if tree is None:
        return [], [], ""
    base_tables = sorted({t.name for t in tree.find_all(exp.Table)
                          if t.name})
    columns: List[str] = []
    for proj in tree.find_all(exp.Alias) if tree.find(exp.Alias) else []:
        columns.append(str(proj.alias_or_name))
    if not columns:
        for proj in tree.expressions if hasattr(tree, "expressions") else []:
            try:
                columns.append(str(proj.alias_or_name))
            except Exception:                          # noqa: BLE001
                continue
    sparql = _sparql_construct_from_view(name, base_tables, columns)
    return base_tables, columns, sparql


def _regex_parse_view(name: str, sql: str) -> Tuple[List[str], List[str], str]:
    """Fallback parse when sqlglot is unavailable or the SELECT is too
    weird for it. Cheap and cheerful — pulls table names from ``FROM``
    and column expressions from the projection."""
    body = re.sub(r"^\s*CREATE(\s+OR\s+REPLACE)?\s+VIEW\s+\S+\s+AS\s+",
                  "", sql, flags=re.IGNORECASE | re.DOTALL)
    base_tables: List[str] = []
    for m in re.finditer(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)",
                         body, flags=re.IGNORECASE):
        base_tables.append(m.group(1))
    for m in re.finditer(r"\bJOIN\s+([A-Za-z_][A-Za-z0-9_]*)",
                         body, flags=re.IGNORECASE):
        base_tables.append(m.group(1))
    base_tables = sorted(set(base_tables))
    columns: List[str] = []
    proj_match = re.search(r"SELECT\s+(.+?)\s+FROM\b", body,
                           flags=re.IGNORECASE | re.DOTALL)
    if proj_match:
        for col in proj_match.group(1).split(","):
            col = col.strip()
            if not col or col == "*":
                continue
            # 'foo AS bar' -> 'bar'
            m = re.search(r"(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*$",
                          col, flags=re.IGNORECASE)
            if m:
                columns.append(m.group(1))
    sparql = _sparql_construct_from_view(name, base_tables, columns)
    return base_tables, columns, sparql


def _sparql_construct_from_view(name: str,
                                base_tables: Sequence[str],
                                columns: Sequence[str]) -> str:
    cname = "".join(p.capitalize() for p in name.split("_") if p)
    base_pat = " .\n  ".join(f"?s a :{_label_from_snake(t).replace(' ', '')}"
                              for t in base_tables) or "?s ?p ?o"
    cols_pat = "\n  ".join(f":has{_label_from_snake(c).replace(' ', '')} ?{c}"
                            for c in columns)
    return (
        f"# SPARQL CONSTRUCT for derived class :{cname}\n"
        f"CONSTRUCT {{\n"
        f"  ?s a :{cname} .\n"
        + (f"  ?s {cols_pat} .\n" if cols_pat else "")
        + f"}} WHERE {{\n"
        f"  {base_pat} .\n"
        f"  # Edit at approval time — verify WHERE matches view semantics.\n"
        f"}}"
    )


# ── Top-level enhancer ───────────────────────────────────────────────────


@dataclass
class SemanticEnhanceReport:
    junctions_collapsed:  int = 0
    fk_chains_found:      int = 0
    cardinalities_added:  int = 0
    derived_classes:      int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "junctions_collapsed":  self.junctions_collapsed,
            "fk_chains_found":      self.fk_chains_found,
            "cardinalities_added":  self.cardinalities_added,
            "derived_classes":      self.derived_classes,
        }


def enhance_schema(session: Dict[str, Any],
                   schema: Dict[str, Any],
                   *,
                   detect_fk_chains_flag: bool = True,
                   detect_junctions_flag: bool = True,
                   null_to_cardinality: bool = True,
                   views_to_classes: bool = True,
                   ) -> Tuple[Dict[str, Any], SemanticEnhanceReport]:
    """Apply the four T1.4 enhancements to ``session``. Returns the
    enhanced session and a report counting what was added.

    ``session`` is the wizard-shaped dict from ``_norm_schema``.
    ``schema`` is the original raw ``{tables: …}`` input — we still
    need its FK lists, view definitions, and column-level NULL flags
    after the structural pass dropped them.
    """
    out = copy.deepcopy(session)
    out.setdefault("property_paths", [])
    out.setdefault("derived_classes", [])
    report = SemanticEnhanceReport()

    name_to_label = {t["name"]: t.get("label") or _label_from_snake(t["name"])
                     for t in (out.get("entities") or [])
                     if t.get("name")}

    # ── Junction collapse ─────────────────────────────────────────────
    junctions: List[JunctionInfo] = []
    if detect_junctions_flag:
        junctions = detect_junction_tables(schema)
        report.junctions_collapsed = len(junctions)
        junction_tables: Set[str] = {j.table for j in junctions}

        # Replace the two FK-derived relationships that point at the
        # junction with a single direct relationship endpoint_a ↔ endpoint_b.
        new_rels: List[Dict[str, Any]] = []
        for rel in out.get("relationships") or []:
            if rel.get("from_entity") in junction_tables \
                    or rel.get("to_entity") in junction_tables \
                    or name_to_label.get(rel.get("from_entity", ""), rel.get("from_entity", "")) in junction_tables \
                    or name_to_label.get(rel.get("to_entity", ""), rel.get("to_entity", "")) in junction_tables:
                continue
            new_rels.append(rel)
        # Dedup against any already-collapsed via-rels on a re-run.
        existing_via = {r.get("via") for r in new_rels if r.get("via")}
        for j in junctions:
            if j.table in existing_via:
                continue
            new_rels.append({
                "from_entity": name_to_label.get(j.endpoint_a, j.endpoint_a),
                "label":       j.label,
                "to_entity":   name_to_label.get(j.endpoint_b, j.endpoint_b),
                "via":         j.table,
                "extra_cols":  list(j.extra_cols),
            })
        out["relationships"] = new_rels
        # Drop the junction tables from the entity list — they're
        # represented as relationships now.
        out["entities"] = [e for e in (out.get("entities") or [])
                            if e.get("name") not in junction_tables]

    # ── FK chains ─────────────────────────────────────────────────────
    if detect_fk_chains_flag:
        chains = detect_fk_chains(schema)
        report.fk_chains_found = len(chains)
        # Dedup via (start, end, shacl_path) so a second pass on
        # already-enhanced session doesn't double the list.
        existing_paths = {
            (p.get("start"), p.get("end"), p.get("shacl_path"))
            for p in out["property_paths"]
        }
        for c in chains:
            key = (c.start_table, c.end_table, c.as_property_path())
            if key in existing_paths:
                continue
            out["property_paths"].append({
                "start": c.start_table,
                "end":   c.end_table,
                "steps": [
                    {"from": s[0], "via_column": s[1], "to": s[2]}
                    for s in c.steps
                ],
                "shacl_path": c.as_property_path(),
            })
            existing_paths.add(key)

    # ── NULL → cardinality ────────────────────────────────────────────
    if null_to_cardinality:
        # Build lookup: table_name -> {col_name -> column dict}
        col_lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for t in schema.get("tables") or []:
            tn = t.get("name") or ""
            col_lookup[tn] = {c.get("name"): c for c in _table_columns(t)
                              if c.get("name")}
        for entity in out.get("entities") or []:
            tname = entity.get("name") or ""
            cols = col_lookup.get(tname, {})
            for prop in entity.get("properties") or []:
                col = cols.get(prop.get("name"))
                if not col:
                    continue
                card = derive_cardinality(col)
                if card["minCount"] is not None or card["maxCount"] is not None:
                    prop["cardinality"] = {
                        k: v for k, v in card.items() if v is not None
                    }
                    report.cardinalities_added += 1

    # ── Views → derived classes ───────────────────────────────────────
    if views_to_classes:
        derived = detect_views(schema)
        report.derived_classes = len(derived)
        # Dedup by name (a view is uniquely identified by its name in
        # SQL — re-running shouldn't add a duplicate row).
        existing_names = {d.get("name") for d in out["derived_classes"]}
        for d in derived:
            if d.name in existing_names:
                continue
            out["derived_classes"].append({
                "name":             d.name,
                "label":            d.label,
                "base_tables":      d.base_tables,
                "select_columns":   d.select_columns,
                "raw_sql":          d.raw_sql,
                "sparql_skeleton":  d.sparql_skeleton,
            })
            existing_names.add(d.name)

    return out, report


__all__ = [
    "JunctionInfo", "FkChainInfo", "DerivedClassInfo",
    "SemanticEnhanceReport",
    "detect_junction_tables", "detect_fk_chains",
    "derive_cardinality", "detect_views",
    "enhance_schema",
]
