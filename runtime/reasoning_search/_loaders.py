"""Loaders: flavor controlled-vocabulary + logical↔physical mapping (§11 #6/#7).

These turn the artifacts Ontomesh already generates — the flavor configs under
``runtime/flavors/`` and ``output/mapping/logical_physical_map.csv`` — into the
in-memory structures the planner and query compiler need.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field


# ── Flavor ────────────────────────────────────────────────────────────────
def load_flavor(flavor: str, flavors_dir: str) -> dict:
    """Load a flavor config dict by name from ``flavors_dir``."""
    path = os.path.join(flavors_dir, f"{flavor}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"unknown flavor '{flavor}' (looked in {flavors_dir})")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def controlled_vocab(flavor_cfg: dict) -> set[str]:
    """The terms the planner may reference: OWL classes + context-term keys.

    Anything the planner emits outside this set is rejected — the ontology is the
    guardrail against hallucinated entities.
    """
    vocab: set[str] = set(flavor_cfg.get("owl_classes", []) or [])
    vocab |= set((flavor_cfg.get("context_terms") or {}).keys())
    return vocab


# ── Mapping ───────────────────────────────────────────────────────────────
@dataclass
class Mapping:
    """Logical↔physical map distilled from logical_physical_map.csv."""

    class_table: dict[str, str] = field(default_factory=dict)            # OWL class -> table
    prop_col: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)  # (class,prop)->(table,col)
    tier: dict[str, str] = field(default_factory=dict)                   # element -> sensitivity tier

    def table_for(self, owl_class: str) -> str | None:
        return self.class_table.get(owl_class)

    def column_for(self, owl_class: str, prop: str) -> tuple[str, str] | None:
        loc = self.resolve(owl_class, prop)
        return (loc[1], loc[2]) if loc else None

    def resolve(self, owl_class: str, prop: str) -> tuple[str, str, str] | None:
        """Resolve a property to ``(canonical_prop, table, column)``.

        Tries an exact match first, then a naming-convention-tolerant match so a
        planner term like ``alarmState`` still resolves to the mapping's
        ``hasAlarmState`` (the OWL property names are commonly ``has``/``is``
        prefixed while flavor ``context_terms`` use the short form).
        """
        exact = self.prop_col.get((owl_class, prop))
        if exact:
            return (prop, exact[0], exact[1])
        key = _norm_prop(prop)
        for (c, p), (table, col) in self.prop_col.items():
            if c == owl_class and _norm_prop(p) == key:
                return (p, table, col)
        return None


def _norm_prop(prop: str) -> str:
    """Normalize a property name for tolerant matching: lowercase, alnum-only,
    drop a leading ``has``/``is`` prefix (camelCase OWL convention)."""
    s = "".join(ch for ch in str(prop).lower() if ch.isalnum())
    for pre in ("has", "is"):
        if s.startswith(pre) and len(s) > len(pre) + 2:
            return s[len(pre):]
    return s


def load_mapping(csv_path: str) -> Mapping:
    """Parse the generated logical↔physical CSV into a `Mapping`.

    Columns: ontology_class, ontology_property, property_type, logical_element,
    physical_table, physical_column, xsd_type, required, sensitivity_tier, …
    """
    m = Mapping()
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"mapping not found: {csv_path} (run the toolkit first)")
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cls = (row.get("ontology_class") or "").strip()
            prop = (row.get("ontology_property") or "").strip()
            table = (row.get("physical_table") or "").strip()
            col = (row.get("physical_column") or "").strip()
            tier = (row.get("sensitivity_tier") or "").strip()
            if not cls or not table:
                continue
            # Class row: ontology_property == "(class)" or physical_column == "(table)"
            if prop in ("", "(class)") or col in ("", "(table)"):
                m.class_table[cls] = table
                if tier:
                    m.tier[cls] = tier
            else:
                m.prop_col[(cls, prop)] = (table, col)
                if tier:
                    m.tier[f"{cls}.{prop}"] = tier
    return m
