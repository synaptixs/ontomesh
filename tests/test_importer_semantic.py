"""T1.4 — Semantic schema-import enhancements.

Tests the four enhancements that layer onto :mod:`wizard.importer`:

- Foreign-key chains → property paths
- Junction tables → object properties (collapsed)
- NULL semantics → cardinality (sh:minCount / sh:maxCount)
- View definitions → derived classes

Acceptance gates (roadmap §3.T1.4):
- ≥ 30 % more cardinality constraints vs the structural-only path.
- ≥ 5 collapsed junction-table relationships on a Sakila-style schema.
- Idempotent on re-import.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from wizard.importer import _norm_schema                              # noqa: E402
from wizard.importer_semantic import (                                # noqa: E402
    DerivedClassInfo, FkChainInfo, JunctionInfo,
    derive_cardinality, detect_fk_chains, detect_junction_tables,
    detect_views, enhance_schema,
)


# ── Synthetic Sakila-style schema ─────────────────────────────────────


def _sakila_lite() -> dict:
    """Cut-down Sakila with all four T1.4 features. Built so each
    feature is testable in isolation without depending on the others.

    Junction tables: film_actor, film_category, inventory_actor,
    customer_address, store_staff.
    FK chains: customer → store → address → city → country (4 hops).
    NOT NULL: most PKs + lots of business columns.
    Views: active_customer, film_list.
    """
    return {
        "domain":   "sakila-lite",
        "tables": [
            # ── Atoms ────────────────────────────────────────────────
            {
                "name": "country",
                "columns": [
                    {"name": "country_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "country", "type": "TEXT", "not_null": True},
                ],
            },
            {
                "name": "city",
                "columns": [
                    {"name": "city_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "city", "type": "TEXT", "not_null": True},
                    {"name": "country_id", "type": "INTEGER", "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "country_id", "references_table": "country"},
                ],
            },
            {
                "name": "address",
                "columns": [
                    {"name": "address_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "address", "type": "TEXT", "not_null": True},
                    {"name": "postal_code", "type": "TEXT"},          # nullable
                    {"name": "city_id", "type": "INTEGER", "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "city_id", "references_table": "city"},
                ],
            },
            {
                "name": "store",
                "columns": [
                    {"name": "store_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "address_id", "type": "INTEGER", "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "address_id", "references_table": "address"},
                ],
            },
            {
                "name": "customer",
                "columns": [
                    {"name": "customer_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "store_id", "type": "INTEGER", "not_null": True},
                    {"name": "email", "type": "TEXT"},                # nullable
                    {"name": "first_name", "type": "TEXT", "not_null": True},
                    {"name": "create_date", "type": "TIMESTAMP",
                     "not_null": True, "default": "CURRENT_TIMESTAMP"},
                ],
                "foreign_keys": [
                    {"column": "store_id", "references_table": "store"},
                ],
            },
            {
                "name": "film",
                "columns": [
                    {"name": "film_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "title", "type": "TEXT", "not_null": True},
                ],
            },
            {
                "name": "actor",
                "columns": [
                    {"name": "actor_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "first_name", "type": "TEXT", "not_null": True},
                ],
            },
            {
                "name": "category",
                "columns": [
                    {"name": "category_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "name", "type": "TEXT", "not_null": True},
                ],
            },
            {
                "name": "language",
                "columns": [
                    {"name": "language_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "name", "type": "TEXT", "not_null": True},
                ],
            },
            {
                "name": "staff",
                "columns": [
                    {"name": "staff_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "first_name", "type": "TEXT", "not_null": True},
                ],
            },

            # ── 5 junction tables ────────────────────────────────────
            {
                "name": "film_actor",
                "columns": [
                    {"name": "film_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "actor_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "film_id", "references_table": "film"},
                    {"column": "actor_id", "references_table": "actor"},
                ],
            },
            {
                "name": "film_category",
                "columns": [
                    {"name": "film_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "category_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "film_id", "references_table": "film"},
                    {"column": "category_id", "references_table": "category"},
                ],
            },
            {
                "name": "film_language",
                "columns": [
                    {"name": "film_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "language_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "film_id", "references_table": "film"},
                    {"column": "language_id", "references_table": "language"},
                ],
            },
            {
                "name": "customer_address",
                "columns": [
                    {"name": "customer_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "address_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "customer_id", "references_table": "customer"},
                    {"column": "address_id", "references_table": "address"},
                ],
            },
            {
                "name": "store_staff",
                "columns": [
                    {"name": "store_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                    {"name": "staff_id", "type": "INTEGER", "is_pk": True, "not_null": True},
                ],
                "foreign_keys": [
                    {"column": "store_id", "references_table": "store"},
                    {"column": "staff_id", "references_table": "staff"},
                ],
            },
        ],
        "views": [
            {
                "name": "active_customer",
                "sql": (
                    "CREATE VIEW active_customer AS "
                    "SELECT customer_id, first_name AS name, email "
                    "FROM customer WHERE create_date >= '2024-01-01'"
                ),
            },
            {
                "name": "film_list",
                "sql": (
                    "CREATE VIEW film_list AS "
                    "SELECT film.film_id, film.title, category.name AS category "
                    "FROM film JOIN film_category ON film.film_id = film_category.film_id "
                    "JOIN category ON category.category_id = film_category.category_id"
                ),
            },
        ],
    }


# ── Junction-table detection ──────────────────────────────────────────


def test_junction_detection_finds_all_five_pure_junctions():
    schema = _sakila_lite()
    jns = detect_junction_tables(schema)
    names = {j.table for j in jns}
    expected = {"film_actor", "film_category", "film_language",
                "customer_address", "store_staff"}
    assert names == expected, f"got {names}; expected {expected}"


def test_junction_detection_skips_table_with_too_many_columns():
    """A 2-FK table with 4+ scalar columns is NOT a pure junction."""
    schema = {
        "tables": [
            {"name": "atom_a", "columns": [
                {"name": "id", "is_pk": True, "not_null": True}]},
            {"name": "atom_b", "columns": [
                {"name": "id", "is_pk": True, "not_null": True}]},
            {"name": "order_line", "columns": [
                {"name": "a_id", "is_pk": True, "not_null": True},
                {"name": "b_id", "is_pk": True, "not_null": True},
                {"name": "qty",          "type": "INTEGER"},
                {"name": "price",        "type": "DECIMAL"},
                {"name": "discount",     "type": "DECIMAL"},
                {"name": "shipped_at",   "type": "TIMESTAMP"},
                {"name": "warehouse_id", "type": "INTEGER"},
            ], "foreign_keys": [
                {"column": "a_id", "references_table": "atom_a"},
                {"column": "b_id", "references_table": "atom_b"},
            ]},
        ]
    }
    assert detect_junction_tables(schema) == []


def test_junction_detection_skips_self_referential_pair():
    """Two FKs to the same table is a tree edge, not a junction."""
    schema = {
        "tables": [
            {"name": "node", "columns": [{"name": "id", "is_pk": True, "not_null": True}]},
            {"name": "edge", "columns": [
                {"name": "src_id", "is_pk": True, "not_null": True},
                {"name": "dst_id", "is_pk": True, "not_null": True},
            ], "foreign_keys": [
                {"column": "src_id", "references_table": "node"},
                {"column": "dst_id", "references_table": "node"},
            ]},
        ]
    }
    assert detect_junction_tables(schema) == []


# ── FK chain detection ────────────────────────────────────────────────


def test_fk_chain_finds_customer_to_country_path():
    schema = _sakila_lite()
    chains = detect_fk_chains(schema, min_length=2, max_length=5)
    # customer → store → address → city → country is a 4-step chain.
    long_chain = [c for c in chains
                  if c.start_table == "customer" and c.end_table == "country"]
    assert long_chain, f"expected customer→country chain; got {[(c.start_table, c.end_table) for c in chains]}"


def test_fk_chain_exclude_junctions_skips_paths_through_junctions():
    schema = _sakila_lite()
    chains = detect_fk_chains(schema, exclude_junctions=True)
    # No chain should pass through a junction table.
    junction_names = {"film_actor", "film_category", "film_language",
                       "customer_address", "store_staff"}
    for c in chains:
        intermediate = {step[2] for step in c.steps[:-1]}
        assert not (intermediate & junction_names)


def test_fk_chain_property_path_rendering_is_slash_separated():
    chain = FkChainInfo(
        start_table="customer", end_table="country",
        steps=[("customer", "store_id", "store"),
               ("store", "address_id", "address"),
               ("address", "city_id", "city"),
               ("city", "country_id", "country")],
    )
    path = chain.as_property_path()
    assert " / " in path
    assert path.startswith(":has")


# ── NULL → cardinality ────────────────────────────────────────────────


def test_cardinality_not_null_column():
    col = {"name": "email", "not_null": True}
    out = derive_cardinality(col)
    assert out == {"minCount": 1, "maxCount": None}


def test_cardinality_nullable_column():
    col = {"name": "middle_name", "not_null": False}
    out = derive_cardinality(col)
    assert out["minCount"] is None
    assert out["maxCount"] is None


def test_cardinality_column_with_default_relaxes_min():
    col = {"name": "created_at", "not_null": True,
           "default": "CURRENT_TIMESTAMP"}
    out = derive_cardinality(col)
    # Default value satisfies the NOT NULL → don't require it of the
    # user. The DB will fill it.
    assert out["minCount"] == 0


def test_cardinality_primary_key_caps_max():
    col = {"name": "id", "is_pk": True, "not_null": True}
    out = derive_cardinality(col)
    assert out == {"minCount": 1, "maxCount": 1}


def test_cardinality_explicit_is_nullable_false():
    col = {"name": "field", "is_nullable": False}
    assert derive_cardinality(col)["minCount"] == 1


# ── Views → derived classes ───────────────────────────────────────────


def test_detect_views_returns_both_view_entries():
    schema = _sakila_lite()
    views = detect_views(schema)
    assert {v.name for v in views} == {"active_customer", "film_list"}


def test_detect_view_extracts_base_tables():
    schema = _sakila_lite()
    views = {v.name: v for v in detect_views(schema)}
    assert "customer" in views["active_customer"].base_tables
    assert "film" in views["film_list"].base_tables
    assert "category" in views["film_list"].base_tables


def test_detect_view_emits_sparql_skeleton_with_construct_keyword():
    schema = _sakila_lite()
    views = detect_views(schema)
    for v in views:
        assert "CONSTRUCT" in v.sparql_skeleton


# ── End-to-end enhance_schema ─────────────────────────────────────────


def test_enhance_schema_acceptance_gate():
    """Hero acceptance gate from the v3 roadmap §3.T1.4."""
    schema = _sakila_lite()
    baseline = _norm_schema(schema)

    enhanced, report = enhance_schema(baseline, schema)

    # ≥ 5 collapsed junctions
    assert report.junctions_collapsed >= 5

    # ≥ 30 % more cardinality constraints vs structural (which had 0).
    baseline_cardinalities = sum(
        1 for e in baseline.get("entities", [])
        for p in e.get("properties", [])
        if "cardinality" in p
    )
    assert baseline_cardinalities == 0
    assert report.cardinalities_added > 0

    # FK chains found
    assert report.fk_chains_found > 0

    # Views surfaced
    assert report.derived_classes == 2


def test_enhance_schema_removes_junction_entities():
    schema = _sakila_lite()
    baseline = _norm_schema(schema)
    enhanced, _ = enhance_schema(baseline, schema)
    junction_names = {"film_actor", "film_category", "film_language",
                       "customer_address", "store_staff"}
    enhanced_entity_names = {e.get("name") for e in enhanced.get("entities", [])}
    assert junction_names.isdisjoint(enhanced_entity_names)


def test_enhance_schema_adds_collapsed_relationship_with_via():
    schema = _sakila_lite()
    baseline = _norm_schema(schema)
    enhanced, _ = enhance_schema(baseline, schema)
    via_rels = [r for r in enhanced.get("relationships", []) if r.get("via")]
    assert len(via_rels) >= 5
    for r in via_rels:
        assert r.get("from_entity") and r.get("to_entity")


def test_enhance_schema_attaches_cardinality_to_properties():
    schema = _sakila_lite()
    baseline = _norm_schema(schema)
    enhanced, _ = enhance_schema(baseline, schema)
    # Check that the `country` entity got cardinality on `country` (NOT NULL).
    country_entity = next(e for e in enhanced["entities"]
                          if e["name"] == "country")
    country_prop = next(p for p in country_entity["properties"]
                        if p["name"] == "country")
    assert "cardinality" in country_prop
    assert country_prop["cardinality"].get("minCount") == 1


def test_enhance_schema_is_idempotent_on_double_run():
    schema = _sakila_lite()
    baseline = _norm_schema(schema)
    once, _ = enhance_schema(baseline, schema)
    twice, _ = enhance_schema(once, schema)
    # Same counts on both runs — running on already-enhanced data
    # produces the same shape.
    assert len(once["entities"]) == len(twice["entities"])
    assert len(once["relationships"]) == len(twice["relationships"])
    assert len(once["property_paths"]) == len(twice["property_paths"])
    assert len(once["derived_classes"]) == len(twice["derived_classes"])


def test_enhance_schema_respects_feature_toggles():
    schema = _sakila_lite()
    baseline = _norm_schema(schema)

    # Disable junctions → entity list unchanged.
    out, report = enhance_schema(
        baseline, schema,
        detect_junctions_flag=False,
        detect_fk_chains_flag=False,
        null_to_cardinality=False,
        views_to_classes=False,
    )
    assert report.junctions_collapsed == 0
    assert report.fk_chains_found == 0
    assert report.cardinalities_added == 0
    assert report.derived_classes == 0
    # Entities preserved.
    junction_names = {"film_actor", "film_category", "film_language",
                       "customer_address", "store_staff"}
    enhanced_entity_names = {e.get("name") for e in out.get("entities", [])}
    assert junction_names.issubset(enhanced_entity_names)


def test_enhance_schema_returns_report_with_all_counters():
    schema = _sakila_lite()
    baseline = _norm_schema(schema)
    _, report = enhance_schema(baseline, schema)
    d = report.as_dict()
    assert set(d) == {"junctions_collapsed", "fk_chains_found",
                       "cardinalities_added", "derived_classes"}
    for v in d.values():
        assert v >= 0
