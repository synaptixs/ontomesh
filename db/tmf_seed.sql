-- ============================================================
-- TMF SID Seed Data  v1.0
-- Ontology metadata with full TMF alignment + 5G sample data
-- ============================================================

-- ── TMF ONTOLOGY METADATA ────────────────────────────────────
-- TABLE-level annotations — all 8 SID domains represented

INSERT INTO ontology_metadata (
    target_type, table_name, semantic_type, label, description,
    sensitivity_tier, is_event_class,
    skos_pref_label, skos_alt_labels, cq_coverage,
    sid_domain, sid_abe, tmf_api_id, tmf_api_version, tmf_entity_name, etom_process
) VALUES

-- COMMON DOMAIN
('TABLE','tmf_place','GeographicLocation',
 'Geographic Place','A geographic location, address, or site per TMF673/674/675.',
 'Internal',0,'Geographic Place','Location,Address,Site','CQ-001,CQ-002',
 'Common','Location','TMF673','v4.0','GeographicAddress','1.1.1'),

('TABLE','tmf_characteristic','Characteristic',
 'Characteristic','A key-value attribute pair that extends any entity per SID Characteristic ABE.',
 'Internal',0,'Characteristic','Attribute,Property,Feature','CQ-002',
 'Common','Characteristic',NULL,NULL,'Characteristic',NULL),

-- RESOURCE DOMAIN
('TABLE','tmf_resource_spec','ResourceSpecification',
 'Resource Specification','Catalog template for a resource type. Specification pattern per SID/TMF634.',
 'Public',0,'Resource Specification','Resource Template,Resource Catalog Entry','CQ-001,CQ-002',
 'Resource','Resource Specification','TMF634','v4.0','ResourceSpecification','1.1.1'),

('TABLE','tmf_resource','Resource',
 'Resource','A logical or physical telecom resource instance (TMF639). Covers NetworkFunction, Equipment, IPAddress.',
 'Internal',0,'Resource','Network Element,Network Function,Physical Asset','CQ-001,CQ-002,CQ-003,CQ-TMF01',
 'Resource','Logical Resource','TMF639','v5.0','Resource','1.1.1'),

('TABLE','tmf_resource_relationship','ResourceRelationship',
 'Resource Relationship','Typed association between two resources (composedOf, connectsTo, dependsOn).',
 'Internal',0,'Resource Relationship','Resource Association,Network Topology Link','CQ-TMF01',
 'Resource','Resource Topology','TMF639','v5.0','ResourceRelationship','1.1.1'),

-- SERVICE DOMAIN
('TABLE','tmf_service_spec','ServiceSpecification',
 'Service Specification','Catalog definition of a service type. Specification pattern per SID/TMF633.',
 'Public',0,'Service Specification','Service Template,Service Catalog Entry','CQ-003',
 'Service','Service Specification','TMF633','v4.0','ServiceSpecification','1.1.2'),

('TABLE','tmf_service','Service',
 'Service','An active service instance in the service inventory (TMF638). Covers CFS and RFS.',
 'Internal',0,'Service','Customer Facing Service,Resource Facing Service','CQ-003,CQ-TMF02',
 'Service','Customer Facing Service','TMF638','v4.0','Service','1.1.2'),

-- PRODUCT DOMAIN
('TABLE','tmf_product_spec','ProductSpecification',
 'Product Specification','Specification of a product type per SID Product domain/TMF620.',
 'Public',0,'Product Specification','Product Template,Product Catalog Entry','CQ-004',
 'Product','Product Specification','TMF620','v5.0','ProductSpecification','1.1.3'),

('TABLE','tmf_product_offering','ProductOffering',
 'Product Offering','A commercial offering available to customers per TMF620.',
 'Public',0,'Product Offering','Commercial Offer,Tariff Plan','CQ-004',
 'Product','Product Offering','TMF620','v5.0','ProductOffering','1.1.3'),

('TABLE','tmf_product','Product',
 'Product','A product instance subscribed to by a party per TMF637.',
 'Confidential',0,'Product','Subscribed Product,Active Subscription','CQ-004,CQ-TMF03',
 'Product','Product','TMF637','v4.0','Product','1.1.3'),

