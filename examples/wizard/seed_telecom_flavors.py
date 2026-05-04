"""
seed_telecom_flavors.py
───────────────────────
Seed the wizard's library with two distinct telecom-flavor ontologies so
the Library + Viewer screens have realistic content to demo.

Run with the wizard server already up:

    python3 wizard/app.py --port 5000        # in one terminal
    python3 examples/wizard/seed_telecom_flavors.py http://127.0.0.1:5000

The two saved ontologies are:
  • telecom · oss-assurance · fault-management
  • telecom · oss-charging  · usage-records
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from urllib import request as _req


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Flavor 1: Fault Management ─────────────────────────────────────────────

FAULT_MANAGEMENT = {
    "domain": {
        "name": "Telecom Fault Management",
        "description": "Alarm correlation, incident triage, and service-impact analysis "
                       "across the access, transport, and core network layers.",
        "base_iri": "https://ontology.example.com/telecom/oss-assurance/fault/",
        "industry": "telecom",
    },
    "entities": [
        {"name": "network_element",  "label": "Network Element",  "description": "A managed node (RAN, transport, or core).", "sensitivity": "Internal", "is_event": False, "properties": []},
        {"name": "alarm",            "label": "Alarm",            "description": "A fault notification from a network element.", "sensitivity": "Internal", "is_event": False, "properties": []},
        {"name": "incident",         "label": "Incident",         "description": "A correlated cluster of alarms with a common root cause.", "sensitivity": "Internal", "is_event": False, "properties": []},
        {"name": "service",          "label": "Service",          "description": "A customer-facing telecom service (broadband, voice, IoT).", "sensitivity": "Confidential", "is_event": False, "properties": []},
        {"name": "engineer",         "label": "Engineer",         "description": "Field or NOC engineer responsible for a work order.", "sensitivity": "Internal", "is_event": False, "properties": []},
    ],
    "events": [
        {"name": "alarm_raised",      "label": "Alarm Raised",      "description": "A network element emitted a new alarm."},
        {"name": "incident_opened",   "label": "Incident Opened",   "description": "Correlation produced a new incident."},
        {"name": "service_degraded",  "label": "Service Degraded",  "description": "A customer-facing service crossed an SLA threshold."},
        {"name": "incident_resolved", "label": "Incident Resolved", "description": "Root cause cleared and alarms acked."},
    ],
    "relationships": [
        {"from_entity": "alarm",    "label": "raised against", "to_entity": "network_element"},
        {"from_entity": "incident", "label": "correlates",     "to_entity": "alarm"},
        {"from_entity": "incident", "label": "impacts",        "to_entity": "service"},
        {"from_entity": "incident", "label": "assigned to",    "to_entity": "engineer"},
    ],
    "competency_questions": [
        {"id": "CQ-01", "question": "Which incidents are currently impacting Tier-1 services?",                  "priority": "High"},
        {"id": "CQ-02", "question": "Which alarms correlate into a given incident?",                            "priority": "High"},
        {"id": "CQ-03", "question": "Which network elements have produced the most alarms in the last 24 hours?", "priority": "Medium"},
        {"id": "CQ-04", "question": "Which engineer owns each open incident, and how long has it been open?",   "priority": "Medium"},
        {"id": "CQ-05", "question": "What is the mean time to repair (MTTR) by element type?",                  "priority": "Low"},
    ],
    "created_at": _now(),
    "updated_at": _now(),
}

FAULT_TTL = """\
@prefix :       <https://ontology.example.com/telecom/oss-assurance/fault/> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .

<https://ontology.example.com/telecom/oss-assurance/fault/>
    a owl:Ontology ;
    rdfs:label "Telecom Fault Management Ontology" ;
    rdfs:comment "Alarm correlation, incident triage, and service-impact analysis." .

:NetworkElement  a owl:Class ; rdfs:label "Network Element" .
:Alarm           a owl:Class ; rdfs:label "Alarm" .
:Incident        a owl:Class ; rdfs:label "Incident" .
:Service         a owl:Class ; rdfs:label "Service" .
:Engineer        a owl:Class ; rdfs:label "Engineer" .

