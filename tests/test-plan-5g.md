# Demo Test Plan — Ontology vs No-Ontology LLM Output (5G Network Functions)

**Purpose.** Demonstrate, side-by-side, the difference in answer quality, semantic precision, and auditability when an LLM is asked the same question over a 5G core/RAN Network-Function (NF) inventory (a) directly over raw SQLite rows and (b) through the toolkit's runtime layer with a generated OWL ontology, SHACL shapes, JSON-LD grounding, and PROV-O output stamping.

**Companion to** [test-plan.md](test-plan.md) (retail domain). Same pipeline, different domain — chosen because 5G NF semantics are standardised (3GPP, O-RAN, GSMA) yet still cause real interop pain, so the ontology delta is measurable against an external ground truth rather than our own opinion.

**Audience.** Telco architects, OSS/BSS leads, SMO/RIC teams, NF vendor integration engineers.

**Models under test.** Anthropic `claude-sonnet-4-5` · OpenAI `gpt-4o`. Same prompt, same data, same question in every row of the comparison matrix.

---

## 1. Why this domain — documented real-world semantic issues

5G is a rare case where we can point at public specifications and say "this exact ambiguity is known to bite operators." Each question in §6 is tied to one of these:

| # | Real-world issue | Authoritative reference |
|---|---|---|
| R1 | `status` is overloaded across layers: NF-level `nfStatus` (REGISTERED / SUSPENDED / UNDISCOVERABLE) vs service-level `nfServiceStatus` vs UE-level `registrationState` (REGISTERED / DEREGISTERED) vs `connectionState` (IDLE / CONNECTED) vs PDU-session `sessionStatus` (ACTIVE / INACTIVE / RELEASED) vs alarm `state` (ACTIVE / CLEARED). Operators routinely ask "is this NF active?" and mean any of six things. | 3GPP TS 29.510 §6.1.6.2.3 (NFStatus); TS 29.518 §5.2.2 (AMF registration context); TS 23.502 §4.3 (PDU session states); TS 28.532 (alarm lifecycle) |
| R2 | `S-NSSAI` is a composite identifier: 8-bit `SST` + optional 24-bit `SD`. Vendors variously store it as one string (`"1-000001"`), two columns, or a packed integer — joining slice inventory across two systems without a shared IRI is a known OSS pain. | 3GPP TS 23.003 §28.4.2; TS 23.501 §5.15.2 |
| R3 | **State-vs-event conflation.** NGAP/Namf procedures (`Registration`, `Deregistration`, `Handover`, `PDU Session Establishment`) are events, but management northbound APIs often expose only the *current* state. A query like "which UEs failed to register?" has no answer from `registrationState` alone — you need the event log. | 3GPP TS 29.518 §5.2; TS 38.413 §8.2 (NGAP Initial UE Message) |
| R4 | **Heartbeat-inferred deregistration.** An NF can leave the NRF two ways: (a) explicit `Nnrf_NFManagement_NFDeregister`, or (b) NRF-side timeout after N missed heartbeats. Same observable end-state; different root cause. Incident post-mortems need to distinguish them. | 3GPP TS 29.510 §5.2.2.3 (heartbeat), §5.2.2.4 (deregister) |
| R5 | **PM counter namespace collision.** `RRC.ConnEstabAtt` exists in both LTE (TS 32.425) and NR (TS 28.552) with different counting rules. An "RRC connection attempts" question against a mixed 4G/5G PM table is under-specified without the NR vs LTE class. | 3GPP TS 28.552 §5.1.1.5 (NR); TS 32.425 §4.1.1.1 (LTE) |
| R6 | **Slice type vocabulary.** `SST=1` ↔ `eMBB`, `SST=2` ↔ `URLLC`, `SST=3` ↔ `mIoT`, `SST=4` ↔ `V2X`. Operators mix the numeric code and the string freely. Slice SLA templates are defined against the string. | 3GPP TS 23.501 Table 5.15.2.2-1; GSMA NG.116 "Generic Slice Template" |
| R7 | **Vendor naming divergence on the O1 interface.** O-RAN `O1-NETCONF` YANG attribute names differ from 3GPP NRM attribute names for the same concept (e.g. `administrativeState` vs `adminState`). Multi-vendor SMOs normalise in code that nobody wants to maintain. | O-RAN.WG10.O1-Interface.0-v07.00; 3GPP TS 28.541 §4.3.4 |
| R8 | **Implicit actor on NF-lifecycle events.** NF events in OSS often log *what* happened (`SUSPENDED`, `PROFILE_UPDATED`) with no FK to *who/what* caused it (operator, fault manager, NRF heartbeat monitor, CI/CD pipeline). The toolkit's `IMPLICIT_ACTOR` finding is designed exactly for this. | TS 28.532 §6.3 (alarm causation); O-RAN.WG10 Fault-Management |

