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
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Optional
from db_introspector import (
    DBIntrospector, TableModel, ColumnModel,
    BASE_IRI, SHAPES_IRI, VOCAB_IRI, snake_to_lower_camel, snake_to_camel,
    value_to_local_name,
)

VERSION = "1.0.0"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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


LICENSE_IRI = os.environ.get(
    "ONTOLOGY_LICENSE", "https://www.apache.org/licenses/LICENSE-2.0")


def _prior_version(path: str) -> Optional[str]:
    """Read owl:versionInfo from a previously emitted ontology, if any."""
    if not os.path.isfile(path):
        return None
    try:
        import rdflib
        g = rdflib.Graph()
        g.parse(path, format="turtle")
        for _, _, v in g.triples((None, rdflib.OWL.versionInfo, None)):
            return str(v)
    except Exception:
        return None
    return None


def _ontology_header(label: str, comment: str, version: str, iri: str,
                     prior: Optional[str] = None) -> str:
    """Ontology declaration with version lineage and a licence.

    `owl:priorVersion` was never emitted, so a consumer had no way to tell
    which release a graph superseded — and `dcterms:license` was absent
    entirely, which the P41 pitfall check now flags.
    """
    lines = [
        f"<{iri}>",
        "  a owl:Ontology ;",
        f"  owl:versionIRI <{iri}{version}> ;",
        f'  owl:versionInfo "{version}" ;',
    ]
    if prior and prior != version:
        lines.append(f"  owl:priorVersion <{iri}{prior}> ;")
        lines.append(f"  owl:backwardCompatibleWith <{iri}{prior}> ;")
    lines += [
        f'  rdfs:label "{label}" ;',
        f'  rdfs:comment "{comment}" ;',
        f"  dcterms:license <{LICENSE_IRI}> ;",
        f'  dcterms:created "{NOW}"^^xsd:dateTime ;',
        '  dcterms:creator "Ontology Toolkit — Auto-generated from DB schema" .',
        "",
        "",
    ]
    return "\n".join(lines)


def _deprecation_tombstones(prior_path: str, current_names: set) -> str:
    """Mark entities that existed in the previous version and no longer do.

    Removals were reported by ontology_diff and recorded nowhere in the
    artifact, so a consumer holding an old IRI could not tell whether it
    had been retired or was simply missing. `owl:deprecated` is the
    standard signal; the entity is kept rather than deleted so existing
    references still resolve.
    """
    if not os.path.isfile(prior_path):
        return ""
    try:
        import rdflib
        g = rdflib.Graph()
        g.parse(prior_path, format="turtle")
    except Exception:
        return ""
    prior_names = set()
    for ty in (rdflib.OWL.Class, rdflib.OWL.ObjectProperty,
               rdflib.OWL.DatatypeProperty):
        prior_names |= {str(s).rsplit("/", 1)[-1]
                        for s in g.subjects(rdflib.RDF.type, ty)
                        if isinstance(s, rdflib.URIRef)
                        and str(s).startswith(BASE_IRI)}
    removed = sorted(prior_names - current_names)
    # Already-deprecated entities are not re-tombstoned.
    already = {str(s).rsplit("/", 1)[-1]
               for s, _, _ in g.triples((None, rdflib.OWL.deprecated, None))}
    removed = [r for r in removed if r not in already]
    if not removed:
        return ""
    blocks = ["\n# ── Deprecated ───────────────────────────────────────────\n"
              "# Present in the previous version and absent from this one.\n"
              "# Retained as tombstones so held IRIs still resolve, and\n"
              "# marked owl:deprecated so consumers can act on the change.\n"]
    for name in removed:
        blocks.append(
            f":{name}\n"
            f'  owl:deprecated true ;\n'
            f'  rdfs:comment "Deprecated: no longer produced by the '
            f'source schema as of version {VERSION}." .\n'
        )
    return "\n".join(blocks)


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


# ── L5.2 helpers — log-derived class emission ──────────────────────────


_SEVERITY_TO_TIER = {
    "DEBUG":   "Public",
    "INFO":    "Public",
    "WARN":    "Internal",
    "WARNING": "Internal",
    "ERROR":   "Confidential",
    "CRITICAL": "Restricted",
    "FATAL":   "Restricted",
}


