-- ============================================================
-- TMF SID-Aligned Telecom Schema  v1.0
-- ============================================================
-- Models the 8 TM Forum Information Framework (SID) domains:
--   Resource        → TMF639 Resource Inventory, TMF634 Resource Catalog
--   Service         → TMF638 Service Inventory, TMF633 Service Catalog
--   Product         → TMF637 Product Inventory, TMF620 Product Catalog
--   EngagedParty    → TMF632 Party, TMF629 Customer, TMF666 Account
--   Market/Sales    → TMF699 Sales Channel, TMF678 Customer Bill
--   Supplier/Partner→ TMF701 Process Flow, TMF669 Party Role
--   Enterprise      → TMF651 Agreement, TMF672 User Roles
--   Common          → TMF673/674/675 Geographic, Characteristic, Note
--
-- SID design patterns used throughout:
--   Specification–Instance  (XxxSpecification → Xxx)
--   Composite               (parent/child resource trees)
--   Characteristic          (key-value extensibility)
--   Status lifecycle        (stateOrStatus with eTOM state machine values)
-- ============================================================

PRAGMA foreign_keys = ON;

-- ── SYSTEM TABLES (required by toolkit) ──────────────────────
-- ── EXTEND ontology_metadata with TMF columns (safe for both fresh and existing DBs)
CREATE TABLE IF NOT EXISTS ontology_metadata (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type      TEXT NOT NULL CHECK(target_type IN ('TABLE','COLUMN')),
    table_name       TEXT NOT NULL,
    column_name      TEXT,
    semantic_type    TEXT,
    label            TEXT,
    description      TEXT,
    sensitivity_tier TEXT DEFAULT 'Internal'
                     CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),
    is_event_class   INTEGER DEFAULT 0,
    skos_pref_label  TEXT,
    skos_alt_labels  TEXT,
    cq_coverage      TEXT,
    sid_domain       TEXT,
    sid_abe          TEXT,
    tmf_api_id       TEXT,
    tmf_api_version  TEXT,
    tmf_entity_name  TEXT,
    etom_process     TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);
-- Add TMF columns to existing ontology_metadata if migrating from generic schema
-- SQLite does not support IF NOT EXISTS on ALTER TABLE — use try/catch at app level.
-- These are handled by the toolkit's setup_db migration logic:

CREATE TABLE IF NOT EXISTS semantic_loss_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name   TEXT NOT NULL,
    column_name  TEXT,
    loss_type    TEXT NOT NULL,
    description  TEXT NOT NULL,
    severity     TEXT CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    remediation  TEXT,
    detected_at  TEXT DEFAULT (datetime('now')),
    resolved     INTEGER DEFAULT 0
);

-- ============================================================
-- COMMON DOMAIN  (cross-cutting — used by all other domains)
-- SID ABEs: TimePeriod, Note, Attachment, Characteristic,
--           CalendarPeriod, Money, Quantity
-- ============================================================