If any of these references moves or expires (3GPP specs do get re-numbered across releases), the test plan's scope still holds — the issues themselves are stable and reproducible across Open5GS, free5GC, ONAP AAI, and every commercial 5GC vendor we've worked with.

---

## 2. Scope

**In scope**

- A small 5G-NF SQLite schema (8 tables, ~80 rows of seed data) modelled on 3GPP TS 28.541 (5G NRM) and TS 29.510 (NRF profile), simplified to one database file.
- Toolkit pipeline end-to-end: Phases 1–5 + TMF-skip + test + report.
- Two runtime configurations per question: **Baseline** (raw rows + plain prompt) and **Ontology-grounded** (`RuntimeClient.ask(flavor="fiveg")`).
- Two vendors (Anthropic, OpenAI).

**Out of scope**

- Live NF integration (no NETCONF/YANG pull, no SBI calls) — the seed data is hand-authored to mirror spec examples.
- Cross-enterprise federation, vector retrieval (covered by Gen-2 workstreams; see [docs/advanced.md](../docs/advanced.md)).
- LTE / 4G. Schema is NR/5GC only, though R5 is tested with one deliberately mis-typed counter.

---

## 3. Success criteria

Same table as [test-plan.md §2](test-plan.md) — answer references correct OWL class, stable IRIs, SHACL-valid, PROV-O stamped, stored as `ObservationRecord`, ambiguity deterministically resolved. At least **4 of 8** questions must produce materially different answers between baseline and grounded modes (raised from 3/8 in the retail plan because the 5G vocabulary collisions are sharper).

Additional 5G-specific pass criteria:

- Q2 grounded output must present S-NSSAI as a single IRI (e.g. `fiveg:snssai/1-000001`) regardless of how columns are stored.
- Q6 grounded output must cite PROV-O `derivation=INFERRED` for heartbeat-timeout deregistrations and `derivation=MEASURED` for explicit NFDeregister calls.
- Q7 grounded output must resolve `SST=1` ↔ `eMBB` through the generated SKOS vocabulary, not LLM priors.

---

## 4. Test environment

Identical to [test-plan.md §3](test-plan.md). Branch `first-contact`, Python 3.10+, SQLite 3, `pip install anthropic openai`. Output dir `output/demo-5g/` (distinct from the retail demo so they can coexist).

---

## 5. 5G-NF demo schema

Eight tables. Modelled on 3GPP `NFProfile` (TS 29.510), `SubscriberData` / UE registration context (TS 29.518), PDU Session (TS 23.502), Slice Instance (TS 28.541), PM counter record (TS 28.552), and fault alarm (TS 28.532). Shortened to the columns that carry the semantic weight.

```
nf_instance ─── nf_service
     │
     ├─ ue_registration       (AMF-owned)
     ├─ pdu_session ─── slice_instance   (SMF-owned, slice via S-NSSAI)
     ├─ pm_counter
     ├─ alarm
     └─ nf_event              (lifecycle transitions — PROV-O rich)
```

### 5.1 DDL — `db/demo_5g.sql`