def _session_has_log_discovery(session) -> bool:
    if not isinstance(session, dict):
        return False
    for bucket in ("events", "entities", "relationships", "causal_rules"):
        for item in (session.get(bucket) or []):
            if isinstance(item, dict) and item.get("source") == "log-discovery":
                return True
    return False


def _emit_log_derived_classes(session: dict) -> str:
    """Per log-derived event/entity, emit a class block subclass-of
    :CausalEvent (events) or :DomainEntity (entities), with
    auto-generated time-interval data properties on events and a
    severity-mapped sensitivity tier."""
    if not isinstance(session, dict):
        return ""
    parts = ["# ── Log-Derived Classes (Phase L5) ──────────────────────────────────\n"]
    seen = set()
    for ev in session.get("events") or []:
        if not isinstance(ev, dict) or ev.get("source") != "log-discovery":
            continue
        cls = _to_class_name(ev.get("name") or ev.get("label") or "LogEvent")
        if cls in seen:
            continue
        seen.add(cls)
        tier = _SEVERITY_TO_TIER.get(
            (ev.get("severity") or "INFO").upper(), "Internal"
        )
        label = (ev.get("label") or cls).replace('"', "'")
        comment = (ev.get("description") or "Mined from log corpus.").replace('"', "'")
        parts.append(
            f":{cls}\n"
            f"  a owl:Class ;\n"
            f"  rdfs:subClassOf :CausalEvent ;\n"
            f'  rdfs:label "{label}" ;\n'
            f'  rdfs:comment "{comment}" ;\n'
            f"  :sensitivityTier :{tier} .\n"
        )
        # Time-interval data properties (one set per class — keeps the
        # ontology compact, every log-derived class shares them).
    if not seen:
        return ""
    parts.append(
        ":startedAt\n"
        "  a owl:DatatypeProperty ;\n"
        "  rdfs:label \"started at\" ;\n"
        "  rdfs:domain :CausalEvent ;\n"
        "  rdfs:range xsd:dateTime ;\n"
        "  :sensitivityTier :Internal .\n\n"
        ":endedAt\n"
        "  a owl:DatatypeProperty ;\n"
        "  rdfs:label \"ended at\" ;\n"
        "  rdfs:domain :CausalEvent ;\n"
        "  rdfs:range xsd:dateTime ;\n"
        "  :sensitivityTier :Internal .\n\n"
        ":duration\n"
        "  a owl:DatatypeProperty ;\n"
        "  rdfs:label \"duration\" ;\n"
        "  rdfs:domain :CausalEvent ;\n"
        "  rdfs:range xsd:duration ;\n"
        "  :sensitivityTier :Internal .\n"
    )
    return "\n".join(parts) + "\n"


def _to_class_name(s: str) -> str:
    """`event_18` / `Network Failure` / `outage event` → `Event18` /
    `NetworkFailure` / `OutageEvent`."""
    out = []
    for token in (s or "").replace("-", " ").replace("_", " ").split():
        out.append(token[0].upper() + token[1:])
    return "".join(out) or "LogClass"


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


# Classes declared by _base_classes(). A table whose name transliterates to
# one of these shadows the built-in — e.g. a `domain_events` table yields
# :DomainEvent, which was then given `rdfs:subClassOf :DomainEvent`, a
# self-referential axiom that makes the class its own superclass.
_BASE_CLASS_NAMES = frozenset({"DomainEntity", "DomainEvent", "ObservationRecord"})


def _class_block(t: TableModel) -> str:
    parent = ":DomainEvent" if t.is_event_class else ":DomainEntity"
    lines = [
        f":{t.class_name}",
        f"  a owl:Class ;",
    ]
    # Never assert a class as its own superclass. When a table shadows a
    # base class the built-in declaration already carries the hierarchy,
    # so the parent link is simply omitted here.
    if f":{t.class_name}" != parent:
        lines.append(f"  rdfs:subClassOf {parent} ;")
    lines.append(f'  rdfs:label "{_str(t.effective_label)}" ;')
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
    # NOT NULL columns as owl:Restriction subclass axioms.
    #
    # This information used to be emitted as `owl:minCardinality` asserted
    # directly on the property IRI, which is not an axiom at all — in OWL 2
    # a cardinality is only meaningful inside an owl:Restriction, so those
    # 139 triples were stray RDF that ROBOT and HermiT drop or reject. They
    # were removed in Phase 2; this restores the same information in the
    # form a reasoner can actually use.
    for col in t.data_properties:
        if not col.not_null:
            continue
        lines.append(
            f"  rdfs:subClassOf [ a owl:Restriction ;\n"
            f"                    owl:onProperty :has{snake_to_camel(col.name)} ;\n"
            f'                    owl:minCardinality "1"^^xsd:nonNegativeInteger ] ;'
        )
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


