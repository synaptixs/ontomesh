-- ============================================================
-- Seed Data — Telecom Network Operations Example
-- (Swap this file to target any other industry)
-- ============================================================

-- ── ONTOLOGY METADATA ─────────────────────────────────────────
-- TABLE-level annotations
INSERT INTO ontology_metadata (target_type, table_name, semantic_type, label, description, sensitivity_tier, is_event_class, skos_pref_label, skos_alt_labels, cq_coverage) VALUES
('TABLE','organizations','Organization','Organization','A legal or operational entity that owns, operates, or governs assets.','Internal',0,'Organization','Enterprise,Company,Entity','CQ-001,CQ-006'),
('TABLE','asset_types','AssetType','Asset Type','A classification category for managed assets.','Public',0,'Asset Type','Asset Category,Resource Class','CQ-002'),
('TABLE','assets','Asset','Asset','A physical or logical resource managed by the organization.','Internal',0,'Asset','Resource,Managed Object,Network Element','CQ-001,CQ-002,CQ-003,CQ-007'),
('TABLE','agents','Agent','Agent','A human, system, AI agent, or sensor that produces or acts on domain facts.','Internal',0,'Agent','Actor,System Agent,Sensor','CQ-004,CQ-005'),
('TABLE','roles','Role','Role','A contextual function an agent performs in a specific scope.','Internal',0,'Role','Function,Responsibility','CQ-006'),
('TABLE','policies','Policy','Policy','A rule or constraint that governs operations.','Internal',0,'Policy','Rule,Regulation,SLA,Standard','CQ-007'),
('TABLE','domain_events','DomainEvent','Domain Event','A significant occurrence in the domain that changes state or produces evidence.','Internal',1,'Domain Event','Operation,Activity,Incident,Inspection','CQ-003,CQ-004,CQ-005,CQ-007'),
('TABLE','observations','ObservationRecord','Observation','A measured, computed, or imported fact about an asset or event, with provenance.','Confidential',0,'Observation','Measurement,Reading,Detection,Finding','CQ-004,CQ-005,CQ-008'),
('TABLE','policies','Policy','Policy','A rule or constraint that governs asset operations and agent behaviour.','Internal',0,'Policy','Rule,Standard,SLA','CQ-007'),
('TABLE','policy_applications','PolicyApplication','Policy Application','Records the application of a policy to an event or asset with outcome.','Internal',1,'Policy Application','Compliance Check,Audit Record','CQ-007');

-- COLUMN-level annotations (selected important columns)
INSERT INTO ontology_metadata (target_type, table_name, column_name, semantic_type, label, description, sensitivity_tier, cq_coverage) VALUES
('COLUMN','assets','status','xsd:string','Asset Status','Current operational lifecycle status of the asset.','Internal','CQ-002'),
('COLUMN','assets','external_id','xsd:string','External Identifier','Identifier used in external systems (e.g. OSS/BSS, NMS).','Internal','CQ-001'),
('COLUMN','observations','confidence_score','xsd:decimal','Confidence Score','Numeric confidence in the observation value between 0.0 and 1.0.','Confidential','CQ-005'),
('COLUMN','observations','derivation_method','xsd:string','Derivation Method','How the value was obtained: MEASURED, INFERRED, IMPORTED, or SYNTHESIZED.','Internal','CQ-005'),
('COLUMN','observations','source_ref','xsd:anyURI','Source Reference','IRI or document reference for the external source of this observation.','Internal','CQ-005'),
('COLUMN','domain_events','event_type','xsd:string','Event Type','Subclass discriminator for OWL event class hierarchy.','Internal','CQ-003'),
('COLUMN','agents','agent_iri','xsd:anyURI','Agent IRI','Persistent IRI for use in PROV-O provenance graphs.','Internal','CQ-004'),
('COLUMN','agents','credential_expiry','xsd:dateTime','Credential Expiry','Expiry timestamp for AI agent credentials.','Confidential','CQ-006'),
('COLUMN','policies','policy_type','xsd:string','Policy Type','Category of policy: OPERATIONAL, COMPLIANCE, SECURITY, SLA, SAFETY.','Internal','CQ-007');