-- ENGAGED PARTY DOMAIN
('TABLE','tmf_party','Party',
 'Party','An individual or organisation that plays a role in the business (TMF632).',
 'Confidential',0,'Party','Individual,Organization,Customer,Partner','CQ-005,CQ-TMF04',
 'EngagedParty','Party','TMF632','v5.0','Party','1.1.4'),

('TABLE','tmf_party_role','PartyRole',
 'Party Role','A contextual role a party plays, such as Customer or Partner (TMF669).',
 'Internal',0,'Party Role','Role,Function,Relationship','CQ-005',
 'EngagedParty','Party Role','TMF669','v5.0','PartyRole','1.1.4'),

('TABLE','tmf_customer_account','CustomerAccount',
 'Customer Account','A billing and service management account per TMF666.',
 'Confidential',0,'Customer Account','Account,Billing Account','CQ-005,CQ-TMF03',
 'EngagedParty','Customer Account','TMF666','v5.0','CustomerAccount','1.1.4'),

('TABLE','tmf_agreement','Agreement',
 'Agreement','A commercial, SLA, or roaming agreement between parties (TMF651).',
 'Confidential',0,'Agreement','SLA,Contract,Service Level Agreement','CQ-005,CQ-TMF05',
 'EngagedParty','Agreement','TMF651','v4.0','Agreement','1.1.5'),

-- ENTERPRISE DOMAIN
('TABLE','tmf_policy','Policy',
 'Policy','A rule or constraint governing operations, network, or compliance.',
 'Internal',0,'Policy','Rule,Regulation,Standard,SLA Policy','CQ-006',
 'Enterprise','Policy','TMF672','v4.0','Policy','1.4.1'),

-- ALARM / TROUBLE DOMAIN (TMF642)
('TABLE','tmf_alarm','Alarm',
 'Alarm','A network fault notification raised by a network function or element (TMF642).',
 'Internal',1,'Alarm','Fault,Notification,Alert','CQ-007,CQ-TMF06',
 'Resource','Resource Trouble','TMF642','v4.0','Alarm','1.4.4'),

-- SERVICE PROBLEM DOMAIN
('TABLE','tmf_service_problem','ServiceProblem',
 'Service Problem','A service quality or availability problem raised against a customer service (TMF656).',
 'Confidential',1,'Service Problem','Trouble Ticket,Incident,Fault Report','CQ-007,CQ-TMF06',
 'Service','Service Trouble','TMF656','v4.0','ServiceProblem','1.4.2'),

-- ORDERING DOMAIN
('TABLE','tmf_product_order','ProductOrder',
 'Product Order','A customer request to provision, modify, or terminate a product (TMF622).',
 'Confidential',1,'Product Order','Customer Order,Service Request','CQ-004,CQ-TMF03',
 'Product','Customer Order','TMF622','v5.0','ProductOrder','1.2.1'),

('TABLE','tmf_service_order','ServiceOrder',
 'Service Order','An internal fulfilment order to provision or modify a service (TMF641).',
 'Internal',1,'Service Order','Fulfilment Order,Provisioning Order','CQ-003,CQ-TMF02',
 'Service','Service Order','TMF641','v4.0','ServiceOrder','1.1.2'),

-- PERFORMANCE / KPI DOMAIN
('TABLE','tmf_performance_indicator','PerformanceIndicator',
 'Performance Indicator','A KPI measurement or ML-derived metric with PROV-O provenance.',
 'Confidential',0,'Performance Indicator','KPI,Metric,Measurement,Observation','CQ-008,CQ-TMF07',
 'Resource','Resource Performance','TMF688','v4.0','PerformanceIndicator','1.4.3');

-- ── COLUMN-LEVEL TMF ANNOTATIONS ────────────────────────────
INSERT INTO ontology_metadata (
    target_type, table_name, column_name, semantic_type, label, description,
    sensitivity_tier, tmf_entity_name, cq_coverage
) VALUES
('COLUMN','tmf_resource','nf_type','xsd:string','Network Function Type',
 'eTOM/5G network function discriminator: AMF, SMF, UPF, gNB, PCF, UDM, AUSF, NRF.','Internal','NetworkFunctionType','CQ-TMF01'),
('COLUMN','tmf_resource','operational_state','xsd:string','Operational State',
 'SID OperationalState: Enabled or Disabled (eTOM resource state machine).','Internal','OperationalState','CQ-TMF01'),
('COLUMN','tmf_resource','admin_state','xsd:string','Administrative State',
 'SID AdministrativeState: Locked, Unlocked, Shutting Down.','Internal','AdministrativeState','CQ-TMF01'),