def _render_domain(class_names: List[str]) -> str:
    """Render an rdfs:domain clause for the classes a property is used on.

    Multiple `rdfs:domain` axioms on one property **conjoin** in OWL: a
    property declared once per table accumulated one domain per table, so
    `:hasCreatedAt` carried 43 of them and any individual with a creation
    timestamp was inferred to be all 43 classes at once. Loading a single
    instance triple into the shipped ontology and running OWL-RL produced
    47 rdf:type assertions from one asserted fact.

    The union class is the correct idiom for "used on any of these": the
    individual is inferred to be a member of the union, not the
    intersection. A single class is emitted directly, since a one-member
    union adds nothing.
    """
    unique = sorted(set(class_names))
    if len(unique) == 1:
        return f"  rdfs:domain :{unique[0]} ;"
    members = " ".join(f":{c}" for c in unique)
    return (
        "  rdfs:domain [ a owl:Class ;\n"
        f"                owl:unionOf ( {members} ) ] ;"
    )


def _data_property_block(cols: List[ColumnModel], class_names: List[str]) -> str:
    """Emit one datatype property, covering every class that declares it."""
    col = cols[0]
    prop_name = f"has{snake_to_camel(col.name)}"
    lines = [
        f":{prop_name}",
        f"  a owl:DatatypeProperty ;",
        f'  rdfs:label "{_str(col.effective_label)}" ;',
        _render_domain(class_names),
        f"  rdfs:range {col.effective_xsd_type} ;",
    ]
    description = next((c.description for c in cols if c.description), None)
    if description:
        lines.append(f'  rdfs:comment "{_str(description)}" ;')
    # Sensitivity is the most restrictive tier seen across the declaring
    # tables — a property shared with a Confidential class must not be
    # advertised as Public because another table happened to be listed first.
    tier = _most_restrictive_tier([c.sensitivity_tier for c in cols])
    lines.append(f"  :sensitivityTier :{tier} .")
    return "\n".join(lines) + "\n"


_TIER_ORDER = ["Public", "Internal", "Confidential", "Restricted"]


def _most_restrictive_tier(tiers: List[str]) -> str:
    best = "Public"
    for tier in tiers:
        if tier in _TIER_ORDER and _TIER_ORDER.index(tier) > _TIER_ORDER.index(best):
            best = tier
    return best


def object_property_name(col_name: str) -> str:
    """Derive an object-property name from an FK column name.

    The single source of truth for object-property naming — the ontology,
    the mapping workbook and the ABox all call this, so the three cannot
    drift apart. They previously each had their own rule and disagreed on
    53 of 100 properties.

    Only a *trailing* `_id` is stripped. The older rule removed `_id`,
    `_org` and `_type` anywhere in the name, which collapsed distinct
    relations onto one IRI: `asset_type_id` and `asset_id` both became
    `assetOf`, giving one property two unrelated domains and ranges.

    No `Of` suffix. A foreign key means "this row *has* that thing", so
    `agent_id` is `agent`, not `agentOf` — which reads as the inverse of
    what the column asserts. Dropping it also raised agreement with the
    mapping workbook from 47/100 to 94/100.
    """
    stripped = col_name[:-3] if col_name.endswith("_id") else col_name
    if not stripped:
        stripped = col_name
    return snake_to_lower_camel(stripped)


def _object_property_range(col: ColumnModel,
                           all_tables: List[TableModel]) -> Optional[str]:
    """Resolve the FK target class, or None when it is outside this ontology."""
    ref_table_name = col.fk_references.split(".")[0] if col.fk_references else None
    if not ref_table_name:
        return None
    for t in all_tables:
        if t.name == ref_table_name:
            return f":{t.class_name}"
    return None