:raisedAgainst a owl:ObjectProperty ; rdfs:domain :Alarm    ; rdfs:range :NetworkElement .
:correlates    a owl:ObjectProperty ; rdfs:domain :Incident ; rdfs:range :Alarm .
:impacts       a owl:ObjectProperty ; rdfs:domain :Incident ; rdfs:range :Service .
:assignedTo    a owl:ObjectProperty ; rdfs:domain :Incident ; rdfs:range :Engineer .
"""

FAULT_JSONLD = {
    "@context": {
        "@vocab": "https://ontology.example.com/telecom/oss-assurance/fault/",
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "NetworkElement": "https://ontology.example.com/telecom/oss-assurance/fault/NetworkElement",
        "Alarm":          "https://ontology.example.com/telecom/oss-assurance/fault/Alarm",
        "Incident":       "https://ontology.example.com/telecom/oss-assurance/fault/Incident",
        "Service":        "https://ontology.example.com/telecom/oss-assurance/fault/Service",
        "Engineer":       "https://ontology.example.com/telecom/oss-assurance/fault/Engineer",
        "raisedAgainst":  {"@id": "https://ontology.example.com/telecom/oss-assurance/fault/raisedAgainst", "@type": "@id"},
        "correlates":     {"@id": "https://ontology.example.com/telecom/oss-assurance/fault/correlates",    "@type": "@id"},
        "impacts":        {"@id": "https://ontology.example.com/telecom/oss-assurance/fault/impacts",       "@type": "@id"},
        "assignedTo":     {"@id": "https://ontology.example.com/telecom/oss-assurance/fault/assignedTo",    "@type": "@id"},
    }
}


# ── Flavor 2: Charging / Usage Records ─────────────────────────────────────

USAGE_RECORDS = {
    "domain": {
        "name": "Telecom Charging & Usage Records",
        "description": "Subscriber sessions, usage events, rating, and revenue assurance "
                       "for postpaid and prepaid telecom services.",
        "base_iri": "https://ontology.example.com/telecom/oss-charging/usage/",
        "industry": "telecom",
    },
    "entities": [
        {"name": "subscriber",     "label": "Subscriber",     "description": "An identifiable mobile or fixed-line customer.", "sensitivity": "Confidential", "is_event": False, "properties": []},
        {"name": "session",        "label": "Session",        "description": "A data, voice, or messaging session.", "sensitivity": "Confidential", "is_event": False, "properties": []},
        {"name": "usage_record",   "label": "Usage Record",   "description": "A charging-data-record (CDR) for a session or event.", "sensitivity": "Confidential", "is_event": False, "properties": []},
        {"name": "rating_plan",    "label": "Rating Plan",    "description": "The tariff applied to a usage record.", "sensitivity": "Internal", "is_event": False, "properties": []},
        {"name": "invoice",        "label": "Invoice",        "description": "A periodic bill aggregating usage records.", "sensitivity": "Confidential", "is_event": False, "properties": []},
    ],
    "events": [
        {"name": "session_started",  "label": "Session Started",  "description": "A subscriber began a chargeable session."},
        {"name": "session_ended",    "label": "Session Ended",    "description": "A session terminated; usage record emitted."},
        {"name": "rating_applied",   "label": "Rating Applied",   "description": "A usage record was priced under a rating plan."},
        {"name": "invoice_issued",   "label": "Invoice Issued",   "description": "An invoice was generated and dispatched."},
    ],
    "relationships": [
        {"from_entity": "session",      "label": "belongs to",    "to_entity": "subscriber"},
        {"from_entity": "usage_record", "label": "derived from",  "to_entity": "session"},
        {"from_entity": "usage_record", "label": "rated under",   "to_entity": "rating_plan"},
        {"from_entity": "invoice",      "label": "aggregates",    "to_entity": "usage_record"},
    ],
    "competency_questions": [
        {"id": "CQ-01", "question": "Which usage records contributed to a subscriber's last invoice?",        "priority": "High"},
        {"id": "CQ-02", "question": "Which sessions were rated under a deprecated rating plan in the last 7 days?", "priority": "High"},
        {"id": "CQ-03", "question": "What is the average usage per subscriber by service type?",              "priority": "Medium"},
        {"id": "CQ-04", "question": "Which usage records have no matching session (revenue leakage)?",        "priority": "High"},
        {"id": "CQ-05", "question": "Which rating plans have changed since the start of the billing cycle?",  "priority": "Low"},
    ],
    "created_at": _now(),
    "updated_at": _now(),
}

USAGE_TTL = """\
@prefix :       <https://ontology.example.com/telecom/oss-charging/usage/> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .

