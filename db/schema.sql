-- ============================================================
-- Generic Enterprise Operations Schema
-- Applies to: Telecom, Healthcare, Finance, Manufacturing,
--             Logistics, Energy, Retail, Government
--
-- Metadata columns drive ontology generation:
--   _semantic_type  → OWL class hint
--   _description    → rdfs:comment
--   _sensitivity    → sensitivity tier annotation
--   _is_event       → flag event tables for event-class modeling
-- ============================================================

PRAGMA foreign_keys = ON;

-- ── METADATA REGISTRY ──────────────────────────────────────────
-- This table is the control plane for the ontology generator.
-- Every table and column can be annotated here without altering
-- the operational schema.

CREATE TABLE IF NOT EXISTS ontology_metadata (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type       TEXT NOT NULL CHECK(target_type IN ('TABLE','COLUMN')),
    table_name        TEXT NOT NULL,
    column_name       TEXT,                  -- NULL for TABLE-level metadata
    semantic_type     TEXT,                  -- OWL class name or xsd datatype
    label             TEXT,                  -- rdfs:label override
    description       TEXT,                  -- rdfs:comment
    sensitivity_tier  TEXT DEFAULT 'Internal'
                      CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),
    is_event_class    INTEGER DEFAULT 0,     -- 1 = model as OWL event class
    skos_pref_label   TEXT,                  -- SKOS preferred label
    skos_alt_labels   TEXT,                  -- comma-separated synonyms
    cq_coverage       TEXT,                  -- comma-separated CQ-IDs this supports
    -- ── Phase A: richer axiom signals ──────────────────────────
    -- Object-property characteristics (set on COLUMN rows for FK/object props)
    is_transitive         INTEGER DEFAULT 0,
    is_symmetric          INTEGER DEFAULT 0,
    is_functional         INTEGER DEFAULT 0,
    is_inverse_functional INTEGER DEFAULT 0,
    inverse_of            TEXT,              -- counterpart property name (lowerCamel)
    -- Class-level disjointness grouping (set on TABLE rows)
    disjoint_group        TEXT,              -- shared name → AllDisjointClasses
    -- Class-level meaningful key columns (set on TABLE rows)
    has_key_columns       TEXT,              -- comma-separated column names → owl:hasKey
    created_at        TEXT DEFAULT (datetime('now'))
);

-- ── ORGANIZATIONS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organizations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    org_type          TEXT NOT NULL,         -- SUPPLIER, CUSTOMER, PARTNER, INTERNAL
    parent_org_id     INTEGER REFERENCES organizations(id),
    jurisdiction      TEXT,                  -- country/region code
    active            INTEGER DEFAULT 1,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- ── ASSET TYPES ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS asset_types (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL UNIQUE,
    label             TEXT NOT NULL,
    parent_type_id    INTEGER REFERENCES asset_types(id),
    description       TEXT,
    unit_of_measure   TEXT,
    created_at        TEXT DEFAULT (datetime('now'))
);

-- ── ASSETS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id       TEXT UNIQUE,           -- external system identifier
    name              TEXT NOT NULL,
    asset_type_id     INTEGER NOT NULL REFERENCES asset_types(id),
    owner_org_id      INTEGER REFERENCES organizations(id),
    operator_org_id   INTEGER REFERENCES organizations(id),
    location_code     TEXT,
    status            TEXT DEFAULT 'ACTIVE'
                      CHECK(status IN ('ACTIVE','INACTIVE','DECOMMISSIONED','UNDER_MAINTENANCE')),
    commissioned_at   TEXT,
    decommissioned_at TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- ── AGENTS ─────────────────────────────────────────────────────
