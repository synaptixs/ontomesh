"""F1 + suggestion #3.

Covers the ontology vocabulary catalogue and the slot-fill SHACL
compiler that drives the graphical rule builder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from vocabulary import get_vocabulary, parse_vocabulary, clear_cache  # noqa: E402
from wizard.rules import (  # noqa: E402
    compile_slots, normalise_rule, validate_rule,
)


# ── Vocabulary parser ────────────────────────────────────────────────────


@pytest.fixture
def tiny_ontology(tmp_path: Path) -> str:
    ttl = tmp_path / "ent.ttl"
    ttl.write_text("""\
@prefix : <https://test.example/v1#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Asset a owl:Class ; rdfs:label "Asset" .
:Site  a owl:Class ; rdfs:subClassOf :Asset ; rdfs:label "Site" .

:hosts a owl:ObjectProperty ;
       rdfs:label "hosts" ;
       rdfs:domain :Site ; rdfs:range :Asset .

:status a owl:DatatypeProperty ;
        rdfs:label "status" ;
        rdfs:domain :Asset ; rdfs:range xsd:string .
""")
    return str(ttl)


def test_parse_vocabulary_finds_classes_and_properties(tiny_ontology):
    vocab = parse_vocabulary(tiny_ontology)
    assert vocab.triple_count > 0
    qnames = {c.qname for c in vocab.classes}
    assert ":Asset" in qnames
    assert ":Site" in qnames
    site = next(c for c in vocab.classes if c.qname == ":Site")
    assert any(p.endswith("Asset") for p in site.parents)

    props = {p.qname: p for p in vocab.properties}
    assert props[":hosts"].kind == "object"
    assert props[":hosts"].domain[0].endswith("Site")
    assert props[":hosts"].range[0].endswith("Asset")
    assert props[":status"].kind == "data"


def test_get_vocabulary_caches_by_mtime(tiny_ontology, monkeypatch):
    clear_cache()
    v1 = get_vocabulary(tiny_ontology)
    v2 = get_vocabulary(tiny_ontology)
    # Same object identity → cache hit.
    assert v1 is v2
    # Touching the file invalidates the cache.
    Path(tiny_ontology).touch()
    v3 = get_vocabulary(tiny_ontology)
    assert v3 is not v1


def test_vocabulary_missing_file_returns_empty(tmp_path):
    vocab = parse_vocabulary(str(tmp_path / "absent.ttl"))
    assert vocab.classes == [] and vocab.properties == []


# ── Slot-fill compiler ───────────────────────────────────────────────────


def test_compile_slots_produces_valid_shacl():
    meta = {
        "target_class": ":Site",
        "conditions": [
            {"path": ":hosts", "op": "exists"},
            {"path": ":status", "op": "=", "value": "OUTAGE"},
        ],
        "assertion": {"path": ":hasIncident", "value": True},
    }
    body = compile_slots(meta, rule_id="site-impact")
    assert "sh:NodeShape" in body
    assert "sh:targetClass :Site" in body
    assert "sh:hasValue \"OUTAGE\"" in body
    assert "sh:rule" in body
    # Round-trip through validate_rule (parses SHACL + smoke executes).
    res = validate_rule({"kind": "shacl", "label": "x", "meta": meta, "body": body})
    assert res.ok, res.errors


@pytest.mark.parametrize("op,value,expected", [
    ("=",       "OUTAGE",     'sh:hasValue "OUTAGE"'),
    ("!=",      "OK",         'sh:not [ sh:hasValue "OK" ]'),
    (">=",      "10",         "sh:minInclusive 10.0"),
    ("<",       "5",          "sh:maxExclusive 5.0"),
    ("regex",   "^[A-Z]+$",   'sh:pattern "^[A-Z]+$"'),
    ("in",      ["A", "B"],   'sh:in ( "A" "B" )'),
    ("exists",  None,         "sh:minCount 1"),
])
def test_compile_slots_operator_mappings(op, value, expected):
    meta = {
        "target_class": ":Foo",
        "conditions": [{"path": ":bar", "op": op, "value": value}],
        "assertion": {"path": ":flag", "value": True},
    }
    body = compile_slots(meta, rule_id="op-test")
    assert expected in body, f"missing '{expected}' for op={op}"


def test_compile_slots_iri_value_kept_unquoted():
    meta = {
        "target_class": ":Site",
        "conditions": [{"path": ":kind", "op": "=", "value": ":SiteCategory"}],
        "assertion": {"path": ":memberOf", "value": ":SiteCategory",
                      "value_kind": "iri"},
    }
    body = compile_slots(meta, rule_id="iri")
    assert "sh:hasValue :SiteCategory" in body
    assert "sh:object :SiteCategory" in body


def test_compile_slots_rejects_missing_target_class():
    with pytest.raises(ValueError, match="target_class"):
        compile_slots({"target_class": "", "assertion": {"path": ":x", "value": 1}})


def test_compile_slots_rejects_missing_assertion():
    with pytest.raises(ValueError, match="assertion"):
        compile_slots({"target_class": ":X", "conditions": []})


def test_compile_slots_rejects_unknown_operator():
    with pytest.raises(ValueError, match="unknown operator"):
        compile_slots({
            "target_class": ":X",
            "conditions": [{"path": ":y", "op": "@@", "value": 1}],
            "assertion": {"path": ":a", "value": True},
        })


def test_normalise_rule_compiles_meta_into_body():
    """When a SHACL rule arrives with `meta` and an empty body, the
    slot-fill compiler is the source of truth for `body`."""
    rule = {
        "kind": "shacl", "label": "Auto compiled",
        "meta": {
            "target_class": ":Site",
            "conditions": [],
            "assertion": {"path": ":hasIncident", "value": True},
        },
    }
    out = normalise_rule(rule)
    assert "sh:NodeShape" in out["body"]
    assert "sh:targetClass :Site" in out["body"]


def test_normalise_rule_meta_overrides_existing_body():
    """The slot-fill spec wins over a stale textarea body — guarantees
    a single source of truth so the UI never gets out of sync."""
    rule = {
        "kind": "shacl", "label": "x",
        "body": "# stale Turtle nobody asked for",
        "meta": {
            "target_class": ":A",
            "conditions": [],
            "assertion": {"path": ":p", "value": True},
        },
    }
    out = normalise_rule(rule)
    assert "sh:targetClass :A" in out["body"]
    assert "stale" not in out["body"]


# ── API endpoint smoke (require Flask) ───────────────────────────────────


def test_api_routes_register():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    assert "/api/ontology/vocabulary" in rules
    assert "/api/rules/compile" in rules
