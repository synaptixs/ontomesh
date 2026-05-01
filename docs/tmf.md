# TM Forum alignment

How the toolkit aligns generated ontologies to TM Forum SID, ITU-T X.733 alarms, 3GPP 5G NF schemas, and the 24 TMF Open APIs. Includes Phase 2B conflict resolution and ontology alignment + federation.

---

## 5. TM Forum alignment

Run with `--phase tmf` or as part of the full pipeline.

### The SID domains (Phase 2B complete — 24 Open APIs)

| Domain | Key ABEs | Primary APIs | Phase |
|---|---|---|---|
| Resource | LogicalResource, PhysicalResource, NetworkFunction, NetworkSlice | TMF634, TMF639 | 1 |
| Service | CustomerFacingService, ResourceFacingService, ServiceOrder, ServiceProblem | TMF633, TMF638, TMF641, TMF656 | 1 |
| Product | Product, ProductOffering, ProductSpecification, ProductOrder | TMF620, TMF622, TMF637 | 1 |
| EngagedParty | Party, Individual, Organization, PartyRole, CustomerAccount, Agreement | TMF629, TMF632, TMF651, TMF666, TMF669 | 1 |
| Market/Sales | MarketSegment, ProductCatalog, SalesChannel | TMF620 | 1 |
| Supplier/Partner | SupplierAccount, SupplierOrder, SupplierSLA | TMF651 | 1 |
| Enterprise | Policy, UserRole, BusinessInteraction, EventSubscription, ConflictEvent | TMF672, TMF688 | 1 + 2B |
| Common | Characteristic, Note, Attachment, GeographicPlace, GeographicSite | TMF673, TMF674, TMF675 | 1 + 2B |
| **TroubleMgmt** ✓ | **TroubleTicket, ResourceTroubleTicket, CustomerTroubleTicket** | **TMF621** | **2B** |
| **NetworkSliceMgmt** ✓ | **NetworkSliceProfile (3GPP S-NSSAI)** | **TMF645** | **2B** |
| **ServiceQuality** ✓ | **ServiceQualityReport, SLA compliance, KQI** | **TMF657** | **2B** |
| **Billing** ✓ | **CustomerBill, BillingAccount** | **TMF678** | **2B** |
| **Qualification** ✓ | **ProductOfferingQualification, QualificationItem** | **TMF679** | **2B** |

### 5G network functions (3GPP TS 23.501)

`AMF` · `SMF` · `UPF` · `PCF` · `UDM` · `AUSF` · `NRF` · `NEF` · `gNB`

Each is an OWL subclass of `NetworkFunction` with SID annotations, TMF API reference, and eTOM state machine values.

### Alarm model (ITU-T X.733 / TMF642)

Six subtypes: CommunicationsAlarm, EquipmentAlarm, EnvironmentalAlarm, ProcessingErrorAlarm, QualityOfServiceAlarm, SecurityViolation. Full severity ladder (Critical → Cleared), state machine (Active → Acknowledged → Cleared), root cause chaining.

### SID design patterns

**Specification–Instance** — XxxSpec table (catalog template) + instance table pair for Resource, Service, Product.

**Composite** — self-referential parent FK for hierarchies (NetworkSlice composed of NetworkFunctions).

**Characteristic** — polymorphic key-value extensibility table for any entity without schema changes.

### TMF CQ tests (13 tests, all passing)