def _object_property_block(cols: List[ColumnModel], class_names: List[str],
                            all_tables: List[TableModel]) -> str:
    """Emit one object property, covering every class that declares it."""
    col = cols[0]
    prop_name = object_property_name(col.name)

    ranges = sorted({r for r in (_object_property_range(c, all_tables) for c in cols) if r})

    # Phase A: object-property characteristic types.
    # FK columns are inherently functional — one row references at most one
    # parent — so we always emit owl:FunctionalProperty for FK-backed object
    # properties unless the metadata explicitly disables it. Authors can
    # additionally flag transitive/symmetric/inverse-functional.
    fk_default_functional = any(c.is_fk for c in cols)
    types = ["owl:ObjectProperty"]
    if any(c.is_transitive for c in cols):
        types.append("owl:TransitiveProperty")
    if any(c.is_symmetric for c in cols):
        types.append("owl:SymmetricProperty")
    if any(c.is_functional for c in cols) or fk_default_functional:
        types.append("owl:FunctionalProperty")
    if any(c.is_inverse_functional for c in cols):
        types.append("owl:InverseFunctionalProperty")

    lines = [
        f":{prop_name}",
        f"  a {', '.join(types)} ;",
        f'  rdfs:label "{_str(col.effective_label)}" ;',
        _render_domain(class_names),
    ]
    # An unresolvable FK target used to be written as `rdfs:range owl:Thing`.
    # That asserts nothing — every individual is an owl:Thing — while reading
    # like a constraint. The range is omitted instead, and the unresolved
    # target is recorded so it is visible rather than disguised.
    if len(ranges) == 1:
        lines.append(f"  rdfs:range {ranges[0]} ;")
    elif len(ranges) > 1:
        members = " ".join(ranges)
        lines.append("  rdfs:range [ a owl:Class ;\n"
                     f"               owl:unionOf ( {members} ) ] ;")
    else:
        target = next((c.fk_references for c in cols if c.fk_references), None)
        note = (f"FK target '{target}' is outside this ontology"
                if target else "no FK target declared")
        lines.append(f'  rdfs:comment "Range unresolved: {note}." ;')

    inverse = next((c.inverse_of for c in cols if c.inverse_of), None)
    if inverse:
        lines.append(f"  owl:inverseOf :{inverse} ;")
    description = next((c.description for c in cols if c.description), None)
    if description:
        lines.append(f'  rdfs:comment "{_str(description)}" ;')
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
            # Guard against non-values reaching the TBox. A CSV header row
            # loaded as data put the literal string "event_type" in the
            # column, which minted an :EventTypeEvent class describing
            # nothing. Skip the column's own name and blank/NULL sentinels.
            normalised = (val or "").strip().lower()
            if normalised in ("", "event_type", "null", "none", "n/a", "-"):
                continue
            class_name = value_to_local_name(val) + "Event"
            if class_name == "Event" or class_name in seen:
                continue
            seen.add(class_name)
            siblings.append(class_name)
            label = val.replace("_", " ").title() + " Event"
            # A *defined* class, not a bare subclass. The membership rule was
            # previously stated only in an rdfs:comment ("for event_type =
            # INCIDENT"), which a reasoner cannot read — so the ontology had
            # no class anything could be classified into, and an OWL-RL run
            # produced zero classifications. As an owl:equivalentClass over a
            # hasValue restriction, an event carrying that discriminator is
            # inferred to be a member. This is the ontology's first real
            # deductive content. See ONTOLOGY_ROADMAP.md Phase 3.
            blocks.append(
                f":{class_name}\n"
                f"  a owl:Class ;\n"
                f"  rdfs:subClassOf :{et.class_name} ;\n"
                f"  owl:equivalentClass [\n"
                f"    a owl:Class ;\n"
                f"    owl:intersectionOf (\n"
                f"      :{et.class_name}\n"
                f"      [ a owl:Restriction ;\n"
                f"        owl:onProperty :hasEventType ;\n"
                f'        owl:hasValue "{_str(val)}" ]\n'
                f"    )\n"
                f"  ] ;\n"
                f'  rdfs:label "{label}" ;\n'
                f'  rdfs:comment "Events of {et.class_name} whose event_type is {val}." ;\n'
                f"  :sensitivityTier :{et.sensitivity_tier} .\n"
            )
        if len(siblings) >= 2:
            sibling_groups.append(siblings)

    # Disjointness over event_type siblings is NOT emitted.
    #
    # The original justification — "a row has exactly one event_type, so the
    # subclasses are mutually exclusive by construction" — holds only if each
    # transition is reified as its own individual. It is not. The generated
    # groups were lifecycle *phases* of a single entity:
    #
    #     AllDisjointClasses( PlacedEvent ConfirmedEvent ShippedEvent
    #                         DeliveredEvent CancelledEvent RefundedEvent )
    #
    # An order that is placed and later shipped belongs to two of those, so
    # the axiom makes it unsatisfiable — a reasoner is entitled to conclude
    # the data is contradictory. Asserting disjointness requires knowing the
    # values are mutually exclusive *for the same individual*, which the
    # schema does not tell us.
    #
    # The sibling grouping is still computed so it can be surfaced for
    # review; see ONTOLOGY_ROADMAP.md Phase 2.
    if sibling_groups:
        blocks.append(
            "# Sibling event subclasses were detected but no "
            "owl:AllDisjointClasses\n"
            "# axiom is emitted: event_type values are frequently lifecycle\n"
            "# phases of one entity rather than mutually exclusive kinds, and\n"
            "# asserting disjointness over them makes any entity that passes\n"
            "# through two phases unsatisfiable. Declare disjointness "
            "explicitly\n"
            "# in metadata when it genuinely holds.\n"
        )
        for group in sibling_groups:
            blocks.append("#   candidate group: "
                          + " ".join(f":{c}" for c in group) + "\n")

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