```sql
-- System tables required by the toolkit (same as db/schema.sql)
CREATE TABLE ontology_metadata (...);
CREATE TABLE semantic_loss_log (...);

-- 3GPP TS 29.510 §6.1.6.2 NFProfile (simplified)
CREATE TABLE nf_instance (
    id              INTEGER PRIMARY KEY,
    nf_instance_id  TEXT NOT NULL UNIQUE,      -- UUID per NF
    nf_type         TEXT CHECK (nf_type IN
        ('AMF','SMF','UPF','PCF','UDM','AUSF','NRF','NSSF','NEF','SMSF','UDR')) NOT NULL,
    nf_status       TEXT CHECK (nf_status IN
        ('REGISTERED','SUSPENDED','UNDISCOVERABLE')) NOT NULL,  -- TS 29.510 §6.1.6.2.3
    fqdn            TEXT NOT NULL,
    plmn_mcc        TEXT NOT NULL,
    plmn_mnc        TEXT NOT NULL,
    heartbeat_timer INTEGER NOT NULL,          -- seconds
    last_heartbeat  TEXT,
    created_at      TEXT NOT NULL
);

-- TS 29.510 §6.1.6.2.4 NFService
CREATE TABLE nf_service (
    id                 INTEGER PRIMARY KEY,
    nf_instance_id     INTEGER NOT NULL REFERENCES nf_instance(id),
    service_name       TEXT NOT NULL,          -- e.g. Namf_Communication
    service_status     TEXT CHECK (service_status IN
        ('REGISTERED','SUSPENDED')) NOT NULL,
    api_version        TEXT NOT NULL,          -- e.g. v1
    scheme             TEXT CHECK (scheme IN ('http','https')) NOT NULL
);

-- TS 29.518 §5.2.2 UE Registration Context (AMF-owned, one per SUPI)
CREATE TABLE ue_registration (
    id                 INTEGER PRIMARY KEY,
    supi               TEXT NOT NULL,          -- imsi-<15-digit>
    amf_instance_id    INTEGER NOT NULL REFERENCES nf_instance(id),
    registration_state TEXT CHECK (registration_state IN
        ('REGISTERED','DEREGISTERED')) NOT NULL,
    connection_state   TEXT CHECK (connection_state IN
        ('IDLE','CONNECTED')) NOT NULL,
    plmn_mcc           TEXT NOT NULL,
    plmn_mnc           TEXT NOT NULL,
    registered_at      TEXT NOT NULL,
    last_activity_at   TEXT
);

-- TS 23.502 §4.3 / TS 29.502 PDU Session
CREATE TABLE pdu_session (
    id                 INTEGER PRIMARY KEY,
    pdu_session_id     INTEGER NOT NULL,       -- 1..15 per UE
    supi               TEXT NOT NULL,
    smf_instance_id    INTEGER NOT NULL REFERENCES nf_instance(id),
    upf_instance_id    INTEGER NOT NULL REFERENCES nf_instance(id),
    snssai_sst         INTEGER NOT NULL,       -- 1=eMBB 2=URLLC 3=mIoT 4=V2X (TS 23.501 T.5.15.2.2-1)
    snssai_sd          TEXT,                   -- 6 hex digits or NULL
    dnn                TEXT NOT NULL,          -- Data Network Name
    session_status     TEXT CHECK (session_status IN
        ('ACTIVE','INACTIVE','RELEASED')) NOT NULL,
    established_at     TEXT NOT NULL
);

-- TS 28.541 Slice Profile / NSSI
CREATE TABLE slice_instance (
    id                 INTEGER PRIMARY KEY,
    nssi_id            TEXT NOT NULL UNIQUE,
    sst                INTEGER NOT NULL,
    sd                 TEXT,
    slice_type_label   TEXT,                   -- free-text: "eMBB","URLLC",... — OVERLOADED_TYPE finding
    sla_latency_ms     INTEGER,                -- GSMA NG.116 "maxEndToEndLatency"
    sla_avail_pct      REAL,                   -- GSMA NG.116 "serviceAvailability"
    operational_state  TEXT CHECK (operational_state IN ('ENABLED','DISABLED')) NOT NULL
);

-- TS 28.552 PM counter record
CREATE TABLE pm_counter (
    id                 INTEGER PRIMARY KEY,
    nf_instance_id     INTEGER NOT NULL REFERENCES nf_instance(id),
    counter_name       TEXT NOT NULL,          -- e.g. RRC.ConnEstabAtt, SM.PduSessionCreationReq
    technology         TEXT CHECK (technology IN ('NR','LTE')) NOT NULL,  -- disambiguates R5
    value              REAL NOT NULL,
    granularity_sec    INTEGER NOT NULL,       -- 60,300,900
    collected_at       TEXT NOT NULL
);

-- TS 28.532 §6.3 Alarm
CREATE TABLE alarm (
    id                 INTEGER PRIMARY KEY,
    nf_instance_id     INTEGER NOT NULL REFERENCES nf_instance(id),
    alarm_type         TEXT NOT NULL,          -- e.g. NRF_HEARTBEAT_TIMEOUT
    perceived_severity TEXT CHECK (perceived_severity IN
        ('CRITICAL','MAJOR','MINOR','WARNING','INDETERMINATE')) NOT NULL,
    state              TEXT CHECK (state IN ('ACTIVE','CLEARED')) NOT NULL,
    raised_at          TEXT NOT NULL,
    cleared_at         TEXT
);

-- Event table — drives PROV-O + STATUS_AS_EVENT + IMPLICIT_ACTOR findings
CREATE TABLE nf_event (
    id             INTEGER PRIMARY KEY,
    nf_instance_id INTEGER NOT NULL REFERENCES nf_instance(id),
    event_type     TEXT CHECK (event_type IN
        ('REGISTERED','DEREGISTERED','HEARTBEAT_FAILED','SUSPENDED',
         'PROFILE_UPDATED','SERVICE_STARTED','SERVICE_STOPPED')) NOT NULL,
    occurred_at    TEXT NOT NULL,
    actor_party    TEXT,                       -- free-text: "nf","nrf-monitor","operator","cicd" → IMPLICIT_ACTOR
    confidence     REAL CHECK (confidence BETWEEN 0.0 AND 1.0),
    derivation     TEXT CHECK (derivation IN ('MEASURED','INFERRED','IMPORTED','SYNTHESIZED'))
);
```

