"""
shacl_generator.py — Phase 3
──────────────────────────────
Generates SHACL NodeShapes from the introspected database model.

Produces:
  output/shapes/enterprise-shapes.ttl   — all NodeShapes
  output/shapes/agent-gate.ttl          — agent acceptance gate shapes

Every class gets:
  - sh:property for each NOT NULL column (minCount 1)
  - sh:property for FK-based object properties (class constraint)
  - sh:property for sensitivity tier (mandatory annotation)
  - Confidence score range constraint on ObservationRecord
  - Agent credential expiry constraint on Agent
"""

import os
from typing import List
from db_introspector import (
    DBIntrospector, TableModel, ColumnModel,
    BASE_IRI, SHAPES_IRI, snake_to_camel
)

PREFIXES = f"""\
@prefix :     <{BASE_IRI}> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix shapes: <{SHAPES_IRI}> .
"""


def _sensitivity_shape() -> str:
    """Meta-shape: every class must have sensitivityTier annotation."""
    return """\
# ── Meta-shape: Sensitivity Annotation Required ───────────────────────
shapes:SensitivityAnnotationShape
  a sh:NodeShape ;
  sh:targetClass owl:Class ;
  sh:property [
    sh:path :sensitivityTier ;
    sh:minCount 1 ;
    sh:in ( :Public :Internal :Confidential :Restricted ) ;
    sh:message "Every OWL class must have a :sensitivityTier annotation." ;
    sh:severity sh:Violation
  ] .

"""


def _node_shape(t: TableModel, all_tables: List[TableModel]) -> str:
    lines = [
        f"# ── {t.class_name} ──────────────────────────────────────────",
        f"shapes:{t.class_name}Shape",
        f"  a sh:NodeShape ;",
        f"  sh:targetClass :{t.class_name} ;",
    ]

    # Data properties
    for col in t.data_properties:
        prop_name = f"has{snake_to_camel(col.name)}"
        prop_lines = [f"  sh:property ["]
        prop_lines.append(f"    sh:path :{prop_name} ;")
        prop_lines.append(f"    sh:datatype {col.effective_xsd_type} ;")
        if col.not_null:
            prop_lines.append(f"    sh:minCount 1 ;")
        # Special range constraints
        if "confidence" in col.name.lower() or "score" in col.name.lower():
            prop_lines.append(f"    sh:minInclusive 0.0 ;")
            prop_lines.append(f"    sh:maxInclusive 1.0 ;")
        prop_lines.append(
            f'    sh:message "{col.effective_label}: '
            f'{"required, " if col.not_null else ""}type {col.effective_xsd_type}." ;'
        )
        prop_lines.append(f"    sh:severity {'sh:Violation' if col.not_null else 'sh:Warning'}")
        prop_lines.append(f"  ] ;")
        lines.extend(prop_lines)

    # Object properties (FK relationships)
    for col in t.object_properties:
        ref_table_name = col.fk_references.split(".")[0] if col.fk_references else None
        range_class = "owl:Thing"
        if ref_table_name:
            for rt in all_tables:
                if rt.name == ref_table_name:
                    range_class = f":{rt.class_name}"
                    break

        col_stripped = col.name.replace("_id", "").replace("_org", "").replace("_type", "")
        from db_introspector import snake_to_lower_camel
        prop_name = snake_to_lower_camel(col_stripped)

        prop_lines = [f"  sh:property ["]
        prop_lines.append(f"    sh:path :{prop_name} ;")
        prop_lines.append(f"    sh:class {range_class} ;")
        if col.not_null:
            prop_lines.append(f"    sh:minCount 1 ;")
        prop_lines.append(
            f'    sh:message "{col.effective_label}: '
            f'{"required " if col.not_null else ""}reference to {range_class}." ;'
        )
        prop_lines.append(f"    sh:severity {'sh:Violation' if col.not_null else 'sh:Warning'}")
        prop_lines.append(f"  ] ;")
        lines.extend(prop_lines)

    # Mandatory sensitivity tier on all instances
    lines.append("  sh:property [")
    lines.append("    sh:path :sensitivityTier ;")
    lines.append("    sh:minCount 1 ;")
    lines.append("    sh:in ( :Public :Internal :Confidential :Restricted ) ;")
    lines.append('    sh:message "Sensitivity tier annotation is required." ;')
    lines.append("    sh:severity sh:Violation")
    lines.append("  ] .")
    lines.append("")

    return "\n".join(lines) + "\n"


