-- ============================================================
-- 5G NF Demo Seed — ~100 rows across 8 tables, plus full
-- ontology_metadata annotations. Rows reflect configurations
-- observable in open-source 5G cores (Open5GS, free5GC) and
-- documented in 3GPP TS examples.
--
-- Deliberate edge cases (drive the teaching moments):
--   • UDM instance 5 is SUSPENDED yet PDU sessions 7, 9 remain ACTIVE
--     → exposes "active" ambiguity (Q1, Q4)
--   • S-NSSAI composite: pdu_session rows use (snssai_sst, snssai_sd)
--     → exposes COMPOSITE_IDENTIFIER finding (Q2)
--   • UE registrations 4 and 9 DEREGISTERED; events show 2 INFERRED
--     (nrf-monitor heartbeat timeout) + 2 MEASURED (explicit NFDeregister)
--     → exposes PROV-O derivation (Q6)
--   • pm_counter row 15 uses name "RRC.ConnEstabAtt" but technology='LTE'
--     → exposes NAMESPACE_COLLISION (Q5/Q8 context)
--   • slice_instance 2 (URLLC) has strict 5ms SLA; slice 1 (eMBB) has
--     NULL sla_latency_ms → exposes slice SLA ambiguity (Q7)
-- ============================================================

-- ── NF INSTANCES (12) ─────────────────────────────────────────
-- one AMF, two SMFs, three UPFs, plus one each of PCF/UDM/AUSF/NRF/NSSF/NEF.
-- UDM (id=5) is SUSPENDED — heartbeat timed out from the NRF's perspective.
INSERT INTO nf_instance VALUES
 (1,  '550e8400-e29b-41d4-a716-446655440001','AMF','REGISTERED',    'amf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (2,  '550e8400-e29b-41d4-a716-446655440002','SMF','REGISTERED',    'smf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (3,  '550e8400-e29b-41d4-a716-446655440003','SMF','REGISTERED',    'smf-02.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-02 00:00:00'),
 (4,  '550e8400-e29b-41d4-a716-446655440004','UPF','REGISTERED',    'upf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (5,  '550e8400-e29b-41d4-a716-446655440005','UDM','SUSPENDED',     'udm-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 11:42:05','2026-04-01 00:00:00'),  -- stuck but sessions stay up
 (6,  '550e8400-e29b-41d4-a716-446655440006','UPF','REGISTERED',    'upf-02.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-03 00:00:00'),
 (7,  '550e8400-e29b-41d4-a716-446655440007','UPF','REGISTERED',    'upf-03.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-05 00:00:00'),
 (8,  '550e8400-e29b-41d4-a716-446655440008','PCF','REGISTERED',    'pcf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (9,  '550e8400-e29b-41d4-a716-446655440009','AUSF','REGISTERED',   'ausf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (10, '550e8400-e29b-41d4-a716-446655440010','NRF','REGISTERED',    'nrf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (11, '550e8400-e29b-41d4-a716-446655440011','NSSF','REGISTERED',   'nssf-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-23 12:00:00','2026-04-01 00:00:00'),
 (12, '550e8400-e29b-41d4-a716-446655440012','NEF','UNDISCOVERABLE','nef-01.5gc.mnc001.mcc001.3gppnetwork.org','001','01',30,'2026-04-22 18:15:00','2026-04-01 00:00:00');

-- ── NF SERVICES (14) ──────────────────────────────────────────
-- Service name per 3GPP TS 29.5xx family.
INSERT INTO nf_service VALUES
 (1,  1,'Namf_Communication',         'REGISTERED','v1','https'),
 (2,  1,'Namf_EventExposure',         'REGISTERED','v1','https'),
 (3,  2,'Nsmf_PDUSession',            'REGISTERED','v1','https'),
 (4,  3,'Nsmf_PDUSession',            'REGISTERED','v1','https'),
 (5,  8,'Npcf_SMPolicyControl',       'REGISTERED','v1','https'),
 (6,  8,'Npcf_AMPolicyControl',       'REGISTERED','v1','https'),
 (7,  5,'Nudm_SubscriberDataManagement','SUSPENDED','v1','https'),  -- matches SUSPENDED NF
 (8,  5,'Nudm_UEAuthentication',      'SUSPENDED','v1','https'),
 (9,  9,'Nausf_UEAuthentication',     'REGISTERED','v1','https'),
 (10,10,'Nnrf_NFManagement',          'REGISTERED','v1','https'),
 (11,10,'Nnrf_NFDiscovery',           'REGISTERED','v1','https'),
 (12,11,'Nnssf_NSSelection',          'REGISTERED','v1','https'),
 (13,12,'Nnef_EventExposure',         'REGISTERED','v1','https'),
 (14, 1,'Namf_MT',                    'REGISTERED','v1','https');

-- ── UE REGISTRATIONS (10) — all anchored at AMF id=1 ──────────
INSERT INTO ue_registration VALUES
 (1, 'imsi-001010000000001',1,'REGISTERED',  'CONNECTED','001','01','2026-04-23 08:15:00','2026-04-23 11:55:00'),
 (2, 'imsi-001010000000002',1,'REGISTERED',  'IDLE',     '001','01','2026-04-23 08:40:00','2026-04-23 10:12:00'),
 (3, 'imsi-001010000000003',1,'REGISTERED',  'CONNECTED','001','01','2026-04-23 09:05:00','2026-04-23 11:57:00'),
 (4, 'imsi-001010000000004',1,'DEREGISTERED','IDLE',     '001','01','2026-04-23 09:30:00','2026-04-23 10:01:00'),
 (5, 'imsi-001010000000005',1,'REGISTERED',  'IDLE',     '001','01','2026-04-23 09:45:00','2026-04-23 11:40:00'),
 (6, 'imsi-001010000000006',1,'REGISTERED',  'CONNECTED','001','01','2026-04-23 10:02:00','2026-04-23 11:58:00'),
 (7, 'imsi-001010000000007',1,'REGISTERED',  'CONNECTED','001','01','2026-04-23 10:18:00','2026-04-23 11:59:00'),
 (8, 'imsi-001010000000008',1,'REGISTERED',  'IDLE',     '001','01','2026-04-23 10:30:00','2026-04-23 11:05:00'),
 (9, 'imsi-001010000000009',1,'DEREGISTERED','IDLE',     '001','01','2026-04-23 10:40:00','2026-04-23 10:52:00'),
 (10,'imsi-001010000000010',1,'REGISTERED',  'CONNECTED','001','01','2026-04-23 11:00:00','2026-04-23 11:58:00');

-- ── PDU SESSIONS (12) across 4 slices ─────────────────────────
-- SST: 1=eMBB, 2=URLLC, 3=MIoT, 4=V2X (TS 23.501 Table 5.15.2.2-1)
-- Sessions 7 and 9 belong to UEs whose UDM is SUSPENDED but sessions remain ACTIVE.
INSERT INTO pdu_session VALUES
 (1,  1,'imsi-001010000000001',2,4, 1,'000001','internet','ACTIVE',  '2026-04-23 08:16:00'),
 (2,  2,'imsi-001010000000001',2,4, 1,'000001','ims',     'ACTIVE',  '2026-04-23 08:17:00'),
 (3,  1,'imsi-001010000000002',2,6, 1,'000001','internet','INACTIVE','2026-04-23 08:42:00'),
 (4,  1,'imsi-001010000000003',3,6, 2,'00A1B2','v2x-ue',  'ACTIVE',  '2026-04-23 09:06:00'),
 (5,  1,'imsi-001010000000004',2,4, 1,'000001','internet','RELEASED','2026-04-23 09:31:00'),
 (6,  1,'imsi-001010000000005',2,7, 3,NULL,    'iot.mnc001.mcc001.gprs','ACTIVE','2026-04-23 09:46:00'),
 (7,  1,'imsi-001010000000006',3,6, 2,'00A1B2','urllc-app','ACTIVE','2026-04-23 10:03:00'),  -- URLLC, UDM suspended
 (8,  1,'imsi-001010000000007',3,7, 4,'00F001','v2x-ue',  'ACTIVE',  '2026-04-23 10:19:00'),
 (9,  1,'imsi-001010000000008',2,4, 1,'000001','internet','ACTIVE',  '2026-04-23 10:31:00'),  -- also during UDM suspend
 (10, 1,'imsi-001010000000009',2,6, 1,'000001','internet','RELEASED','2026-04-23 10:41:00'),
 (11, 1,'imsi-001010000000010',3,7, 2,'00A1B2','urllc-app','ACTIVE','2026-04-23 11:01:00'),
 (12, 2,'imsi-001010000000010',3,7, 4,'00F001','v2x-ue',  'ACTIVE',  '2026-04-23 11:02:00');

-- ── SLICE INSTANCES (4) ───────────────────────────────────────
-- Slice 1 (eMBB) has NULL sla_latency_ms — missing SLA.
-- Slice 2 (URLLC) has 5 ms E2E latency target per GSMA NG.116 URLLC profile.
INSERT INTO slice_instance VALUES
 (1,'nssi-embb-01', 1,'000001','eMBB', NULL, 99.9, 'ENABLED'),
 (2,'nssi-urllc-01',2,'00A1B2','URLLC',  5,  99.999,'ENABLED'),
 (3,'nssi-miot-01', 3,NULL,    'MIoT', 500, 99.0,  'ENABLED'),
 (4,'nssi-v2x-01',  4,'00F001','V2X',   20, 99.99, 'ENABLED');

-- ── PM COUNTERS (15) — one deliberate NR/LTE collision ────────
-- TS 28.552 §5.1.1.x for NR; TS 32.425 §4.1.1.x for LTE (same-named counters exist).
INSERT INTO pm_counter VALUES
 (1,  1,'AMF.RegisteredSubNbrMean',                'NR', 842.0, 300,'2026-04-23 11:30:00'),
 (2,  1,'AMF.RegistrationReq.AuthFail',            'NR',  12.0, 300,'2026-04-23 11:30:00'),
 (3,  1,'AMF.RegistrationReq.AuthSucc',            'NR', 318.0, 300,'2026-04-23 11:30:00'),
 (4,  2,'SM.PduSessionCreationReq',                'NR', 205.0, 300,'2026-04-23 11:30:00'),
 (5,  2,'SM.PduSessionCreationSucc',               'NR', 198.0, 300,'2026-04-23 11:30:00'),
 (6,  3,'SM.PduSessionCreationReq',                'NR', 189.0, 300,'2026-04-23 11:30:00'),
 (7,  4,'UPF.UplinkThroughputMbps',                'NR',1820.5, 300,'2026-04-23 11:30:00'),
 (8,  4,'UPF.DownlinkThroughputMbps',              'NR',4120.8, 300,'2026-04-23 11:30:00'),
 (9,  6,'UPF.UplinkThroughputMbps',                'NR',2240.1, 300,'2026-04-23 11:30:00'),
 (10, 7,'UPF.UplinkThroughputMbps',                'NR', 910.4, 300,'2026-04-23 11:30:00'),
 (11, 5,'UDM.AuthSubscriptionDataSubs',            'NR',   0.0, 300,'2026-04-23 11:30:00'),   -- zero during suspend
 (12,10,'NRF.NFDiscoveryReq',                      'NR', 412.0, 300,'2026-04-23 11:30:00'),
 (13,10,'NRF.NFHeartbeatMissed',                   'NR',   3.0, 300,'2026-04-23 11:30:00'),   -- drove UDM into SUSPENDED
 (14, 1,'RRC.ConnEstabAtt',                        'NR', 520.0,  60,'2026-04-23 11:30:00'),   -- NR counter
 (15, 1,'RRC.ConnEstabAtt',                        'LTE',140.0,  60,'2026-04-23 11:30:00');   -- NAMESPACE_COLLISION with id=14

-- ── ALARMS (6) — NRF heartbeat timeout on UDM-01 ──────────────
INSERT INTO alarm VALUES
 (1, 5,'NRF_HEARTBEAT_TIMEOUT',   'MAJOR',   'ACTIVE', '2026-04-23 11:42:05',NULL),
 (2, 5,'NF_STATUS_SUSPENDED',     'MAJOR',   'ACTIVE', '2026-04-23 11:42:05',NULL),
 (3,12,'NF_UNDISCOVERABLE',       'MINOR',   'ACTIVE', '2026-04-22 18:15:00',NULL),
 (4, 4,'UPF_NG_U_LINK_DOWN',      'CRITICAL','CLEARED','2026-04-23 07:10:00','2026-04-23 07:18:00'),
 (5, 8,'PCF_POLICY_TIMEOUT',      'MINOR',   'CLEARED','2026-04-23 09:44:00','2026-04-23 09:45:30'),
 (6, 3,'SMF_CONGESTION',          'WARNING', 'CLEARED','2026-04-23 10:20:00','2026-04-23 10:35:00');

-- ── NF EVENTS (15) — mix of MEASURED and INFERRED ─────────────
-- Rows 8 and 11 are heartbeat-inferred deregistrations (actor_party='nrf-monitor', derivation='INFERRED').
-- Rows 5 and 14 are explicit deregistrations (actor_party='nf', derivation='MEASURED').
INSERT INTO nf_event VALUES
 (1,  1,'REGISTERED',      '2026-04-01 00:00:00','nf',         0.99,'MEASURED'),
 (2,  2,'REGISTERED',      '2026-04-01 00:00:00','nf',         0.99,'MEASURED'),
 (3,  4,'SERVICE_STARTED', '2026-04-01 00:05:00','nf',         0.99,'MEASURED'),
 (4,  5,'REGISTERED',      '2026-04-01 00:00:00','nf',         0.99,'MEASURED'),
 (5,  7,'DEREGISTERED',    '2026-04-15 14:20:00','nf',         0.99,'MEASURED'),   -- explicit Nnrf_NFManagement_NFDeregister
 (6,  7,'REGISTERED',      '2026-04-15 14:25:00','nf',         0.99,'MEASURED'),
 (7, 12,'PROFILE_UPDATED', '2026-04-22 17:45:00','operator',   0.99,'MEASURED'),
 (8, 12,'DEREGISTERED',    '2026-04-22 18:15:00','nrf-monitor',0.78,'INFERRED'),   -- heartbeat timeout
 (9,  5,'HEARTBEAT_FAILED','2026-04-23 11:41:30','nrf-monitor',0.95,'MEASURED'),
 (10, 5,'SUSPENDED',       '2026-04-23 11:42:05','nrf-monitor',0.92,'INFERRED'),   -- NRF-side decision after missed HBs
 (11, 8,'DEREGISTERED',    '2026-04-10 03:14:00','nrf-monitor',0.74,'INFERRED'),   -- heartbeat timeout
 (12, 8,'REGISTERED',      '2026-04-10 03:20:00','nf',         0.99,'MEASURED'),
 (13, 3,'PROFILE_UPDATED', '2026-04-18 09:12:00','cicd',       0.99,'MEASURED'),
 (14, 6,'DEREGISTERED',    '2026-04-20 21:00:00','nf',         0.99,'MEASURED'),   -- explicit deregister (maintenance)
 (15, 6,'REGISTERED',      '2026-04-20 21:05:00','nf',         0.99,'MEASURED');

-- ============================================================
-- ONTOLOGY METADATA — drives OWL/SHACL/JSON-LD generation
-- ============================================================

-- TABLE-level
INSERT INTO ontology_metadata
 (target_type,table_name,semantic_type,label,description,sensitivity_tier,is_event_class,skos_pref_label,skos_alt_labels,cq_coverage)
VALUES
 ('TABLE','nf_instance',    'NetworkFunction',       'Network Function',          'A 5G Core Network Function instance (NRF NFProfile per 3GPP TS 29.510).', 'Confidential',0,'Network Function','NF,NF Instance','CQ-5G-001,CQ-5G-002'),
 ('TABLE','nf_service',     'NFService',             'NF Service',                'A service exposed by an NF (Namf, Nsmf, Nudm, ... per 3GPP TS 29.510 §6.1.6.2.4).','Confidential',0,'NF Service','Service','CQ-5G-003'),
 ('TABLE','ue_registration','UERegistrationContext', 'UE Registration Context',   'AMF-owned UE registration state (TS 29.518 §5.2.2).',                    'Restricted',  0,'UE Registration Context','UE Context','CQ-5G-004'),
 ('TABLE','pdu_session',    'PDUSession',            'PDU Session',               'An SMF-managed data session anchored on a UPF (TS 23.502 §4.3).',         'Confidential',0,'PDU Session','Data Session','CQ-5G-005'),
 ('TABLE','slice_instance', 'NetworkSliceInstance',  'Network Slice Instance',    'A Network Slice Instance (NSSI) per 3GPP TS 28.541.',                     'Internal',    0,'Network Slice Instance','NSSI','CQ-5G-006'),
 ('TABLE','pm_counter',     'PMCounter',             'PM Counter',                'Performance-management counter reading (TS 28.552).',                     'Internal',    0,'PM Counter','Performance Counter','CQ-5G-007'),
 ('TABLE','alarm',          'Alarm',                 'Alarm',                     'Fault-management alarm (TS 28.532 §6.3).',                                'Internal',    0,'Alarm','Fault','CQ-5G-008'),
 ('TABLE','nf_event',       'NFLifecycleEvent',      'NF Lifecycle Event',        'Lifecycle transition of a Network Function (registered, deregistered, suspended, ...).','Internal',1,'NF Lifecycle Event','NF Event','CQ-5G-009,CQ-5G-010');

-- COLUMN-level (disambiguate 5 different "status" columns + composite S-NSSAI + SKOS slice-type + PM collision)
INSERT INTO ontology_metadata
 (target_type,table_name,column_name,semantic_type,label,description,sensitivity_tier)
VALUES
 ('COLUMN','nf_instance',    'nf_status',          'xsd:string',     'NF Status',            'NF registration state at the NRF (REGISTERED / SUSPENDED / UNDISCOVERABLE) — TS 29.510 §6.1.6.2.3.',                                         'Confidential'),
 ('COLUMN','nf_service',     'service_status',     'xsd:string',     'Service Status',       'NFService status (REGISTERED / SUSPENDED) — TS 29.510 §6.1.6.2.4.',                                                                      'Confidential'),
 ('COLUMN','ue_registration','registration_state', 'xsd:string',     'Registration State',   'UE registration state at AMF (REGISTERED / DEREGISTERED) — TS 29.518 §5.2.2.',                                                           'Restricted'),
 ('COLUMN','ue_registration','connection_state',   'xsd:string',     'Connection State',     'UE CM state at AMF (IDLE / CONNECTED) — TS 29.518 §5.2.2.',                                                                              'Restricted'),
 ('COLUMN','ue_registration','supi',               'PII',            'SUPI',                 'Subscription Permanent Identifier — direct subscriber PII (TS 23.003 §2.2).',                                                            'Restricted'),
 ('COLUMN','pdu_session',    'session_status',     'xsd:string',     'Session Status',       'PDU session state (ACTIVE / INACTIVE / RELEASED) — TS 23.502 §4.3.',                                                                     'Confidential'),
 ('COLUMN','pdu_session',    'snssai_sst',         'xsd:unsignedByte','S-NSSAI SST',         'Slice/Service Type component of S-NSSAI (8 bits) — TS 23.003 §28.4.2. Composite identifier with snssai_sd.',                         'Internal'),
 ('COLUMN','pdu_session',    'snssai_sd',          'xsd:string',     'S-NSSAI SD',           'Slice Differentiator component of S-NSSAI (24 bits as 6 hex digits) — TS 23.003 §28.4.2. Composite identifier with snssai_sst.',       'Internal'),
 ('COLUMN','slice_instance', 'slice_type_label',   'xsd:string',     'Slice Type Label',     'SKOS-aligned slice type label (eMBB / URLLC / MIoT / V2X) — TS 23.501 Table 5.15.2.2-1.',                                                  'Internal'),
 ('COLUMN','slice_instance', 'sla_latency_ms',     'xsd:integer',    'Max E2E Latency (ms)', 'GSMA NG.116 maxEndToEndLatency.',                                                                                                          'Internal'),
 ('COLUMN','slice_instance', 'operational_state',  'xsd:string',     'Operational State',    'NSSI operational state (ENABLED / DISABLED) — TS 28.541.',                                                                                 'Internal'),
 ('COLUMN','alarm',          'state',              'xsd:string',     'Alarm State',          'Alarm state (ACTIVE / CLEARED) — TS 28.532 §6.3.',                                                                                         'Internal'),
 ('COLUMN','pm_counter',     'counter_name',       'xsd:string',     'Counter Name',         'PM counter name (TS 28.552 for NR). Namespace-collides with TS 32.425 LTE counters — disambiguated by the technology column.',             'Internal'),
 ('COLUMN','pm_counter',     'technology',         'xsd:string',     'Technology',           'NR or LTE — disambiguates PM counter namespace.',                                                                                           'Internal'),
 ('COLUMN','nf_event',       'event_type',         'xsd:string',     'Event Type',           'Discriminator column driving NFLifecycleEvent OWL subclass generation.',                                                                   'Internal'),
 ('COLUMN','nf_event',       'confidence',         'xsd:decimal',    'Confidence',           'PROV-O confidence score (0.0 to 1.0).',                                                                                                     'Internal'),
 ('COLUMN','nf_event',       'derivation',         'xsd:string',     'Derivation Method',    'PROV-O derivation (MEASURED = explicit NFDeregister; INFERRED = NRF heartbeat-timeout triggered).',                                        'Internal'),
 ('COLUMN','nf_event',       'actor_party',        'xsd:string',     'Actor',                'Party that triggered the event (nf / nrf-monitor / operator / cicd). Free-text → IMPLICIT_ACTOR finding.',                                   'Internal');