DIMENSION_PREFIXES = PREFIXES + """\
@prefix time: <http://www.w3.org/2006/time#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
"""


def _temporal_patterns() -> str:
    """OWL-Time alignment and an explicit bitemporal distinction.

    The ontology had no temporal model at all: no intervals, no Allen
    relations, and — more consequentially — no separation between *when a
    fact was true* and *when the system recorded it*. Every timestamp was
    an undifferentiated xsd:dateTime, so "the policy was effective from
    March" and "we entered the policy in June" were indistinguishable.

    The source supports the distinction: `valid_from` / `effective_from` /
    `effective_until` carry valid time, while `created_at` carries
    transaction time. Declaring the two axes lets a consumer ask
    as-of questions — which is what runtime/temporal_queries/TQ-03
    (a bi-temporal SPARQL template) was written for and has never had a
    vocabulary to run against.
    """
    return """\
# ── Temporal Model (OWL-Time) ─────────────────────────────────────────
:TemporalExtent
  a owl:Class ;
  rdfs:subClassOf time:TemporalEntity ;
  rdfs:label "Temporal Extent" ;
  rdfs:comment "The period over which a fact is asserted to hold." ;
  :sensitivityTier :Internal .

# ── Valid time — when the fact was true in the world ──────────────────
:validFrom
  a owl:DatatypeProperty ;
  rdfs:label "valid from" ;
  rdfs:range xsd:dateTime ;
  rdfs:comment "Start of the period during which the fact holds in the modelled world. Distinct from when it was recorded." ;
  :sensitivityTier :Internal .

:validUntil
  a owl:DatatypeProperty ;
  rdfs:label "valid until" ;
  rdfs:range xsd:dateTime ;
  rdfs:comment "End of the period during which the fact holds. Absent means still valid." ;
  :sensitivityTier :Internal .

:hasValidityPeriod
  a owl:ObjectProperty ;
  rdfs:subPropertyOf time:hasTime ;
  rdfs:label "has validity period" ;
  rdfs:range :TemporalExtent ;
  rdfs:comment "Links a record to the interval over which it holds." ;
  :sensitivityTier :Internal .

# ── Transaction time — when the system recorded it ────────────────────
# prov:generatedAtTime already carries this on provenance-bearing records;
# :recordedAt is its counterpart for records outside the PROV profile.
:recordedAt
  a owl:DatatypeProperty ;
  rdfs:label "recorded at" ;
  rdfs:range xsd:dateTime ;
  rdfs:comment "When the assertion entered the system. Transaction time, not valid time." ;
  :sensitivityTier :Internal .

"""