<https://ontology.example.com/telecom/oss-charging/usage/>
    a owl:Ontology ;
    rdfs:label "Telecom Charging & Usage Records Ontology" ;
    rdfs:comment "Subscriber sessions, usage events, rating, and invoicing." .

:Subscriber   a owl:Class ; rdfs:label "Subscriber" .
:Session      a owl:Class ; rdfs:label "Session" .
:UsageRecord  a owl:Class ; rdfs:label "Usage Record" .
:RatingPlan   a owl:Class ; rdfs:label "Rating Plan" .
:Invoice      a owl:Class ; rdfs:label "Invoice" .

:belongsTo    a owl:ObjectProperty ; rdfs:domain :Session     ; rdfs:range :Subscriber .
:derivedFrom  a owl:ObjectProperty ; rdfs:domain :UsageRecord ; rdfs:range :Session .
:ratedUnder   a owl:ObjectProperty ; rdfs:domain :UsageRecord ; rdfs:range :RatingPlan .
:aggregates   a owl:ObjectProperty ; rdfs:domain :Invoice     ; rdfs:range :UsageRecord .
"""

USAGE_JSONLD = {
    "@context": {
        "@vocab": "https://ontology.example.com/telecom/oss-charging/usage/",
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "Subscriber":  "https://ontology.example.com/telecom/oss-charging/usage/Subscriber",
        "Session":     "https://ontology.example.com/telecom/oss-charging/usage/Session",
        "UsageRecord": "https://ontology.example.com/telecom/oss-charging/usage/UsageRecord",
        "RatingPlan":  "https://ontology.example.com/telecom/oss-charging/usage/RatingPlan",
        "Invoice":     "https://ontology.example.com/telecom/oss-charging/usage/Invoice",
        "belongsTo":   {"@id": "https://ontology.example.com/telecom/oss-charging/usage/belongsTo",   "@type": "@id"},
        "derivedFrom": {"@id": "https://ontology.example.com/telecom/oss-charging/usage/derivedFrom", "@type": "@id"},
        "ratedUnder":  {"@id": "https://ontology.example.com/telecom/oss-charging/usage/ratedUnder",  "@type": "@id"},
        "aggregates":  {"@id": "https://ontology.example.com/telecom/oss-charging/usage/aggregates",  "@type": "@id"},
    }
}


# ── HTTP helpers ───────────────────────────────────────────────────────────

def _post(base_url: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = _req.Request(base_url.rstrip("/") + path, data=body,
                       headers={"Content-Type": "application/json"},
                       method="POST")
    try:
        with _req.urlopen(req) as resp:
            return json.loads(resp.read().decode() or "{}")
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
    print(f"Seeding two telecom flavors into {base} …")

    flavors = [
        {
            "domain":  "telecom",
            "product": "oss-assurance",
            "label":   "fault-management",
            "session": FAULT_MANAGEMENT,
            "generated": {
                "ttl":    FAULT_TTL,
                "jsonld": json.dumps(FAULT_JSONLD, indent=2),
            },
            "overwrite": True,
        },
        {
            "domain":  "telecom",
            "product": "oss-charging",
            "label":   "usage-records",
            "session": USAGE_RECORDS,
            "generated": {
                "ttl":    USAGE_TTL,
                "jsonld": json.dumps(USAGE_JSONLD, indent=2),
            },
            "overwrite": True,
        },
    ]

    for f in flavors:
        result = _post(base, "/api/ontologies", f)
        slug   = f"{f['domain']}__{f['product']}__{f['label']}"
        if "error" in result:
            print(f"  ✗ {slug}: {result['error']}")
        else:
            print(f"  ✓ {slug}  ({'created' if result.get('created') else 'updated'})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
