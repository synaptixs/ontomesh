"""
alignment_generator.py
──────────────────────
Ontology alignment and federation module for the Ontology Toolkit.

Generates:
  1. output/ontology/alignment.ttl
       owl:equivalentClass and skos:exactMatch axioms aligning the
       generated ontology with DOLCE, FOAF, Schema.org, and SOSA
       (W3C Sensor Observation ontology).

  2. output/ontology/federation-config.ttl
       SPARQL SERVICE endpoint configuration for multi-domain
       federated queries across named graphs.

  3. output/ontology/federation-queries.sparql
       Example federated SPARQL queries that demonstrate cross-domain
       joins via SERVICE clauses.

Standards aligned:
  DOLCE   — Descriptive Ontology for Linguistic and Cognitive Engineering
  FOAF    — Friend of a Friend (foaf:)
  Schema  — Schema.org (schema:)
  SOSA    — Sensor Observation Sample Actuator (W3C SSN/SOSA)
  OWL 2   — owl:equivalentClass, owl:equivalentProperty
  SKOS    — skos:exactMatch, skos:closeMatch, skos:broadMatch

CLI:
  python3 toolkit.py --phase alignment [--db db/tmf.db]
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

# Alignment axioms describe entities in the *generated* ontologies, so their
# subjects must be minted in whichever namespace actually declares them.
#
# This module previously minted every subject under the TMF module namespace
# while 25 of its 29 class alignments describe enterprise classes, so none of
# the 45 axioms attached to anything: `tmf/Agent` and `enterprise/Agent` are
# different IRIs. Subjects are now resolved against the generated Turtle at
# write time — see `_resolve_subject`.
ENTERPRISE_IRI = "https://ontology.example.com/enterprise/"
SID_IRI        = "https://ontology.example.com/tmf/"
BASE_IRI       = SID_IRI  # retained: the alignment module's own ontology IRI
DOLCE_NS   = "http://www.loa-cnr.it/ontologies/DOLCE-Lite.owl#"
FOAF_NS    = "http://xmlns.com/foaf/0.1/"
SCHEMA_NS  = "https://schema.org/"
SOSA_NS    = "http://www.w3.org/ns/sosa/"
SSN_NS     = "http://www.w3.org/ns/ssn/"
SKOS_NS    = "http://www.w3.org/2004/02/skos/core#"
OWL_NS     = "http://www.w3.org/2002/07/owl#"
RDFS_NS    = "http://www.w3.org/2000/01/rdf-schema#"
XSD_NS     = "http://www.w3.org/2001/XMLSchema#"
TMF_NS     = "https://www.tmforum.org/sid/"
PROV_NS    = "http://www.w3.org/ns/prov#"

ALIGN_PREFIXES = f"""\
@prefix :       <{ENTERPRISE_IRI}> .
@prefix sid:    <{SID_IRI}> .
@prefix dolce:  <{DOLCE_NS}> .
@prefix foaf:   <{FOAF_NS}> .
@prefix schema: <{SCHEMA_NS}> .
@prefix sosa:   <{SOSA_NS}> .
@prefix ssn:    <{SSN_NS}> .
@prefix skos:   <{SKOS_NS}> .
@prefix owl:    <{OWL_NS}> .
@prefix rdfs:   <{RDFS_NS}> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:    <{XSD_NS}> .
@prefix tmf:    <{TMF_NS}> .
@prefix prov:   <{PROV_NS}> .
@prefix dcterms:<http://purl.org/dc/terms/> .
"""

# ── Alignment axioms ───────────────────────────────────────────────────────
# Format: (local_class_or_prop, alignment_type, external_IRI, comment)
# alignment_type: equiv_class | equiv_prop | exact_match | close_match | broad_match

CLASS_ALIGNMENTS: list[tuple[str, str, str, str]] = [
    # ── DOLCE alignments ─────────────────────────────────────────────────
    ("TmfEntity",     "equiv_class", f"{DOLCE_NS}particular",
     "DOLCE:particular — all SID entities are spatio-temporal particulars."),
    ("Party",         "close_match", f"{DOLCE_NS}agentive-physical-object",
     "DOLCE:agentive-physical-object — a party is an agentive endurant that can act."),
    ("Resource",      "close_match", f"{DOLCE_NS}non-agentive-physical-object",
     "DOLCE:non-agentive-physical-object — network resources are physical endurants without agency."),
    ("Service",       "close_match", f"{DOLCE_NS}process",
     "DOLCE:process — a service is an ongoing process delivered over time."),
    ("DomainEvent",   "equiv_class", f"{DOLCE_NS}event",
     "DOLCE:event — domain events are perdurants / occurrents in DOLCE."),
    ("Agreement",     "close_match", f"{DOLCE_NS}social-object",
     "DOLCE:social-object — agreements are social non-physical objects."),
    ("Policy",        "close_match", f"{DOLCE_NS}social-object",
     "DOLCE:social-object — policies are normative social objects."),

    # ── FOAF alignments ───────────────────────────────────────────────────
    ("Party",         "equiv_class", f"{FOAF_NS}Agent",
     "foaf:Agent — a Party (individual or organization) is an agent."),
    ("Individual",    "equiv_class", f"{FOAF_NS}Person",
     "foaf:Person — an Individual is a natural person."),
    ("Organization",  "equiv_class", f"{FOAF_NS}Organization",
     "foaf:Organization — an Organization maps directly to foaf:Organization."),
    ("GeographicSite","close_match", f"{FOAF_NS}based_near",
     "foaf:based_near — geographic sites provide location context for agents."),

    # ── Schema.org alignments ─────────────────────────────────────────────
    ("Party",         "close_match", f"{SCHEMA_NS}Person",
     "schema:Person — for individual parties; schema:Organization for organizations."),
    ("Organization",  "equiv_class", f"{SCHEMA_NS}Organization",
     "schema:Organization — direct equivalence for legal/operational entities."),
    ("Individual",    "equiv_class", f"{SCHEMA_NS}Person",
     "schema:Person — direct equivalence for natural persons."),
    ("Product",       "equiv_class", f"{SCHEMA_NS}Product",
     "schema:Product — TMF SID product maps to schema:Product lifecycle."),
    ("ProductOffering","close_match", f"{SCHEMA_NS}Offer",
     "schema:Offer — a ProductOffering is a commercial offer in the catalog."),
    ("GeographicSite","equiv_class", f"{SCHEMA_NS}Place",
     "schema:Place — geographic sites map to schema:Place."),
    ("GeographicPlace","equiv_class", f"{SCHEMA_NS}PostalAddress",
     "schema:PostalAddress — geographic addresses map to PostalAddress."),
    ("Agreement",     "close_match", f"{SCHEMA_NS}Service",
     "schema:Service — agreements (SLA/commercial) govern service delivery."),
    ("CustomerBill",  "close_match", f"{SCHEMA_NS}Invoice",
     "schema:Invoice — customer bills map closely to schema:Invoice."),
    ("ServiceOrder",  "close_match", f"{SCHEMA_NS}Order",
     "schema:Order — service/product orders map to schema:Order."),
    ("ProductOrder",  "equiv_class", f"{SCHEMA_NS}Order",
     "schema:Order — product orders are customer purchase orders."),
    ("TroubleTicket", "close_match", f"{SCHEMA_NS}Question",
     "schema:Question — trouble tickets are support requests requiring resolution."),

    # ── SOSA/SSN alignments ───────────────────────────────────────────────
    ("ObservationRecord","equiv_class", f"{SOSA_NS}Observation",
     "sosa:Observation — an ObservationRecord is a SOSA observation with provenance."),
    ("PerformanceIndicator","equiv_class", f"{SOSA_NS}Observation",
     "sosa:Observation — KPI measurements are sensor observations with result values."),
    ("Resource",      "close_match", f"{SOSA_NS}FeatureOfInterest",
     "sosa:FeatureOfInterest — resources are the features that observations are about."),
    ("NetworkFunction","close_match", f"{SOSA_NS}FeatureOfInterest",
     "sosa:FeatureOfInterest — NFs are monitored features of interest."),
    ("Agent",         "close_match", f"{SOSA_NS}Sensor",
     "sosa:Sensor — monitoring agents (ML Agent, NOC system) act as sensors."),
    ("ServiceQualityReport","close_match", f"{SOSA_NS}Result",
     "sosa:Result — quality reports aggregate sensor observation results."),
    ("DriftObservation","equiv_class", f"{SOSA_NS}Observation",
     "sosa:Observation — ML drift observations are specialized SOSA observations."),
    ("NetworkSliceProfile","close_match", f"{SSN_NS}System",
     "ssn:System — a network slice profile describes a sensing/acting system."),
]

PROPERTY_ALIGNMENTS: list[tuple[str, str, str, str]] = [
    # FOAF property alignments
    ("hasName",       "equiv_prop", f"{FOAF_NS}name",
     "foaf:name — entity names map to foaf:name."),
    ("hasEmail",      "equiv_prop", f"{FOAF_NS}mbox",
     "foaf:mbox — email properties map to foaf:mbox."),
    # Schema.org property alignments
    ("hasName",       "close_match", f"{SCHEMA_NS}name",
     "schema:name — entity name maps to schema:name."),
    ("hasDescription","equiv_prop",  f"{SCHEMA_NS}description",
     "schema:description — description maps directly."),
    ("startDate",     "equiv_prop",  f"{SCHEMA_NS}startDate",
     "schema:startDate — start dates align with schema:startDate."),
    ("endDate",       "equiv_prop",  f"{SCHEMA_NS}endDate",
     "schema:endDate — end dates align with schema:endDate."),
    ("amountDue",     "close_match", f"{SCHEMA_NS}totalPaymentDue",
     "schema:totalPaymentDue — bill amount due maps to schema:totalPaymentDue."),
    # SOSA property alignments
    ("hasConfidenceScore","close_match", f"{SOSA_NS}resultQuality",
     "sosa:resultQuality — confidence score maps to observation result quality."),
    ("observedAt",    "equiv_prop",  f"{SOSA_NS}resultTime",
     "sosa:resultTime — observation timestamp maps to resultTime."),
    ("derivationMethod","close_match", f"{PROV_NS}wasGeneratedBy",
     "prov:wasGeneratedBy — derivation method relates to provenance generation."),
    ("sourceRef",     "equiv_prop",  f"{PROV_NS}hadPrimarySource",
     "prov:hadPrimarySource — sourceRef maps to PROV-O primary source."),
    ("recordedBy",    "equiv_prop",  f"{SOSA_NS}madeBySensor",
     "sosa:madeBySensor — the agent making the observation is the sensor."),
    ("refersToResource","equiv_prop", f"{SOSA_NS}hasFeatureOfInterest",
     "sosa:hasFeatureOfInterest — the resource being observed."),
]

# ── Federation endpoint configuration ──────────────────────────────────────
FEDERATION_ENDPOINTS: list[dict] = [
    {
        "name": "local-resource",
        "description": "Resource domain named graph — NFs, slices, equipment.",
        "endpoint": "http://localhost:3030/ontology/sparql",
        "named_graph": "https://gtc.example.com/graphs/resource",
        "sid_domain": "Resource",
        "sensitivity_tier": "Internal",
    },
    {
        "name": "local-service",
        "description": "Service domain named graph — CFS, RFS, service orders.",
        "endpoint": "http://localhost:3030/ontology/sparql",
        "named_graph": "https://gtc.example.com/graphs/service",
        "sid_domain": "Service",
        "sensitivity_tier": "Internal",
    },
    {
        "name": "local-party",
        "description": "Party/EngagedParty domain named graph — customers, agreements.",
        "endpoint": "http://localhost:3030/ontology/sparql",
        "named_graph": "https://gtc.example.com/graphs/party",
        "sid_domain": "EngagedParty",
        "sensitivity_tier": "Confidential",
    },
    {
        "name": "local-billing",
        "description": "Billing domain named graph — bills, accounts.",
        "endpoint": "http://localhost:3030/ontology/sparql",
        "named_graph": "https://gtc.example.com/graphs/billing",
        "sid_domain": "Billing",
        "sensitivity_tier": "Confidential",
    },
    {
        "name": "local-trouble",
        "description": "Trouble/alarm domain named graph — tickets, alarms, problems.",
        "endpoint": "http://localhost:3030/ontology/sparql",
        "named_graph": "https://gtc.example.com/graphs/trouble",
        "sid_domain": "TroubleMgmt",
        "sensitivity_tier": "Internal",
    },
]


def _declared_local_names(output_dir: str, filename: str) -> set[str]:
    """Local names of every subject declared in a generated Turtle file.

    Parsed with rdflib when available; falls back to a line scan so the
    alignment phase still runs in a minimal install.
    """
    path = os.path.join(output_dir, filename)
    if not os.path.isfile(path):
        return set()
    try:
        import rdflib
        g = rdflib.Graph()
        g.parse(path, format="turtle")
        return {str(s).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                for s in g.subjects() if isinstance(s, rdflib.URIRef)}
    except Exception:
        names: set[str] = set()
        try:
            with open(path) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(":") and len(stripped) > 1:
                        names.add(stripped[1:].split()[0].rstrip(";,."))
        except OSError:
            return set()
        return names


def _resolve_subject(local_name: str,
                     enterprise: set[str],
                     sid: set[str]) -> str | None:
    """Render an alignment subject in the namespace that declares it.

    Returns a prefixed name (``:Agent`` or ``sid:TmfEntity``), or None when
    the entity exists in neither ontology — in which case the axiom is
    dropped rather than emitted against an IRI nothing declares.

    Data properties are generated with a ``has`` prefix (``amountDue`` is
    declared as ``hasAmountDue``), so that variant is tried too.
    """
    variants = [local_name, "has" + local_name[:1].upper() + local_name[1:]]
    for name in variants:
        if name in enterprise:
            return f":{name}"
    for name in variants:
        if name in sid:
            return f"sid:{name}"
    return None


def generate_alignment_ontology(output_dir: str) -> None:
    """Generate alignment.ttl with owl:equivalentClass/Property and skos:exactMatch axioms."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Resolve subjects against what was actually generated.
    enterprise_names: set[str] = set()
    for fname in ("enterprise.ttl", "events.ttl", "provenance.ttl", "drift.ttl"):
        enterprise_names |= _declared_local_names(output_dir, fname)
    sid_names = _declared_local_names(output_dir, "tmf-sid-hierarchy.ttl")
    unresolved: list[str] = []

    lines = [
        ALIGN_PREFIXES,
        f'\n<{BASE_IRI}alignment/>\n'
        f'  a owl:Ontology ;\n'
        f'  rdfs:label "Ontology Alignment Module" ;\n'
        f'  rdfs:comment "Alignment axioms linking the generated ontology to DOLCE, FOAF, Schema.org, and SOSA." ;\n'
        f'  owl:imports <{BASE_IRI}> ;\n'
        f'  dcterms:created "{ts}"^^xsd:dateTime ;\n'
        f'  dcterms:description '
        f'"Phase 2B: owl:equivalentClass and skos:exactMatch axioms for cross-ontology alignment." .\n\n',
    ]

    # Class alignments
    lines.append("# ═══════════════════════════════════════════════════════\n")
    lines.append("# CLASS ALIGNMENTS\n")
    lines.append("# ═══════════════════════════════════════════════════════\n\n")

    current_section = None
    section_prefixes = {
        DOLCE_NS: "DOLCE", FOAF_NS: "FOAF",
        SCHEMA_NS: "Schema.org", SOSA_NS: "SOSA/SSN", SSN_NS: "SOSA/SSN",
    }
    for ns in [DOLCE_NS, FOAF_NS, SCHEMA_NS, SOSA_NS, SSN_NS]:
        section = section_prefixes[ns]
        relevant = [(lc, at, ext, cm)
                    for lc, at, ext, cm in CLASS_ALIGNMENTS
                    if ext.startswith(ns)]
        if not relevant:
            continue
        if section != current_section:
            lines.append(f"# ── {section} Class Alignments {'─'*(48-len(section))}\n")
            current_section = section
        for local_cls, align_type, ext_iri, comment in relevant:
            subject = _resolve_subject(local_cls, enterprise_names, sid_names)
            if subject is None:
                unresolved.append(local_cls)
                continue
            pred = {
                "equiv_class":  "owl:equivalentClass",
                "exact_match":  "skos:exactMatch",
                "close_match":  "skos:closeMatch",
                "broad_match":  "skos:broadMatch",
            }.get(align_type, "skos:closeMatch")
            lines.append(
                f"{subject}\n"
                f'  {pred} <{ext_iri}> ;\n'
                f'  rdfs:comment "{comment}" .\n\n'
            )

    # Property alignments
    lines.append("# ═══════════════════════════════════════════════════════\n")
    lines.append("# PROPERTY ALIGNMENTS\n")
    lines.append("# ═══════════════════════════════════════════════════════\n\n")

    for local_prop, align_type, ext_iri, comment in PROPERTY_ALIGNMENTS:
        subject = _resolve_subject(local_prop, enterprise_names, sid_names)
        if subject is None:
            unresolved.append(local_prop)
            continue
        pred = {
            "equiv_prop":   "owl:equivalentProperty",
            "exact_match":  "skos:exactMatch",
            "close_match":  "skos:closeMatch",
        }.get(align_type, "skos:closeMatch")
        lines.append(
            f"{subject}\n"
            f'  {pred} <{ext_iri}> ;\n'
            f'  rdfs:comment "{comment}" .\n\n'
        )

    if unresolved:
        lines.append(
            "# ── Unresolved ─────────────────────────────────────────────\n"
            "# These alignments name entities that neither the enterprise\n"
            "# ontology nor the TMF SID module declares, so emitting them\n"
            "# would create IRIs nothing defines. Fix the alignment table or\n"
            "# generate the missing entity, then re-run.\n"
            + "".join(f"#   {n}\n" for n in sorted(set(unresolved)))
            + "\n"
        )

    path = os.path.join(output_dir, "alignment.ttl")
    with open(path, "w") as f:
        f.write("".join(lines))

    n_class = len(CLASS_ALIGNMENTS)
    n_prop  = len(PROPERTY_ALIGNMENTS)
    n_bound = n_class + n_prop - len(unresolved)
    print(f"  ✓ Alignment ontology       → {path}")
    print(f"    Class alignments: {n_class}  |  Property alignments: {n_prop}")
    print(f"    Bound to a declared entity: {n_bound}/{n_class + n_prop}")
    if unresolved:
        print(f"    ⚠ {len(unresolved)} unresolved (listed in alignment.ttl): "
              f"{', '.join(sorted(set(unresolved))[:6])}"
              + (" …" if len(set(unresolved)) > 6 else ""))
    print(f"    Standards: DOLCE, FOAF, Schema.org, SOSA, SSN")