('COLUMN','tmf_alarm','perceived_severity','xsd:string','Perceived Severity',
 'ITU-T X.733 / TMF642 alarm severity: Critical, Major, Minor, Warning, Indeterminate, Cleared.','Internal','PerceivedSeverity','CQ-007,CQ-TMF06'),
('COLUMN','tmf_alarm','probable_cause','xsd:string','Probable Cause',
 'ITU-T probable cause code for the alarm (e.g. softwareError, equipmentFailure).','Internal','ProbableCause','CQ-TMF06'),
('COLUMN','tmf_performance_indicator','confidence_score','xsd:decimal','Confidence Score',
 'Numeric confidence in the measurement or derived value. Range 0.0–1.0.','Confidential','ConfidenceScore','CQ-008'),
('COLUMN','tmf_performance_indicator','derivation_method','xsd:string','Derivation Method',
 'How the value was obtained per PROV-O: MEASURED, INFERRED, IMPORTED, SYNTHESIZED.','Internal','DerivationMethod','CQ-008'),
('COLUMN','tmf_party','party_iri','xsd:anyURI','Party IRI',
 'Persistent IRI for use in PROV-O provenance graphs and TMF632 external IDs.','Confidential','PartyIRI','CQ-005');

-- ── GEOGRAPHIC PLACES ────────────────────────────────────────
INSERT INTO tmf_place (place_iri, name, place_type, city, state_or_province, country, latitude, longitude) VALUES
('https://gtc.example.com/places/dc-east','Data Centre East','GEOGRAPHIC_SITE','New York','NY','US',40.7128,-74.0060),
('https://gtc.example.com/places/dc-west','Data Centre West','GEOGRAPHIC_SITE','San Jose','CA','US',37.3382,-121.8863),
('https://gtc.example.com/places/site-042','RAN Site 042','GEOGRAPHIC_SITE','Brooklyn','NY','US',40.6501,-73.9496),
('https://gtc.example.com/places/site-043','RAN Site 043','GEOGRAPHIC_SITE','Queens','NY','US',40.7282,-73.7949),
('https://gtc.example.com/places/hq','HQ Office','GEOGRAPHIC_ADDRESS','New York','NY','US',40.7580,-73.9855);

-- ── RESOURCE SPECIFICATIONS ───────────────────────────────────
INSERT INTO tmf_resource_spec (spec_iri, name, version, description, category, lifecycle_status) VALUES
('https://gtc.example.com/catalog/spec/amf-5g-v2','AMF 5G Specification','2.0','3GPP TS 23.501 Access and Mobility Function — virtualized NF spec.','LOGICAL','Active'),
('https://gtc.example.com/catalog/spec/smf-5g-v2','SMF 5G Specification','2.0','3GPP TS 23.501 Session Management Function — virtualized NF spec.','LOGICAL','Active'),
('https://gtc.example.com/catalog/spec/upf-5g-v2','UPF 5G Specification','2.0','3GPP TS 23.501 User Plane Function — virtualized NF spec.','LOGICAL','Active'),
('https://gtc.example.com/catalog/spec/gnb-v3','gNB Radio Specification','3.0','5G NR gNodeB base station — physical resource spec.','PHYSICAL','Active'),
('https://gtc.example.com/catalog/spec/nrf-5g','NRF 5G Specification','1.0','3GPP NF Repository Function spec.','LOGICAL','Active'),
('https://gtc.example.com/catalog/spec/pcf-5g','PCF 5G Specification','1.0','3GPP Policy Control Function spec.','LOGICAL','Active'),
('https://gtc.example.com/catalog/spec/ns-embb','Network Slice eMBB Spec','1.0','Enhanced Mobile Broadband network slice specification.','LOGICAL','Active'),
('https://gtc.example.com/catalog/spec/ns-urllc','Network Slice URLLC Spec','1.0','Ultra-Reliable Low Latency Communication slice specification.','LOGICAL','Active');

-- ── 5G NETWORK RESOURCES (TMF639) ────────────────────────────
INSERT INTO tmf_resource (resource_iri, name, resource_type, resource_spec_id, nf_type,
    operational_state, admin_state, usage_state, place_id, external_id, external_system, start_operating_date) VALUES
