"""T1.5 — Multi-target generation.

Tests for the three target adapters (Cypher, GraphQL, detection
rules) plus the registry / dispatcher.

Acceptance gates (roadmap §3.T1.5):
- Same ontology emits OWL, Cypher, and GraphQL in one pass.
- ≥ 3 generated Datadog alerts pass YAML schema validation on a
  sample causal-edge set.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from targets import (                                                # noqa: E402
    AVAILABLE_TARGETS, CypherTarget, DetectionRulesTarget,
    GenerationContext, GraphQLTarget, get_target, render_targets,
)
from targets.registry import write_target_outputs                    # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────


@dataclass
class FakeColumn:
    """Minimal stand-in for db_introspector.ColumnModel."""
    name: str
    sqlite_type: str = "TEXT"
    is_pk: bool = False
    is_fk: bool = False
    fk_references: Any = None
    not_null: bool = False


@dataclass
class FakeTable:
    """Minimal stand-in for db_introspector.TableModel."""
    name: str
    columns: List[FakeColumn] = field(default_factory=list)
    pk_columns: List[str] = field(default_factory=list)
    label: str = ""
    description: str = ""


def _ctx_with_two_tables() -> GenerationContext:
    customer = FakeTable(
        name="customer", pk_columns=["id"], label="Customer",
        columns=[
            FakeColumn("id", "INTEGER", is_pk=True, not_null=True),
            FakeColumn("name", "TEXT", not_null=True),
            FakeColumn("email", "TEXT"),
        ],
    )
    order = FakeTable(
        name="order", pk_columns=["id"], label="Order",
        columns=[
            FakeColumn("id", "INTEGER", is_pk=True, not_null=True),
            FakeColumn("customer_id", "INTEGER",
                       is_fk=True, fk_references="customer", not_null=True),
            FakeColumn("total", "DECIMAL"),
        ],
    )
    return GenerationContext(
        tables=[customer, order],
        session={"domain": {"name": "Retail", "base_iri": "http://example.com/retail/"}},
        base_iri="http://example.com/retail/",
        domain_name="Retail",
    )


def _ctx_with_causal_proposals() -> GenerationContext:
    return GenerationContext(
        proposals=[
            {
                "kind": "LOG_CAUSAL_EDGE",
                "proposal_id": "edge-1",
                "title": "Causal candidate: NetworkPartition → ServiceADown (PMI 7.2, via granger)",
                "confidence_score": 0.93,
                "shared_causes": [],
            },
            {
                "kind": "LOG_CAUSAL_EDGE",
                "proposal_id": "edge-2",
                "title": "Causal candidate: DeployStart → ServiceBLatency (PMI 5.8, via granger)",
                "confidence_score": 0.78,
                "shared_causes": [42],
            },
            {
                "kind": "LOG_CAUSAL_EDGE",
                "proposal_id": "edge-3",
                "title": "Causal candidate: AuthFailure → SessionRetryStorm (PMI 6.1, via transfer-entropy)",
                "confidence_score": 0.65,
                "shared_causes": [],
            },
            # A non-causal proposal that should be ignored.
            {"kind": "LOG_EVENT", "proposal_id": "evt-1", "title": "noise"},
        ],
        domain_name="LogRCA",
    )


# ── Registry ─────────────────────────────────────────────────────────


def test_available_targets_lists_all_three():
    assert "cypher" in AVAILABLE_TARGETS
    assert "graphql" in AVAILABLE_TARGETS
    assert "detection_rules" in AVAILABLE_TARGETS


def test_get_target_known_and_unknown():
    assert get_target("cypher") is not None
    assert get_target("graphql") is not None
    assert get_target("detection_rules") is not None
    assert get_target("nonexistent") is None
    assert get_target("") is None


def test_render_targets_unknown_name_returns_warning_not_raise():
    ctx = _ctx_with_two_tables()
    out = render_targets(ctx, names=["cypher", "nonexistent"])
    assert "cypher" in out
    assert "nonexistent" in out
    assert out["nonexistent"].warnings
    assert "unknown" in out["nonexistent"].warnings[0]
    assert out["nonexistent"].files == {}


# ── Cypher target ────────────────────────────────────────────────────


def test_cypher_emits_schema_and_migration_files():
    ctx = _ctx_with_two_tables()
    res = CypherTarget().generate(ctx)
    assert "cypher/schema.cypher" in res.files
    assert "cypher/migration.cypher" in res.files


def test_cypher_creates_unique_constraints_for_pks():
    ctx = _ctx_with_two_tables()
    res = CypherTarget().generate(ctx)
    schema = res.files["cypher/schema.cypher"]
    assert "CREATE CONSTRAINT" in schema
    assert "IS UNIQUE" in schema
    assert "Customer_id_unique" in schema
    assert "Order_id_unique" in schema


def test_cypher_pascalcases_table_names():
    table = FakeTable(name="order_items", pk_columns=["id"],
                      columns=[FakeColumn("id", is_pk=True)])
    ctx = GenerationContext(tables=[table])
    res = CypherTarget().generate(ctx)
    assert "OrderItems" in res.files["cypher/schema.cypher"]


def test_cypher_stats_count_nodes_and_constraints():
    ctx = _ctx_with_two_tables()
    res = CypherTarget().generate(ctx)
    assert res.stats["nodes"] == 2
    assert res.stats["constraints"] == 2


# ── GraphQL target ───────────────────────────────────────────────────


def test_graphql_emits_schema_file():
    ctx = _ctx_with_two_tables()
    res = GraphQLTarget().generate(ctx)
    assert "graphql/schema.graphql" in res.files


def test_graphql_renders_types_for_each_table():
    ctx = _ctx_with_two_tables()
    res = GraphQLTarget().generate(ctx)
    sdl = res.files["graphql/schema.graphql"]
    assert "type Customer {" in sdl
    assert "type Order {" in sdl


def test_graphql_pk_columns_become_id_not_null():
    ctx = _ctx_with_two_tables()
    sdl = GraphQLTarget().generate(ctx).files["graphql/schema.graphql"]
    # PK 'id' → 'id: ID!' (uppercase Id treated as scalar ID)
    assert "id: ID!" in sdl


def test_graphql_not_null_columns_are_marked_required():
    ctx = _ctx_with_two_tables()
    sdl = GraphQLTarget().generate(ctx).files["graphql/schema.graphql"]
    # name is not_null=True on Customer
    assert "name: String!" in sdl


def test_graphql_fk_columns_become_reference_fields():
    ctx = _ctx_with_two_tables()
    sdl = GraphQLTarget().generate(ctx).files["graphql/schema.graphql"]
    # The order's customer_id FK should produce a customer: Customer field
    assert "customer: Customer" in sdl


def test_graphql_emits_query_root_with_all_resolvers():
    ctx = _ctx_with_two_tables()
    sdl = GraphQLTarget().generate(ctx).files["graphql/schema.graphql"]
    assert "type Query {" in sdl
    assert "allCustomers: [Customer!]!" in sdl
    assert "allOrders: [Order!]!" in sdl


def test_graphql_works_on_wizard_entities_without_tables():
    """When there's no DBIntrospector, the wizard session's entities
    should be used as the source of truth."""
    ctx = GenerationContext(
        tables=[],
        session={
            "domain": {"name": "Wiz", "base_iri": "http://w/"},
            "entities": [
                {"name": "agent", "label": "Agent", "properties": [
                    {"name": "id", "type": "uuid",
                     "cardinality": {"minCount": 1, "maxCount": 1}},
                    {"name": "memory_size", "type": "integer",
                     "cardinality": {"minCount": 1}},
                ]},
            ],
        },
    )
    sdl = GraphQLTarget().generate(ctx).files["graphql/schema.graphql"]
    assert "type Agent {" in sdl
    assert "id: ID!" in sdl


# ── Detection rules target ───────────────────────────────────────────


def test_detection_rules_no_causal_edges_emits_no_files_but_warns():
    ctx = GenerationContext(proposals=[])
    res = DetectionRulesTarget().generate(ctx)
    assert res.files == {}
    assert res.warnings
    assert "no LOG_CAUSAL_EDGE" in res.warnings[0]


def test_detection_rules_emits_three_pairs_for_three_edges():
    """Roadmap §3.T1.5 gate: ≥ 3 generated Datadog alerts on a
    sample causal-edge set."""
    ctx = _ctx_with_causal_proposals()
    res = DetectionRulesTarget().generate(ctx)
    assert res.stats["datadog"] == 3
    assert res.stats["splunk"] == 3
    # Each edge gets 2 files (DD + Splunk) plus one shared index.
    assert sum(1 for k in res.files if k.startswith("detection_rules/datadog/")) == 3
    assert sum(1 for k in res.files if k.startswith("detection_rules/splunk/")) == 3
    assert "detection_rules/index.json" in res.files


def test_detection_rules_index_is_valid_json_with_edges():
    ctx = _ctx_with_causal_proposals()
    res = DetectionRulesTarget().generate(ctx)
    idx = json.loads(res.files["detection_rules/index.json"])
    assert idx["generator"] == "T1.5"
    assert len(idx["edges"]) == 3
    for e in idx["edges"]:
        assert {"edge_id", "cause", "effect", "confidence",
                "priority", "datadog", "splunk"} <= set(e)


def test_detection_rules_priority_maps_from_confidence():
    ctx = _ctx_with_causal_proposals()
    res = DetectionRulesTarget().generate(ctx)
    idx = json.loads(res.files["detection_rules/index.json"])
    by_edge = {e["edge_id"]: e for e in idx["edges"]}
    # 0.93 → priority 1, 0.78 → 2, 0.65 → 3
    priorities = sorted(e["priority"] for e in idx["edges"])
    assert priorities == [1, 2, 3]


def test_detection_rules_datadog_yaml_parses():
    """Hero acceptance proxy: every Datadog YAML produced should
    parse via PyYAML — the closest we can get to "Datadog YAML
    linter passes" without the linter binary."""
    pytest.importorskip("yaml")
    import yaml
    ctx = _ctx_with_causal_proposals()
    res = DetectionRulesTarget().generate(ctx)
    parsed = 0
    for path, content in res.files.items():
        if path.startswith("detection_rules/datadog/"):
            doc = yaml.safe_load(content)
            assert isinstance(doc, dict)
            assert "name" in doc and "tags" in doc and "priority" in doc
            parsed += 1
    assert parsed >= 3