-- Human operators, automated systems, AI agents, sensors
CREATE TABLE IF NOT EXISTS agents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_iri         TEXT UNIQUE,           -- persistent IRI for provenance
    name              TEXT NOT NULL,
    agent_type        TEXT NOT NULL
                      CHECK(agent_type IN ('HUMAN','SYSTEM','AI_AGENT','SENSOR','EXTERNAL')),
    org_id            INTEGER REFERENCES organizations(id),
    credential_expiry TEXT,                  -- ISO 8601 for AI agents
    authorized_tiers  TEXT DEFAULT 'Public,Internal',  -- comma-separated
    active            INTEGER DEFAULT 1,
    created_at        TEXT DEFAULT (datetime('now'))
);

-- ── ROLES ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS roles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL UNIQUE,
    label             TEXT NOT NULL,
    description       TEXT,
    sensitivity_tier  TEXT DEFAULT 'Internal'
);

-- ── AGENT ROLE ASSIGNMENTS ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_roles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id          INTEGER NOT NULL REFERENCES agents(id),
    role_id           INTEGER NOT NULL REFERENCES roles(id),
    scope_asset_id    INTEGER REFERENCES assets(id),   -- optional scope
    valid_from        TEXT,
    valid_until       TEXT,
    UNIQUE(agent_id, role_id, scope_asset_id)
);

-- ── POLICIES ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policies (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL UNIQUE,
    title             TEXT NOT NULL,
    policy_type       TEXT NOT NULL
                      CHECK(policy_type IN ('OPERATIONAL','COMPLIANCE','SECURITY','SLA','SAFETY')),
    description       TEXT,
    effective_from    TEXT,
    effective_until   TEXT,
    governing_org_id  INTEGER REFERENCES organizations(id),
    sensitivity_tier  TEXT DEFAULT 'Internal',
    active            INTEGER DEFAULT 1
);

-- ── DOMAIN EVENTS ──────────────────────────────────────────────
-- Stores all significant domain events regardless of type.
-- event_type drives subclass assignment in the ontology generator.
CREATE TABLE IF NOT EXISTS domain_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_iri         TEXT UNIQUE,           -- persistent provenance IRI
    event_type        TEXT NOT NULL,         -- drives OWL subclass
    title             TEXT NOT NULL,
    description       TEXT,
    asset_id          INTEGER REFERENCES assets(id),
    initiated_by      INTEGER REFERENCES agents(id),
    status            TEXT DEFAULT 'OPEN'
                      CHECK(status IN ('OPEN','IN_PROGRESS','COMPLETED','FAILED','CANCELLED')),
    outcome           TEXT,                   -- result code or free text
    policy_id         INTEGER REFERENCES policies(id),
    started_at        TEXT,
    completed_at      TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- ── EVENT PARTICIPANTS ─────────────────────────────────────────
-- Many-to-many: agents participating in an event with a role
CREATE TABLE IF NOT EXISTS event_participants (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          INTEGER NOT NULL REFERENCES domain_events(id),
    agent_id          INTEGER NOT NULL REFERENCES agents(id),
    participation_role TEXT NOT NULL,        -- INITIATOR, APPROVER, OBSERVER, EXECUTOR
    joined_at         TEXT DEFAULT (datetime('now')),
    UNIQUE(event_id, agent_id, participation_role)
);

-- ── OBSERVATIONS ───────────────────────────────────────────────
-- Any measured, detected, or computed fact about an asset or event.
-- PROV-O-aligned: every observation carries provenance.
CREATE TABLE IF NOT EXISTS observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_iri   TEXT UNIQUE,
    observation_type  TEXT NOT NULL,
    asset_id          INTEGER REFERENCES assets(id),
    event_id          INTEGER REFERENCES domain_events(id),
    recorded_by       INTEGER NOT NULL REFERENCES agents(id),
    numeric_value     REAL,
    text_value        TEXT,
    unit_of_measure   TEXT,
    confidence_score  REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),
    derivation_method TEXT,                  -- MEASURED, INFERRED, IMPORTED, SYNTHESIZED
    source_ref        TEXT,                  -- external source IRI or document ref
    observed_at       TEXT NOT NULL,
    created_at        TEXT DEFAULT (datetime('now'))
);