def generate_federation_config(output_dir: str) -> None:
    """Generate federation-config.ttl — SPARQL SERVICE endpoint registry."""
    os.makedirs(output_dir, exist_ok=True)
    BASE = BASE_IRI

    lines = [
        ALIGN_PREFIXES,
        f'@prefix fed:    <{BASE}federation/> .\n\n',
        f'<{BASE}federation/>\n'
        f'  a owl:Ontology ;\n'
        f'  rdfs:label "SPARQL Federation Configuration" ;\n'
        f'  rdfs:comment "Named graph federation endpoints for multi-domain SPARQL SERVICE queries." .\n\n',
        "# ── Federation Endpoints ────────────────────────────────────────\n\n",
    ]

    for ep in FEDERATION_ENDPOINTS:
        iri = f"{BASE}federation/{ep['name']}"
        lines.append(
            f"<{iri}>\n"
            f"  a fed:FederationEndpoint ;\n"
            f'  rdfs:label "{ep["name"]}" ;\n'
            f'  rdfs:comment "{ep["description"]}" ;\n'
            f'  fed:sparqlEndpoint <{ep["endpoint"]}> ;\n'
            f'  fed:namedGraph <{ep["named_graph"]}> ;\n'
            f'  fed:sidDomain "{ep["sid_domain"]}" ;\n'
            f'  fed:sensitivityTier "{ep["sensitivity_tier"]}" .\n\n'
        )

    path = os.path.join(output_dir, "federation-config.ttl")
    with open(path, "w") as f:
        f.write("".join(lines))
    print(f"  ✓ Federation config        → {path}")
    print(f"    Endpoints configured: {len(FEDERATION_ENDPOINTS)}")