-- Core NFs — Data Centre East
('https://gtc.example.com/resources/amf-east-01','AMF East 01','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='AMF 5G Specification'),'AMF',
 'Enabled','Unlocked','Active',1,'NF-AMF-EAST-01','5G-NMS','2024-01-15'),
('https://gtc.example.com/resources/smf-east-01','SMF East 01','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='SMF 5G Specification'),'SMF',
 'Enabled','Unlocked','Active',1,'NF-SMF-EAST-01','5G-NMS','2024-01-15'),
('https://gtc.example.com/resources/upf-east-01','UPF East 01','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='UPF 5G Specification'),'UPF',
 'Enabled','Unlocked','Active',1,'NF-UPF-EAST-01','5G-NMS','2024-01-15'),
('https://gtc.example.com/resources/nrf-east-01','NRF East 01','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='NRF 5G Specification'),'NRF',
 'Enabled','Unlocked','Active',1,'NF-NRF-EAST-01','5G-NMS','2024-01-15'),
('https://gtc.example.com/resources/pcf-east-01','PCF East 01','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='PCF 5G Specification'),'PCF',
 'Enabled','Unlocked','Active',1,'NF-PCF-EAST-01','5G-NMS','2024-01-15'),
-- RAN sites
('https://gtc.example.com/resources/gnb-042','gNB Site 042','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='gNB Radio Specification'),'gNB',
 'Enabled','Unlocked','Active',3,'RAN-GNB-042','NMS-RAN','2023-06-01'),
('https://gtc.example.com/resources/gnb-043','gNB Site 043','NETWORK_FUNCTION',
 (SELECT id FROM tmf_resource_spec WHERE name='gNB Radio Specification'),'gNB',
 'Disabled','Locked','Idle',4,'RAN-GNB-043','NMS-RAN','2023-06-01'),
-- Network slices (LogicalResource)
('https://gtc.example.com/resources/ns-embb-01','eMBB Slice East 01','NETWORK_SLICE',
 (SELECT id FROM tmf_resource_spec WHERE name='Network Slice eMBB Spec'),NULL,
 'Enabled','Unlocked','Active',1,'NS-EMBB-01','5G-NMS','2024-03-01'),
('https://gtc.example.com/resources/ns-urllc-01','URLLC Slice East 01','NETWORK_SLICE',
 (SELECT id FROM tmf_resource_spec WHERE name='Network Slice URLLC Spec'),NULL,
 'Enabled','Unlocked','Active',1,'NS-URLLC-01','5G-NMS','2024-06-01');

-- Resource relationships (topology)
INSERT INTO tmf_resource_relationship (resource_id, related_resource_id, relationship_type) VALUES
((SELECT id FROM tmf_resource WHERE name='AMF East 01'),(SELECT id FROM tmf_resource WHERE name='NRF East 01'),'relies-on'),
((SELECT id FROM tmf_resource WHERE name='SMF East 01'),(SELECT id FROM tmf_resource WHERE name='UPF East 01'),'controls'),
((SELECT id FROM tmf_resource WHERE name='SMF East 01'),(SELECT id FROM tmf_resource WHERE name='PCF East 01'),'relies-on'),
((SELECT id FROM tmf_resource WHERE name='eMBB Slice East 01'),(SELECT id FROM tmf_resource WHERE name='AMF East 01'),'composedOf'),
((SELECT id FROM tmf_resource WHERE name='eMBB Slice East 01'),(SELECT id FROM tmf_resource WHERE name='UPF East 01'),'composedOf'),
((SELECT id FROM tmf_resource WHERE name='gNB Site 042'),(SELECT id FROM tmf_resource WHERE name='AMF East 01'),'connectsTo');

-- ── SERVICE SPECS & INSTANCES (TMF633/638) ────────────────────
INSERT INTO tmf_service_spec (spec_iri, name, version, service_type, description) VALUES
('https://gtc.example.com/catalog/svcspec/5g-mobile-broadband','5G Mobile Broadband RFS','2.0',
 'RESOURCE_FACING_SERVICE','5G eMBB resource-facing service delivered via 5G NR + Core.'),
('https://gtc.example.com/catalog/svcspec/5g-urllc-connectivity','5G URLLC Connectivity RFS','1.0',
 'RESOURCE_FACING_SERVICE','Ultra-reliable low-latency connectivity slice-based service.'),
