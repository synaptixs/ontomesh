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

-- ============================================================
-- PHASE 2B SEED DATA
-- ============================================================

-- ── ONTOLOGY METADATA for Phase 2B tables ──────────────────
INSERT INTO ontology_metadata (
    target_type, table_name, semantic_type, label, description,
    sensitivity_tier, is_event_class,
    skos_pref_label, skos_alt_labels, cq_coverage,
    sid_domain, sid_abe, tmf_api_id, tmf_api_version, tmf_entity_name, etom_process
) VALUES
('TABLE','tmf_trouble_ticket','TroubleTicket',
 'Trouble Ticket','A customer or resource trouble ticket per TMF621. Tracks issue lifecycle from New to Closed.',
 'Confidential',1,'Trouble Ticket','Incident,Issue,Problem Ticket','CQ-007,CQ-TMF06,CQ-TMF10',
 'Service','Service Trouble','TMF621','v4.0','TroubleTicket','1.4.2'),

('TABLE','tmf_network_slice_profile','NetworkSliceProfile',
 'Network Slice Profile','A 3GPP S-NSSAI-aligned network slice profile with SLA parameters per TMF645.',
 'Internal',0,'Network Slice Profile','Slice Template,NST,Network Slice Specification','CQ-TMF01,CQ-TMF11',
 'Resource','Logical Resource','TMF645','v4.0','NetworkSliceProfile','1.1.1'),

('TABLE','tmf_service_quality_report','ServiceQualityReport',
 'Service Quality Report','An SLA compliance or KQI quality report per TMF657.',
 'Confidential',0,'Service Quality Report','SLA Report,KQI Report,QoS Assessment','CQ-TMF05,CQ-TMF12',
 'Service','Service Quality','TMF657','v4.0','ServiceQualityReport','1.4.3'),

('TABLE','tmf_geographic_site','GeographicSite',
 'Geographic Site','A structured physical site record (data centre, cell tower, pop) per TMF674.',
 'Internal',0,'Geographic Site','Site,Location,Data Centre,Cell Site','CQ-001,CQ-002',
 'Common','Location','TMF674','v4.0','GeographicSite','1.1.1'),

('TABLE','tmf_customer_bill','CustomerBill',
 'Customer Bill','A customer invoice per TMF678 Customer Bill Management.',
 'Confidential',0,'Customer Bill','Invoice,Bill,Statement','CQ-TMF03,CQ-TMF13',
 'EngagedParty','Customer Account','TMF678','v4.0','CustomerBill','1.3.1'),

('TABLE','tmf_product_offering_qualification','ProductOfferingQualification',
 'Product Offering Qualification','Eligibility check for a product offering at a given location per TMF679.',
 'Internal',0,'Product Offering Qualification','Eligibility Check,Feasibility Check','CQ-TMF03',
 'Product','Product Offering','TMF679','v4.0','ProductOfferingQualification','1.2.1'),

('TABLE','tmf_event_subscription','EventSubscription',
 'Event Subscription','An async event subscription per TMF630 §5 notification pattern.',
 'Internal',0,'Event Subscription','Notification Subscription,Hub Subscription','CQ-002',
 'Enterprise','Business Interaction','TMF688','v4.0','EventSubscription','1.5.1'),

('TABLE','tmf_conflict_event','ConflictEvent',
 'Conflict Event','A multi-agent assertion conflict record with 3-tier resolution chain (framework §10.1).',
 'Internal',1,'Conflict Event','Assertion Conflict,Resolution Event','CQ-002',
 'Enterprise','Policy','TMF672','v4.0','ConflictEvent','1.4.1');

-- ── GEOGRAPHIC SITES (TMF674) ─────────────────────────────────
INSERT INTO tmf_geographic_site (site_iri, name, site_type, description, place_id,
    site_category, power_supply, cooling_type, rack_capacity,
    operational_status, latitude, longitude, owner_party_id) VALUES