-- ── ASSET TYPES (Telecom) ────────────────────────────────────
INSERT INTO asset_types (code, label, description, unit_of_measure) VALUES
('NETWORK_ELEMENT','Network Element','Any physical or virtual network function node.',NULL),
('AMF','Access and Mobility Function','5G core AMF network function.',NULL),
('SMF','Session Management Function','5G core SMF network function.',NULL),
('UPF','User Plane Function','5G core UPF network function.',NULL),
('RAN_NODE','RAN Node','Radio access network node (gNB, eNB).',NULL),
('TRANSMISSION','Transmission Link','Fibre or microwave transmission segment.','Gbps'),
('SERVER','Compute Server','Physical or virtual compute host.',NULL),
('SENSOR','Monitoring Sensor','A device that records measurements against assets.',NULL);

-- Link subtypes
UPDATE asset_types SET parent_type_id = (SELECT id FROM asset_types WHERE code='NETWORK_ELEMENT') WHERE code IN ('AMF','SMF','UPF','RAN_NODE','TRANSMISSION');

-- ── ORGANIZATIONS ────────────────────────────────────────────
INSERT INTO organizations (name, org_type, jurisdiction) VALUES
('Global Telecom Corp', 'INTERNAL', 'US'),
('NetOps Division', 'INTERNAL', 'US'),
('Vendor Alpha', 'SUPPLIER', 'DE'),
('Regulator Beta', 'PARTNER', 'EU');

-- ── AGENTS ──────────────────────────────────────────────────
INSERT INTO agents (agent_iri, name, agent_type, org_id, credential_expiry, authorized_tiers) VALUES
('https://gtc.example.com/agents/noc-engineer-01','NOC Engineer 01','HUMAN',2,NULL,'Public,Internal,Confidential'),
('https://gtc.example.com/agents/ml-monitor-agent','ML Monitor Agent','AI_AGENT',2,'2026-12-31T23:59:59Z','Public,Internal'),
('https://gtc.example.com/agents/rf-sensor-007','RF Sensor Node 7','SENSOR',2,NULL,'Public,Internal'),
('https://gtc.example.com/agents/oss-system','OSS Integration System','SYSTEM',2,NULL,'Public,Internal,Confidential'),
('https://gtc.example.com/agents/audit-bot','Compliance Audit Bot','AI_AGENT',2,'2026-06-30T23:59:59Z','Public,Internal,Confidential');

-- ── ROLES ───────────────────────────────────────────────────
INSERT INTO roles (code, label, description) VALUES
('ASSET_OWNER','Asset Owner','Accountable for the asset lifecycle and compliance.'),
('ASSET_OPERATOR','Asset Operator','Responsible for day-to-day asset operation.'),
('INCIDENT_RESPONDER','Incident Responder','Responds to and resolves asset incidents.'),
('COMPLIANCE_AUDITOR','Compliance Auditor','Reviews policy compliance and produces audit records.'),
('DATA_PRODUCER','Data Producer','An agent that records observations and measurements.');

-- ── POLICIES ────────────────────────────────────────────────
INSERT INTO policies (code, title, policy_type, description, effective_from, governing_org_id) VALUES
('SLA-AVAIL-99.99','Network Availability SLA 99.99%','SLA','Core network elements must maintain 99.99% monthly availability.','2025-01-01',1),
('SEC-CRED-90D','Agent Credential Rotation 90-Day','SECURITY','AI agent credentials must be rotated every 90 days.','2025-01-01',1),
('COMP-AUDIT-Q','Quarterly Compliance Audit','COMPLIANCE','All network elements must be audited for policy compliance quarterly.','2025-01-01',4),
('OPS-INC-RTO-4H','Incident RTO 4 Hours','OPERATIONAL','All critical incidents must be resolved within 4 hours.','2025-01-01',1);

