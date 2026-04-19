"""
jsonld_generator.py — Phase 5
───────────────────────────────
Generates:
  output/jsonld/enterprise-context.json   — canonical JSON-LD context
  output/jsonld/observation-payload.json  — sample agent payload
  output/vocab/enterprise-skos.ttl        — SKOS terminology scheme
"""

import os
import json
from typing import List
from db_introspector import (
    DBIntrospector, TableModel,
    BASE_IRI, VOCAB_IRI, snake_to_camel, snake_to_lower_camel
)

XSD = "http://www.w3.org/2001/XMLSchema#"
PROV = "http://www.w3.org/ns/prov#"
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
OWL_NS  = "http://www.w3.org/2002/07/owl#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"


# ── JSON-LD Context ──────────────────────────────────────────────────────

def _build_context(tables: List[TableModel]) -> dict:
    ctx = {
        "@vocab":   BASE_IRI,
        "xsd":      XSD,
        "prov":     PROV,
        "skos":     SKOS_NS,
        "owl":      OWL_NS,
        "rdfs":     RDFS_NS,
        # PROV-O shorthand aliases for agent payloads
        "generatedBy":   {"@id": "prov:wasGeneratedBy",    "@type": "@id"},
        "generatedAt":   {"@id": "prov:generatedAtTime",   "@type": "xsd:dateTime"},
        "startedAt":     {"@id": "prov:startedAtTime",     "@type": "xsd:dateTime"},
        "endedAt":       {"@id": "prov:endedAtTime",       "@type": "xsd:dateTime"},
        "wasAssociatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
        "derivedFrom":   {"@id": "prov:wasDerivedFrom",    "@type": "@id"},
        # Sensitivity annotation
        "sensitivityTier": {"@id": f"{BASE_IRI}sensitivityTier", "@type": "@id"},
        # Core cross-domain properties
        "confidence":    {"@id": f"{BASE_IRI}hasConfidenceScore", "@type": "xsd:decimal"},
        "derivedBy":     {"@id": f"{BASE_IRI}derivationMethod",   "@type": "xsd:string"},
        "sourceRef":     {"@id": f"{BASE_IRI}sourceRef",          "@type": "xsd:anyURI"},
        "agentIri":      {"@id": f"{BASE_IRI}hasAgentIri",        "@type": "xsd:anyURI"},
        "observedAsset": {"@id": f"{BASE_IRI}refersToAsset",      "@type": "@id"},
        "participant":   {"@id": f"{BASE_IRI}hasParticipant",     "@type": "@id"},
        "governedBy":    {"@id": f"{BASE_IRI}governedBy",         "@type": "@id"},
    }

    # Add class term definitions
    for t in tables:
        ctx[t.class_name] = {"@id": f"{BASE_IRI}{t.class_name}"}

    # Add data property shorthand aliases for key columns
    for t in tables:
        for col in t.data_properties:
            prop_name = f"has{snake_to_camel(col.name)}"
            alias = snake_to_lower_camel(col.name)
            if alias not in ctx:
                ctx[alias] = {
                    "@id": f"{BASE_IRI}{prop_name}",
                    "@type": col.effective_xsd_type.replace("xsd:", XSD),
                }

    return {"@context": ctx}


def _sample_observation_payload() -> dict:
    """Concrete example of a PROV-O-aligned agent observation payload."""
    return {
        "@context": f"{BASE_IRI}jsonld/enterprise-context.json",
        "@type": "ObservationRecord",
        "@id": "https://gtc.example.com/obs/obs-001",
        "observationType": "PACKET_LOSS_RATE",
        "numericValue": 18.7,
        "unitOfMeasure": "percent",
        "confidence": 0.98,
        "derivedBy": "MEASURED",
        "sourceRef": "https://oss.gtc.example.com/metrics/ran043",
        "observedAsset": {
            "@type": "Asset",
            "@id": "https://gtc.example.com/assets/NE-RAN-043",
            "name": "gNB Site 043",
            "sensitivityTier": f"{BASE_IRI}Internal"
        },
        "generatedBy": {
            "@type": ["Agent", "prov:Activity"],
            "@id": "https://gtc.example.com/events/measure-activity-obs-001",
            "wasAssociatedWith": {
                "@type": "Agent",
                "@id": "https://gtc.example.com/agents/ml-monitor-agent",
                "name": "ML Monitor Agent",
                "agentType": "AI_AGENT",
                "agentIri": "https://gtc.example.com/agents/ml-monitor-agent",
                "credentialExpiry": "2026-12-31T23:59:59Z",
                "sensitivityTier": f"{BASE_IRI}Internal"
            }
        },
        "generatedAt": "2026-04-10T02:14:00Z",
        "sensitivityTier": f"{BASE_IRI}Confidential",
        "_validation": {
            "shacl_gate": "enterprise-shapes.ttl#ObservationAcceptanceGate",
            "status": "PASS",
            "validated_at": "2026-04-10T02:14:01Z"
        }
    }