### 5.2 Seed — `db/demo_5g_seed.sql`

~80 rows: 12 NF instances (one AMF, two SMFs, three UPFs, one each of PCF/UDM/AUSF/NRF/NSSF, one SUSPENDED UDM), 18 `nf_service` entries, 10 UE registrations (mixed REGISTERED/DEREGISTERED, 2 CONNECTED 8 IDLE, including one UE that registered-then-deregistered within 60 s), 12 PDU sessions across 4 slices (SST 1/2/3/4), 4 `slice_instance` rows (one URLLC slice with `sla_latency_ms=5`, one eMBB slice with a NULL SLA), 15 PM counters (including **one LTE row with `counter_name='RRC.ConnEstabAtt'` deliberately co-mingled** — exercises R5), 6 alarms (one ACTIVE `NRF_HEARTBEAT_TIMEOUT` on the SUSPENDED UDM), and 15 `nf_event` rows. Of the event rows, two are DEREGISTERED with `derivation=INFERRED` + `actor_party='nrf-monitor'` + `confidence=0.78` (heartbeat timeout) and two are DEREGISTERED with `derivation=MEASURED` + `actor_party='nf'` (explicit NFDeregister) — Q6 hinges on this pair.

### 5.3 Ontology metadata seed

Annotate every table + every key column in `ontology_metadata`:

| target | table | column | semantic_type | sensitivity | notes |
|---|---|---|---|---|---|
| TABLE | nf_instance | — | NetworkFunction | Confidential | NRF profile (TS 29.510) |
| TABLE | nf_service | — | NFService | Confidential | |
| TABLE | ue_registration | — | UERegistrationContext | Restricted | SUPI is PII |
| TABLE | pdu_session | — | PDUSession | Confidential | |
| TABLE | slice_instance | — | NetworkSliceInstance | Internal | TS 28.541 |
| TABLE | pm_counter | — | PMCounter | Internal | TS 28.552 |
| TABLE | alarm | — | Alarm | Internal | TS 28.532 |
| TABLE | nf_event | — | NFLifecycleEvent | Internal | `is_event_class=1` |
| COLUMN | nf_event | event_type | event discriminator | — | triggers OWL subclass generation |
| COLUMN | nf_event | confidence | xsd:decimal | — | PROV-O confidence |
| COLUMN | nf_event | derivation | xsd:string | — | MEASURED/INFERRED/IMPORTED/SYNTHESIZED |
| COLUMN | pdu_session | snssai_sst | S-NSSAI.sst | — | composite with snssai_sd — R2 |
| COLUMN | pdu_session | snssai_sd | S-NSSAI.sd | — | composite with snssai_sst — R2 |
| COLUMN | slice_instance | slice_type_label | SKOS concept | — | map to eMBB/URLLC/mIoT/V2X — R6 |
| COLUMN | pm_counter | technology | xsd:string | — | NR/LTE disambiguator — R5 |
| COLUMN | ue_registration | supi | PII | PII-Direct | |