('https://gtc.example.com/catalog/svcspec/enterprise-5g-cfs','Enterprise 5G CFS','1.0',
 'CUSTOMER_FACING_SERVICE','Customer-facing 5G connectivity service for enterprise accounts.'),
('https://gtc.example.com/catalog/svcspec/iot-connectivity-cfs','IoT Connectivity CFS','1.0',
 'CUSTOMER_FACING_SERVICE','Customer-facing IoT device connectivity service.');

INSERT INTO tmf_service (service_iri, name, service_type, service_spec_id,
    state, realising_resource_id, start_date) VALUES
('https://gtc.example.com/services/svc-rfs-embb-01','eMBB RFS East 01',
 'RESOURCE_FACING_SERVICE',
 (SELECT id FROM tmf_service_spec WHERE name='5G Mobile Broadband RFS'),
 'Active',(SELECT id FROM tmf_resource WHERE name='eMBB Slice East 01'),'2024-03-01'),
('https://gtc.example.com/services/svc-cfs-ent-001','Enterprise 5G Service — Acme Corp',
 'CUSTOMER_FACING_SERVICE',
 (SELECT id FROM tmf_service_spec WHERE name='Enterprise 5G CFS'),
 'Active',NULL,'2024-04-01'),
('https://gtc.example.com/services/svc-cfs-iot-001','IoT Connectivity — SmartCity',
 'CUSTOMER_FACING_SERVICE',
 (SELECT id FROM tmf_service_spec WHERE name='IoT Connectivity CFS'),
 'Active',NULL,'2024-05-15');

-- ── PRODUCT CATALOG (TMF620) ───────────────────────────────────
INSERT INTO tmf_product_spec (spec_iri, name, version, description, lifecycle_status) VALUES
('https://gtc.example.com/catalog/prodspec/5g-enterprise-unlimited','5G Enterprise Unlimited','2.0',
 '5G unlimited data plan for enterprise customers.','Launched'),
('https://gtc.example.com/catalog/prodspec/5g-iot-basic','5G IoT Basic','1.0',
 'IoT connectivity plan — low bandwidth, high device count.','Launched'),
('https://gtc.example.com/catalog/prodspec/network-slicing-premium','Network Slicing Premium','1.0',
 'Dedicated URLLC network slice for mission-critical applications.','Launched');

INSERT INTO tmf_product_offering (offering_iri, name, description, product_spec_id, lifecycle_status) VALUES
('https://gtc.example.com/catalog/offering/ent-unlimited-2024','Enterprise 5G Unlimited 2024',
 'Commercial offering for enterprise 5G unlimited data.',
 (SELECT id FROM tmf_product_spec WHERE name='5G Enterprise Unlimited'),'Launched'),
('https://gtc.example.com/catalog/offering/iot-basic-2024','IoT Basic 2024',
 'IoT connectivity commercial offering.',
 (SELECT id FROM tmf_product_spec WHERE name='5G IoT Basic'),'Launched'),
('https://gtc.example.com/catalog/offering/slice-premium-2024','Network Slice Premium 2024',
 'Dedicated URLLC slice commercial offering.',
 (SELECT id FROM tmf_product_spec WHERE name='Network Slicing Premium'),'Launched');

-- ── PARTIES (TMF632) ───────────────────────────────────────────
INSERT INTO tmf_party (party_iri, party_type, name, trading_name, org_type, email, place_id) VALUES
('https://gtc.example.com/parties/gtc-operator','ORGANIZATION','Global Telecom Corp','GTC','Operator','ops@gtc.example.com',5),
('https://gtc.example.com/parties/acme-corp','ORGANIZATION','Acme Corporation','Acme','Enterprise Customer','it@acme.example.com',NULL),
('https://gtc.example.com/parties/smartcity-iot','ORGANIZATION','SmartCity IoT Ltd','SmartCity IoT','Enterprise Customer','connect@smartcity.example.com',NULL),
('https://gtc.example.com/parties/vendor-alpha','ORGANIZATION','Vendor Alpha GmbH','Vendor Alpha','Vendor','support@vendor-alpha.example.de',NULL),
('https://gtc.example.com/parties/noc-eng-01','INDIVIDUAL','NOC Engineer 01',NULL,NULL,'noc1@gtc.example.com',NULL),
('https://gtc.example.com/parties/ml-monitor-agent','INDIVIDUAL','ML Monitor Agent',NULL,NULL,NULL,NULL);

