"""
ontology_generator.py — Phase 2
────────────────────────────────
Generates a valid OWL 2 Turtle (.ttl) ontology from the introspected
database model and ontology_metadata annotations.

Produces:
  output/ontology/enterprise.ttl     — primary OWL ontology
  output/ontology/events.ttl         — event subclass hierarchy
  output/ontology/provenance.ttl     — PROV-O provenance patterns

No external dependencies.
"""

import os
from datetime import datetime
from typing import Dict, List
from db_introspector import (
    DBIntrospector, TableModel, ColumnModel,
    BASE_IRI, SHAPES_IRI, VOCAB_IRI, snake_to_lower_camel, snake_to_camel
)

VERSION = "1.0.0"
NOW = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

PREFIXES = f"""\
@prefix :     <{BASE_IRI}> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix sh:   <{SHAPES_IRI}> .
@prefix dcterms: <http://purl.org/dc/terms/> .
"""


def _str(s):
    if s is None:
        return None
    return s.replace('"', '\\"').replace('\n', ' ')


def _ontology_header(label: str, comment: str, version: str, iri: str) -> str:
    return f"""\
<{iri}>
  a owl:Ontology ;
  owl:versionIRI <{iri}{version}> ;
  owl:versionInfo "{version}" ;
  rdfs:label "{label}" ;
  rdfs:comment "{comment}" ;
  dcterms:created "{NOW}"^^xsd:dateTime ;
  dcterms:creator "Ontology Toolkit — Auto-generated from DB schema" .

"""


def _sensitivity_property() -> str:
    return """\
# ── Sensitivity Annotation Property ──────────────────────────────────
:sensitivityTier
  a owl:AnnotationProperty ;
  rdfs:label "Sensitivity Tier" ;
  rdfs:comment "Required on all classes and data properties. Values: Public, Internal, Confidential, Restricted." .

:SensitivityTierValue a owl:Class ;
  rdfs:label "Sensitivity Tier Value" .

:Public       a :SensitivityTierValue ; rdfs:label "Public" .
:Internal     a :SensitivityTierValue ; rdfs:label "Internal" .
:Confidential a :SensitivityTierValue ; rdfs:label "Confidential" .
:Restricted   a :SensitivityTierValue ; rdfs:label "Restricted" .

"""


def _base_classes() -> str:
    return """\
# ── Base Classes ──────────────────────────────────────────────────────
:DomainEntity
  a owl:Class ;
  rdfs:label "Domain Entity" ;
  rdfs:comment "Root class for all domain entities." ;
  :sensitivityTier :Internal .

:DomainEvent
  a owl:Class ;
  rdfs:subClassOf :DomainEntity ;
  rdfs:label "Domain Event" ;
  rdfs:comment "A significant occurrence that changes domain state or produces evidence." ;
  :sensitivityTier :Internal .

:ObservationRecord
  a owl:Class ;
  rdfs:subClassOf :DomainEntity, prov:Entity ;
  rdfs:label "Observation Record" ;
  rdfs:comment "A measured, inferred, or imported fact with full PROV-O provenance." ;
  :sensitivityTier :Confidential .

"""


def _class_block(t: TableModel) -> str:
    parent = ":DomainEvent" if t.is_event_class else ":DomainEntity"
    lines = [
        f":{t.class_name}",
        f"  a owl:Class ;",
        f"  rdfs:subClassOf {parent} ;",
        f'  rdfs:label "{_str(t.effective_label)}" ;',
    ]
    if t.description:
        lines.append(f'  rdfs:comment "{_str(t.description)}" ;')
    lines.append(f"  :sensitivityTier :{t.sensitivity_tier} ;")
    if t.skos_pref_label:
        lines.append(f'  skos:prefLabel "{_str(t.skos_pref_label)}" ;')
    for alt in t.skos_alt_labels:
        lines.append(f'  skos:altLabel "{_str(alt)}" ;')
    if t.cq_coverage:
        lines.append(f'  rdfs:isDefinedBy "{", ".join(t.cq_coverage)}" ;')
    # Phase A: owl:hasKey for metadata-flagged meaningful identifier columns.
    # Surrogate auto-increment `id` PKs are intentionally skipped — they carry
    # no domain semantics. Authors opt in via has_key_columns metadata.
    key_props = _has_key_property_iris(t)
    if key_props:
        lines.append(f"  owl:hasKey ( {' '.join(key_props)} ) ;")
    # Close — replace last ; with .
    lines[-1] = lines[-1][:-1] + " ."
    return "\n".join(lines) + "\n"