---

## 6. Question bank

Each question is paired with the real-world issue (R-ref) it is designed to expose.

| # | Question | Exposes | Reference |
|---|---|---|---|
| Q1 | *"Which NFs are currently active?"* | R1 — `status` overload | TS 29.510 §6.1.6.2.3 |
| Q2 | *"List all PDU sessions on slice S-NSSAI SST=1 SD=000001 and the UPFs that serve them."* | R2 — S-NSSAI composite | TS 23.003 §28.4.2 |
| Q3 | *"Which UEs attempted to register but failed?"* | R3 — state vs event | TS 29.518 §5.2 |
| Q4 | *"Are there any suspended NFs that still have active PDU sessions?"* | R1 + state-machine intersection | TS 29.510 §5.3 |
| Q5 | *"Trace the full chain from SUPI to UPF for PDU session 7."* | FK→object-property chaining + stable IRIs | TS 23.501 §4.3 |
| Q6 | *"Which NF deregistrations were heartbeat-inferred rather than explicitly requested?"* | R4 — MEASURED vs INFERRED derivation | TS 29.510 §5.2.2.3–4 |
| Q7 | *"Which active eMBB slices are missing or violating their latency SLA?"* | R6 — slice type SKOS + GSMA SLA | GSMA NG.116; TS 23.501 T.5.15.2.2-1 |
| Q8 | *"Summarise NF `amf-01`'s current health in one sentence."* | free-form; SHACL-valid narrative | — |

Two of these (Q1, Q4) will often produce **dangerously confident-but-wrong** baseline answers because "active" is valid vocabulary on five different tables; Q6 typically produces a hallucination on the baseline (the model invents a plausible distinction because the vocabulary sounds familiar). These are the teaching moments.

---

## 7. Expected toolkit findings

After Phase 2 (`toolkit.py --db db/demo_5g.db --out output/demo-5g/`), `mapping/semantic_loss_report.csv` is expected to contain at minimum:

| severity | finding | target | remediation |
|---|---|---|---|
| CRITICAL | IMPLICIT_ACTOR | `nf_event.actor_party` | Introduce a `Party` or `Agent` table; replace free-text with FK |
| HIGH | STATUS_AS_EVENT | `ue_registration.registration_state`, `pdu_session.session_status` | Ensure `nf_event` covers both — it does, so mark CONSISTENT |
| HIGH | COMPOSITE_IDENTIFIER | `pdu_session.snssai_sst` + `pdu_session.snssai_sd` | Generate an `S-NSSAI` value-type class; expose as one IRI |
| MEDIUM | OVERLOADED_TYPE | `slice_instance.slice_type_label` | Bind to SKOS concept scheme (eMBB/URLLC/mIoT/V2X) |
| MEDIUM | NAMESPACE_COLLISION | `pm_counter.counter_name` | Require `technology` discriminator on every row |
| LOW | FLOATING_VALUE | `pm_counter.value` | Add `unit` column per TS 28.552 |

Governance scorecard target: **≥ 3.2 / 5.0 on first run**, **≥ 3.9** after resolving CRITICAL + both HIGH findings. (Slightly lower than retail because the 5G schema carries more deliberately introduced semantic debt.)

---

## 8. Phases

Identical to [test-plan.md §5](test-plan.md) with three substitutions: DB path `db/demo_5g.db`, output dir `output/demo-5g/`, runtime flavor `fiveg` (declared in `runtime/flavors/fiveg.json` — `owl_classes = [NetworkFunction, NFService, UERegistrationContext, PDUSession, NetworkSliceInstance, PMCounter, Alarm, NFLifecycleEvent]`, `db_tables` as §5.1, and a `system_prompt_hint` that explicitly tells the LLM to disambiguate "active" by OWL class, to resolve S-NSSAI as one IRI, and to honour the `technology` discriminator on PM counters).