INSERT INTO tmf_party_role (party_id, role_name, role_type, status, valid_from) VALUES
((SELECT id FROM tmf_party WHERE name='Global Telecom Corp'),'Operator','OperatingCompany','Initialized','2020-01-01'),
((SELECT id FROM tmf_party WHERE name='Acme Corporation'),'Customer','BusinessCustomer','Initialized','2024-01-01'),
((SELECT id FROM tmf_party WHERE name='SmartCity IoT Ltd'),'Customer','BusinessCustomer','Initialized','2024-05-01'),
((SELECT id FROM tmf_party WHERE name='Vendor Alpha GmbH'),'Supplier','NetworkEquipmentVendor','Initialized','2022-01-01'),
((SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),'Employee','NOCEngineer','Initialized','2023-01-01');

-- ── CUSTOMER ACCOUNTS (TMF666) ─────────────────────────────────
INSERT INTO tmf_customer_account (account_iri, account_number, name, account_type, status, party_id) VALUES
('https://gtc.example.com/accounts/ACC-001001','ACC-001001','Acme Corp — 5G Enterprise','Enterprise','Active',
 (SELECT id FROM tmf_party WHERE name='Acme Corporation')),
('https://gtc.example.com/accounts/ACC-001002','ACC-001002','SmartCity IoT — Connectivity','Enterprise','Active',
 (SELECT id FROM tmf_party WHERE name='SmartCity IoT Ltd'));

-- ── PRODUCTS (TMF637) ──────────────────────────────────────────
INSERT INTO tmf_product (product_iri, name, product_offering_id, status, realising_service_id, start_date) VALUES
('https://gtc.example.com/products/PROD-ACM-001','Acme 5G Unlimited Plan',
 (SELECT id FROM tmf_product_offering WHERE name='Enterprise 5G Unlimited 2024'),
 'Active',(SELECT id FROM tmf_service WHERE name='Enterprise 5G Service — Acme Corp'),'2024-04-01'),
('https://gtc.example.com/products/PROD-IOT-001','SmartCity IoT Connectivity Plan',
 (SELECT id FROM tmf_product_offering WHERE name='IoT Basic 2024'),
 'Active',(SELECT id FROM tmf_service WHERE name='IoT Connectivity — SmartCity'),'2024-05-15');

-- ── AGREEMENTS / SLAs (TMF651) ─────────────────────────────────
INSERT INTO tmf_agreement (agreement_iri, name, agreement_type, description, status,
    party_a_id, party_b_id, valid_from, valid_until) VALUES
('https://gtc.example.com/agreements/SLA-ACME-2024','Acme 5G Service SLA 2024','SLA',
 '99.95% availability SLA. RTO 4 hours. Throughput floor 1Gbps.',
 'Active',
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp'),
 (SELECT id FROM tmf_party WHERE name='Acme Corporation'),
 '2024-04-01','2025-04-01'),
('https://gtc.example.com/agreements/SLA-IOT-2024','SmartCity IoT SLA 2024','SLA',
 '99.9% availability SLA. Device count SLA: 50,000 concurrent.',
 'Active',
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp'),
 (SELECT id FROM tmf_party WHERE name='SmartCity IoT Ltd'),
 '2024-05-15','2025-05-15');

-- ── ALARMS (TMF642) ────────────────────────────────────────────
INSERT INTO tmf_alarm (alarm_iri, alarm_type, perceived_severity, probable_cause,
    specific_problem, source_resource_id, alarm_state, raised_by_id,
    raised_at, acknowledged_at, cleared_at) VALUES
('https://gtc.example.com/alarms/ALM-20260410-001',
 'CommunicationsAlarm','Critical','transmissionError',
 'gNB 043 lost uplink connectivity to AMF — packet loss 18.7%',
 (SELECT id FROM tmf_resource WHERE name='gNB Site 043'),
 'Cleared',
 (SELECT id FROM tmf_party WHERE name='ML Monitor Agent'),
 '2026-04-10T02:14:00Z','2026-04-10T02:16:00Z','2026-04-10T05:44:00Z'),

('https://gtc.example.com/alarms/ALM-20260415-001',
 'EquipmentAlarm','Major','softwareError',
 'UPF East 01 memory utilization exceeded 90% threshold',
 (SELECT id FROM tmf_resource WHERE name='UPF East 01'),
 'Active',
 (SELECT id FROM tmf_party WHERE name='ML Monitor Agent'),
 '2026-04-15T01:05:00Z',NULL,NULL),

