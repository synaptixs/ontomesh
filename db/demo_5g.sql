-- ============================================================
-- 5G Network-Function Demo Schema — "First Contact" 5G demo
-- Modelled on 3GPP TS 23.501 (architecture), TS 28.541 (NRM),
-- TS 29.510 (NRF/NFProfile), TS 29.518 (AMF UE context),
-- TS 23.502 / 29.502 (PDU session), TS 28.552 (PM counters),
-- TS 28.532 (alarms), GSMA NG.116 (slice SLA).
-- ============================================================

PRAGMA foreign_keys = ON;

-- ── TOOLKIT SYSTEM TABLES ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS ontology_metadata (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type       TEXT NOT NULL CHECK(target_type IN ('TABLE','COLUMN')),
    table_name        TEXT NOT NULL,
    column_name       TEXT,
    semantic_type     TEXT,
    label             TEXT,
    description       TEXT,
    sensitivity_tier  TEXT DEFAULT 'Internal'
                      CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),
    is_event_class    INTEGER DEFAULT 0,
    skos_pref_label   TEXT,
    skos_alt_labels   TEXT,
    cq_coverage       TEXT,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS semantic_loss_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name        TEXT NOT NULL,
    column_name       TEXT,
    loss_type         TEXT NOT NULL,
    description       TEXT NOT NULL,
    severity          TEXT CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    remediation       TEXT,
    detected_at       TEXT DEFAULT (datetime('now')),
    resolved          INTEGER DEFAULT 0
);

-- ── DOMAIN TABLES ─────────────────────────────────────────────

-- 3GPP TS 29.510 §6.1.6.2 NFProfile (simplified)
CREATE TABLE nf_instance (
    id               INTEGER PRIMARY KEY,
    nf_instance_id   TEXT NOT NULL UNIQUE,               -- NF UUID
    nf_type          TEXT NOT NULL
                     CHECK (nf_type IN ('AMF','SMF','UPF','PCF','UDM','AUSF','NRF','NSSF','NEF','SMSF','UDR')),
    nf_status        TEXT NOT NULL
                     CHECK (nf_status IN ('REGISTERED','SUSPENDED','UNDISCOVERABLE')),  -- TS 29.510 §6.1.6.2.3
    fqdn             TEXT NOT NULL,
    plmn_mcc         TEXT NOT NULL,
    plmn_mnc         TEXT NOT NULL,
    heartbeat_timer  INTEGER NOT NULL,                   -- seconds (TS 29.510 §5.2.2.3)
    last_heartbeat   TEXT,
    created_at       TEXT NOT NULL
);

-- TS 29.510 §6.1.6.2.4 NFService
CREATE TABLE nf_service (
    id               INTEGER PRIMARY KEY,
    nf_instance_id   INTEGER NOT NULL REFERENCES nf_instance(id),
    service_name     TEXT NOT NULL,                      -- e.g. Namf_Communication
    service_status   TEXT NOT NULL
                     CHECK (service_status IN ('REGISTERED','SUSPENDED')),
    api_version      TEXT NOT NULL,
    scheme           TEXT NOT NULL CHECK (scheme IN ('http','https'))
);

-- TS 29.518 §5.2.2 UE Registration Context (AMF-owned)
CREATE TABLE ue_registration (
    id                  INTEGER PRIMARY KEY,
    supi                TEXT NOT NULL,                   -- imsi-<15 digit>
    amf_instance_id     INTEGER NOT NULL REFERENCES nf_instance(id),
    registration_state  TEXT NOT NULL
                        CHECK (registration_state IN ('REGISTERED','DEREGISTERED')),
    connection_state    TEXT NOT NULL
                        CHECK (connection_state IN ('IDLE','CONNECTED')),
    plmn_mcc            TEXT NOT NULL,
    plmn_mnc            TEXT NOT NULL,
    registered_at       TEXT NOT NULL,
    last_activity_at    TEXT
);

-- TS 23.502 §4.3 / TS 29.502 PDU Session
CREATE TABLE pdu_session (
    id                INTEGER PRIMARY KEY,
    pdu_session_id    INTEGER NOT NULL,                  -- 1..15 per UE
    supi              TEXT NOT NULL,
    smf_instance_id   INTEGER NOT NULL REFERENCES nf_instance(id),
    upf_instance_id   INTEGER NOT NULL REFERENCES nf_instance(id),
    snssai_sst        INTEGER NOT NULL,                  -- TS 23.501 Table 5.15.2.2-1
    snssai_sd         TEXT,                              -- 6 hex digits or NULL
    dnn               TEXT NOT NULL,                     -- Data Network Name
    session_status    TEXT NOT NULL
                      CHECK (session_status IN ('ACTIVE','INACTIVE','RELEASED')),
    established_at    TEXT NOT NULL
);

-- TS 28.541 Slice Instance / NSSI
CREATE TABLE slice_instance (
    id                 INTEGER PRIMARY KEY,
    nssi_id            TEXT NOT NULL UNIQUE,
    sst                INTEGER NOT NULL,
    sd                 TEXT,
    slice_type_label   TEXT,                             -- free-text: "eMBB","URLLC",...  (OVERLOADED_TYPE finding)
    sla_latency_ms     INTEGER,                          -- GSMA NG.116 maxEndToEndLatency
    sla_avail_pct      REAL,                             -- GSMA NG.116 serviceAvailability
    operational_state  TEXT NOT NULL
                       CHECK (operational_state IN ('ENABLED','DISABLED'))
);

-- TS 28.552 PM counter record
CREATE TABLE pm_counter (
    id                INTEGER PRIMARY KEY,
    nf_instance_id    INTEGER NOT NULL REFERENCES nf_instance(id),
    counter_name      TEXT NOT NULL,                     -- e.g. RRC.ConnEstabAtt
    technology        TEXT NOT NULL CHECK (technology IN ('NR','LTE')),
    value             REAL NOT NULL,
    granularity_sec   INTEGER NOT NULL,                  -- 60,300,900
    collected_at      TEXT NOT NULL
);

-- TS 28.532 §6.3 Alarm
CREATE TABLE alarm (
    id                  INTEGER PRIMARY KEY,
    nf_instance_id      INTEGER NOT NULL REFERENCES nf_instance(id),
    alarm_type          TEXT NOT NULL,                   -- e.g. NRF_HEARTBEAT_TIMEOUT
    perceived_severity  TEXT NOT NULL
                        CHECK (perceived_severity IN ('CRITICAL','MAJOR','MINOR','WARNING','INDETERMINATE')),
    state               TEXT NOT NULL
                        CHECK (state IN ('ACTIVE','CLEARED')),
    raised_at           TEXT NOT NULL,
    cleared_at          TEXT
);

-- Event table — NF lifecycle (drives PROV-O + STATUS_AS_EVENT + IMPLICIT_ACTOR findings)
CREATE TABLE nf_event (
    id              INTEGER PRIMARY KEY,
    nf_instance_id  INTEGER NOT NULL REFERENCES nf_instance(id),
    event_type      TEXT NOT NULL
                    CHECK (event_type IN ('REGISTERED','DEREGISTERED','HEARTBEAT_FAILED',
                                          'SUSPENDED','PROFILE_UPDATED','SERVICE_STARTED','SERVICE_STOPPED')),
    occurred_at     TEXT NOT NULL,
    actor_party     TEXT,                                -- free-text: "nf","nrf-monitor","operator","cicd"
    confidence      REAL CHECK (confidence BETWEEN 0.0 AND 1.0),
    derivation      TEXT CHECK (derivation IN ('MEASURED','INFERRED','IMPORTED','SYNTHESIZED'))
);