def _has_key_property_iris(t: TableModel) -> List[str]:
    """Resolve has_key_columns metadata to property IRIs (data or object)."""
    if not t.has_key_columns:
        return []
    iris: List[str] = []
    for col_name in t.has_key_columns:
        col = next((c for c in t.columns if c.name == col_name), None)
        if col is None:
            continue
        if col.is_object_property:
            # Object properties are not emitted as `has{Camel}` — they use a
            # derived name. Skip object FKs in keys; users almost always mean
            # data identifiers (codes, IRIs, external IDs).
            continue
        iris.append(f":has{snake_to_camel(col.name)}")
    return iris


def _data_property_block(col: ColumnModel, table: TableModel) -> str:
    prop_name = f"has{snake_to_camel(col.name)}"
    lines = [
        f":{prop_name}",
        f"  a owl:DatatypeProperty ;",
        f'  rdfs:label "{_str(col.effective_label)}" ;',
        f"  rdfs:domain :{table.class_name} ;",
        f"  rdfs:range {col.effective_xsd_type} ;",
    ]
    if col.description:
        lines.append(f'  rdfs:comment "{_str(col.description)}" ;')
    if col.not_null:
        lines.append(f'  owl:minCardinality "1"^^xsd:nonNegativeInteger ;')
    lines.append(f"  :sensitivityTier :{col.sensitivity_tier} .")
    return "\n".join(lines) + "\n"


def _object_property_block(col: ColumnModel, table: TableModel,
                            all_tables: List[TableModel]) -> str:
    # Determine range class from FK target table
    ref_table_name = col.fk_references.split(".")[0] if col.fk_references else None
    range_class = "owl:Thing"
    if ref_table_name:
        for t in all_tables:
            if t.name == ref_table_name:
                range_class = f":{t.class_name}"
                break

    # Derive property name: owner_org_id → isOwnedBy
    col_stripped = col.name.replace("_id", "").replace("_org", "").replace("_type", "")
    parts = col_stripped.split("_")
    prop_name = snake_to_lower_camel(col_stripped) + "Of" \
        if len(parts) == 1 else snake_to_lower_camel(col_stripped)

    # Phase A: object-property characteristic types.
    # FK columns are inherently functional — one row references at most one
    # parent — so we always emit owl:FunctionalProperty for FK-backed object
    # properties unless the metadata explicitly disables it. Authors can
    # additionally flag transitive/symmetric/inverse-functional.
    fk_default_functional = col.is_fk
    types = ["owl:ObjectProperty"]
    if col.is_transitive:
        types.append("owl:TransitiveProperty")
    if col.is_symmetric:
        types.append("owl:SymmetricProperty")
    if col.is_functional or fk_default_functional:
        types.append("owl:FunctionalProperty")
    if col.is_inverse_functional:
        types.append("owl:InverseFunctionalProperty")

    lines = [
        f":{prop_name}",
        f"  a {', '.join(types)} ;",
        f'  rdfs:label "{_str(col.effective_label)}" ;',
        f"  rdfs:domain :{table.class_name} ;",
        f"  rdfs:range {range_class} ;",
    ]
    if col.inverse_of:
        lines.append(f"  owl:inverseOf :{col.inverse_of} ;")
    if col.description:
        lines.append(f'  rdfs:comment "{_str(col.description)}" ;')
    if col.not_null:
        lines.append(f"  owl:minCardinality 1 ;")
    lines[-1] = lines[-1][:-1] + " ."
    return "\n".join(lines) + "\n"