def _quantity_patterns() -> str:
    """QUDT alignment for measured values.

    Every numeric measurement was a bare xsd:decimal with no dimension,
    unit, scale or quantity kind — so 15 and 15 were indistinguishable
    whether they meant milliseconds or megawatts. The source records the
    unit alongside the value (`unit_of_measure` sits next to
    `numeric_value`); nothing carried it into the ontology.
    """
    return """\
# ── Quantities and Units (QUDT) ───────────────────────────────────────
:QuantityValue
  a owl:Class ;
  rdfs:subClassOf qudt:QuantityValue ;
  rdfs:label "Quantity Value" ;
  rdfs:comment "A numeric magnitude together with the unit it is expressed in. Reified so a measurement cannot be read without its unit." ;
  :sensitivityTier :Internal .

:hasQuantity
  a owl:ObjectProperty ;
  rdfs:label "has quantity" ;
  rdfs:range :QuantityValue ;
  rdfs:comment "Links a record to its measured value." ;
  :sensitivityTier :Internal .

:numericValue
  a owl:DatatypeProperty ;
  rdfs:subPropertyOf qudt:numericValue ;
  rdfs:domain :QuantityValue ;
  rdfs:range xsd:decimal ;
  rdfs:label "numeric value" ;
  :sensitivityTier :Internal .

:unitOfMeasure
  a owl:DatatypeProperty ;
  rdfs:domain :QuantityValue ;
  rdfs:range xsd:string ;
  rdfs:label "unit of measure" ;
  rdfs:comment "Unit symbol as recorded at source. Map to a qudt:Unit IRI where the vocabulary is known." ;
  :sensitivityTier :Internal .

"""


def _participation_patterns() -> str:
    """Reified event participation with a role.

    The only participation axiom was a blunt
    `:hasParticipant (DomainEvent -> Agent)`, which cannot say *how* an
    agent took part. The source already models this properly — an
    `event_participants` table carrying event, agent, role and join time —
    so the n-ary relation existed in the data and was flattened to a
    binary link on the way into the ontology.
    """
    return """\
# ── Participation (reified n-ary relation) ────────────────────────────
:Participation
  a owl:Class ;
  rdfs:subClassOf :DomainEntity ;
  rdfs:label "Participation" ;
  rdfs:comment "An agent's involvement in an event, in a stated role. Reified because the relation carries its own attributes — role and time — which a binary property cannot hold." ;
  :sensitivityTier :Internal .

:participationIn
  a owl:ObjectProperty ;
  rdfs:domain :Participation ;
  rdfs:range :DomainEvent ;
  rdfs:label "participation in" ;
  :sensitivityTier :Internal .

:participatingAgent
  a owl:ObjectProperty ;
  rdfs:subPropertyOf prov:wasAssociatedWith ;
  rdfs:domain :Participation ;
  rdfs:range :Agent ;
  rdfs:label "participating agent" ;
  :sensitivityTier :Internal .

:participationRole
  a owl:DatatypeProperty ;
  rdfs:domain :Participation ;
  rdfs:range xsd:string ;
  rdfs:label "participation role" ;
  rdfs:comment "The capacity in which the agent took part." ;
  :sensitivityTier :Internal .

"""


def _prov_patterns() -> str:
    return f"""\
# ── PROV-O Integration Patterns ──────────────────────────────────────
# Aligns ObservationRecord with prov:Entity and agents with prov:Agent.

# PROV-O requires an Activity to sit between an Entity and its Agent, so
# the profile needs all three roles declared. Only :ObservationRecord was
# aligned (to prov:Entity); agents were not prov:Agent and no Activity
# class existed, which is why the ABox could not emit a chain at all.
:Agent
  rdfs:subClassOf prov:Agent .

:DerivationActivity
  a owl:Class ;
  rdfs:subClassOf prov:Activity ;
  rdfs:label "Derivation Activity" ;
  rdfs:comment "The act of recording or deriving an observation. Reified so an observation can be linked to both the activity that generated it and the agent responsible." ;
  :sensitivityTier :Internal .

# `rdfs:subPropertyOf prov:wasGeneratedBy` with `rdfs:range :Agent` was
# incorrect: in PROV-O, wasGeneratedBy points at an Activity, so this
# inferred that every agent was an Activity. Entity→Agent is
# prov:wasAttributedTo.
:wasProducedBy
  a owl:ObjectProperty ;
  rdfs:subPropertyOf prov:wasAttributedTo ;
  rdfs:label "was produced by" ;
  rdfs:domain :ObservationRecord ;
  rdfs:range :Agent ;
  rdfs:comment "Links an observation to the agent that produced it." ;
  :sensitivityTier :Internal .

# :hasConfidenceScore is declared by the schema-driven generator in
# enterprise.ttl, where its domain is the union of every class that uses a
# confidence column. Re-declaring it here with `rdfs:domain
# :ObservationRecord` added a second domain axiom, and multiple domains
# conjoin — so a confidence score on a PerformanceIndicator also made that
# individual an ObservationRecord. Only the range and documentation are
# restated; the domain belongs to the authoritative declaration.
:hasConfidenceScore
  a owl:DatatypeProperty ;
  rdfs:label "Confidence Score" ;
  rdfs:range xsd:decimal ;
  rdfs:comment "Numeric confidence in the observation value. Range: 0.0–1.0." ;
  :sensitivityTier :Confidential .

# Semantic alias. The schema-driven generator derives :hasDerivationMethod
# from the derivation_method column, and that is the name instance data
# carries. This hand-authored name reads better and is what the competency
# questions were written against, so it is kept and *linked* rather than
# either one being deleted — owl:equivalentProperty makes them the same
# property to a reasoner. Domain is omitted: the authoritative declaration
# carries it, and a second rdfs:domain would conjoin (see Phase 2).
:derivationMethod
  a owl:DatatypeProperty ;
  owl:equivalentProperty :hasDerivationMethod ;
  rdfs:label "Derivation Method" ;
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

# Semantic alias for the FK-derived :asset. Same reasoning as
# :derivationMethod above — the structural name is what the data carries,
# this one says what the relation means, and owl:equivalentProperty makes
# a query against either find the same triples under a reasoner.
:refersToAsset
  a owl:ObjectProperty ;
  owl:equivalentProperty :asset ;
  rdfs:label "refers to asset" ;
  rdfs:range :Asset ;
  rdfs:comment "The asset this observation is about." ;
  :sensitivityTier :Internal .

"""