| CQ | Question | Phase |
|---|---|---|
| CQ-TMF01 | Which 5G NFs are Disabled/Locked and what resources depend on them? | 1 |
| CQ-TMF02 | Which services are Active and which resources realise them? | 1 |
| CQ-TMF03 | Which products are Active and which accounts and orders cover them? | 1 |
| CQ-TMF04 | Which parties hold which roles and which agreements cover those relationships? | 1 |
| CQ-TMF05 | Which SLA agreements are at risk from active alarms or service problems? | 1 |
| CQ-TMF06 | Which Active or uncleared alarms exist by severity and root cause? | 1 |
| CQ-TMF07 | Which KPIs breach thresholds with confidence score and derivation method? | 1 |
| CQ-TMF08 | Full Resource to Service to Product to Customer traceability chain | 1 |
| CQ-TMF09 | Which service orders are incomplete and what product orders triggered them? | 1 |
| **CQ-TMF10** | **Open trouble tickets with resource/service impact and SLA breach status** | **2B** |
| **CQ-TMF11** | **Active network slice profiles with 3GPP S-NSSAI parameters and backing resources** | **2B** |
| **CQ-TMF12** | **Service quality reports showing SLA non-compliance with breached metrics** | **2B** |
| **CQ-TMF13** | **Outstanding and disputed customer bills per account** | **2B** |

### 24 TMF Open APIs mapped

**Phase 1:** TMF620 · TMF622 · TMF629 · TMF632 · TMF633 · TMF634 · TMF637 · TMF638 · TMF639 · TMF641 · TMF642 · TMF651 · TMF656 · TMF666 · TMF669 · TMF672 · TMF673 · TMF688

**Phase 2B:** TMF621 · TMF645 · TMF657 · TMF674 · TMF678 · TMF679

All Apache 2.0. Specifications: [github.com/tmforum-apis](https://github.com/tmforum-apis).

### Phase 2B: Multi-agent conflict resolution (`--phase conflict`)

Implements the 3-tier resolution chain from framework Section 10.1:

- **Tier 1 — SHACL axiom check**: SQL-equivalent consistency rules that catch logically invalid states (e.g. `operational_state=Disabled` + `admin_state=Unlocked`). Escalates violations to Tier 3 automatically.
- **Tier 2 — Derivation-method priority**: When two agents report conflicting values, the higher-priority derivation method wins: `measured > inferred > imported > synthesized > default`. Records PROV-O `wasInvalidatedBy` on the losing assertion.
- **Tier 3 — Human escalation queue**: Unresolvable conflicts are inserted into `tmf_conflict_event` with `escalated_to_human=1` and await review.

Produces: `output/reports/conflict_resolution_report.json`, `output/shapes/conflict-resolution-shapes.ttl`, `output/jsonld/conflict-resolution-mcp-tools.json`.

Three MCP tools: `subscribe_to_events`, `resolve_assertion_conflict`, `get_conflict_queue`.

### Phase 2B: Ontology alignment & federation (`--phase alignment`)

Generates alignment axioms from the toolkit ontology to four external standards:

| Standard | Alignment type | Classes aligned |
|---|---|---|
| DOLCE | `owl:equivalentClass`, `skos:closeMatch` | TmfEntity, DomainEvent, Party, Resource, Service, Agreement |
| FOAF | `owl:equivalentClass` | Party↔foaf:Agent, Individual↔foaf:Person, Organization↔foaf:Organization |
| Schema.org | `owl:equivalentClass`, `skos:closeMatch` | Organization, Product, ProductOrder, GeographicSite, CustomerBill, and 9 more |
| SOSA/SSN | `owl:equivalentClass`, `skos:closeMatch` | ObservationRecord↔sosa:Observation, Resource↔sosa:FeatureOfInterest, Agent↔sosa:Sensor |

Produces: `output/ontology/alignment.ttl` (44 axioms), `output/ontology/federation-config.ttl` (5 named graph endpoints), `output/ontology/federation-queries.sparql` (5 multi-domain federated SPARQL examples).

### Adding more TMF domains

1. Add a table to `db/tmf_schema.sql`
2. Add `ontology_metadata` rows in `db/tmf_seed.sql` with `tmf_api_id`, `sid_domain`, `sid_abe`
3. Add the API to `TMF_API_MAP` in `src/tmf_mapper.py`
4. Add 1-2 CQs to `TMF_COMPETENCY_QUESTIONS` in `src/tmf_mapper.py`
5. Run `python3 toolkit.py`

---