def _observation_extra_shapes() -> str:
    """Extra shapes specific to ObservationRecord — agent acceptance gate."""
    return """\
# ── Agent Acceptance Gate: ObservationRecord ──────────────────────────
shapes:ObservationAcceptanceGate
  a sh:NodeShape ;
  sh:targetClass :ObservationRecord ;
  sh:property [
    sh:path prov:wasGeneratedBy ;
    sh:minCount 1 ;
    sh:message "Observation must carry prov:wasGeneratedBy (PROV-O required)." ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path prov:generatedAtTime ;
    sh:minCount 1 ;
    sh:datatype xsd:dateTime ;
    sh:message "Observation must carry prov:generatedAtTime timestamp." ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path :hasConfidenceScore ;
    sh:minCount 1 ;
    sh:minInclusive 0.0 ;
    sh:maxInclusive 1.0 ;
    sh:message "Confidence score is required and must be 0.0–1.0." ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path :derivationMethod ;
    sh:minCount 1 ;
    sh:in ( "MEASURED" "INFERRED" "IMPORTED" "SYNTHESIZED" ) ;
    sh:message "Derivation method must be MEASURED, INFERRED, IMPORTED, or SYNTHESIZED." ;
    sh:severity sh:Violation
  ] .

"""


def _agent_credential_shape() -> str:
    """Validates AI agent credentials on inbound payloads."""
    return """\
# ── Agent Credential Acceptance Gate ─────────────────────────────────
shapes:AgentCredentialShape
  a sh:NodeShape ;
  sh:targetClass :Agent ;
  sh:property [
    sh:path :hasAgentIri ;
    sh:minCount 1 ;
    sh:datatype xsd:anyURI ;
    sh:message "Agent must carry a persistent IRI for provenance." ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path :authorizedTiers ;
    sh:minCount 1 ;
    sh:message "Agent must declare its authorized sensitivity tiers." ;
    sh:severity sh:Violation
  ] .

"""


def _event_shape_extensions() -> str:
    """Extra shapes for DomainEvent — participant and policy gates."""
    return """\
# ── DomainEvent Completeness Gate ────────────────────────────────────
shapes:DomainEventCompletenessShape
  a sh:NodeShape ;
  sh:targetClass :DomainEvent ;
  sh:property [
    sh:path :hasParticipant ;
    sh:minCount 1 ;
    sh:class :Agent ;
    sh:message "Every DomainEvent must have at least one participant." ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path :hasEventStatus ;
    sh:minCount 1 ;
    sh:in ( "OPEN" "IN_PROGRESS" "COMPLETED" "FAILED" "CANCELLED" ) ;
    sh:message "Event status must be one of the defined values." ;
    sh:severity sh:Violation
  ] .

"""


def _entity_ref_shape() -> str:
    """SHACL shape validating the EntityRefOrValue reference form (TMF630 Part 2).

    A reference form MUST carry @referredType and href. The @id is the IRI.
    The value form carries a full @type and all attributes — validated by the
    target class NodeShape, not this shape.
    """
    return """\
# ── EntityRefOrValue: Reference Form Validation ──────────────────────
shapes:EntityRefShape
  a sh:NodeShape ;
  sh:targetClass :EntityRef ;
  sh:property [
    sh:path :referredType ;
    sh:minCount 1 ;
    sh:datatype xsd:string ;
    sh:message "EntityRef (reference form) must carry @referredType." ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path :href ;
    sh:minCount 1 ;
    sh:datatype xsd:anyURI ;
    sh:message "EntityRef (reference form) must carry a href following /{apiRoot}/{resource}/{id}." ;
    sh:severity sh:Violation
  ] .

"""


def generate_shacl(intro: DBIntrospector, output_dir: str):
    tables = intro.introspect_all()
    os.makedirs(output_dir, exist_ok=True)

    # ── Primary shapes file ───────────────────────────────────────────
    lines = [PREFIXES, "\n"]
    lines.append(_sensitivity_shape())

    for t in tables:
        lines.append(_node_shape(t, tables))

    # Add domain-specific extensions
    lines.append(_observation_extra_shapes())
    lines.append(_event_shape_extensions())
    lines.append(_entity_ref_shape())

    shapes_path = os.path.join(output_dir, "enterprise-shapes.ttl")
    with open(shapes_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  ✓ SHACL shapes          → {shapes_path}")

    # ── Agent acceptance gate (standalone — for pipeline middleware) ──
    gate_content = PREFIXES + "\n" + _agent_credential_shape() + _observation_extra_shapes()
    gate_path = os.path.join(output_dir, "agent-gate.ttl")
    with open(gate_path, "w") as f:
        f.write(gate_content)
    print(f"  ✓ Agent acceptance gate → {gate_path}")

    # Stats
    total_shapes = len(tables) + 3  # +3 for meta + observation gate + event gate
    total_constraints = sum(
        len(t.data_properties) + len(t.object_properties) + 1
        for t in tables
    ) + 7  # extra constraints in gate shapes
    print(f"    NodeShapes: {total_shapes}  |  Constraints: {total_constraints}")