CREATE TABLE IF NOT EXISTS tmf_characteristic (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    value           TEXT,
    value_type      TEXT,                  -- string, integer, float, boolean, object
    unit            TEXT,
    owner_type      TEXT NOT NULL,         -- discriminator for polymorphic FK
    owner_id        INTEGER NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tmf_note (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    author      TEXT,
    date        TEXT DEFAULT (datetime('now')),
    note_type   TEXT,
    owner_type  TEXT NOT NULL,
    owner_id    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tmf_attachment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    description     TEXT,
    mime_type       TEXT,
    url             TEXT,
    attachment_type TEXT,
    owner_type      TEXT NOT NULL,
    owner_id        INTEGER NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- TMF673/674/675 — Geographic Address / Site / Location
CREATE TABLE IF NOT EXISTS tmf_place (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    place_iri       TEXT UNIQUE,
    name            TEXT NOT NULL,
    place_type      TEXT CHECK(place_type IN
                    ('GEOGRAPHIC_ADDRESS','GEOGRAPHIC_SITE','GEOGRAPHIC_LOCATION')),
    street_nr       TEXT,
    street_name     TEXT,
    city            TEXT,
    state_or_province TEXT,
    postcode        TEXT,
    country         TEXT,
    latitude        REAL,
    longitude       REAL,
    -- SID: RelatedPlace — link to parent site
    parent_place_id INTEGER REFERENCES tmf_place(id),
    lifecycle_status TEXT DEFAULT 'Active',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- RESOURCE DOMAIN  — TMF639 Resource Inventory / TMF634 Catalog
-- SID ABEs: Resource, LogicalResource, PhysicalResource,
--           ResourceSpecification, ResourceTopology,
--           ResourcePerformance, ResourceUsage
-- ============================================================

-- ResourceSpecification (TMF634) — template / catalog entry
CREATE TABLE IF NOT EXISTS tmf_resource_spec (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_iri        TEXT UNIQUE,
    name            TEXT NOT NULL,
    version         TEXT DEFAULT '1.0',
    description     TEXT,
    category        TEXT,    -- LOGICAL, PHYSICAL
    lifecycle_status TEXT DEFAULT 'Active'
                    CHECK(lifecycle_status IN
                    ('In Study','In Design','In Test','Active','Launched',
                     'Retired','Obsolete','Rejected')),
    is_bundle       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Resource — base inventory record (TMF639)
-- Covers both LogicalResource and PhysicalResource via resource_type
CREATE TABLE IF NOT EXISTS tmf_resource (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_iri        TEXT UNIQUE,
    name                TEXT NOT NULL,
    resource_type       TEXT NOT NULL
                        CHECK(resource_type IN
                        ('LOGICAL_RESOURCE','PHYSICAL_RESOURCE',
                         'NETWORK_FUNCTION','NETWORK_SLICE','IP_ADDRESS',
                         'MSISDN','EQUIPMENT','SITE')),
    -- SID Specification pattern
    resource_spec_id    INTEGER REFERENCES tmf_resource_spec(id),
    -- SID Network Function subtype (5G-specific)
    nf_type             TEXT,   -- AMF, SMF, UPF, gNB, eNB, PCF, UDM, AUSF, NRF
    -- Operational state (eTOM state machine)
    operational_state   TEXT DEFAULT 'Enabled'
                        CHECK(operational_state IN ('Enabled','Disabled')),
    admin_state         TEXT DEFAULT 'Unlocked'
                        CHECK(admin_state IN ('Locked','Unlocked','Shutting Down')),
    usage_state         TEXT DEFAULT 'Idle'
                        CHECK(usage_state IN ('Idle','Active','Busy')),
    -- Composite pattern — parent/child resource tree
    parent_resource_id  INTEGER REFERENCES tmf_resource(id),
    -- Location
    place_id            INTEGER REFERENCES tmf_place(id),
    -- External IDs (OSS/NMS cross-reference)
    external_id         TEXT,
    external_system     TEXT,   -- NMS, OSS, EMS, DCIM
    -- Lifecycle
    start_operating_date TEXT,
    end_operating_date  TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ResourceRelationship — SID association between resources
CREATE TABLE IF NOT EXISTS tmf_resource_relationship (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id         INTEGER NOT NULL REFERENCES tmf_resource(id),
    related_resource_id INTEGER NOT NULL REFERENCES tmf_resource(id),
    relationship_type   TEXT NOT NULL,  -- composedOf, relies-on, connectsTo, dependsOn
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- SERVICE DOMAIN  — TMF638 Service Inventory / TMF633 Catalog
-- SID ABEs: Service, CustomerFacingService, ResourceFacingService,
--           ServiceSpecification, ServiceOrder, ServiceProblem
-- ============================================================

CREATE TABLE IF NOT EXISTS tmf_service_spec (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_iri        TEXT UNIQUE,
    name            TEXT NOT NULL,
    version         TEXT DEFAULT '1.0',
    service_type    TEXT CHECK(service_type IN
                    ('CUSTOMER_FACING_SERVICE','RESOURCE_FACING_SERVICE')),
    description     TEXT,
    lifecycle_status TEXT DEFAULT 'Active',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Service inventory instance (TMF638)
CREATE TABLE IF NOT EXISTS tmf_service (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    service_iri         TEXT UNIQUE,
    name                TEXT NOT NULL,
    service_type        TEXT NOT NULL
                        CHECK(service_type IN
                        ('CUSTOMER_FACING_SERVICE','RESOURCE_FACING_SERVICE')),
    -- SID specification pattern
    service_spec_id     INTEGER REFERENCES tmf_service_spec(id),
    -- eTOM states
    state               TEXT DEFAULT 'Active'
                        CHECK(state IN
                        ('Feasibility Checked','Designed','Reserved','Inactive',
                         'Active','Terminated')),
    -- SID: ServiceRelationship → composed-of hierarchy
    parent_service_id   INTEGER REFERENCES tmf_service(id),
    -- The resource(s) realising this service
    realising_resource_id INTEGER REFERENCES tmf_resource(id),
    start_date          TEXT,
    end_date            TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- PRODUCT DOMAIN  — TMF637 Inventory / TMF620 Catalog
-- SID ABEs: Product, ProductOffering, ProductSpecification,
--           ProductOrder, BundledProductOffering
-- ============================================================

CREATE TABLE IF NOT EXISTS tmf_product_spec (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_iri        TEXT UNIQUE,
    name            TEXT NOT NULL,
    version         TEXT DEFAULT '1.0',
    product_number  TEXT,
    brand           TEXT,
    description     TEXT,
    lifecycle_status TEXT DEFAULT 'Launched',
    is_bundle       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ProductOffering (TMF620) — what is sold in the catalog
CREATE TABLE IF NOT EXISTS tmf_product_offering (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    offering_iri        TEXT UNIQUE,
    name                TEXT NOT NULL,
    description         TEXT,
    version             TEXT DEFAULT '1.0',
    product_spec_id     INTEGER REFERENCES tmf_product_spec(id),
    is_bundle           INTEGER DEFAULT 0,
    lifecycle_status    TEXT DEFAULT 'Launched',
    valid_for_start     TEXT,
    valid_for_end       TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Product inventory instance (TMF637)
CREATE TABLE IF NOT EXISTS tmf_product (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_iri         TEXT UNIQUE,
    name                TEXT NOT NULL,
    product_offering_id INTEGER REFERENCES tmf_product_offering(id),
    -- SID: ProductRelationship — bundles / add-ons
    parent_product_id   INTEGER REFERENCES tmf_product(id),
    status              TEXT DEFAULT 'Active'
                        CHECK(status IN
                        ('Created','Pending Active','Cancelled','Active',
                         'Pending Terminate','Terminated','Suspended')),
    -- Which service(s) deliver this product
    realising_service_id INTEGER REFERENCES tmf_service(id),
    start_date          TEXT,
    end_date            TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- ENGAGED PARTY DOMAIN  — TMF632 Party / TMF629 Customer
-- SID ABEs: Party, Individual, Organization, PartyRole,
--           CustomerAccount, Agreement, SLA
-- ============================================================

-- Party — base entity (TMF632)
CREATE TABLE IF NOT EXISTS tmf_party (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    party_iri       TEXT UNIQUE,
    party_type      TEXT NOT NULL CHECK(party_type IN ('INDIVIDUAL','ORGANIZATION')),
    name            TEXT NOT NULL,
    -- Individual attributes
    given_name      TEXT,
    family_name     TEXT,
    nationality     TEXT,
    -- Organization attributes
    trading_name    TEXT,
    org_type        TEXT,  -- Operator, Vendor, Regulator, Partner, Internal
    -- Contact
    email           TEXT,
    phone           TEXT,
    -- Location
    place_id        INTEGER REFERENCES tmf_place(id),
    lifecycle_status TEXT DEFAULT 'Active',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- PartyRole (TMF669) — contextual role a party plays
CREATE TABLE IF NOT EXISTS tmf_party_role (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    party_id        INTEGER NOT NULL REFERENCES tmf_party(id),
    role_name       TEXT NOT NULL,  -- Customer, Partner, Supplier, Employee, Owner
    role_type       TEXT,
    status          TEXT DEFAULT 'Initialized',
    valid_from      TEXT,
    valid_until     TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- CustomerAccount (TMF666)
CREATE TABLE IF NOT EXISTS tmf_customer_account (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_iri     TEXT UNIQUE,
    account_number  TEXT UNIQUE,
    name            TEXT NOT NULL,
    account_type    TEXT,    -- Residential, Enterprise, Wholesale
    status          TEXT DEFAULT 'Active',
    party_id        INTEGER NOT NULL REFERENCES tmf_party(id),
    credit_limit    REAL,
    currency_code   TEXT DEFAULT 'USD',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Agreement (TMF651) — SLA or contract
CREATE TABLE IF NOT EXISTS tmf_agreement (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agreement_iri   TEXT UNIQUE,
    name            TEXT NOT NULL,
    agreement_type  TEXT CHECK(agreement_type IN ('SLA','COMMERCIAL','ROAMING','WHOLESALE')),
    description     TEXT,
    status          TEXT DEFAULT 'Active',
    -- Parties to the agreement
    party_a_id      INTEGER REFERENCES tmf_party(id),
    party_b_id      INTEGER REFERENCES tmf_party(id),
    valid_from      TEXT,
    valid_until     TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- ENTERPRISE DOMAIN  — Policies, UserRoles (TMF672)
-- SID ABEs: Policy, PolicyStatement, EmployeeRole
-- ============================================================

CREATE TABLE IF NOT EXISTS tmf_policy (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_iri      TEXT UNIQUE,
    name            TEXT NOT NULL,
    policy_type     TEXT CHECK(policy_type IN
                    ('OPERATIONAL','COMPLIANCE','SECURITY','SLA','SAFETY','NETWORK')),
    description     TEXT,
    status          TEXT DEFAULT 'Active',
    version         TEXT DEFAULT '1.0',
    governing_body  TEXT,   -- Regulator, Operator, Standards body
    effective_from  TEXT,
    effective_until TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- UserRole (TMF672)
CREATE TABLE IF NOT EXISTS tmf_user_role (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    permission_set  TEXT,   -- JSON array of permission codes
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- DOMAIN EVENTS  — TMF688 Event Management / TMF642 Alarm
-- SID ABEs: ResourceTrouble, ServiceProblem, CustomerProblem
-- eTOM: 1.1.3.4 Problem Handling, 1.4.4 Alarm Surveillance
-- ============================================================

-- Alarm (TMF642) — network fault event
CREATE TABLE IF NOT EXISTS tmf_alarm (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    alarm_iri           TEXT UNIQUE,
    alarm_type          TEXT NOT NULL
                        CHECK(alarm_type IN
                        ('CommunicationsAlarm','EnvironmentalAlarm',
                         'EquipmentAlarm','ProcessingErrorAlarm',
                         'QualityOfServiceAlarm','IntegrityViolation',
                         'SecurityViolation')),
    perceived_severity  TEXT NOT NULL
                        CHECK(perceived_severity IN
                        ('Critical','Major','Minor','Warning','Indeterminate','Cleared')),
    probable_cause      TEXT,
    specific_problem    TEXT,
    -- Source resource
    source_resource_id  INTEGER REFERENCES tmf_resource(id),
    -- eTOM state
    alarm_state         TEXT DEFAULT 'Active'
                        CHECK(alarm_state IN ('Active','Cleared','Acknowledged')),
    -- Correlation
    root_cause_alarm_id INTEGER REFERENCES tmf_alarm(id),
    -- Provenance
    raised_by_id        INTEGER REFERENCES tmf_party(id),
    acknowledged_by_id  INTEGER REFERENCES tmf_party(id),
    raised_at           TEXT NOT NULL,
    acknowledged_at     TEXT,
    cleared_at          TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Service Problem (TMF656 / SID ServiceProblem)
CREATE TABLE IF NOT EXISTS tmf_service_problem (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_iri         TEXT UNIQUE,
    description         TEXT NOT NULL,
    priority            TEXT CHECK(priority IN ('1-Critical','2-High','3-Medium','4-Low')),
    status              TEXT DEFAULT 'Submitted'
                        CHECK(status IN
                        ('Submitted','Received','In Progress','Pending',
                         'Resolved','Closed','Cancelled')),
    category            TEXT,
    -- Links
    service_id          INTEGER REFERENCES tmf_service(id),
    alarm_id            INTEGER REFERENCES tmf_alarm(id),
    raised_by_id        INTEGER REFERENCES tmf_party(id),
    resolved_by_id      INTEGER REFERENCES tmf_party(id),
    -- SLA breach flag
    sla_violated        INTEGER DEFAULT 0,
    resolution_notes    TEXT,
    submitted_at        TEXT NOT NULL,
    resolved_at         TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ProductOrder (TMF622) — customer order for a product
CREATE TABLE IF NOT EXISTS tmf_product_order (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    order_iri           TEXT UNIQUE,
    order_date          TEXT NOT NULL,
    completion_date     TEXT,
    requested_completion TEXT,
    order_type          TEXT CHECK(order_type IN
                        ('NewProduct','ModifyProduct','SuspendProduct',
                         'ResumeProduct','TerminateProduct','MigrateProduct')),
    state               TEXT DEFAULT 'Acknowledged'
                        CHECK(state IN
                        ('Acknowledged','InProgress','Pending','Held',
                         'Failed','Partial','Complete','Cancelled')),
    -- Customer
    customer_account_id INTEGER REFERENCES tmf_customer_account(id),
    -- Offering
    product_offering_id INTEGER REFERENCES tmf_product_offering(id),
    -- Provenance
    submitted_by_id     INTEGER REFERENCES tmf_party(id),
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ServiceOrder (TMF641) — internal fulfilment order
CREATE TABLE IF NOT EXISTS tmf_service_order (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    order_iri           TEXT UNIQUE,
    order_date          TEXT NOT NULL,
    completion_date     TEXT,
    order_type          TEXT CHECK(order_type IN
                        ('Provision','Decommission','Modify','Migrate')),
    state               TEXT DEFAULT 'Acknowledged'
                        CHECK(state IN
                        ('Acknowledged','InProgress','Pending','Held',
                         'Failed','Partial','Complete','Cancelled')),
    -- Related product order
    product_order_id    INTEGER REFERENCES tmf_product_order(id),
    -- Target service
    service_spec_id     INTEGER REFERENCES tmf_service_spec(id),
    -- Provenance
    submitted_by_id     INTEGER REFERENCES tmf_party(id),
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- PERFORMANCE & QUALITY  — SID ResourcePerformance ABE
-- Maps to AI/ML monitoring, PSI detection, KPI tracking
-- ============================================================

CREATE TABLE IF NOT EXISTS tmf_performance_indicator (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kpi_iri             TEXT UNIQUE,
    name                TEXT NOT NULL,
    description         TEXT,
    unit_of_measure     TEXT,
    kpi_type            TEXT CHECK(kpi_type IN
                        ('AVAILABILITY','LATENCY','THROUGHPUT','PACKET_LOSS',
                         'JITTER','SIGNAL_STRENGTH','CAPACITY','ERROR_RATE',
                         'ML_CONFIDENCE','PSI_SCORE','DRIFT_SCORE')),
    -- Source resource
    resource_id         INTEGER REFERENCES tmf_resource(id),
    -- Source service
    service_id          INTEGER REFERENCES tmf_service(id),
    -- Measurement
    numeric_value       REAL,
    string_value        TEXT,
    -- PROV-O provenance
    recorded_by_party_id INTEGER REFERENCES tmf_party(id),
    confidence_score    REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),
    derivation_method   TEXT CHECK(derivation_method IN
                        ('MEASURED','INFERRED','IMPORTED','SYNTHESIZED')),
    source_ref          TEXT,
    -- Thresholds
    threshold_low       REAL,
    threshold_high      REAL,
    breach_indicator    INTEGER DEFAULT 0,
    -- Time
    observed_at         TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- PHASE 2B — TMF REMAINING DOMAINS  (Months 7–9)
-- ============================================================

-- ── TMF621 — Trouble Ticket Management ────────────────────────
-- SID ABE: ResourceTrouble / CustomerProblem
CREATE TABLE IF NOT EXISTS tmf_trouble_ticket (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_iri          TEXT UNIQUE,
    ticket_type         TEXT NOT NULL CHECK(ticket_type IN
                        ('TroubleTicket','ResourceTroubleTicket','CustomerTroubleTicket')),
    description         TEXT NOT NULL,
    severity            TEXT CHECK(severity IN ('1-Critical','2-High','3-Medium','4-Low')),
    priority            TEXT CHECK(priority IN ('1-Critical','2-High','3-Medium','4-Low')),
    status              TEXT DEFAULT 'New'
                        CHECK(status IN
                        ('New','In Progress','Pending','Resolved','Closed','Cancelled')),
    category            TEXT,
    sub_category        TEXT,
    -- Affected entities (polymorphic)
    affected_resource_id  INTEGER REFERENCES tmf_resource(id),
    affected_service_id   INTEGER REFERENCES tmf_service(id),
    related_alarm_id      INTEGER REFERENCES tmf_alarm(id),
    -- Parties
    raised_by_id        INTEGER REFERENCES tmf_party(id),
    assigned_to_id      INTEGER REFERENCES tmf_party(id),
    resolved_by_id      INTEGER REFERENCES tmf_party(id),
    -- Resolution
    resolution_notes    TEXT,
    expected_resolution TEXT,
    -- SLA
    sla_violated        INTEGER DEFAULT 0,
    -- Timestamps
    submitted_at        TEXT NOT NULL,
    resolved_at         TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ── TMF645 — Network Slice Management ─────────────────────────
-- SID ABE: LogicalResource → NetworkSlice (extended profile)
CREATE TABLE IF NOT EXISTS tmf_network_slice_profile (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_iri         TEXT UNIQUE,
    name                TEXT NOT NULL,
    slice_type          TEXT NOT NULL CHECK(slice_type IN
                        ('eMBB','URLLC','mMTC','Custom')),
    -- 3GPP S-NSSAI identifiers
    sst                 INTEGER,    -- Slice/Service Type: 1=eMBB,2=URLLC,3=mMTC
    sd                  TEXT,       -- Slice Differentiator (optional, 6 hex digits)
    -- SLA parameters
    max_dl_throughput   REAL,       -- Mbps
    max_ul_throughput   REAL,       -- Mbps
    latency_target_ms   REAL,
    reliability_target  REAL,       -- percentage
    max_devices         INTEGER,
    -- Lifecycle
    lifecycle_status    TEXT DEFAULT 'Active'
                        CHECK(lifecycle_status IN
                        ('Design','Test','Active','Retired','Suspended')),
    -- Link to resource (network slice instance)
    resource_id         INTEGER REFERENCES tmf_resource(id),
    -- Agreement coverage
    agreement_id        INTEGER REFERENCES tmf_agreement(id),
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ── TMF657 — Service Quality Management ───────────────────────
-- SID ABE: ServiceQualityReport
CREATE TABLE IF NOT EXISTS tmf_service_quality_report (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    report_iri          TEXT UNIQUE,
    report_type         TEXT CHECK(report_type IN
                        ('SLAComplianceReport','KQIReport','QoSReport','XRReport')),
    description         TEXT,
    status              TEXT DEFAULT 'Active'
                        CHECK(status IN ('Active','Submitted','Acknowledged','Closed')),
    -- Covered service
    service_id          INTEGER REFERENCES tmf_service(id),
    -- Covered agreement / SLA
    agreement_id        INTEGER REFERENCES tmf_agreement(id),
    -- Measurement period
    period_start        TEXT,
    period_end          TEXT,
    -- Quality metrics (JSON-serialised array of {name, value, unit, threshold, compliant})
    quality_metrics     TEXT,
    -- Breach flag
    sla_compliant       INTEGER DEFAULT 1,
    overall_quality_score REAL,
    -- Author
    submitted_by_id     INTEGER REFERENCES tmf_party(id),
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ── TMF674 — Geographic Site Management ───────────────────────
-- SID ABE: GeographicSite (more structured than tmf_place)
CREATE TABLE IF NOT EXISTS tmf_geographic_site (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    site_iri            TEXT UNIQUE,
    name                TEXT NOT NULL,
    site_type           TEXT CHECK(site_type IN
                        ('DataCentre','CellTower','CableHead','Exchange',
                         'CustomerPremises','PartnerPremises','PopSite')),
    description         TEXT,
    -- Physical address (links to tmf_place)
    place_id            INTEGER REFERENCES tmf_place(id),
    -- Operational attributes
    site_category       TEXT,   -- Owned, Leased, CoLocation
    power_supply        TEXT,   -- Mains, Generator, Solar, UPS
    cooling_type        TEXT,   -- Air, Liquid, Natural
    rack_capacity       INTEGER,
    operational_status  TEXT DEFAULT 'Operational'
                        CHECK(operational_status IN
                        ('Operational','Planned','Under Construction','Decommissioned')),
    -- Coordinates (override tmf_place if more precise)
    latitude            REAL,
    longitude           REAL,
    -- Owner/operator
    owner_party_id      INTEGER REFERENCES tmf_party(id),
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ── TMF678 — Customer Bill Management ─────────────────────────
-- SID ABE: BillingAccount → CustomerBill
CREATE TABLE IF NOT EXISTS tmf_customer_bill (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_iri            TEXT UNIQUE,
    bill_number         TEXT UNIQUE NOT NULL,
    bill_type           TEXT CHECK(bill_type IN
                        ('Regular','Final','CreditNote','Proforma','Adjustment')),
    -- Billing account
    customer_account_id INTEGER NOT NULL REFERENCES tmf_customer_account(id),
    -- Period
    billing_period_start TEXT,
    billing_period_end   TEXT,
    bill_date           TEXT NOT NULL,
    payment_due_date    TEXT,
    -- Amounts
    amount_due          REAL NOT NULL,
    tax_amount          REAL DEFAULT 0.0,
    payment_method      TEXT,   -- BankTransfer, CreditCard, DirectDebit
    currency_code       TEXT DEFAULT 'USD',
    -- Status
    state               TEXT DEFAULT 'Sent'
                        CHECK(state IN
                        ('New','OnHold','Sent','PartiallyPaid','Settled',
                         'Disputed','Overdue','Cancelled')),
    -- Dispute
    disputed            INTEGER DEFAULT 0,
    dispute_reason      TEXT,
    -- PDF/attachment
    bill_document_url   TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ── TMF679 — Product Offering Qualification ───────────────────
-- SID ABE: ProductOfferingQualification
CREATE TABLE IF NOT EXISTS tmf_product_offering_qualification (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    poq_iri             TEXT UNIQUE,
    description         TEXT,
    -- Request
    requested_product_offering_id INTEGER REFERENCES tmf_product_offering(id),
    -- Customer context
    customer_account_id INTEGER REFERENCES tmf_customer_account(id),
    install_address_id  INTEGER REFERENCES tmf_place(id),
    -- Qualification result
    state               TEXT DEFAULT 'InProgress'
                        CHECK(state IN
                        ('InProgress','Approved','Rejected','Pending','Cancelled')),
    qualification_result TEXT,  -- ELIGIBLE, NOT_ELIGIBLE, PARTIAL
    eligibility_reason  TEXT,
    -- Technical feasibility
    feasibility_check   INTEGER DEFAULT 0,
    feasibility_notes   TEXT,
    -- Expiry
    valid_for_start     TEXT,
    valid_for_end       TEXT,
    requested_at        TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- TMF EVENT HUB  — TMF630 Part 1 §5 Notification Pattern
-- ============================================================
CREATE TABLE IF NOT EXISTS tmf_event_subscription (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_iri    TEXT UNIQUE,
    -- Subscriber
    subscriber_party_id INTEGER REFERENCES tmf_party(id),
    -- Event filter
    event_type          TEXT NOT NULL,  -- e.g. 'AlarmStateChange','ServiceOrderStateChange'
    event_domain        TEXT,           -- Resource, Service, Product, EngagedParty
    filter_criteria     TEXT,           -- JSON: {severity: 'Critical', resource_type: 'NF'}
    -- Callback
    callback_url        TEXT NOT NULL,
    callback_method     TEXT DEFAULT 'POST' CHECK(callback_method IN ('POST','PUT')),
    auth_header         TEXT,           -- Stored encrypted; token or API key header name
    -- Status
    status              TEXT DEFAULT 'Active'
                        CHECK(status IN ('Active','Suspended','Cancelled','Expired')),
    -- Reliability
    retry_policy        TEXT,           -- JSON: {max_retries: 3, backoff_seconds: 30}
    last_delivered_at   TEXT,
    delivery_failures   INTEGER DEFAULT 0,
    -- Validity
    valid_for_start     TEXT,
    valid_for_end       TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- MULTI-AGENT CONFLICT RESOLUTION  (framework Section 10.1)
-- ============================================================
CREATE TABLE IF NOT EXISTS tmf_conflict_event (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_iri        TEXT UNIQUE,
    -- What assertions conflict
    assertion_a_iri     TEXT NOT NULL,  -- PROV-O entity IRI of the first assertion
    assertion_b_iri     TEXT NOT NULL,  -- PROV-O entity IRI of the conflicting assertion
    conflict_type       TEXT NOT NULL CHECK(conflict_type IN
                        ('VALUE_CONFLICT','STATE_CONFLICT',
                         'PROVENANCE_CONFLICT','SHACL_VIOLATION')),
    description         TEXT NOT NULL,
    -- Tier 1 — SHACL axiom check result
    shacl_violation_msg TEXT,
    -- Tier 2 — priority-based resolution
    resolution_tier     INTEGER CHECK(resolution_tier IN (1,2,3)),
    winning_assertion_iri TEXT,
    resolution_rule     TEXT,   -- e.g. 'measured > derived > imported > default'
    -- Tier 3 — human escalation
    escalated_to_human  INTEGER DEFAULT 0,
    assigned_to_id      INTEGER REFERENCES tmf_party(id),
    human_resolution    TEXT,
    resolved_by_id      INTEGER REFERENCES tmf_party(id),
    -- PROV-O wasInvalidatedBy reference on losing assertion
    invalidation_recorded INTEGER DEFAULT 0,
    -- Status
    status              TEXT DEFAULT 'Open'
                        CHECK(status IN ('Open','Resolving','Resolved','Escalated')),
    detected_at         TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at         TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_res_type      ON tmf_resource(resource_type);
CREATE INDEX IF NOT EXISTS idx_res_spec      ON tmf_resource(resource_spec_id);
CREATE INDEX IF NOT EXISTS idx_res_nf        ON tmf_resource(nf_type);
CREATE INDEX IF NOT EXISTS idx_svc_type      ON tmf_service(service_type);
CREATE INDEX IF NOT EXISTS idx_svc_state     ON tmf_service(state);
CREATE INDEX IF NOT EXISTS idx_alarm_sev     ON tmf_alarm(perceived_severity);
CREATE INDEX IF NOT EXISTS idx_alarm_state   ON tmf_alarm(alarm_state);
CREATE INDEX IF NOT EXISTS idx_alarm_res     ON tmf_alarm(source_resource_id);
CREATE INDEX IF NOT EXISTS idx_kpi_res       ON tmf_performance_indicator(resource_id);
CREATE INDEX IF NOT EXISTS idx_kpi_type      ON tmf_performance_indicator(kpi_type);
CREATE INDEX IF NOT EXISTS idx_party_type    ON tmf_party(party_type);
CREATE INDEX IF NOT EXISTS idx_prod_ord_st   ON tmf_product_order(state);
CREATE INDEX IF NOT EXISTS idx_svc_ord_st    ON tmf_service_order(state);
CREATE INDEX IF NOT EXISTS idx_problem_st    ON tmf_service_problem(status);
CREATE INDEX IF NOT EXISTS idx_char_owner    ON tmf_characteristic(owner_type, owner_id);

-- Phase 2B indexes
CREATE INDEX IF NOT EXISTS idx_ticket_status ON tmf_trouble_ticket(status);
CREATE INDEX IF NOT EXISTS idx_ticket_res    ON tmf_trouble_ticket(affected_resource_id);
CREATE INDEX IF NOT EXISTS idx_sliceprof_res ON tmf_network_slice_profile(resource_id);
CREATE INDEX IF NOT EXISTS idx_sqr_svc       ON tmf_service_quality_report(service_id);
CREATE INDEX IF NOT EXISTS idx_sqr_sla       ON tmf_service_quality_report(sla_compliant);
CREATE INDEX IF NOT EXISTS idx_bill_acct     ON tmf_customer_bill(customer_account_id);
CREATE INDEX IF NOT EXISTS idx_bill_state    ON tmf_customer_bill(state);
CREATE INDEX IF NOT EXISTS idx_poq_state     ON tmf_product_offering_qualification(state);
CREATE INDEX IF NOT EXISTS idx_evtsub_status ON tmf_event_subscription(status);
CREATE INDEX IF NOT EXISTS idx_evtsub_type   ON tmf_event_subscription(event_type);
CREATE INDEX IF NOT EXISTS idx_conflict_st   ON tmf_conflict_event(status);
CREATE INDEX IF NOT EXISTS idx_conflict_tier ON tmf_conflict_event(resolution_tier);

-- ============================================================
-- PHASE RT: Runtime Layer
-- ============================================================
-- Tracks LLM flavor registry, assembled payloads, and data
-- grounding events for full PROV-O auditability of all AI calls.
-- ============================================================

-- Runtime Flavor Registry — mirrors the JSON flavor files in DB form
CREATE TABLE IF NOT EXISTS runtime_flavor (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    description         TEXT,
    sensitivity_tier    TEXT NOT NULL
                        CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),
    owl_classes         TEXT NOT NULL,   -- JSON array of class name strings
    shacl_shapes        TEXT,           -- JSON array of shape name strings
    context_terms       TEXT,           -- JSON object {term: IRI, ...}
    db_tables           TEXT NOT NULL,  -- JSON array of table name strings
    system_prompt_hint  TEXT,
    cq_ids              TEXT,           -- JSON array of CQ ID strings
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Runtime Payload — records every assembled LLM payload
CREATE TABLE IF NOT EXISTS runtime_payload (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_id          TEXT NOT NULL UNIQUE,   -- UUID4
    flavor_name         TEXT NOT NULL,
    question            TEXT NOT NULL,
    model_id            TEXT,
    token_budget        INTEGER DEFAULT 4000,
    assembled_at        TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Runtime Grounding — records every data grounding event
CREATE TABLE IF NOT EXISTS runtime_grounding (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    grounding_id        TEXT NOT NULL UNIQUE,   -- UUID4
    payload_id          TEXT REFERENCES runtime_payload(payload_id),
    flavor_name         TEXT NOT NULL,
    question            TEXT NOT NULL,
    tables_queried      TEXT,       -- JSON array of table names
    record_count        INTEGER DEFAULT 0,
    grounded_at         TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Phase RT indexes
CREATE INDEX IF NOT EXISTS idx_rt_flavor_name      ON runtime_flavor(name);
CREATE INDEX IF NOT EXISTS idx_rt_payload_flavor   ON runtime_payload(flavor_name);
CREATE INDEX IF NOT EXISTS idx_rt_grounding_payload ON runtime_grounding(payload_id);