-- ── POLICY APPLICATIONS ────────────────────────────────────────
-- Records when a policy was applied to an event or asset
CREATE TABLE IF NOT EXISTS policy_applications (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id         INTEGER NOT NULL REFERENCES policies(id),
    event_id          INTEGER REFERENCES domain_events(id),
    asset_id          INTEGER REFERENCES assets(id),
    applied_by        INTEGER NOT NULL REFERENCES agents(id),
    outcome           TEXT CHECK(outcome IN ('COMPLIANT','NON_COMPLIANT','EXEMPT','PENDING')),
    notes             TEXT,
    applied_at        TEXT DEFAULT (datetime('now'))
);

-- ── SEMANTIC LOSS LOG ──────────────────────────────────────────
-- Populated by the mapping generator (Phase 4) to record where
-- physical model flattens domain meaning
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

-- ── ONTOLOGY EVOLUTION PROPOSALS ──────────────────────────────
-- Workstream 2 (Gen2): autonomous ontology-evolution proposal store.
-- Every candidate surfaced by the anomaly monitor lands here as
-- PENDING, is scored, passes through a human review gate, and on
-- APPROVED drives CI/CD-auto-versioning of the ontology.
CREATE TABLE IF NOT EXISTS ontology_evolution_proposals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id        TEXT NOT NULL UNIQUE,          -- UUID
    proposal_type      TEXT NOT NULL
                       CHECK(proposal_type IN (
                         'NEW_CLASS','NEW_PROPERTY','NEW_CONSTRAINT','DEPRECATE',
                         -- ── Log-driven RCA (see docs/log-rca-roadmap.md) ──
                         'LOG_ENTITY','LOG_RELATIONSHIP','LOG_EVENT','LOG_CAUSAL_EDGE')),
    title              TEXT NOT NULL,
    candidate_turtle   TEXT NOT NULL,                 -- OWL axiom as Turtle
    evidence_sparql    TEXT NOT NULL,                 -- query that surfaced it
    detection_strategy TEXT NOT NULL
                       CHECK(detection_strategy IN (
                         'SHACL_VIOLATION_ACCUMULATION',
                         'CARDINALITY_BREACH',
                         'CLASS_COOCCURRENCE',
                         'NLP_CANDIDATE_PROMOTION',
                         -- ── Log-driven RCA strategies ──
                         'LOG_TEMPLATE_CLUSTERING',
                         'PMI_TEMPORAL_ORDERING',
                         'HMM_SEQUENCE_ANOMALY',
                         'GRANGER_CAUSALITY',
                         'DRIFT_ON_NEW_TEMPLATE')),
    confidence_score   REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),
    dim_evidence_volume    REAL,
    dim_evidence_recency   REAL,
    dim_cross_domain       REAL,
    dim_consistency_risk   REAL,
    dim_schema_alignment   REAL,
    status             TEXT DEFAULT 'PENDING'
                       CHECK(status IN ('PENDING','APPROVED','REJECTED','DEFERRED')),
    reviewer_id        TEXT,                          -- agent/user IRI
    review_note        TEXT,
    reviewed_at        TEXT,
    defer_until        TEXT,
    version_target     TEXT,                          -- e.g. '1.1.0'
    primary_cq         TEXT,                          -- CQ-ID this proposal answers
    -- ── Log-driven RCA evidence (NULL for hand-authored proposals) ──
    source_log_path    TEXT,
    evidence_template_id INTEGER,
    evidence_sample    TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);