def test_detection_rules_shared_causes_appear_in_index():
    ctx = _ctx_with_causal_proposals()
    res = DetectionRulesTarget().generate(ctx)
    idx = json.loads(res.files["detection_rules/index.json"])
    sc = [e for e in idx["edges"] if e["shared_causes"]]
    assert any(42 in e["shared_causes"] for e in sc)


# ── Full pipeline / acceptance gate ─────────────────────────────────


def test_acceptance_gate_one_context_three_targets():
    """Roadmap §3.T1.5 hero: same ontology emits OWL, Cypher, and
    GraphQL in one pass. OWL is the existing generator (out of
    scope here); we verify that one GenerationContext drives the
    other three targets in a single render_targets call."""
    ctx = _ctx_with_two_tables()
    out = render_targets(ctx, names=["cypher", "graphql", "detection_rules"])
    assert set(out) == {"cypher", "graphql", "detection_rules"}
    assert "cypher/schema.cypher" in out["cypher"].files
    assert "graphql/schema.graphql" in out["graphql"].files
    # detection_rules empty here (no causal edges); that's the
    # expected graceful skip.
    assert out["detection_rules"].files == {}
    assert out["detection_rules"].warnings


def test_write_target_outputs_persists_to_disk(tmp_path):
    ctx = _ctx_with_two_tables()
    out = render_targets(ctx, names=["cypher", "graphql"])
    written = write_target_outputs(out, str(tmp_path))
    assert "cypher/schema.cypher" in written
    assert "graphql/schema.graphql" in written
    for rel, abs_path in written.items():
        assert Path(abs_path).is_file()
        assert Path(abs_path).read_text()


def test_targets_are_idempotent_on_re_render():
    """Same context → same output (no timestamps, no random IDs)."""
    ctx = _ctx_with_two_tables()
    out1 = render_targets(ctx, names=["cypher", "graphql"])
    out2 = render_targets(ctx, names=["cypher", "graphql"])
    assert out1["cypher"].files == out2["cypher"].files
    assert out1["graphql"].files == out2["graphql"].files