-- ── ASSETS ──────────────────────────────────────────────────
INSERT INTO assets (external_id, name, asset_type_id, owner_org_id, operator_org_id, location_code, status, commissioned_at) VALUES
('NE-AMF-001', 'AMF Node — Region East',  (SELECT id FROM asset_types WHERE code='AMF'), 1,2,'REGION-EAST','ACTIVE','2024-01-15'),
('NE-SMF-001', 'SMF Node — Region East',  (SELECT id FROM asset_types WHERE code='SMF'), 1,2,'REGION-EAST','ACTIVE','2024-01-15'),
('NE-UPF-001', 'UPF Node — Region East',  (SELECT id FROM asset_types WHERE code='UPF'), 1,2,'REGION-EAST','ACTIVE','2024-01-15'),
('NE-RAN-042', 'gNB Site 042',            (SELECT id FROM asset_types WHERE code='RAN_NODE'),1,2,'SITE-042','ACTIVE','2023-06-01'),
('NE-RAN-043', 'gNB Site 043',            (SELECT id FROM asset_types WHERE code='RAN_NODE'),1,2,'SITE-043','UNDER_MAINTENANCE','2023-06-01'),
('SENSOR-007',  'RF Sensor Node 7',       (SELECT id FROM asset_types WHERE code='SENSOR'),  1,2,'SITE-042','ACTIVE','2024-03-01');

-- ── AGENT ROLES ─────────────────────────────────────────────
INSERT INTO agent_roles (agent_id, role_id, scope_asset_id, valid_from) VALUES
(1,(SELECT id FROM roles WHERE code='ASSET_OPERATOR'),NULL,'2024-01-01'),
(2,(SELECT id FROM roles WHERE code='DATA_PRODUCER'), NULL,'2024-01-01'),
(3,(SELECT id FROM roles WHERE code='DATA_PRODUCER'), (SELECT id FROM assets WHERE external_id='SENSOR-007'),'2024-03-01'),
(5,(SELECT id FROM roles WHERE code='COMPLIANCE_AUDITOR'),NULL,'2024-01-01');

-- ── DOMAIN EVENTS ────────────────────────────────────────────
INSERT INTO domain_events (event_iri, event_type, title, asset_id, initiated_by, status, outcome, policy_id, started_at, completed_at) VALUES
('https://gtc.example.com/events/evt-001','INCIDENT','High packet loss on gNB 043',
 (SELECT id FROM assets WHERE external_id='NE-RAN-043'),(SELECT id FROM agents WHERE name='NOC Engineer 01'),'COMPLETED','RESOLVED',
 (SELECT id FROM policies WHERE code='OPS-INC-RTO-4H'),'2026-04-10T02:15:00Z','2026-04-10T05:44:00Z'),

('https://gtc.example.com/events/evt-002','MAINTENANCE','Scheduled maintenance — UPF East',
 (SELECT id FROM assets WHERE external_id='NE-UPF-001'),(SELECT id FROM agents WHERE name='NOC Engineer 01'),'IN_PROGRESS',NULL,
 (SELECT id FROM policies WHERE code='SLA-AVAIL-99.99'),'2026-04-15T01:00:00Z',NULL),

('https://gtc.example.com/events/evt-003','COMPLIANCE_AUDIT','Q1 2026 Compliance Audit — AMF East',
 (SELECT id FROM assets WHERE external_id='NE-AMF-001'),(SELECT id FROM agents WHERE name='Compliance Audit Bot'),'COMPLETED','COMPLIANT',
 (SELECT id FROM policies WHERE code='COMP-AUDIT-Q'),'2026-04-01T09:00:00Z','2026-04-01T11:30:00Z'),

('https://gtc.example.com/events/evt-004','INSPECTION','RF quality inspection — gNB 042',
 (SELECT id FROM assets WHERE external_id='NE-RAN-042'),(SELECT id FROM agents WHERE name='NOC Engineer 01'),'COMPLETED','PASS',NULL,
 '2026-04-12T10:00:00Z','2026-04-12T11:00:00Z');