('https://gtc.example.com/alarms/ALM-20260412-001',
 'QualityOfServiceAlarm','Minor','degradedSignal',
 'RF signal strength below threshold — gNB Site 042 Sector 3',
 (SELECT id FROM tmf_resource WHERE name='gNB Site 042'),
 'Acknowledged',
 (SELECT id FROM tmf_party WHERE name='ML Monitor Agent'),
 '2026-04-12T10:00:00Z','2026-04-12T10:15:00Z',NULL);

-- ── SERVICE PROBLEMS (TMF656) ──────────────────────────────────
INSERT INTO tmf_service_problem (problem_iri, description, priority, status,
    category, service_id, alarm_id, raised_by_id, sla_violated, submitted_at, resolved_at) VALUES
('https://gtc.example.com/problems/PROB-20260410-001',
 'Enterprise 5G service degraded for Acme Corp — gNB 043 outage causing packet loss',
 '2-High','Resolved','CommunicationsDisruption',
 (SELECT id FROM tmf_service WHERE name='Enterprise 5G Service — Acme Corp'),
 (SELECT id FROM tmf_alarm WHERE specific_problem LIKE 'gNB 043%'),
 (SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),
 1,'2026-04-10T02:20:00Z','2026-04-10T05:50:00Z'),

('https://gtc.example.com/problems/PROB-20260415-001',
 'Potential service impact from UPF memory pressure — monitoring in progress',
 '3-Medium','In Progress','ResourceDegradation',
 (SELECT id FROM tmf_service WHERE name='eMBB RFS East 01'),
 (SELECT id FROM tmf_alarm WHERE specific_problem LIKE 'UPF East%'),
 (SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),
 0,'2026-04-15T01:10:00Z',NULL);

-- ── ORDERS (TMF622 / TMF641) ────────────────────────────────────
INSERT INTO tmf_product_order (order_iri, order_date, order_type, state,
    customer_account_id, product_offering_id, submitted_by_id) VALUES
('https://gtc.example.com/orders/PRD-ORD-2024-001',
 '2024-03-28','NewProduct','Complete',
 (SELECT id FROM tmf_customer_account WHERE account_number='ACC-001001'),
 (SELECT id FROM tmf_product_offering WHERE name='Enterprise 5G Unlimited 2024'),
 (SELECT id FROM tmf_party WHERE name='Acme Corporation')),
('https://gtc.example.com/orders/PRD-ORD-2024-002',
 '2024-05-10','NewProduct','Complete',
 (SELECT id FROM tmf_customer_account WHERE account_number='ACC-001002'),
 (SELECT id FROM tmf_product_offering WHERE name='IoT Basic 2024'),
 (SELECT id FROM tmf_party WHERE name='SmartCity IoT Ltd'));

INSERT INTO tmf_service_order (order_iri, order_date, order_type, state,
    product_order_id, service_spec_id, submitted_by_id) VALUES