def _event_subclasses(tables: List[TableModel], intro: DBIntrospector) -> str:
    """Generate OWL subclasses for distinct event_type values.

    Sibling subclasses derived from the same parent event table are mutually
    exclusive by construction (a row has exactly one event_type), so we also
    emit an owl:AllDisjointClasses axiom over each sibling group.
    """
    event_tables = [t for t in tables if t.is_event_class]
    if not event_tables:
        return ""

    blocks = ["# ── Event Subclass Hierarchy ────────────────────────────────────────\n"]
    seen = set()
    sibling_groups: List[List[str]] = []
    for et in event_tables:
        distinct = intro.get_distinct_values(et.name, "event_type")
        siblings: List[str] = []
        for val in distinct:
            class_name = snake_to_camel(val.lower()) + "Event"
            if class_name in seen:
                continue
            seen.add(class_name)
            siblings.append(class_name)
            label = val.replace("_", " ").title() + " Event"
            blocks.append(
                f":{class_name}\n"
                f"  a owl:Class ;\n"
                f"  rdfs:subClassOf :{et.class_name} ;\n"
                f'  rdfs:label "{label}" ;\n'
                f'  rdfs:comment "Subclass of {et.class_name} for event_type = {val}." ;\n'
                f"  :sensitivityTier :{et.sensitivity_tier} .\n"
            )
        if len(siblings) >= 2:
            sibling_groups.append(siblings)

    for group in sibling_groups:
        # Turtle RDF-list members must be whitespace-separated. A comma
        # is a "same-subject same-predicate" repeat marker and isn't
        # valid inside a `( ... )` collection — using one breaks parsers
        # downstream (rdflib, pyshacl, ROBOT).
        members = " ".join(f":{c}" for c in group)
        blocks.append(
            "[] a owl:AllDisjointClasses ;\n"
            f"   owl:members ( {members} ) .\n"
        )

    return "\n".join(blocks)


def _disjoint_class_groups(tables: List[TableModel]) -> str:
    """Emit owl:AllDisjointClasses for every shared `disjoint_group` value."""
    groups: Dict[str, List[str]] = {}
    for t in tables:
        if t.disjoint_group:
            groups.setdefault(t.disjoint_group, []).append(t.class_name)
    if not groups:
        return ""
    out = ["# ── Disjoint Class Groups ───────────────────────────────────────────\n"]
    for name, members in groups.items():
        if len(members) < 2:
            continue
        member_iris = " ".join(f":{m}" for m in members)
        out.append(
            f'# Group: "{name}"\n'
            "[] a owl:AllDisjointClasses ;\n"
            f"   owl:members ( {member_iris} ) .\n"
        )
    return "\n".join(out)


def _prov_patterns() -> str:
    return f"""\
# ── PROV-O Integration Patterns ──────────────────────────────────────
# Aligns ObservationRecord with prov:Entity and agents with prov:Agent.

:wasProducedBy
  a owl:ObjectProperty ;
  rdfs:subPropertyOf prov:wasGeneratedBy ;
  rdfs:label "was produced by" ;
  rdfs:domain :ObservationRecord ;
  rdfs:range :Agent ;
  rdfs:comment "Links an observation to the agent that produced it." ;
  :sensitivityTier :Internal .

:hasConfidenceScore
  a owl:DatatypeProperty ;
  rdfs:label "Confidence Score" ;
  rdfs:domain :ObservationRecord ;
  rdfs:range xsd:decimal ;
  rdfs:comment "Numeric confidence in the observation value. Range: 0.0–1.0." ;
  :sensitivityTier :Confidential .

:derivationMethod
  a owl:DatatypeProperty ;
  rdfs:label "Derivation Method" ;
  rdfs:domain :ObservationRecord ;
  rdfs:range xsd:string ;
  rdfs:comment "How the value was obtained: MEASURED, INFERRED, IMPORTED, SYNTHESIZED." ;
  :sensitivityTier :Internal .

:governedBy
  a owl:ObjectProperty ;
  rdfs:label "governed by" ;
  rdfs:domain :DomainEvent ;
  rdfs:range :Policy ;
  rdfs:comment "The policy that governs this event." ;
  :sensitivityTier :Internal .

:hasParticipant
  a owl:ObjectProperty ;
  rdfs:label "has participant" ;
  rdfs:domain :DomainEvent ;
  rdfs:range :Agent ;
  rdfs:comment "An agent that participated in this event." ;
  :sensitivityTier :Internal .

:refersToAsset
  a owl:ObjectProperty ;
  rdfs:label "refers to asset" ;
  rdfs:domain :ObservationRecord ;
  rdfs:range :Asset ;
  rdfs:comment "The asset this observation is about." ;
  :sensitivityTier :Internal .

"""


# ── Main generator ───────────────────────────────────────────────────────