def _sample_event_payload() -> dict:
    """Concrete example of an agent-produced domain event payload."""
    return {
        "@context": f"{BASE_IRI}jsonld/enterprise-context.json",
        "@type": ["DomainEvent", "IncidentEvent"],
        "@id": "https://gtc.example.com/events/evt-001",
        "title": "High packet loss on gNB 043",
        "eventType": "INCIDENT",
        "status": "COMPLETED",
        "outcome": "RESOLVED",
        "observedAsset": {
            "@type": "Asset",
            "@id": "https://gtc.example.com/assets/NE-RAN-043"
        },
        "participant": [
            {
                "@type": "Agent",
                "@id": "https://gtc.example.com/agents/noc-engineer-01",
                "participationRole": "INITIATOR"
            },
            {
                "@type": "Agent",
                "@id": "https://gtc.example.com/agents/ml-monitor-agent",
                "participationRole": "OBSERVER"
            }
        ],
        "governedBy": {
            "@type": "Policy",
            "@id": "https://gtc.example.com/policies/OPS-INC-RTO-4H",
            "code": "OPS-INC-RTO-4H"
        },
        "startedAt": "2026-04-10T02:15:00Z",
        "endedAt":   "2026-04-10T05:44:00Z",
        "sensitivityTier": f"{BASE_IRI}Internal",
        "_validation": {
            "shacl_gate": "enterprise-shapes.ttl#DomainEventCompletenessShape",
            "status": "PASS"
        }
    }


# ── SKOS Vocabulary ──────────────────────────────────────────────────────

SKOS_PREFIXES = f"""\
@prefix :     <{BASE_IRI}> .
@prefix skos: <{SKOS_NS}> .
@prefix owl:  <{OWL_NS}> .
@prefix rdfs: <{RDFS_NS}> .
@prefix dcterms: <http://purl.org/dc/terms/> .
"""


def _skos_scheme_header() -> str:
    return f"""\
<{VOCAB_IRI}>
  a skos:ConceptScheme ;
  skos:prefLabel "Enterprise Domain Vocabulary" ;
  rdfs:comment "Controlled vocabulary for the enterprise domain ontology. "
               "Covers preferred labels, synonyms, and deprecated terms." ;
  dcterms:creator "Ontology Toolkit — Auto-generated from ontology_metadata" .

"""


def _skos_concept(t: TableModel) -> str:
    pref = t.skos_pref_label or t.effective_label
    alts = t.skos_alt_labels
    desc = t.description or f"Vocabulary concept for {t.effective_label}."

    lines = [
        f":{t.class_name}Concept",
        f"  a skos:Concept ;",
        f'  skos:prefLabel "{pref}" ;',
    ]
    for alt in alts:
        lines.append(f'  skos:altLabel "{alt}" ;')
    lines.append(f'  skos:definition "{desc}" ;')
    lines.append(f"  skos:inScheme <{VOCAB_IRI}> ;")
    lines.append(f"  skos:exactMatch :{t.class_name} .")
    return "\n".join(lines) + "\n"


def _status_values_concept(tables: List[TableModel], intro: DBIntrospector) -> str:
    """Generate SKOS concept for status/type enumeration values."""
    lines = ["\n# ── Status and Type Enumerations ───────────────────────────────────\n"]
    for t in tables:
        for col in t.data_properties:
            if col.name in ("status", "event_type", "agent_type", "policy_type",
                            "outcome", "derivation_method", "participation_role"):
                vals = intro.get_distinct_values(t.name, col.name)
                if not vals:
                    continue
                scheme_id = f":{t.class_name}{snake_to_camel(col.name)}Scheme"
                lines.append(f"{scheme_id}")
                lines.append(f"  a skos:ConceptScheme ;")
                lines.append(f'  skos:prefLabel "{t.effective_label} {col.effective_label} Values" ;')
                lines.append(f"  skos:inScheme <{VOCAB_IRI}> .\n")
                for val in vals:
                    label = val.replace("_", " ").title()
                    concept_id = f":{t.class_name}{snake_to_camel(col.name)}{snake_to_camel(val.lower())}"
                    lines.append(f"{concept_id}")
                    lines.append(f"  a skos:Concept ;")
                    lines.append(f'  skos:prefLabel "{label}" ;')
                    lines.append(f'  skos:notation "{val}" ;')
                    lines.append(f"  skos:inScheme {scheme_id} .")
                lines.append("")
    return "\n".join(lines)


# ── MCP Tool Definition ──────────────────────────────────────────────────