def generate_federation_queries(output_dir: str) -> None:
    """Generate example federated SPARQL queries across named graphs."""
    os.makedirs(output_dir, exist_ok=True)

    queries = f"""\
# ============================================================
# Federated SPARQL Queries — Multi-Domain Named Graph Joins
# Ontology Toolkit v1.3 — Phase 2B
# ============================================================
# These queries use SPARQL SERVICE to federate across named
# graph endpoints defined in federation-config.ttl.
# Run against a Fuseki/Stardog/Oxigraph instance with all
# named graphs loaded.
# ============================================================

PREFIX :       <{BASE_IRI}>
PREFIX prov:   <{PROV_NS}>
PREFIX schema: <https://schema.org/>
PREFIX sosa:   <{SOSA_NS}>
PREFIX xsd:    <http://www.w3.org/2001/XMLSchema#>

# ── FQ-01: Full cross-domain traceability chain ──────────────
# Resource → Service → Product → Customer → Bill
# Joins Resource, Service, Party, and Billing named graphs.
# ─────────────────────────────────────────────────────────────
SELECT ?resource ?nfType ?service ?product ?customer ?bill ?amountDue
WHERE {{
  SERVICE <http://localhost:3030/ontology/sparql> {{
    GRAPH <https://gtc.example.com/graphs/resource> {{
      ?resource a :Resource ;
                :hasNfType ?nfType ;
                :hasOperationalState "Enabled" .
    }}
    GRAPH <https://gtc.example.com/graphs/service> {{
      ?service a :Service ;
               :realisedByResource ?resource ;
               :hasServiceState "Active" .
      ?product a :Product ;
               :realisedByService ?service ;
               :hasStatus "Active" .
    }}
    GRAPH <https://gtc.example.com/graphs/party> {{
      ?account a :CustomerAccount ;
               :holdsProduct ?product .
      ?customer a :Party ;
                :hasAccount ?account .
    }}
    GRAPH <https://gtc.example.com/graphs/billing> {{
      ?bill a :CustomerBill ;
            :billedToAccount ?account ;
            :amountDue ?amountDue .
      FILTER(?amountDue > 0)
    }}
  }}
}}
ORDER BY ?customer ?resource


# ── FQ-02: Active trouble tickets with SLA breach risk ───────
# Joins Trouble, Service, and Party named graphs.
# ─────────────────────────────────────────────────────────────
SELECT ?ticket ?severity ?service ?slaAgreement ?dueDate
WHERE {{
  SERVICE <http://localhost:3030/ontology/sparql> {{
    GRAPH <https://gtc.example.com/graphs/trouble> {{
      ?ticket a :TroubleTicket ;
              :hasTicketStatus ?status ;
              :ticketSeverity ?severity .
      FILTER(?status NOT IN ("Resolved","Closed","Cancelled"))
    }}
    GRAPH <https://gtc.example.com/graphs/service> {{
      ?ticket :affectsService ?service .
    }}
    GRAPH <https://gtc.example.com/graphs/party> {{
      OPTIONAL {{
        ?slaAgreement a :Agreement ;
                      :agreementType "SLA" ;
                      :coversService ?service ;
                      :validUntil ?dueDate .
      }}
    }}
  }}
}}
ORDER BY
  CASE ?severity
    WHEN "1-Critical" THEN 1
    WHEN "2-High"     THEN 2
    ELSE 3
  END


# ── FQ-03: SOSA observation federation ───────────────────────
# Cross-domain join: SOSA observations about resources with
# provenance from the EngagedParty graph (who made observation).
# ─────────────────────────────────────────────────────────────
SELECT ?obs ?feature ?sensor ?value ?confidence ?method ?observedAt
WHERE {{
  SERVICE <http://localhost:3030/ontology/sparql> {{
    GRAPH <https://gtc.example.com/graphs/resource> {{
      ?obs a sosa:Observation ;
           sosa:hasFeatureOfInterest ?feature ;
           sosa:madeBySensor ?sensor ;
           sosa:hasSimpleResult ?value ;
           sosa:resultTime ?observedAt .
      OPTIONAL {{ ?obs :hasConfidenceScore ?confidence }}
      OPTIONAL {{ ?obs :derivationMethod ?method }}
    }}
    GRAPH <https://gtc.example.com/graphs/party> {{
      ?sensor a :Agent ;
              :hasName ?sensorName .
    }}
  }}
}}
ORDER BY DESC(?observedAt)


# ── FQ-04: Network slice profile SLA compliance federation ───
# Joins Resource, Service, and Party (billing) named graphs.
# ─────────────────────────────────────────────────────────────
SELECT ?sliceProfile ?sliceType ?latencyTarget ?actualLatency
       ?slaBreached ?agreement
WHERE {{
  SERVICE <http://localhost:3030/ontology/sparql> {{
    GRAPH <https://gtc.example.com/graphs/resource> {{
      ?sliceProfile a :NetworkSliceProfile ;
                    :hasSliceType ?sliceType ;
                    :latencyTargetMs ?latencyTarget ;
                    :lifecycleStatus "Active" .
      OPTIONAL {{
        ?latKpi a :PerformanceIndicator ;
                :kpiType "LATENCY" ;
                :aboutResource ?sliceRes ;
                :numericValue ?actualLatency .
        ?sliceProfile :backedByResource ?sliceRes .
      }}
    }}
    GRAPH <https://gtc.example.com/graphs/party> {{
      OPTIONAL {{
        ?agreement a :Agreement ;
                   :agreementType "SLA" ;
                   :coversSliceProfile ?sliceProfile .
      }}
    }}
  }}
  BIND(IF(?actualLatency > ?latencyTarget, true, false) AS ?slaBreached)
}}
ORDER BY ?sliceType


# ── FQ-05: Event subscription coverage audit ─────────────────
# Shows which event types are subscribed to and by which parties.
# ─────────────────────────────────────────────────────────────
SELECT ?subscription ?eventType ?subscriber ?callbackUrl ?status
WHERE {{
  SERVICE <http://localhost:3030/ontology/sparql> {{
    GRAPH <https://gtc.example.com/graphs/resource> {{
      ?subscription a :EventSubscription ;
                    :eventType ?eventType ;
                    :callbackUrl ?callbackUrl ;
                    :hasTicketStatus ?status .
      FILTER(?status = "Active")
    }}
    GRAPH <https://gtc.example.com/graphs/party> {{
      ?subscription :subscriberParty ?subscriber .
    }}
  }}
}}
ORDER BY ?eventType ?subscriber
"""

    path = os.path.join(output_dir, "federation-queries.sparql")
    with open(path, "w") as f:
        f.write(queries)
    print(f"  ✓ Federation queries       → {path}")
    print(f"    Example federated queries: 5 (FQ-01..FQ-05)")


def run_alignment(output_dir: str) -> None:
    """Run all alignment and federation generation steps."""
    ontology_dir = os.path.join(output_dir, "ontology")
    generate_alignment_ontology(ontology_dir)
    generate_federation_config(ontology_dir)
    generate_federation_queries(ontology_dir)

    total_class  = len(CLASS_ALIGNMENTS)
    total_prop   = len(PROPERTY_ALIGNMENTS)
    total_ep     = len(FEDERATION_ENDPOINTS)
    print(f"\n  ── Alignment summary ────────────────────────────────────")
    print(f"  Class alignments   : {total_class}  (DOLCE, FOAF, Schema.org, SOSA)")
    print(f"  Property alignments: {total_prop}  (foaf:, schema:, sosa:, prov:)")
    print(f"  Federation endpoints: {total_ep}  named graphs configured")
    print(f"  Federation queries : 5  example multi-domain SPARQL queries")