-- ── ONTOLOGY VERSION LEDGER ──────────────────────────────────
-- Appended by the CI/CD auto-versioner whenever an APPROVED proposal
-- increments the ontology version.  Supports forward/backward trace
-- from any axiom to the decision that introduced it.
CREATE TABLE IF NOT EXISTS ontology_version_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    version            TEXT NOT NULL UNIQUE,          -- semver '1.1.0'
    parent_version     TEXT,                          -- version this builds on
    proposal_id        TEXT REFERENCES ontology_evolution_proposals(proposal_id),
    reasoner_status    TEXT,                          -- PASS/FAIL/SKIPPED
    shacl_status       TEXT,                          -- PASS/FAIL/SKIPPED
    sparql_status      TEXT,                          -- PASS/FAIL
    pr_url             TEXT,                          -- GitHub PR link
    scorecard_delta    TEXT,                          -- JSON delta blob
    created_at         TEXT DEFAULT (datetime('now'))
);

-- ── FEDERATION PARTNERS ───────────────────────────────────────
-- Workstream 3 (Gen2): cross-enterprise federated ontology network.
-- Each partner row represents one registered external organisation
-- with a cryptographically signed capability manifest declaring what
-- it exposes, to whom, and at what sensitivity tier.
CREATE TABLE IF NOT EXISTS federation_partners (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_id         TEXT NOT NULL UNIQUE,           -- UUID
    partner_iri        TEXT NOT NULL UNIQUE,           -- persistent IRI
    display_name       TEXT NOT NULL,
    sparql_endpoint    TEXT NOT NULL,
    manifest_url       TEXT,                           -- well-known capability URI
    manifest_jsonld    TEXT,                           -- most-recent signed manifest
    manifest_signature TEXT,                           -- Ed25519 signature (b64)
    public_key         TEXT NOT NULL,                  -- Ed25519 public key (b64)
    exposed_classes    TEXT,                           -- JSON array of class IRIs
    max_shareable_tier TEXT DEFAULT 'Internal'
                       CHECK(max_shareable_tier IN ('Public','Internal','Confidential','Restricted')),
    trust_state        TEXT DEFAULT 'PROPOSED'
                       CHECK(trust_state IN (
                         'PROPOSED','HANDSHAKE_SENT','COUNTERSIGNED','ACTIVE',
                         'EXPIRED','REVOKED')),
    valid_from         TEXT,
    valid_until        TEXT,
    registered_at      TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);

-- ── FEDERATION QUERY LOG ─────────────────────────────────────
-- Captures every cross-enterprise SPARQL query for audit + governance.
CREATE TABLE IF NOT EXISTS federation_query_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id           TEXT NOT NULL UNIQUE,           -- UUID
    partner_id         TEXT REFERENCES federation_partners(partner_id),
    requesting_flavor  TEXT,                           -- agent flavor initiating query
    original_query     TEXT NOT NULL,
    rewritten_query    TEXT,                           -- after sensitivity filters applied
    result_triples     INTEGER DEFAULT 0,
    violations         INTEGER DEFAULT 0,              -- boundary violations detected
    status             TEXT DEFAULT 'PENDING'
                       CHECK(status IN ('PENDING','OK','REJECTED','ERROR')),
    duration_ms        INTEGER,
    executed_at        TEXT DEFAULT (datetime('now'))
);

-- ── FEDERATION TRUST HANDSHAKE LEDGER ────────────────────────
-- Append-only log of the bilateral trust bootstrap events.
CREATE TABLE IF NOT EXISTS federation_trust_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id           TEXT NOT NULL UNIQUE,           -- UUID
    partner_id         TEXT REFERENCES federation_partners(partner_id),
    event_type         TEXT NOT NULL
                       CHECK(event_type IN (
                         'MANIFEST_SENT','MANIFEST_RECEIVED','COUNTERSIGNED',
                         'ACTIVATED','TEST_QUERY','REVOKED','EXPIRED')),
    payload_hash       TEXT,                           -- sha256 of bytes signed
    signature          TEXT,                           -- Ed25519 signature (b64)
    note               TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
);