Phase 6 report goes to `output/demo-5g/comparison.html` and `output/demo-5g/executive.html`.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 3GPP spec drift between releases (Rel-15 → Rel-18) | The test plan cites stable clause numbers; all enum values used are unchanged since Rel-15 |
| SUPI is PII → vendor refuses the prompt | `ue_registration` is marked `Restricted`; grounded flavor hashes SUPI before it reaches the LLM (uses `PayloadAssembler`'s redaction hook) |
| Baseline accidentally answers Q1 correctly (lucky guess) | Run each call 3× at temperature 0.2 and report modal answer; the single-shot result goes in the report but the run-of-3 is archived |
| Reviewer challenges the ground truth | Every ground-truth row in `illustrative.json` carries a short citation back to the spec clause in §1 |

---

## 10. Deliverables

| Artefact | Path |
|---|---|
| DDL + seed | `db/demo_5g.sql` · `db/demo_5g_seed.sql` |
| Runtime flavor | `runtime/flavors/fiveg.json` |
| Generated ontology | `output/demo-5g/ontology/*.ttl` |
| SHACL shapes | `output/demo-5g/shapes/*.ttl` |
| JSON-LD context | `output/demo-5g/jsonld/fiveg-context.json` |
| Baseline LLM outputs | `output/demo-5g/cache/baseline_{vendor}_{qid}.json` |
| Grounded LLM outputs | `output/demo-5g/cache/grounded_{vendor}_{qid}.json` |
| Side-by-side report | `output/demo-5g/comparison.html` · `output/demo-5g/comparison.csv` |
| Demo scripts (reuse) | `scripts/demo_baseline.py` · `scripts/demo_grounded.py` · `scripts/demo_report.py` — parameterised by `--flavor fiveg` |
| This test plan | [test-plan-5g.md](test-plan-5g.md) |

---

## 11. Demo narrative (5-minute version)

1. **30 s — The data.** Show `db/demo_5g.db`. Eight tables modelled directly on 3GPP NRM. Point at `nf_status`, `service_status`, `registration_state`, `session_status`, `alarm.state` — five columns, five different definitions of "active."
2. **60 s — The toolkit.** Run `python3 toolkit.py --db db/demo_5g.db --out output/demo-5g/`. Open `toolkit_report.html`. Walk through the OWL hierarchy (note `NFLifecycleEvent` subclasses), the `COMPOSITE_IDENTIFIER` finding on S-NSSAI, and the `NAMESPACE_COLLISION` finding on `pm_counter`.
3. **90 s — Baseline.** Paste Q1, Q4, Q6 into each vendor. Show the cross-vendor disagreement on Q1 ("active" resolves to whichever table the model noticed first), the false-negative on Q4 (baseline misses the SUSPENDED UDM with an ACTIVE PDU session because it reads NF and session columns in isolation), and the hallucinated explanation on Q6 ("the system determined…" — no such field exists in raw rows).
4. **90 s — Grounded.** Run the same three through `RuntimeClient.ask(flavor="fiveg")`. Both vendors return identical OWL class names and IRIs. Q6 correctly cites PROV-O `derivation=INFERRED` and points at the two heartbeat-timeout rows in `nf_event`. Open the stored `ObservationRecord` — `prov:wasGeneratedBy`, `generatedAtTime`, `confidence`, `derivation`.
5. **30 s — The takeaway.** A 5G OSS query against raw rows is a guess against ambiguous vocabulary. The same query through an ontology-grounded runtime is an auditable, spec-traceable, multi-vendor-consistent answer — and the trace goes back to the 3GPP clause number.

---

*Branch: `first-contact` · Toolkit: v2.0 · Demo 5G-NF schema (based on 3GPP TS 23.501 / 28.541 / 29.510 / 29.518, TS 28.532 / 28.552, GSMA NG.116, O-RAN WG10 O1) · Models: Anthropic `claude-sonnet-4-5` · OpenAI `gpt-4o`*