def _mcp_tool_definitions() -> list:
    """Generate MCP tool definitions with semantic bindings."""
    return [
        {
            "name": "record_observation",
            "description": "Records a sensor or agent observation against an asset with full PROV-O provenance.",
            "x-semantic-context": f"{BASE_IRI}jsonld/enterprise-context.json",
            "x-shacl-gate": f"{BASE_IRI}shapes/agent-gate.ttl#ObservationAcceptanceGate",
            "x-ontology-class": f"{BASE_IRI}ObservationRecord",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "asset_id":        {"type": "string", "description": "IRI of the target asset"},
                    "observation_type":{"type": "string"},
                    "numeric_value":   {"type": "number"},
                    "unit":            {"type": "string"},
                    "confidence":      {"type": "number", "minimum": 0, "maximum": 1},
                    "derivation":      {"type": "string", "enum": ["MEASURED","INFERRED","IMPORTED","SYNTHESIZED"]},
                    "source_ref":      {"type": "string", "format": "uri"},
                    "observed_at":     {"type": "string", "format": "date-time"},
                    "agent_iri":       {"type": "string", "format": "uri"},
                },
                "required": ["asset_id", "observation_type", "confidence", "derivation", "observed_at", "agent_iri"]
            }
        },
        {
            "name": "create_domain_event",
            "description": "Creates a domain event (incident, maintenance, inspection, audit) with participant and policy linkage.",
            "x-semantic-context": f"{BASE_IRI}jsonld/enterprise-context.json",
            "x-shacl-gate": f"{BASE_IRI}shapes/enterprise-shapes.ttl#DomainEventCompletenessShape",
            "x-ontology-class": f"{BASE_IRI}DomainEvent",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_type":   {"type": "string", "enum": ["INCIDENT","MAINTENANCE","INSPECTION","COMPLIANCE_AUDIT","CHANGE"]},
                    "title":        {"type": "string"},
                    "asset_id":     {"type": "string"},
                    "initiated_by": {"type": "string", "description": "Agent IRI"},
                    "policy_id":    {"type": "string"},
                    "started_at":   {"type": "string", "format": "date-time"},
                },
                "required": ["event_type", "title", "asset_id", "initiated_by", "started_at"]
            }
        },
        {
            "name": "validate_payload",
            "description": "Validates a JSON-LD payload against the enterprise SHACL shapes before any action.",
            "x-semantic-context": f"{BASE_IRI}jsonld/enterprise-context.json",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "payload":     {"type": "object", "description": "JSON-LD payload to validate"},
                    "shape_class": {"type": "string", "description": "Target SHACL shape name"},
                },
                "required": ["payload"]
            }
        }
    ]


# ── Main ─────────────────────────────────────────────────────────────────

def generate_jsonld(intro: DBIntrospector, output_dir: str, vocab_dir: str):
    tables = intro.introspect_all()
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(vocab_dir, exist_ok=True)

    # Context
    context = _build_context(tables)
    ctx_path = os.path.join(output_dir, "enterprise-context.json")
    with open(ctx_path, "w") as f:
        json.dump(context, f, indent=2)
    print(f"  ✓ JSON-LD context       → {ctx_path}")
    print(f"    Terms defined: {len(context['@context'])}")

    # Sample observation payload
    obs = _sample_observation_payload()
    obs_path = os.path.join(output_dir, "sample-observation-payload.json")
    with open(obs_path, "w") as f:
        json.dump(obs, f, indent=2)
    print(f"  ✓ Sample obs payload    → {obs_path}")

    # Sample event payload
    evt = _sample_event_payload()
    evt_path = os.path.join(output_dir, "sample-event-payload.json")
    with open(evt_path, "w") as f:
        json.dump(evt, f, indent=2)
    print(f"  ✓ Sample event payload  → {evt_path}")

    # MCP tool definitions
    tools = _mcp_tool_definitions()
    tools_path = os.path.join(output_dir, "mcp-tool-definitions.json")
    with open(tools_path, "w") as f:
        json.dump({"mcp_tools": tools}, f, indent=2)
    print(f"  ✓ MCP tool definitions  → {tools_path}")

    # SKOS vocabulary
    skos_lines = [
        SKOS_PREFIXES, "\n",
        _skos_scheme_header(),
        "# ── Concept per Domain Class ────────────────────────────────────────\n",
    ]
    for t in tables:
        skos_lines.append(_skos_concept(t))
    skos_lines.append(_status_values_concept(tables, intro))

    skos_path = os.path.join(vocab_dir, "enterprise-skos.ttl")
    with open(skos_path, "w") as f:
        f.write("\n".join(skos_lines))
    print(f"  ✓ SKOS vocabulary       → {skos_path}")