-- ── COMPLIANCE BUNDLES ───────────────────────────────────────
-- Workstream 4 (Gen2): Regulatory AI Compliance Evidence Engine.
-- Every bundle emitted by compliance.bundle.export_bundle() is
-- registered here so the graph carries an auditable pointer to
-- the signed ZIP on disk.  Row-level sensitivity = Restricted.
CREATE TABLE IF NOT EXISTS compliance_bundles (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_id          TEXT NOT NULL UNIQUE,
    regulation_id      TEXT NOT NULL,
    decision_iri       TEXT,
    bundle_path        TEXT NOT NULL,
    sha256             TEXT NOT NULL,
    signer_iri         TEXT,
    verified           INTEGER DEFAULT 1,
    coverage_percent   INTEGER,
    sensitivity_tier   TEXT DEFAULT 'Restricted',
    assembled_at       TEXT,
    stored_at          TEXT DEFAULT (datetime('now'))
);

-- ── EMBEDDING INDEX METADATA ─────────────────────────────────
-- Workstream 5 (Gen2): Ontology-Bounded Vector Retrieval.
-- One row per named embedding index (typically one per flavor).
-- Tracks OWL class coverage, record count, active model, and the
-- connection string of the underlying vector store.
CREATE TABLE IF NOT EXISTS embedding_indexes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name         TEXT NOT NULL UNIQUE,           -- e.g. "network-ops"
    flavor             TEXT NOT NULL,
    vector_store       TEXT NOT NULL,                  -- qdrant|chroma|weaviate|pgvector|memory
    connection_string  TEXT NOT NULL,
    model_id           TEXT NOT NULL,                  -- e.g. "hash-local-384" or model name
    dimensions         INTEGER NOT NULL,
    owl_classes        TEXT,                           -- JSON array of indexed IRIs
    record_count       INTEGER DEFAULT 0,
    max_sensitivity    TEXT DEFAULT 'Internal'
                       CHECK(max_sensitivity IN ('Public','Internal','Confidential','Restricted')),
    last_indexed_at    TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    updated_at         TEXT DEFAULT (datetime('now'))
);

-- ── EMBEDDING RECORDS ─────────────────────────────────────────
-- Each row stores an embedding vector (b64-packed float32) alongside
-- the ontology metadata needed for class-hierarchy and sensitivity
-- filtering.  When an external vector store is used, this table acts
-- as a cache + source-of-truth for reindexing.
CREATE TABLE IF NOT EXISTS embedding_records (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name         TEXT NOT NULL REFERENCES embedding_indexes(index_name),
    record_iri         TEXT NOT NULL,                  -- IRI of the typed instance
    owl_class          TEXT NOT NULL,                  -- full OWL class IRI
    flavor             TEXT NOT NULL,
    sensitivity_tier   TEXT NOT NULL
                       CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),
    primary_key        TEXT,                           -- source table primary key
    source_table       TEXT,
    text_repr          TEXT NOT NULL,                  -- serialised text used to embed
    vector_b64         TEXT NOT NULL,                  -- base64-encoded float32 LE
    content_hash       TEXT NOT NULL,                  -- sha256 of text_repr — drives incremental reindex
    indexed_at         TEXT DEFAULT (datetime('now')),
    UNIQUE(index_name, record_iri)
);

-- ── VECTOR QUERY LOG ─────────────────────────────────────────
-- Captures every hybrid retrieval call for audit + benchmarking.
CREATE TABLE IF NOT EXISTS vector_query_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id           TEXT NOT NULL UNIQUE,
    index_name         TEXT,
    flavor             TEXT,
    question           TEXT NOT NULL,
    class_filter       TEXT,                           -- OWL class expression or flavor name
    resolved_classes   TEXT,                           -- JSON array after hierarchy expansion
    k_requested        INTEGER,
    k_returned         INTEGER,
    latency_ms         INTEGER,
    strategy           TEXT CHECK(strategy IN (
                         'UNFILTERED_VECTOR','ONTOLOGY_BOUNDED','PURE_SPARQL','HYBRID')),
    executed_at        TEXT DEFAULT (datetime('now'))
);