def generate_ontology(intro: DBIntrospector, output_dir: str):
    tables = intro.introspect_all()
    os.makedirs(output_dir, exist_ok=True)

    # ── Primary ontology ──────────────────────────────────────────────
    lines = [
        PREFIXES,
        _ontology_header(
            "Enterprise Domain Ontology",
            "Auto-generated from relational schema + ontology_metadata. "
            "Covers all operational domain entities, events, agents, "
            "policies, observations, and provenance patterns.",
            VERSION,
            BASE_IRI
        ),
        _sensitivity_property(),
        _base_classes(),
    ]

    lines.append("# ── Domain Classes ──────────────────────────────────────────────────\n")
    for t in tables:
        # Skip tables that are pure junction/log tables not needing a top-level class
        lines.append(_class_block(t))

    lines.append("\n# ── Data Properties ─────────────────────────────────────────────────\n")
    for t in tables:
        for col in t.data_properties:
            lines.append(_data_property_block(col, t))

    lines.append("\n# ── Object Properties ───────────────────────────────────────────────\n")
    for t in tables:
        for col in t.object_properties:
            lines.append(_object_property_block(col, t, tables))

    disjoint_block = _disjoint_class_groups(tables)
    if disjoint_block:
        lines.append("\n")
        lines.append(disjoint_block)

    lines.append("\n")
    lines.append(_prov_patterns())

    ontology_path = os.path.join(output_dir, "enterprise.ttl")
    with open(ontology_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  ✓ Ontology written      → {ontology_path}")
    _report_stats(tables, ontology_path)

    # OWL profile selection — writes profile_recommendation.md
    write_profile_recommendation(tables, ontology_path, output_dir)

    # ── Events sub-module ────────────────────────────────────────────
    event_content = (
        PREFIXES + "\n"
        f'<{BASE_IRI}events/>\n'
        f'  a owl:Ontology ;\n'
        f'  owl:imports <{BASE_IRI}> ;\n'
        f'  rdfs:label "Enterprise Event Subclass Hierarchy" .\n\n'
        + _event_subclasses(tables, intro)
    )
    events_path = os.path.join(output_dir, "events.ttl")
    with open(events_path, "w") as f:
        f.write(event_content)
    print(f"  ✓ Event hierarchy       → {events_path}")

    # ── Provenance patterns sub-module ───────────────────────────────
    prov_content = (
        PREFIXES + "\n"
        f'<{BASE_IRI}provenance/>\n'
        f'  a owl:Ontology ;\n'
        f'  owl:imports <{BASE_IRI}> ;\n'
        f'  rdfs:label "Enterprise Provenance Profile" .\n\n'
        + _prov_patterns()
    )
    prov_path = os.path.join(output_dir, "provenance.ttl")
    with open(prov_path, "w") as f:
        f.write(prov_content)
    print(f"  ✓ Provenance profile    → {prov_path}")


def _report_stats(tables, path):
    classes = len(tables)
    data_props = sum(len(t.data_properties) for t in tables)
    obj_props  = sum(len(t.object_properties) for t in tables)
    event_classes = sum(1 for t in tables if t.is_event_class)
    print(f"    Classes: {classes}  |  Data properties: {data_props}  "
          f"|  Object properties: {obj_props}  |  Event tables: {event_classes}")


# ── OWL Profile Selection ────────────────────────────────────────────────

def _detect_owl_profile(tables: list, ontology_path: str) -> dict:
    """Detect the appropriate OWL 2 profile for the generated ontology.

    Rules (aligned with OWL 2 profiles spec):
    - EL profile:  count axioms <= 50000, no role chains, no nominals
    - DL profile:  role chains (owl:propertyChainAxiom) or nominals (owl:oneOf) present
    - RL profile:  data-only, no existential restrictions (not currently auto-detected)

    Returns a dict with: profile, axiom_count, has_role_chains, has_nominals, rationale
    """
    classes     = len(tables)
    data_props  = sum(len(t.data_properties) for t in tables)
    obj_props   = sum(len(t.object_properties) for t in tables)
    axiom_count = classes + data_props + obj_props

    has_role_chains = False
    has_nominals    = False
    has_inverse_of  = False
    has_symmetric   = False
    has_inv_func    = False
    try:
        with open(ontology_path) as f:
            content = f.read()
        has_role_chains = "propertyChainAxiom" in content
        has_nominals    = "owl:oneOf" in content
        has_inverse_of  = "owl:inverseOf" in content
        has_symmetric   = "owl:SymmetricProperty" in content
        has_inv_func    = "owl:InverseFunctionalProperty" in content
    except OSError:
        pass

    dl_constructs = []
    if has_role_chains:
        dl_constructs.append("role chains")
    if has_nominals:
        dl_constructs.append("nominals")
    if has_inverse_of:
        dl_constructs.append("owl:inverseOf")
    if has_symmetric:
        dl_constructs.append("owl:SymmetricProperty")
    if has_inv_func:
        dl_constructs.append("owl:InverseFunctionalProperty")

    if dl_constructs:
        profile  = "OWL 2 DL"
        rationale = (
            f"OWL 2 DL constructs detected ({', '.join(dl_constructs)}). "
            "OWL 2 EL does not permit these — the ontology requires a full DL "
            "reasoner. Use HermiT or Pellet."
        )
    elif axiom_count > 50_000:
        profile  = "OWL 2 EL"
        rationale = (f"Axiom count {axiom_count} exceeds 50 000 — OWL 2 EL recommended "
                     "for tractable classification. Use ELK as the reasoner.")
    else:
        profile  = "OWL 2 EL"
        rationale = (f"Axiom count {axiom_count} is within EL limits and no DL "
                     "constructs detected — OWL 2 EL profile is sufficient. "
                     "ELK reasoner recommended.")

    return {
        "profile":         profile,
        "axiom_count":     axiom_count,
        "classes":         classes,
        "data_properties": data_props,
        "object_properties": obj_props,
        "has_role_chains": has_role_chains,
        "has_nominals":    has_nominals,
        "has_inverse_of":  has_inverse_of,
        "has_symmetric":   has_symmetric,
        "has_inverse_functional": has_inv_func,
        "dl_constructs":   dl_constructs,
        "rationale":       rationale,
        "reasoner":        "HermiT" if profile == "OWL 2 DL" else "ELK",
    }


def write_profile_recommendation(tables: list, ontology_path: str, output_dir: str) -> str:
    """Write profile_recommendation.md alongside the schema artifacts."""
    result = _detect_owl_profile(tables, ontology_path)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "profile_recommendation.md")
    lines = [
        "# OWL 2 Profile Recommendation\n",
        f"**Recommended profile:** {result['profile']}  \n",
        f"**Recommended reasoner:** {result['reasoner']}  \n\n",
        "## Axiom summary\n\n",
        f"| Metric | Count |\n",
        f"|--------|-------|\n",
        f"| OWL classes | {result['classes']} |\n",
        f"| Data properties | {result['data_properties']} |\n",
        f"| Object properties | {result['object_properties']} |\n",
        f"| **Total axioms (est.)** | **{result['axiom_count']}** |\n\n",
        "## Decision rationale\n\n",
        f"{result['rationale']}\n\n",
        "## Profile decision rules\n\n",
        "| Rule | Trigger | Profile |\n",
        "|------|---------|--------|\n",
        "| Role chains present | `owl:propertyChainAxiom` in ontology | OWL 2 DL |\n",
        "| Nominals present | `owl:oneOf` in ontology | OWL 2 DL |\n",
        "| Inverse properties | `owl:inverseOf` in ontology | OWL 2 DL |\n",
        "| Symmetric properties | `owl:SymmetricProperty` in ontology | OWL 2 DL |\n",
        "| Inverse-functional properties | `owl:InverseFunctionalProperty` in ontology | OWL 2 DL |\n",
        "| Axiom count > 50 000 | Large schema | OWL 2 EL |\n",
        "| Default | No complex constructs, ≤ 50 000 axioms | OWL 2 EL |\n\n",
        "## Reasoner integration\n\n",
        "Run the reasoner via ROBOT after Phase 2:\n\n",
        "```bash\n",
        f"robot reason --reasoner {result['reasoner'].lower()} \\\n",
        "  --input output/ontology/enterprise.ttl \\\n",
        "  --output output/ontology/enterprise-classified.ttl\n",
        "```\n\n",
        "*Generated by Ontology Toolkit — Phase 1 OWL Profile Selection*\n",
    ]
    with open(path, "w") as f:
        f.writelines(lines)
    print(f"  ✓ OWL profile recommendation → {path}  [{result['profile']}]")
    return result["profile"]
