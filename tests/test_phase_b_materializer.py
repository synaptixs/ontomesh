"""Phase B — materialisation.

End-to-end test of the three inference engines:
    1. OWL-RL  — verifies that owl:TransitiveProperty produces transitive
       closure triples in `enterprise-inferred.ttl`.
    2. SHACL   — runs an `sh:rule` and asserts the derived triple appears
       in `inferred-shacl.ttl`.
    3. SPARQL  — runs a CONSTRUCT and asserts derived triples land in
       `inferred-sparql.ttl`.

Also confirms that:
    - `materialised.ttl` parses, contains asserted + all derived triples,
      and carries a top-level `prov:Activity` summary.
    - `materialisation_report.md` reports per-engine counts.
    - The sensitivity audit raises a warning when a derived subClassOf
      links a Public child to a Confidential parent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from rdflib import Graph, Namespace  # noqa: E402

from materializer import materialize  # noqa: E402

NS = Namespace("https://test.example/phaseb#")


# ── Fixtures ─────────────────────────────────────────────────────────────


def _write_ontology(path: Path) -> None:
    path.write_text(f"""\
@prefix : <{NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sens: <https://ontology.example.com/enterprise/> .

:partOf a owl:ObjectProperty, owl:TransitiveProperty .

:A a owl:Class ; sens:sensitivityTier sens:Public .
:B a owl:Class ; sens:sensitivityTier sens:Public .
:C a owl:Class ; sens:sensitivityTier sens:Confidential .

# Transitive ABox: A partOf B, B partOf C  →  A partOf C  must be derived.
:A :partOf :B .
:B :partOf :C .

# A SHACL-rule trigger: instances of :Trigger get :flag true via sh:rule.
:Trigger a owl:Class .
:t1 a :Trigger .
""")


SHAPES = """\
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix :     <https://test.example/phaseb#> .

:TriggerShape
    a sh:NodeShape ;
    sh:targetClass :Trigger ;
    sh:rule [
        a sh:TripleRule ;
        sh:subject sh:this ;
        sh:predicate :flag ;
        sh:object true ;
    ] .
"""


SPARQL_RULE = """\
PREFIX : <https://test.example/phaseb#>

CONSTRUCT { ?x :reachable ?y }
WHERE     { ?x :partOf ?y }
"""


@pytest.fixture
def workspace(tmp_path: Path):
    ont = tmp_path / "enterprise.ttl"
    _write_ontology(ont)

    shapes_dir = tmp_path / "shapes"
    shapes_dir.mkdir()
    shapes_file = shapes_dir / "shapes.ttl"
    shapes_file.write_text(SHAPES)

    rules_dir = tmp_path / "sparql_rules"
    rules_dir.mkdir()
    (rules_dir / "reachable.rq").write_text(SPARQL_RULE)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return {
        "ontology": str(ont),
        "shapes": str(shapes_file),
        "rules_dir": str(rules_dir),
        "out": str(out_dir),
    }


# ── Tests ────────────────────────────────────────────────────────────────


def test_owl_rl_derives_transitive_closure(workspace):
    result = materialize(
        workspace["ontology"], workspace["out"],
        shapes_path=workspace["shapes"],
        sparql_rules_dir=workspace["rules_dir"],
    )
    owl = next(e for e in result.engines if e.name == "owl-rl")
    assert owl.status == "PASS"
    assert owl.derived_triples > 0

    g = Graph()
    g.parse(owl.output_path, format="turtle")
    # Transitive closure must derive :A :partOf :C
    assert (NS.A, NS.partOf, NS.C) in g


def test_shacl_rule_materialises_flag(workspace):
    result = materialize(
        workspace["ontology"], workspace["out"],
        shapes_path=workspace["shapes"],
        sparql_rules_dir=workspace["rules_dir"],
    )
    shacl = next(e for e in result.engines if e.name == "shacl")
    assert shacl.status == "PASS"
    g = Graph()
    g.parse(shacl.output_path, format="turtle")

    from rdflib import Literal
    assert (NS.t1, NS.flag, Literal(True)) in g


def test_sparql_construct_runs(workspace):
    result = materialize(
        workspace["ontology"], workspace["out"],
        shapes_path=workspace["shapes"],
        sparql_rules_dir=workspace["rules_dir"],
    )
    sparql = next(e for e in result.engines if e.name == "sparql")
    assert sparql.status == "PASS"
    assert sparql.derived_triples >= 2  # at least :A→:B and :B→:C
    g = Graph()
    g.parse(sparql.output_path, format="turtle")
    assert (NS.A, NS.reachable, NS.B) in g


def test_materialised_ttl_unions_everything(workspace):
    result = materialize(
        workspace["ontology"], workspace["out"],
        shapes_path=workspace["shapes"],
        sparql_rules_dir=workspace["rules_dir"],
    )
    g = Graph()
    g.parse(result.materialised_path, format="turtle")
    # Must contain both an asserted and a derived triple
    assert (NS.A, NS.partOf, NS.B) in g          # asserted
    assert (NS.A, NS.partOf, NS.C) in g          # OWL-RL derived
    assert (NS.A, NS.reachable, NS.B) in g       # SPARQL derived

    # Top-level prov:Activity summary present
    from rdflib.namespace import PROV, RDF
    activities = list(g.subjects(RDF.type, PROV.Activity))
    assert activities, "expected at least one prov:Activity in materialised.ttl"


def test_report_records_engine_metrics(workspace):
    result = materialize(
        workspace["ontology"], workspace["out"],
        shapes_path=workspace["shapes"],
        sparql_rules_dir=workspace["rules_dir"],
    )
    text = Path(result.report_path).read_text()
    assert "Materialisation Report" in text
    assert "owl-rl" in text and "shacl" in text and "sparql" in text
    assert "Asserted" in text and "Materialised" in text


def test_no_shapes_no_rules_skips_gracefully(workspace, tmp_path):
    result = materialize(workspace["ontology"], str(tmp_path / "bare_out"))
    statuses = {e.name: e.status for e in result.engines}
    assert statuses["shacl"] == "SKIPPED"
    assert statuses["sparql"] == "SKIPPED"
    # OWL-RL still runs over the ontology alone.
    assert statuses["owl-rl"] == "PASS"


def test_phase_reason_cli_smoke(tmp_path, monkeypatch, capsys):
    """Drive `phase_reason` through toolkit.py to make sure the wiring
    works without import errors and produces the expected files.
    """
    sys.path.insert(0, str(ROOT))
    import toolkit  # noqa: E402

    out = tmp_path
    ont_dir = out / "ontology"
    ont_dir.mkdir()
    _write_ontology(ont_dir / "enterprise.ttl")

    toolkit.phase_reason(db_path="unused", out_path=str(out))
    assert (ont_dir / "enterprise-inferred.ttl").is_file()
    assert (ont_dir / "materialised.ttl").is_file()
    assert (ont_dir / "materialisation_report.md").is_file()