('https://gtc.example.com/sites/DC-EAST-01','Data Centre East 01','DataCentre',
 'Primary Tier-3 data centre — East US. Hosts AMF, SMF, UPF, NRF, PCF.',
 1,'Owned','Mains','Liquid',400,'Operational',40.7128,-74.0060,
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp')),
('https://gtc.example.com/sites/DC-WEST-01','Data Centre West 01','DataCentre',
 'Secondary data centre — West US. Disaster recovery site.',
 2,'Owned','Mains','Air',200,'Operational',37.3382,-121.8863,
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp')),
('https://gtc.example.com/sites/RAN-042','RAN Site 042','CellTower',
 '5G NR gNB site. Sector 1–3, MIMO 64T64R.',
 3,'Leased','Mains','Natural',4,'Operational',40.6501,-73.9496,
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp')),
('https://gtc.example.com/sites/RAN-043','RAN Site 043','CellTower',
 '5G NR gNB site. Currently Locked — maintenance.',
 4,'Leased','Generator','Natural',4,'Operational',40.7282,-73.7949,
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp'));

-- ── NETWORK SLICE PROFILES (TMF645) ──────────────────────────
INSERT INTO tmf_network_slice_profile (profile_iri, name, slice_type,
    sst, sd, max_dl_throughput, max_ul_throughput,
    latency_target_ms, reliability_target, max_devices,
    lifecycle_status, resource_id, agreement_id) VALUES
('https://gtc.example.com/slice-profiles/EMBB-EAST-01','eMBB East 01 Profile','eMBB',
 1,'000001',1000.0,500.0,20.0,99.9,10000,'Active',
 (SELECT id FROM tmf_resource WHERE name='eMBB Slice East 01'),
 (SELECT id FROM tmf_agreement WHERE name='Acme 5G Service SLA 2024')),
('https://gtc.example.com/slice-profiles/URLLC-EAST-01','URLLC East 01 Profile','URLLC',
 2,'000002',100.0,50.0,1.0,99.9999,500,'Active',
 (SELECT id FROM tmf_resource WHERE name='URLLC Slice East 01'),
 NULL);

-- ── SERVICE QUALITY REPORTS (TMF657) ──────────────────────────
INSERT INTO tmf_service_quality_report (report_iri, report_type, description,
    status, service_id, agreement_id, period_start, period_end,
    quality_metrics, sla_compliant, overall_quality_score, submitted_by_id) VALUES
('https://gtc.example.com/sqr/SQR-ACME-2026-04','SLAComplianceReport',
 'Monthly SLA compliance report for Acme Corp 5G Enterprise service — April 2026.',
 'Active',
 (SELECT id FROM tmf_service WHERE name='Enterprise 5G Service — Acme Corp'),
 (SELECT id FROM tmf_agreement WHERE name='Acme 5G Service SLA 2024'),
 '2026-04-01','2026-04-30',
 '[{"name":"Availability","value":99.91,"unit":"percent","threshold":99.95,"compliant":false},{"name":"Throughput","value":1050,"unit":"Mbps","threshold":1000,"compliant":true}]',
 0,4.2,
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp')),
('https://gtc.example.com/sqr/SQR-IOT-2026-04','KQIReport',
 'Monthly KQI report for SmartCity IoT connectivity service — April 2026.',
 'Active',
 (SELECT id FROM tmf_service WHERE name='IoT Connectivity — SmartCity'),
 (SELECT id FROM tmf_agreement WHERE name='SmartCity IoT SLA 2024'),
 '2026-04-01','2026-04-30',
 '[{"name":"Availability","value":99.97,"unit":"percent","threshold":99.9,"compliant":true},{"name":"DeviceCount","value":48200,"unit":"devices","threshold":50000,"compliant":true}]',
 1,4.8,
 (SELECT id FROM tmf_party WHERE name='Global Telecom Corp'));

-- ── TROUBLE TICKETS (TMF621) ──────────────────────────────────
INSERT INTO tmf_trouble_ticket (ticket_iri, ticket_type, description, severity, priority,
    status, category, affected_resource_id, related_alarm_id,
    raised_by_id, assigned_to_id, sla_violated, submitted_at, resolved_at) VALUES
('https://gtc.example.com/tickets/TT-2026-0042','TroubleTicket',
 'UPF East 01 memory pressure — potential service impact. Threshold exceeded at 91.4%.',
 '2-High','2-High','In Progress','ResourceDegradation',
 (SELECT id FROM tmf_resource WHERE name='UPF East 01'),
 (SELECT id FROM tmf_alarm WHERE specific_problem LIKE 'UPF East%'),
 (SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),
 (SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),
 0,'2026-04-15T01:15:00Z',NULL),
('https://gtc.example.com/tickets/TT-2026-0039','ResourceTroubleTicket',
 'gNB Site 043 locked — connectivity loss to AMF resolved after maintenance window.',
 '1-Critical','1-Critical','Resolved','CommunicationsDisruption',
 (SELECT id FROM tmf_resource WHERE name='gNB Site 043'),
 (SELECT id FROM tmf_alarm WHERE specific_problem LIKE 'gNB 043%'),
 (SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),
 (SELECT id FROM tmf_party WHERE name='NOC Engineer 01'),
 1,'2026-04-10T02:20:00Z','2026-04-10T06:00:00Z');

-- ── CUSTOMER BILLS (TMF678) ───────────────────────────────────
INSERT INTO tmf_customer_bill (bill_iri, bill_number, bill_type,
    customer_account_id, billing_period_start, billing_period_end,
    bill_date, payment_due_date, amount_due, tax_amount, currency_code,
    state, disputed) VALUES
('https://gtc.example.com/bills/BILL-ACC001-202604','BILL-ACC001-202604','Regular',
 (SELECT id FROM tmf_customer_account WHERE account_number='ACC-001001'),
 '2026-04-01','2026-04-30',
 '2026-05-01','2026-05-15',
 18500.00,1850.00,'USD','Sent',0),
('https://gtc.example.com/bills/BILL-ACC002-202604','BILL-ACC002-202604','Regular',
 (SELECT id FROM tmf_customer_account WHERE account_number='ACC-001002'),
 '2026-04-01','2026-04-30',
 '2026-05-01','2026-05-15',
 4200.00,420.00,'USD','Sent',0),
('https://gtc.example.com/bills/BILL-ACC001-202603-CREDIT','BILL-ACC001-202603-CR','CreditNote',
 (SELECT id FROM tmf_customer_account WHERE account_number='ACC-001001'),
 '2026-03-01','2026-03-31',
 '2026-04-05','2026-04-05',
 -925.00,0.00,'USD','Settled',0);

-- ── PRODUCT OFFERING QUALIFICATIONS (TMF679) ──────────────────
INSERT INTO tmf_product_offering_qualification (poq_iri, description,
    requested_product_offering_id, customer_account_id, install_address_id,
    state, qualification_result, eligibility_reason,
    feasibility_check, feasibility_notes,
    valid_for_start, valid_for_end, requested_at) VALUES
('https://gtc.example.com/poq/POQ-2026-0101',
 'Eligibility check for URLLC Network Slice Premium — Acme Corp HQ',
 (SELECT id FROM tmf_product_offering WHERE name='Network Slice Premium 2024'),
 (SELECT id FROM tmf_customer_account WHERE account_number='ACC-001001'),
 (SELECT id FROM tmf_place WHERE name='HQ Office'),
 'Approved','ELIGIBLE',
 'Customer location within URLLC slice coverage area. Coverage confirmed for Data Centre East.',
 1,'URLLC slice resource available. Latency <1ms at customer site confirmed.',
 '2026-04-20','2026-07-20','2026-04-15T09:00:00Z');

-- ── EVENT SUBSCRIPTIONS (TMF Event Hub) ───────────────────────
INSERT INTO tmf_event_subscription (subscription_iri, subscriber_party_id,
    event_type, event_domain, filter_criteria,
    callback_url, callback_method, status,
    retry_policy, valid_for_start) VALUES
('https://gtc.example.com/hub/SUB-ACME-ALARM-001',
 (SELECT id FROM tmf_party WHERE name='Acme Corporation'),
 'AlarmStateChange','Resource',
 '{"perceived_severity":["Critical","Major"],"affected_service_type":"CUSTOMER_FACING_SERVICE"}',
 'https://api.acme.example.com/webhooks/network-events','POST','Active',
 '{"max_retries":3,"backoff_seconds":30}','2024-04-01'),
('https://gtc.example.com/hub/SUB-ACME-ORDER-001',
 (SELECT id FROM tmf_party WHERE name='Acme Corporation'),
 'ServiceOrderStateChange','Service',
 '{"account_id":"ACC-001001"}',
 'https://api.acme.example.com/webhooks/order-updates','POST','Active',
 '{"max_retries":3,"backoff_seconds":10}','2024-04-01'),
('https://gtc.example.com/hub/SUB-ML-KPI-001',
 (SELECT id FROM tmf_party WHERE name='ML Monitor Agent'),
 'KPIThresholdBreach','Resource',
 '{"kpi_type":["PSI_SCORE","DRIFT_SCORE","CAPACITY"],"breach_indicator":true}',
 'https://ml.gtc.example.com/events/kpi-breach','POST','Active',
 '{"max_retries":5,"backoff_seconds":5}','2024-03-01');

-- ── CONFLICT EVENTS (Multi-Agent Conflict Resolution) ─────────
INSERT INTO tmf_conflict_event (conflict_iri, assertion_a_iri, assertion_b_iri,
    conflict_type, description, shacl_violation_msg,
    resolution_tier, winning_assertion_iri, resolution_rule,
    escalated_to_human, invalidation_recorded,
    status, detected_at, resolved_at) VALUES
('https://gtc.example.com/conflicts/CONF-2026-0001',
 'https://gtc.example.com/kpi/UPF-E01-MEM-20260415',
 'https://gtc.example.com/kpi/UPF-E01-MEM-AGENT-ESTIMATE',
 'VALUE_CONFLICT',
 'Two agents reported conflicting memory utilization for UPF East 01: measured 91.4% vs. inferred 78.2%.',
 NULL,
 2,'https://gtc.example.com/kpi/UPF-E01-MEM-20260415',
 'measured > inferred (derivation_method priority chain)',
 0,1,'Resolved','2026-04-15T01:05:00Z','2026-04-15T01:05:01Z'),
('https://gtc.example.com/conflicts/CONF-2026-0002',
 'https://gtc.example.com/resources/gnb-043',
 'https://gtc.example.com/resources/gnb-043-state-imported',
 'STATE_CONFLICT',
 'SHACL validation rejected imported state assertion: admin_state=Unlocked conflicts with measured operational_state=Disabled. Disabled+Unlocked is not a valid state combination per eTOM.',
 'sh:Violation: OperationalAndAdminStateConsistency — Disabled resource must not be Unlocked.',
 1,NULL,NULL,
 1,0,'Escalated','2026-04-10T02:14:00Z',NULL);

-- ============================================================
-- PHASE RT: Runtime Layer seed
-- ============================================================

-- ── Runtime table ontology_metadata annotations ───────────────
INSERT INTO ontology_metadata (
    target_type, table_name, semantic_type, label, description,
    sensitivity_tier, is_event_class,
    skos_pref_label, skos_alt_labels, cq_coverage,
    sid_domain, sid_abe, tmf_api_id, tmf_api_version, tmf_entity_name, etom_process
) VALUES

('TABLE','runtime_flavor','RuntimeFlavor',
 'Runtime Flavor','An ontology domain flavor configuration defining scope, OWL classes, SHACL shapes, and sensitivity tier for AI runtime sessions.',
 'Internal',0,'Runtime Flavor','Ontology Flavor,Domain Flavor,LLM Scope','CQ-RT-01',
 'Enterprise','Policy',NULL,NULL,'RuntimeFlavor','1.1.4'),

('TABLE','runtime_payload','RuntimePayload',
 'Runtime Payload','A fully assembled LLM input payload capturing question, flavor, model, and token budget for a single AI call.',
 'Internal',0,'Runtime Payload','LLM Payload,AI Payload','CQ-RT-03',
 'Enterprise','Policy',NULL,NULL,'RuntimePayload','1.1.4'),

('TABLE','runtime_grounding','RuntimeGrounding',
 'Runtime Grounding','A data grounding event linking a payload to the DB tables and records retrieved for context.',
 'Internal',0,'Runtime Grounding','Data Grounding,Context Retrieval','CQ-RT-02',
 'Enterprise','Policy',NULL,NULL,'RuntimeGrounding','1.1.4'),

('TABLE','observation_record','ObservationRecord',
 'Observation Record','A PROV-O annotated observation produced by measurement, inference, import, synthesis, or grounding.',
 'Internal',0,'Observation Record','PROV Observation,KPI Record','CQ-004,CQ-005,CQ-RT-02',
 'Common','Observation',NULL,NULL,'ObservationRecord','1.4.4'),

('TABLE','tmf_conflict_event','ConflictEvent',
 'Conflict Event','A detected conflict between two ontology assertions with 3-tier resolution chain tracking.',
 'Internal',1,'Conflict Event','Assertion Conflict,Semantic Conflict','CQ-P2B-conflict-resolution',
 'Enterprise','Conflict Resolution',NULL,NULL,'ConflictEvent','1.1.4'),

('TABLE','semantic_loss_log','SemanticLossRecord',
 'Semantic Loss Log','Records of semantic information loss including rejected records, unmapped columns, and derivation gaps.',
 'Internal',0,'Semantic Loss','Information Loss,Data Quality','CQ-005',
 'Enterprise','Quality Management',NULL,NULL,'SemanticLossRecord','1.1.4');

-- ── Runtime Flavor seed rows (one per JSON flavor file) ────────
INSERT INTO runtime_flavor (
    name, description, sensitivity_tier,
    owl_classes, shacl_shapes, context_terms, db_tables,
    system_prompt_hint, cq_ids
) VALUES

('network-ops',
 'Network Operations domain — resource inventory, network function management, alarm surveillance, performance monitoring, and 5G slice management.',
 'Internal',
 '["Resource","NetworkFunction","NetworkSlice","Alarm","PerformanceIndicator"]',
 '["ResourceShape","AlarmShape","PerformanceIndicatorShape","NetworkFunctionShape"]',
 '{"resourceType":"https://ontology.example.com/tmf/resourceType","operationalState":"https://ontology.example.com/tmf/operationalState","alarmType":"https://ontology.example.com/tmf/alarmType","perceivedSeverity":"https://ontology.example.com/tmf/perceivedSeverity","kpiType":"https://ontology.example.com/tmf/kpiType"}',
 '["tmf_resource","tmf_alarm","tmf_performance_indicator"]',
 'Focus on resource operational states, alarm severity and correlation, KPI threshold breaches, and 5G network function health.',
 '["CQ-TMF1","CQ-TMF2","CQ-TMF3","CQ-TMF4","CQ-TMF5"]'),

('billing',
 'Billing and Revenue Management domain — customer bills, billing accounts, product subscriptions, commercial agreements, and party financial relationships.',
 'Confidential',
 '["CustomerBill","BillingAccount","Product","Agreement","Party"]',
 '["CustomerBillShape","BillingAccountShape","ProductShape","AgreementShape"]',
 '{"billNumber":"https://ontology.example.com/tmf/billNumber","amountDue":"https://ontology.example.com/tmf/amountDue","billState":"https://ontology.example.com/tmf/billState","currencyCode":"https://ontology.example.com/tmf/currencyCode","agreementType":"https://ontology.example.com/tmf/agreementType"}',
 '["tmf_customer_bill","tmf_product","tmf_agreement"]',
 'Focus on bill disputes, overdue payments, SLA-linked commercial agreements, and product subscription lifecycles.',
 '["CQ-TMF13"]'),

('compliance',
 'Compliance and Governance domain — semantic consistency checks, ontology-level conflict resolution, observation record auditing, and policy enforcement.',
 'Internal',
 '["TmfEntity","ObservationRecord","ConflictEvent","Policy"]',
 '["TmfEntityShape","ObservationRecordShape","ConflictEventShape","PolicyShape"]',
 '{"recordType":"https://ontology.example.com/tmf/recordType","derivationMethod":"https://ontology.example.com/tmf/derivationMethod","confidenceScore":"https://ontology.example.com/tmf/confidenceScore","conflictType":"https://ontology.example.com/tmf/conflictType","resolutionTier":"https://ontology.example.com/tmf/resolutionTier"}',
 '["tmf_conflict_event","observation_record","semantic_loss_log"]',
 'Focus on unresolved conflict events, SHACL violation patterns, low-confidence observations, and policy adherence.',
 '["CQ-P2B-conflict-resolution"]'),

('customer',
 'Customer and Engaged Party domain — party management (individuals and organizations), related party relationships, product subscriptions, and customer-facing service instances.',
 'Internal',
 '["Party","Individual","Organization","RelatedParty","Product","Service"]',
 '["PartyShape","IndividualShape","OrganizationShape","ProductShape","ServiceShape"]',
 '{"partyType":"https://ontology.example.com/tmf/partyType","givenName":"https://ontology.example.com/tmf/givenName","familyName":"https://ontology.example.com/tmf/familyName","tradingName":"https://ontology.example.com/tmf/tradingName","serviceType":"https://ontology.example.com/tmf/serviceType"}',
 '["tmf_party","tmf_product","tmf_service"]',
 'Focus on party lifecycle states, customer product holdings, service activation status, and related party associations.',
 '["CQ-TMF6","CQ-TMF7","CQ-TMF8"]'),

('fault-management',
 'Fault Management domain — alarm lifecycle management, trouble ticket triage, affected resource identification, and service quality reporting.',
 'Internal',
 '["Alarm","TroubleTicket","Resource","ServiceQualityReport"]',
 '["AlarmShape","TroubleTicketShape","ResourceShape","ServiceQualityReportShape"]',
 '{"alarmType":"https://ontology.example.com/tmf/alarmType","perceivedSeverity":"https://ontology.example.com/tmf/perceivedSeverity","alarmState":"https://ontology.example.com/tmf/alarmState","ticketStatus":"https://ontology.example.com/tmf/ticketStatus","slaViolated":"https://ontology.example.com/tmf/slaViolated"}',
 '["tmf_alarm","tmf_trouble_ticket","tmf_service_quality_report"]',
 'Focus on active alarms, open trouble tickets, SLA violation flags, and service quality degradation.',
 '["CQ-TMF10","CQ-TMF11","CQ-TMF12"]');