('https://gtc.example.com/orders/SVC-ORD-2024-001',
 '2024-03-28','Provision','Complete',
 (SELECT id FROM tmf_product_order WHERE order_iri='https://gtc.example.com/orders/PRD-ORD-2024-001'),
 (SELECT id FROM tmf_service_spec WHERE name='Enterprise 5G CFS'),
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp'));

-- ── PERFORMANCE KPIs (TMF688 / SID ResourcePerformance) ────────
INSERT INTO tmf_performance_indicator (kpi_iri, name, description, unit_of_measure,
    kpi_type, resource_id, numeric_value, confidence_score, derivation_method,
    source_ref, threshold_low, threshold_high, breach_indicator, observed_at) VALUES
('https://gtc.example.com/kpi/AMF-E01-AVAIL-20260410',
 'AMF East 01 Availability','Monthly availability measurement','percent',
 'AVAILABILITY',(SELECT id FROM tmf_resource WHERE name='AMF East 01'),
 99.997,0.99,'MEASURED','https://oss.gtc.example.com/kpi/amf-east-01',
 99.99,NULL,0,'2026-04-10T00:00:00Z'),

('https://gtc.example.com/kpi/GNB043-PKT-LOSS-20260410',
 'gNB 043 Packet Loss Rate','Packet loss rate during incident ALM-20260410-001','percent',
 'PACKET_LOSS',(SELECT id FROM tmf_resource WHERE name='gNB Site 043'),
 18.7,0.98,'MEASURED','https://oss.gtc.example.com/kpi/gnb-043',
 NULL,1.0,1,'2026-04-10T02:14:00Z'),

('https://gtc.example.com/kpi/UPF-E01-MEM-20260415',
 'UPF East 01 Memory Utilization','Memory utilization triggering Major alarm','percent',
 'CAPACITY',(SELECT id FROM tmf_resource WHERE name='UPF East 01'),
 91.4,0.99,'MEASURED','https://oss.gtc.example.com/kpi/upf-east-01',
 NULL,90.0,1,'2026-04-15T01:00:00Z'),

('https://gtc.example.com/kpi/GNB042-RF-20260412',
 'gNB Site 042 RF Signal Strength','RF reference signal received power (RSRP)','dBm',
 'SIGNAL_STRENGTH',(SELECT id FROM tmf_resource WHERE name='gNB Site 042'),
 -72.4,0.94,'MEASURED',NULL,-80.0,NULL,0,'2026-04-12T10:05:00Z'),

('https://gtc.example.com/kpi/NS-EMBB-LAT-20260410',
 'eMBB Slice Latency','End-to-end user plane latency','ms',
 'LATENCY',(SELECT id FROM tmf_resource WHERE name='eMBB Slice East 01'),
 14.2,0.97,'MEASURED','https://oss.gtc.example.com/kpi/ns-embb-01',
 NULL,20.0,0,'2026-04-10T08:00:00Z'),

('https://gtc.example.com/kpi/AMF-E01-PSI-20260410',
 'AMF East 01 ML Drift Score','Population Stability Index score from ML monitor agent','score',
 'PSI_SCORE',(SELECT id FROM tmf_resource WHERE name='AMF East 01'),
 0.12,0.91,'SYNTHESIZED','https://ml.gtc.example.com/drift/amf-east-01',
 NULL,0.2,0,'2026-04-10T06:00:00Z');

-- ── ADDITIONAL METADATA: Common Domain support tables ────────
INSERT INTO ontology_metadata (target_type, table_name, semantic_type, label, description,
    sensitivity_tier, skos_pref_label, cq_coverage, sid_domain, sid_abe, tmf_entity_name)
VALUES
('TABLE','tmf_attachment','Attachment',
 'Attachment','A file or URL attachment linked to any TMF entity per SID Common ABE.',
 'Internal','Attachment',NULL,'Common','Attachment','Attachment'),
('TABLE','tmf_note','Note',
 'Note','A free-text annotation linked to any TMF entity per SID Common ABE.',
 'Internal','Note',NULL,'Common','Note','Note'),
('TABLE','tmf_user_role','UserRole',
 'User Role','A named permission set for users per SID Enterprise ABE / TMF672.',
 'Internal','User Role','CQ-006','Enterprise','User Role','UserRole');

-- ── OVERLOADED TYPE column metadata ──────────────────────────
INSERT INTO ontology_metadata (target_type, table_name, column_name, semantic_type,
    label, description, sensitivity_tier, tmf_entity_name, cq_coverage)
VALUES
('COLUMN','tmf_resource_spec','category','xsd:string','Resource Category',
 'SID ResourceCategory discriminator: LOGICAL or PHYSICAL. Drives OWL subclass assignment.','Public','ResourceCategory','CQ-TMF01'),
('COLUMN','tmf_service_problem','category','xsd:string','Problem Category',
 'Free-text problem category (e.g. CommunicationsDisruption, ResourceDegradation).','Internal','ProblemCategory','CQ-TMF06');

-- ── CFS → RFS service hierarchy links ────────────────────────
-- Links Customer Facing Services to their Resource Facing Services via parent_service_id
-- This enables the full Resource→RFS→CFS→Product→Customer traceability chain (CQ-TMF08)
UPDATE tmf_service
SET parent_service_id = (SELECT id FROM tmf_service WHERE name = 'eMBB RFS East 01')
WHERE name = 'Enterprise 5G Service — Acme Corp';

UPDATE tmf_service
SET parent_service_id = (SELECT id FROM tmf_service WHERE name = 'eMBB RFS East 01')
WHERE name = 'IoT Connectivity — SmartCity';
