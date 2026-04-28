"""Question bank for the 5G-NF first-contact demo.

Each question is anchored to a real-world 5G semantic issue documented in a
3GPP / GSMA / O-RAN specification. See test-plan-5g.md §1 for the R-table that
maps each question to its authoritative reference.
"""

QUESTIONS = [
    {
        "id": "Q1",
        "text": "Which Network Functions are currently active?",
        "why": "'active' is valid on 5 tables (nf_instance.nf_status, nf_service.service_status, ue_registration.registration_state, pdu_session.session_status, alarm.state, slice_instance.operational_state). Baseline guesses which one; grounded answer names the OWL class.",
        "reference": "3GPP TS 29.510 §6.1.6.2.3",
        "tables_for_baseline": ["nf_instance", "nf_service", "ue_registration", "pdu_session", "alarm"],
    },
    {
        "id": "Q2",
        "text": "List all PDU sessions on slice S-NSSAI (SST=1, SD=000001) and the UPFs that serve them.",
        "why": "S-NSSAI is a composite identifier (SST + SD per TS 23.003 §28.4). Baseline returns fragmented columns; grounded answer presents one IRI and a typed UPF reference.",
        "reference": "3GPP TS 23.003 §28.4.2",
        "tables_for_baseline": ["pdu_session", "slice_instance", "nf_instance"],
    },
    {
        "id": "Q3",
        "text": "Which UEs failed to reach REGISTERED state, or were deregistered in the last 24 hours?",
        "why": "Baseline reads registration_state snapshot. Grounded answer reads NFLifecycleEvent + UERegistrationContext events and returns events (not snapshots).",
        "reference": "3GPP TS 29.518 §5.2.2",
        "tables_for_baseline": ["ue_registration", "nf_event"],
    },
    {
        "id": "Q4",
        "text": "Are there any suspended NFs that still have active PDU sessions?",
        "why": "State-machine intersection across nf_instance (SUSPENDED) and pdu_session (ACTIVE). Baseline often misses because 'suspended' and 'active' look like opposite states.",
        "reference": "3GPP TS 29.510 §5.3",
        "tables_for_baseline": ["nf_instance", "pdu_session"],
    },
    {
        "id": "Q5",
        "text": "Trace the full chain from SUPI to UPF for PDU session 7.",
        "why": "FK→object-property traversal (UE → AMF → SMF → UPF); grounded returns stable IRIs + SUPI is redacted per sensitivity tier.",
        "reference": "3GPP TS 23.501 §4.3",
        "tables_for_baseline": ["pdu_session", "ue_registration", "nf_instance"],
    },
    {
        "id": "Q6",
        "text": "Which NF deregistrations were heartbeat-inferred rather than explicitly requested?",
        "why": "Requires PROV-O derivation vocabulary (MEASURED vs INFERRED). Baseline has no column-name for this distinction.",
        "reference": "3GPP TS 29.510 §5.2.2.3–4",
        "tables_for_baseline": ["nf_event"],
    },
    {
        "id": "Q7",
        "text": "Which active eMBB slices are missing or violating their latency SLA?",
        "why": "Needs SST↔slice-type SKOS mapping (SST=1 ↔ eMBB) + GSMA NG.116 SLA semantics. Baseline has no vocabulary binding.",
        "reference": "GSMA NG.116 + 3GPP TS 23.501 Table 5.15.2.2-1",
        "tables_for_baseline": ["slice_instance", "pdu_session"],
    },
    {
        "id": "Q8",
        "text": "Summarise NF amf-01's current health in one sentence.",
        "why": "Free-form; tests whether grounded output remains SHACL-valid while reading naturally (with PM counters disambiguated by NR vs LTE).",
        "reference": "3GPP TS 28.552; TS 28.532",
        "tables_for_baseline": ["nf_instance", "nf_service", "alarm", "pm_counter", "ue_registration"],
    },
]