-- ── RETRIEVAL BENCHMARKS ─────────────────────────────────────
-- Persistent store for benchmark runs (precision@k, recall@k, MRR, latency).
CREATE TABLE IF NOT EXISTS retrieval_benchmarks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT NOT NULL UNIQUE,
    domain             TEXT,                           -- telecom | healthcare | ...
    strategy           TEXT NOT NULL,
    corpus_size        INTEGER,
    queries            INTEGER,
    precision_at_5     REAL,
    recall_at_5        REAL,
    mean_reciprocal_rank REAL,
    latency_p50_ms     INTEGER,
    latency_p95_ms     INTEGER,
    improvement_over_baseline REAL,                    -- precision@5 delta vs UNFILTERED_VECTOR
    wrong_class_blocked REAL,                          -- fraction of wrong-class hits filtered out
    executed_at        TEXT DEFAULT (datetime('now'))
);

-- ── INDEXES ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_assets_type     ON assets(asset_type_id);
CREATE INDEX IF NOT EXISTS idx_assets_owner    ON assets(owner_org_id);
CREATE INDEX IF NOT EXISTS idx_events_asset    ON domain_events(asset_id);
CREATE INDEX IF NOT EXISTS idx_events_agent    ON domain_events(initiated_by);
CREATE INDEX IF NOT EXISTS idx_events_type     ON domain_events(event_type);
CREATE INDEX IF NOT EXISTS idx_obs_asset       ON observations(asset_id);
CREATE INDEX IF NOT EXISTS idx_obs_agent       ON observations(recorded_by);
CREATE INDEX IF NOT EXISTS idx_obs_event       ON observations(event_id);
CREATE INDEX IF NOT EXISTS idx_pa_policy       ON policy_applications(policy_id);
CREATE INDEX IF NOT EXISTS idx_evo_status      ON ontology_evolution_proposals(status);
CREATE INDEX IF NOT EXISTS idx_evo_conf        ON ontology_evolution_proposals(confidence_score);
CREATE INDEX IF NOT EXISTS idx_evo_strategy    ON ontology_evolution_proposals(detection_strategy);
CREATE INDEX IF NOT EXISTS idx_version_ledger  ON ontology_version_ledger(version);
CREATE INDEX IF NOT EXISTS idx_fed_partner_state ON federation_partners(trust_state);
CREATE INDEX IF NOT EXISTS idx_fed_query_partner ON federation_query_log(partner_id);
CREATE INDEX IF NOT EXISTS idx_fed_query_status  ON federation_query_log(status);
CREATE INDEX IF NOT EXISTS idx_fed_ledger_partner ON federation_trust_ledger(partner_id);
CREATE INDEX IF NOT EXISTS idx_cmp_bundle_regulation ON compliance_bundles(regulation_id);
CREATE INDEX IF NOT EXISTS idx_cmp_bundle_decision  ON compliance_bundles(decision_iri);
CREATE INDEX IF NOT EXISTS idx_emb_records_index  ON embedding_records(index_name);
CREATE INDEX IF NOT EXISTS idx_emb_records_class  ON embedding_records(owl_class);
CREATE INDEX IF NOT EXISTS idx_emb_records_flavor ON embedding_records(flavor);
CREATE INDEX IF NOT EXISTS idx_emb_records_tier   ON embedding_records(sensitivity_tier);
CREATE INDEX IF NOT EXISTS idx_vec_qlog_flavor    ON vector_query_log(flavor);
CREATE INDEX IF NOT EXISTS idx_vec_qlog_strategy  ON vector_query_log(strategy);
CREATE INDEX IF NOT EXISTS idx_rbench_strategy    ON retrieval_benchmarks(strategy);
CREATE INDEX IF NOT EXISTS idx_rbench_domain      ON retrieval_benchmarks(domain);