-- ── EVENT PARTICIPANTS ───────────────────────────────────────
INSERT INTO event_participants (event_id, agent_id, participation_role) VALUES
(1,(SELECT id FROM agents WHERE name='NOC Engineer 01'),'INITIATOR'),
(1,(SELECT id FROM agents WHERE name='ML Monitor Agent'),'OBSERVER'),
(2,(SELECT id FROM agents WHERE name='NOC Engineer 01'),'EXECUTOR'),
(3,(SELECT id FROM agents WHERE name='Compliance Audit Bot'),'INITIATOR'),
(4,(SELECT id FROM agents WHERE name='NOC Engineer 01'),'INITIATOR'),
(4,(SELECT id FROM agents WHERE name='RF Sensor Node 7'),'OBSERVER');

-- ── OBSERVATIONS ─────────────────────────────────────────────
INSERT INTO observations (observation_iri, observation_type, asset_id, event_id, recorded_by, numeric_value, unit_of_measure, confidence_score, derivation_method, source_ref, observed_at) VALUES
('https://gtc.example.com/obs/obs-001','PACKET_LOSS_RATE',
 (SELECT id FROM assets WHERE external_id='NE-RAN-043'),1,
 (SELECT id FROM agents WHERE name='ML Monitor Agent'),
 18.7,'percent',0.98,'MEASURED','https://oss.gtc.example.com/metrics/ran043','2026-04-10T02:14:00Z'),

('https://gtc.example.com/obs/obs-002','AVAILABILITY',
 (SELECT id FROM assets WHERE external_id='NE-AMF-001'),NULL,
 (SELECT id FROM agents WHERE name='OSS Integration System'),
 99.997,'percent',0.99,'MEASURED','https://oss.gtc.example.com/metrics/amf001','2026-04-10T00:00:00Z'),

('https://gtc.example.com/obs/obs-003','RF_SIGNAL_STRENGTH',
 (SELECT id FROM assets WHERE external_id='NE-RAN-042'),4,
 (SELECT id FROM agents WHERE name='RF Sensor Node 7'),
 -72.4,'dBm',0.94,'MEASURED',NULL,'2026-04-12T10:05:00Z'),

('https://gtc.example.com/obs/obs-004','COMPLIANCE_SCORE',
 (SELECT id FROM assets WHERE external_id='NE-AMF-001'),3,
 (SELECT id FROM agents WHERE name='Compliance Audit Bot'),
 0.96,'score',0.91,'SYNTHESIZED','https://audit.gtc.example.com/q1-2026','2026-04-01T11:25:00Z');

-- ── POLICY APPLICATIONS ──────────────────────────────────────
INSERT INTO policy_applications (policy_id, event_id, asset_id, applied_by, outcome, notes) VALUES
((SELECT id FROM policies WHERE code='OPS-INC-RTO-4H'),    1,NULL,(SELECT id FROM agents WHERE name='NOC Engineer 01'),'COMPLIANT','Resolved in 3h29m, within 4h RTO.'),
((SELECT id FROM policies WHERE code='COMP-AUDIT-Q'),       3,(SELECT id FROM assets WHERE external_id='NE-AMF-001'),(SELECT id FROM agents WHERE name='Compliance Audit Bot'),'COMPLIANT','Score 0.96, threshold 0.80.'),
((SELECT id FROM policies WHERE code='SLA-AVAIL-99.99'),NULL,(SELECT id FROM assets WHERE external_id='NE-AMF-001'),(SELECT id FROM agents WHERE name='OSS Integration System'),'COMPLIANT','Monthly availability 99.997%.'),
((SELECT id FROM policies WHERE code='SLA-AVAIL-99.99'),NULL,(SELECT id FROM assets WHERE external_id='NE-RAN-043'),(SELECT id FROM agents WHERE name='OSS Integration System'),'NON_COMPLIANT','Availability degraded during incident evt-001.');