# ── Main generator ───────────────────────────────────────────────────────

def generate_ontology(intro: DBIntrospector, output_dir: str,
                      *, session: dict = None):
    """Generate the enterprise ontology.

    Args:
        intro: introspector around the operational DB.
        output_dir: where to write enterprise.ttl + sibling files.
        session: optional wizard session. When the session contains any
            event/entity with ``source == "log-discovery"``, the RCA
            taxonomy (:class:`rca_taxonomy.emit_taxonomy`) is included
            so :hasCause / :rootCause queries work end-to-end. Per-class
            time-interval data properties and severity-tier mappings
            are also emitted for log-derived classes.
    """
    tables = intro.introspect_all()
    os.makedirs(output_dir, exist_ok=True)

    # Read the previous emission before overwriting it, so the new header
    # can carry owl:priorVersion and removed entities can be tombstoned.
    _ont_path_prior = os.path.join(output_dir, "enterprise.ttl")
    _prior = _prior_version(_ont_path_prior)

    # ── Primary ontology ──────────────────────────────────────────────
    lines = [
        PREFIXES,
        _ontology_header(
            "Enterprise Domain Ontology",
            "Auto-generated from relational schema + ontology_metadata. "
            "Covers all operational domain entities, events, agents, "
            "policies, observations, and provenance patterns.",
            VERSION,
            BASE_IRI,
            prior=_prior,
        ),
        _sensitivity_property(),
        _base_classes(),
    ]

    # L5.1 — RCA taxonomy. Pulled in when the active session carries
    # any log-discovery output so :hasCause/:rootCause queries work.
    if _session_has_log_discovery(session):
        from rca_taxonomy import emit_taxonomy
        lines.append(emit_taxonomy())
        # L5.2 — log-derived classes from session.events + entities.
        lines.append(_emit_log_derived_classes(session))

    lines.append("# ── Domain Classes ──────────────────────────────────────────────────\n")
    for t in tables:
        # Skip tables that are pure junction/log tables not needing a top-level class
        lines.append(_class_block(t))

    # Properties are grouped by IRI before emission. Emitting one block per
    # (table, column) re-declared the same property once per table, and each
    # declaration carried its own rdfs:domain — which conjoin. Grouping lets
    # a property be declared exactly once, with a union domain covering every
    # class that uses it. See _render_domain.
    data_props: "OrderedDict[str, tuple]" = OrderedDict()
    for t in tables:
        for col in t.data_properties:
            key = f"has{snake_to_camel(col.name)}"
            cols, classes = data_props.setdefault(key, ([], []))
            cols.append(col)
            classes.append(t.class_name)

    lines.append("\n# ── Data Properties ─────────────────────────────────────────────────\n")
    for cols, classes in data_props.values():
        lines.append(_data_property_block(cols, classes))

    obj_props: "OrderedDict[str, tuple]" = OrderedDict()
    for t in tables:
        for col in t.object_properties:
            key = object_property_name(col.name)
            cols, classes = obj_props.setdefault(key, ([], []))
            cols.append(col)
            classes.append(t.class_name)

    lines.append("\n# ── Object Properties ───────────────────────────────────────────────\n")
    for cols, classes in obj_props.values():
        lines.append(_object_property_block(cols, classes, tables))

    _current_names = {t.class_name for t in tables}
    _current_names |= set(data_props.keys()) | set(obj_props.keys())
    _tombstones = _deprecation_tombstones(_ont_path_prior, _current_names)
    if _tombstones:
        lines.append(_tombstones)

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

    # ── Dimensions sub-module (Phase 5) ──────────────────────────────
    dim_content = (
        DIMENSION_PREFIXES + "\n"
        f'<{BASE_IRI}dimensions/>\n'
        f'  a owl:Ontology ;\n'
        f'  owl:imports <{BASE_IRI}> ;\n'
        f'  rdfs:label "Enterprise Dimensions Profile" ;\n'
        f'  rdfs:comment "Time, quantity and participation patterns: the '
        f'dimensions a relational schema flattens away." .\n\n'
        + _temporal_patterns()
        + _quantity_patterns()
        + _participation_patterns()
    )
    dim_path = os.path.join(output_dir, "dimensions.ttl")
    with open(dim_path, "w") as f:
        f.write(dim_content)
    print(f"  ✓ Dimensions profile    → {dim_path}")


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
    has_disjoint    = False
    has_union       = False
    has_complement  = False
    graph_parsed    = False

    # Parse the graph rather than substring-search the file. The previous
    # implementation asked whether the *text* contained "owl:oneOf", which
    # matches a comment, a prefix declaration or a URL fragment as readily
    # as an axiom — and could never see a construct written in a different
    # syntactic form. It also counted "axioms" as classes + properties,
    # which is not an axiom count.
    try:
        import rdflib
        g = rdflib.Graph()
        g.parse(ontology_path, format="turtle")
        graph_parsed = True
        axiom_count = len(g)
        has_role_chains = bool(list(g.triples((None, rdflib.OWL.propertyChainAxiom, None))))
        has_nominals    = bool(list(g.triples((None, rdflib.OWL.oneOf, None))))
        has_inverse_of  = bool(list(g.triples((None, rdflib.OWL.inverseOf, None))))
        has_symmetric   = bool(list(g.triples((None, rdflib.RDF.type, rdflib.OWL.SymmetricProperty))))
        has_inv_func    = bool(list(g.triples((None, rdflib.RDF.type, rdflib.OWL.InverseFunctionalProperty))))
        has_disjoint    = bool(
            list(g.triples((None, rdflib.RDF.type, rdflib.OWL.AllDisjointClasses)))
            or list(g.triples((None, rdflib.OWL.disjointWith, None)))
        )
        # Disjunction. OWL 2 EL has no union constructor, so a union class
        # expression — which the union-domain fix now emits routinely —
        # puts the ontology outside EL. Missing this would report EL for an
        # ontology ELK cannot fully classify.
        has_union       = bool(list(g.triples((None, rdflib.OWL.unionOf, None))))
        has_complement  = bool(list(g.triples((None, rdflib.OWL.complementOf, None))))
    except Exception:
        # rdflib unavailable or the file does not parse. Report honestly
        # rather than fall back to a guess that reads like a measurement.
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
    # AllDisjointClasses / disjointWith are not in OWL 2 EL either. The old
    # detector omitted them, so an ontology carrying disjointness was still
    # reported as EL — which was wrong even when the answer happened to be
    # "EL" for other reasons.
    if has_disjoint:
        dl_constructs.append("class disjointness")
    if has_union:
        dl_constructs.append("owl:unionOf (disjunction)")
    if has_complement:
        dl_constructs.append("owl:complementOf (negation)")

    if not graph_parsed:
        return {
            "profile":         "unknown",
            "axiom_count":     axiom_count,
            "classes":         classes,
            "data_properties": data_props,
            "object_properties": obj_props,
            "has_role_chains": False,
            "has_nominals":    False,
            "has_inverse_of":  False,
            "has_symmetric":   False,
            "has_inverse_functional": False,
            "rationale": (
                "Profile not determined: the ontology could not be parsed "
                "(rdflib missing, or the file is malformed). No profile is "
                "reported rather than guessing one."
            ),
        }

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
