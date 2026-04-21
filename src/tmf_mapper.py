"""
tmf_mapper.py
──────────────
TM Forum SID alignment layer for the Ontology Toolkit.

Responsibilities:
  1. SID_DOMAINS    — canonical domain → class hierarchy mapping
  2. TMF_API_MAP    — Open API ID → SID class, URL pattern, version
  3. generate_sid_hierarchy()   — OWL Turtle for the SID class tree
  4. generate_tmf_jsonld()      — JSON-LD context with TMF namespaces
  5. TMF_COMPETENCY_QUESTIONS   — 9 additional CQs covering TMF entities
  6. generate_tmf_report()      — CSV report of TMF alignment coverage

Standards covered:
  SID v23.0  — GB922 Information Framework
  eTOM v21.5 — GB921 Business Process Framework
  Open APIs  — 100+ APIs (Apache 2.0), versions per spec
  ODA        — Open Digital Architecture Canvas
"""

import os
import json
import csv
from datetime import datetime

# ── SID Domain → OWL Class Hierarchy ──────────────────────────────────────
#
# Structure: domain → { class: (parent, description, tmf_api, abe) }
# Mirrors the SID Level-1 ABE → Level-2 ABE decomposition

SID_DOMAINS = {
    "Common": {
        "TmfEntity": (None,
            "Root class for all TM Forum SID entities. Carries @type, @baseType, @schemaLocation.", None, "Root BE"),
        "Characteristic": ("TmfEntity",
            "SID Characteristic ABE — extensible key-value pair for any entity.", None, "Characteristic"),
        "TimePeriod": ("TmfEntity",
            "A specific period of time bounded by start and end datetime.", None, "TimePeriod"),
        "Note": ("TmfEntity",
            "Free-text annotation attached to any entity.", None, "Note"),
        "Attachment": ("TmfEntity",
            "A file or URL attachment linked to any entity.", None, "Attachment"),
        "GeographicPlace": ("TmfEntity",
            "A geographic address, site, or location per TMF673/674/675.", "TMF673", "Location"),
        "RelatedParty": ("TmfEntity",
            "A reference to a party and their role in relation to an entity.", "TMF632", "Party"),
    },
    "Resource": {
        "Resource": ("TmfEntity",
            "Base resource entity per SID Resource ABE / TMF639.", "TMF639", "Resource"),
        "LogicalResource": ("Resource",
            "A non-physical resource: IP address, MSISDN, NetworkSlice, NetworkFunction.", "TMF639", "Logical Resource"),
        "PhysicalResource": ("Resource",
            "A physical resource: equipment, antenna, server, card.", "TMF639", "Physical Resource"),
        "NetworkFunction": ("LogicalResource",
            "A 3GPP or ETSI NFV virtualised network function instance (AMF, SMF, UPF, gNB, etc.).", "TMF639", "Logical Resource"),
        "NetworkSlice": ("LogicalResource",
            "An end-to-end 3GPP network slice instance (eMBB, URLLC, mMTC).", "TMF639", "Logical Resource"),
        "ResourceSpecification": ("TmfEntity",
            "Specification / catalog template for a resource type per TMF634.", "TMF634", "Resource Specification"),
        "ResourceRelationship": ("TmfEntity",
            "A typed association between two resource instances (composedOf, connectsTo, dependsOn).", "TMF639", "Resource Topology"),
    },
    "Service": {
        "Service": ("TmfEntity",
            "Base service entity per SID Service ABE / TMF638.", "TMF638", "Service"),
        "CustomerFacingService": ("Service",
            "A service directly perceived by the customer. Maps to TMF638 CFS subtype.", "TMF638", "Customer Facing Service"),
        "ResourceFacingService": ("Service",
            "An internal service that realises a CFS using resources. Maps to TMF638 RFS subtype.", "TMF638", "Resource Facing Service"),
        "ServiceSpecification": ("TmfEntity",
            "Catalog template for a service type per TMF633.", "TMF633", "Service Specification"),
        "ServiceOrder": ("TmfEntity",
            "An internal fulfilment order to provision or modify a service per TMF641.", "TMF641", "Service Order"),
        "ServiceProblem": ("TmfEntity",
            "A service quality or availability problem per SID ServiceProblem / TMF656.", "TMF656", "Service Trouble"),
    },
    "Product": {
        "Product": ("TmfEntity",
            "A product instance subscribed to by a party per SID Product ABE / TMF637.", "TMF637", "Product"),
        "ProductOffering": ("TmfEntity",
            "A commercial product offering available in the catalog per TMF620.", "TMF620", "Product Offering"),
        "ProductSpecification": ("TmfEntity",
            "Specification of a product type per TMF620.", "TMF620", "Product Specification"),
        "ProductOrder": ("TmfEntity",
            "A customer order for a product per TMF622.", "TMF622", "Customer Order"),
        "BundledProductOffering": ("ProductOffering",
            "A product offering composed of multiple component offerings (bundle).", "TMF620", "Product Offering"),
    },
    "EngagedParty": {
        "Party": ("TmfEntity",
            "An individual or organisation that plays a role per SID EngagedParty / TMF632.", "TMF632", "Party"),
        "Individual": ("Party",
            "A natural person — customer, employee, or contact.", "TMF632", "Party"),
        "Organization": ("Party",
            "A legal or operational entity — operator, vendor, regulator, partner.", "TMF632", "Party"),
        "PartyRole": ("TmfEntity",
            "A contextual role a party plays (Customer, Partner, Supplier) per TMF669.", "TMF669", "Party Role"),
        "CustomerAccount": ("TmfEntity",
            "A billing and service management account per TMF666.", "TMF666", "Customer Account"),
        "Agreement": ("TmfEntity",
            "A commercial, SLA, or roaming agreement between parties per TMF651.", "TMF651", "Agreement"),
    },
    "MarketSales": {
        "MarketSegment": ("TmfEntity",
            "A defined segment of the market targeted by products and campaigns.", None, "Market Segment"),
        "ProductCatalog": ("TmfEntity",
            "The catalog of all product offerings available to customers per TMF620.", "TMF620", "Product Offering"),
        "SalesChannel": ("TmfEntity",
            "A channel through which products are sold (retail, online, partner).", None, "Sales Channel"),
    },
    "Enterprise": {
        "Policy": ("TmfEntity",
            "A rule or constraint governing network, operations, or compliance.", "TMF672", "Policy"),
        "UserRole": ("TmfEntity",
            "A named set of permissions for a user per TMF672.", "TMF672", "User Role"),
        "BusinessInteraction": ("TmfEntity",
            "An interaction between enterprise entities (e.g. order, complaint, request).", None, "Business Interaction"),
    },
    "SupplierPartner": {
        "SupplierAccount": ("TmfEntity",
            "A supplier or partner account managed in the supplier/partner domain.", None, "S/P Account"),
        "SupplierOrder": ("TmfEntity",
            "An order placed with a supplier or partner.", None, "S/P Order"),
        "SupplierSLA": ("Agreement",
            "A service level agreement with a supplier or partner.", "TMF651", "S/P SLA"),
    },
    # ── Phase 2B — TMF Remaining Domains ────────────────────
    "TroubleMgmt": {
        "TroubleTicket": ("TmfEntity",
            "A customer or resource trouble ticket per TMF621. Tracks issue lifecycle from New to Closed.", "TMF621", "Service Trouble"),
        "ResourceTroubleTicket": ("TroubleTicket",
            "A trouble ticket specifically associated with a resource fault or outage.", "TMF621", "Resource Trouble"),
        "CustomerTroubleTicket": ("TroubleTicket",
            "A trouble ticket raised by or on behalf of a customer.", "TMF621", "Customer Problem"),
    },
    "NetworkSliceMgmt": {
        "NetworkSliceProfile": ("TmfEntity",
            "A 3GPP S-NSSAI-aligned network slice profile with SLA parameters per TMF645.", "TMF645", "Logical Resource"),
    },
    "ServiceQuality": {
        "ServiceQualityReport": ("TmfEntity",
            "An SLA compliance or KQI quality assessment report per TMF657.", "TMF657", "Service Quality"),
    },
    "GeographicSite": {
        "GeographicSite": ("TmfEntity",
            "A structured physical site record (data centre, cell tower, PoP) per TMF674.", "TMF674", "Location"),
    },
    "Billing": {
        "CustomerBill": ("TmfEntity",
            "A customer invoice per TMF678 Customer Bill Management.", "TMF678", "Customer Account"),
        "BillingAccount": ("TmfEntity",
            "The billing account that owns the bill relationship per TMF678.", "TMF678", "Customer Account"),
    },
    "Qualification": {
        "ProductOfferingQualification": ("TmfEntity",
            "An eligibility/feasibility check for a product offering at a customer site per TMF679.", "TMF679", "Product Offering"),
        "QualificationItem": ("ProductOfferingQualification",
            "A single line item within a product offering qualification request.", "TMF679", "Product Offering"),
    },
    # ── Event Hub & Conflict Resolution ─────────────────────
    "EventHub": {
        "EventSubscription": ("TmfEntity",
            "An async notification subscription per TMF630 §5 event hub pattern.", "TMF688", "Business Interaction"),
        "EventNotification": ("TmfEntity",
            "An event notification payload delivered to a subscriber's callback URL.", "TMF688", "Business Interaction"),
    },
    "ConflictResolution": {
        "ConflictEvent": ("TmfEntity",
            "A multi-agent assertion conflict record with 3-tier resolution chain per framework §10.1.", None, "Policy"),
        "AssertionResolution": ("ConflictEvent",
            "The winning assertion and resolution rationale for a resolved conflict event.", None, "Policy"),
    },
}

# ── TMF Open API Reference Map ─────────────────────────────────────────────
# api_id → { name, version, sid_class, sid_domain, url_pattern, description }

TMF_API_MAP = {
    "TMF620": {
        "name": "Product Catalog Management API",
        "version": "v5.0",
        "sid_class": "ProductOffering",
        "sid_domain": "Product",
        "url_pattern": "/tmf-api/productCatalogManagement/v5/",
        "resource_name": "productOffering",
        "schema_location": "https://tmforum-apis.github.io/V5.0.0_OneAPI/swagger2.0/TMF620-ProductCatalog-v5.0.0.swagger.json",
        "description": "Manages the lifecycle of catalog elements: productSpecification, productOffering, category.",
    },
    "TMF622": {
        "name": "Product Ordering Management API",
        "version": "v5.0",
        "sid_class": "ProductOrder",
        "sid_domain": "Product",
        "url_pattern": "/tmf-api/productOrderingManagement/v5/productOrder",
        "resource_name": "productOrder",
        "schema_location": "https://tmforum-apis.github.io/V5.0.0_OneAPI/swagger2.0/TMF622-ProductOrdering-v5.0.0.swagger.json",
        "description": "Manages product orders from submission through completion.",
    },
    "TMF629": {
        "name": "Customer Management API",
        "version": "v4.0",
        "sid_class": "Party",
        "sid_domain": "EngagedParty",
        "url_pattern": "/tmf-api/customerManagement/v4/customer",
        "resource_name": "customer",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF629-Customer-v4.0.0.swagger.json",
        "description": "Provides customer lifecycle management.",
    },
    "TMF632": {
        "name": "Party Management API",
        "version": "v5.0",
        "sid_class": "Party",
        "sid_domain": "EngagedParty",
        "url_pattern": "/tmf-api/partyManagement/v5/individual",
        "resource_name": "individual",
        "schema_location": "https://tmforum-apis.github.io/V5.0.0_OneAPI/swagger2.0/TMF632-Party-v5.0.0.swagger.json",
        "description": "Manages individuals and organisations.",
    },
    "TMF633": {
        "name": "Service Catalog Management API",
        "version": "v4.0",
        "sid_class": "ServiceSpecification",
        "sid_domain": "Service",
        "url_pattern": "/tmf-api/serviceCatalogManagement/v4/serviceSpecification",
        "resource_name": "serviceSpecification",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF633-ServiceCatalog-v4.0.0.swagger.json",
        "description": "Manages service catalog: serviceSpecification and serviceCategory.",
    },
    "TMF634": {
        "name": "Resource Catalog Management API",
        "version": "v4.0",
        "sid_class": "ResourceSpecification",
        "sid_domain": "Resource",
        "url_pattern": "/tmf-api/resourceCatalog/v4/resourceSpecification",
        "resource_name": "resourceSpecification",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF634-ResourceCatalog-v4.0.0.swagger.json",
        "description": "Manages resource specifications and catalog entries.",
    },
    "TMF637": {
        "name": "Product Inventory Management API",
        "version": "v4.0",
        "sid_class": "Product",
        "sid_domain": "Product",
        "url_pattern": "/tmf-api/productInventory/v4/product",
        "resource_name": "product",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF637-ProductInventory-v4.0.0.swagger.json",
        "description": "Manages product instances in the inventory.",
    },
    "TMF638": {
        "name": "Service Inventory Management API",
        "version": "v4.0",
        "sid_class": "Service",
        "sid_domain": "Service",
        "url_pattern": "/tmf-api/serviceInventory/v4/service",
        "resource_name": "service",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF638-ServiceInventory-v4.0.0.swagger.json",
        "description": "Manages service instances (CFS and RFS) in the inventory.",
    },
    "TMF639": {
        "name": "Resource Inventory Management API",
        "version": "v5.0",
        "sid_class": "Resource",
        "sid_domain": "Resource",
        "url_pattern": "/tmf-api/resourceInventoryManagement/v5/resource",
        "resource_name": "resource",
        "schema_location": "https://tmforum-apis.github.io/V5.0.0_OneAPI/swagger2.0/TMF639-ResourceInventory-v5.0.0.swagger.json",
        "description": "Manages logical and physical resource instances.",
    },
    "TMF641": {
        "name": "Service Order Management API",
        "version": "v4.0",
        "sid_class": "ServiceOrder",
        "sid_domain": "Service",
        "url_pattern": "/tmf-api/serviceOrdering/v4/serviceOrder",
        "resource_name": "serviceOrder",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF641-ServiceOrdering-v4.0.0.swagger.json",
        "description": "Manages service fulfilment orders.",
    },
    "TMF642": {
        "name": "Alarm Management API",
        "version": "v4.0",
        "sid_class": "Alarm",
        "sid_domain": "Resource",
        "url_pattern": "/tmf-api/alarmManagement/v4/alarm",
        "resource_name": "alarm",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF642-Alarm-v4.0.0.swagger.json",
        "description": "Manages network alarms per ITU-T X.733 and 3GPP fault management.",
    },
    "TMF651": {
        "name": "Agreement Management API",
        "version": "v4.0",
        "sid_class": "Agreement",
        "sid_domain": "EngagedParty",
        "url_pattern": "/tmf-api/agreementManagement/v4/agreement",
        "resource_name": "agreement",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF651-Agreement-v4.0.0.swagger.json",
        "description": "Manages commercial and SLA agreements between parties.",
    },
    "TMF656": {
        "name": "Service Problem Management API",
        "version": "v4.0",
        "sid_class": "ServiceProblem",
        "sid_domain": "Service",
        "url_pattern": "/tmf-api/serviceProblemManagement/v4/serviceProblem",
        "resource_name": "serviceProblem",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF656-ServiceProblem-v4.0.0.swagger.json",
        "description": "Manages service problems and trouble tickets.",
    },
    "TMF666": {
        "name": "Account Management API",
        "version": "v5.0",
        "sid_class": "CustomerAccount",
        "sid_domain": "EngagedParty",
        "url_pattern": "/tmf-api/accountManagement/v5/partyAccount",
        "resource_name": "partyAccount",
        "schema_location": "https://tmforum-apis.github.io/V5.0.0_OneAPI/swagger2.0/TMF666-Account-v5.0.0.swagger.json",
        "description": "Manages customer and party accounts.",
    },
    "TMF669": {
        "name": "Party Role Management API",
        "version": "v5.0",
        "sid_class": "PartyRole",
        "sid_domain": "EngagedParty",
        "url_pattern": "/tmf-api/partyRoleManagement/v5/partyRole",
        "resource_name": "partyRole",
        "schema_location": "https://tmforum-apis.github.io/V5.0.0_OneAPI/swagger2.0/TMF669-PartyRole-v5.0.0.swagger.json",
        "description": "Manages the roles parties play in business interactions.",
    },
    "TMF672": {
        "name": "User Roles and Permissions API",
        "version": "v4.0",
        "sid_class": "UserRole",
        "sid_domain": "Enterprise",
        "url_pattern": "/tmf-api/userRolesPermissions/v4/userRole",
        "resource_name": "userRole",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF672-UserRolesPermissions-v4.0.0.swagger.json",
        "description": "Manages user roles and permission grants.",
    },
    "TMF673": {
        "name": "Geographic Address Management API",
        "version": "v4.0",
        "sid_class": "GeographicPlace",
        "sid_domain": "Common",
        "url_pattern": "/tmf-api/geographicAddressManagement/v4/geographicAddress",
        "resource_name": "geographicAddress",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF673-GeographicAddress-v4.0.0.swagger.json",
        "description": "Manages geographic addresses and address validation.",
    },
    "TMF688": {
        "name": "Event Management API",
        "version": "v4.0",
        "sid_class": "BusinessInteraction",
        "sid_domain": "Enterprise",
        "url_pattern": "/tmf-api/eventManagement/v4/event",
        "resource_name": "event",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF688-Event-v4.0.0.swagger.json",
        "description": "Manages asynchronous event publication and subscription.",
    },
    # ── Phase 2B — New APIs ──────────────────────────────────
    "TMF621": {
        "name": "Trouble Ticket Management API",
        "version": "v4.0",
        "sid_class": "TroubleTicket",
        "sid_domain": "TroubleMgmt",
        "url_pattern": "/tmf-api/troubleTicket/v4/troubleTicket",
        "resource_name": "troubleTicket",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF621-TroubleTicket-v4.0.0.swagger.json",
        "description": "Manages customer and resource trouble tickets from creation through resolution.",
    },
    "TMF645": {
        "name": "Service Qualification Management API",
        "version": "v4.0",
        "sid_class": "NetworkSliceProfile",
        "sid_domain": "NetworkSliceMgmt",
        "url_pattern": "/tmf-api/serviceQualificationManagement/v4/checkServiceQualification",
        "resource_name": "checkServiceQualification",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF645-ServiceQualification-v4.0.0.swagger.json",
        "description": "Manages network slice profiles and service qualification checks (3GPP S-NSSAI).",
    },
    "TMF657": {
        "name": "Service Quality Management API",
        "version": "v4.0",
        "sid_class": "ServiceQualityReport",
        "sid_domain": "ServiceQuality",
        "url_pattern": "/tmf-api/serviceQualityManagement/v4/serviceLevelObjective",
        "resource_name": "serviceLevelObjective",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF657-ServiceQuality-v4.0.0.swagger.json",
        "description": "Manages service quality reports, SLA compliance checks, and KQI assessments.",
    },
    "TMF674": {
        "name": "Geographic Site Management API",
        "version": "v4.0",
        "sid_class": "GeographicSite",
        "sid_domain": "GeographicSite",
        "url_pattern": "/tmf-api/geographicSiteManagement/v4/geographicSite",
        "resource_name": "geographicSite",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF674-GeographicSite-v4.0.0.swagger.json",
        "description": "Manages geographic sites (data centres, cell towers, PoP sites) with full operational attributes.",
    },
    "TMF678": {
        "name": "Customer Bill Management API",
        "version": "v4.0",
        "sid_class": "CustomerBill",
        "sid_domain": "Billing",
        "url_pattern": "/tmf-api/customerBillManagement/v4/customerBill",
        "resource_name": "customerBill",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF678-CustomerBill-v4.0.0.swagger.json",
        "description": "Manages customer bills, invoices, and credit notes with dispute tracking.",
    },
    "TMF679": {
        "name": "Product Offering Qualification API",
        "version": "v4.0",
        "sid_class": "ProductOfferingQualification",
        "sid_domain": "Qualification",
        "url_pattern": "/tmf-api/productOfferingQualification/v4/productOfferingQualification",
        "resource_name": "productOfferingQualification",
        "schema_location": "https://tmforum-apis.github.io/V4.0.0_OneAPI/swagger2.0/TMF679-ProductOfferingQualification-v4.0.0.swagger.json",
        "description": "Checks eligibility and technical feasibility for product offerings at a given customer location.",
    },
}

# ── TMF-specific Competency Questions ─────────────────────────────────────
TMF_COMPETENCY_QUESTIONS = [
    {
        "id": "CQ-TMF01",
        "question": "Which 5G network functions are currently Disabled or Locked, and what resources depend on them?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?nf ?state ?admin ?dependent WHERE { "
            "?nf a :NetworkFunction ; :hasOperationalState ?state ; :hasAdminState ?admin . "
            "OPTIONAL { ?dependent :reliesOn ?nf } "
            "FILTER(?state='Disabled' || ?admin='Locked') }"
        ),
        "sql": """
            SELECT r.name AS network_function, r.nf_type,
                   r.operational_state, r.admin_state,
                   dep.name AS dependent_resource
            FROM tmf_resource r
            LEFT JOIN tmf_resource_relationship rr ON rr.related_resource_id = r.id
                AND rr.relationship_type IN ('relies-on','composedOf')
            LEFT JOIN tmf_resource dep ON rr.resource_id = dep.id
            WHERE r.resource_type IN ('NETWORK_FUNCTION','NETWORK_SLICE')
              AND (r.operational_state = 'Disabled' OR r.admin_state = 'Locked')
            ORDER BY r.nf_type
        """,
        "expected_non_empty": True,
        "validates": "SID Resource ABE operational state, resource topology relationship",
    },
    {
        "id": "CQ-TMF02",
        "question": "Which services are in Active state and which resources realise them (SID CFS→RFS→Resource chain)?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?cfs ?rfs ?resource WHERE { "
            "?cfs a :CustomerFacingService ; :state 'Active' . "
            "OPTIONAL { ?rfs a :ResourceFacingService ; :realisedBy ?cfs . "
            "?resource a :Resource ; :realisesService ?rfs } }"
        ),
        "sql": """
            SELECT s.name AS service, s.service_type, s.state,
                   r.name AS realising_resource, r.nf_type,
                   r.operational_state
            FROM tmf_service s
            LEFT JOIN tmf_resource r ON s.realising_resource_id = r.id
            WHERE s.state = 'Active'
            ORDER BY s.service_type, s.name
        """,
        "expected_non_empty": True,
        "validates": "SID Service ABE CFS/RFS pattern, Service-Resource realisation",
    },
    {
        "id": "CQ-TMF03",
        "question": "Which products are Active and which customer accounts and orders are associated with them?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?product ?account ?order WHERE { "
            "?product a :Product ; :hasStatus 'Active' . "
            "?order a :ProductOrder ; :hasProduct ?product . "
            "?account a :CustomerAccount ; :placeOrder ?order }"
        ),
        "sql": """
            SELECT p.name AS product, p.status,
                   ca.account_number, ca.name AS account_name,
                   po.order_iri, po.order_type, po.state AS order_state
            FROM tmf_product p
            LEFT JOIN tmf_product_offering po2 ON p.product_offering_id = po2.id
            LEFT JOIN tmf_product_order po ON po.product_offering_id = po2.id
            LEFT JOIN tmf_customer_account ca ON po.customer_account_id = ca.id
            WHERE p.status = 'Active'
            ORDER BY p.name
        """,
        "expected_non_empty": True,
        "validates": "SID Product ABE, ProductOrder, CustomerAccount chain",
    },
    {
        "id": "CQ-TMF04",
        "question": "Which parties hold which roles, and which agreements cover those relationships?",
        "priority": "High",
        "sparql_equiv": (
            "SELECT ?party ?role ?agreement WHERE { "
            "?party a :Party ; :playsRole ?role . "
            "OPTIONAL { ?agreement a :Agreement ; :involvesParty ?party } }"
        ),
        "sql": """
            SELECT p.name AS party, p.party_type,
                   pr.role_name, pr.role_type,
                   a.name AS agreement_name, a.agreement_type, a.status AS agreement_status
            FROM tmf_party p
            LEFT JOIN tmf_party_role pr ON pr.party_id = p.id
            LEFT JOIN tmf_agreement a ON a.party_a_id = p.id OR a.party_b_id = p.id
            ORDER BY p.name
        """,
        "expected_non_empty": True,
        "validates": "SID EngagedParty domain, Party-PartyRole-Agreement chain",
    },
    {
        "id": "CQ-TMF05",
        "question": "Which SLA agreements are at risk due to active alarms or service problems on covered services?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?sla ?service ?problem ?sla_violated WHERE { "
            "?sla a :Agreement ; :agreement_type 'SLA' . "
            "?problem a :ServiceProblem ; :affectsService ?service ; "
            ":slaViolated ?sla_violated }"
        ),
        "sql": """
            SELECT a.name AS sla_name, a.valid_until,
                   sp.description AS problem, sp.priority, sp.status,
                   sp.sla_violated,
                   s.name AS affected_service,
                   al.perceived_severity AS alarm_severity
            FROM tmf_agreement a
            JOIN tmf_customer_account ca ON
                ca.party_id = a.party_b_id
            JOIN tmf_product po ON po.status='Active'
            JOIN tmf_service s ON po.realising_service_id = s.id
            LEFT JOIN tmf_service_problem sp ON sp.service_id = s.id
            LEFT JOIN tmf_alarm al ON sp.alarm_id = al.id
            WHERE a.agreement_type = 'SLA'
              AND a.status = 'Active'
            ORDER BY sp.sla_violated DESC, sp.priority
        """,
        "expected_non_empty": True,
        "validates": "SID Agreement ABE, SLA breach linkage to ServiceProblem",
    },
    {
        "id": "CQ-TMF06",
        "question": "Which Active or uncleared alarms exist, their severity, source resource, and root cause chain?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?alarm ?severity ?resource ?rootCause WHERE { "
            "?alarm a :Alarm ; :perceivedSeverity ?severity ; "
            ":sourceResource ?resource . "
            "?alarm :alarmState ?state FILTER(?state != 'Cleared') "
            "OPTIONAL { ?alarm :rootCauseAlarm ?rootCause } }"
        ),
        "sql": """
            SELECT al.alarm_iri, al.alarm_type, al.perceived_severity,
                   al.alarm_state, al.probable_cause, al.specific_problem,
                   r.name AS source_resource, r.nf_type,
                   rc.specific_problem AS root_cause_problem
            FROM tmf_alarm al
            LEFT JOIN tmf_resource r ON al.source_resource_id = r.id
            LEFT JOIN tmf_alarm rc ON al.root_cause_alarm_id = rc.id
            WHERE al.alarm_state != 'Cleared'
            ORDER BY
              CASE al.perceived_severity
                WHEN 'Critical' THEN 1 WHEN 'Major' THEN 2
                WHEN 'Minor' THEN 3 WHEN 'Warning' THEN 4 ELSE 5
              END
        """,
        "expected_non_empty": True,
        "validates": "SID Resource Trouble ABE, TMF642 alarm severity and root cause",
    },
    {
        "id": "CQ-TMF07",
        "question": "Which KPIs breach their thresholds, and what is the confidence score and derivation method for each measurement?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?kpi ?resource ?value ?threshold ?confidence ?method WHERE { "
            "?kpi a :PerformanceIndicator ; :breachIndicator true ; "
            ":numericValue ?value ; :thresholdHigh ?threshold ; "
            ":hasConfidenceScore ?confidence ; :derivationMethod ?method ; "
            ":aboutResource ?resource }"
        ),
        "sql": """
            SELECT pi.name AS kpi_name, pi.kpi_type,
                   r.name AS resource, r.nf_type,
                   pi.numeric_value, pi.unit_of_measure,
                   pi.threshold_high, pi.threshold_low,
                   pi.confidence_score, pi.derivation_method,
                   pi.observed_at
            FROM tmf_performance_indicator pi
            LEFT JOIN tmf_resource r ON pi.resource_id = r.id
            WHERE pi.breach_indicator = 1
            ORDER BY pi.kpi_type, pi.observed_at DESC
        """,
        "expected_non_empty": True,
        "validates": "SID ResourcePerformance ABE, PROV-O confidence and derivation",
    },
    {
        "id": "CQ-TMF08",
        "question": "What is the complete resource-to-service-to-product-to-customer traceability chain for a given resource?",
        "priority": "High",
        "sparql_equiv": (
            "SELECT ?resource ?service ?product ?customer WHERE { "
            "?service :realisedBy ?resource . "
            "?product :realisedByService ?service . "
            "?order :orderedProduct ?product . "
            "?account :placedOrder ?order . "
            "?customer :hasAccount ?account }"
        ),
        "sql": """
            -- Full vertical chain: Resource → RFS → CFS → Product → Order → Account → Customer
            -- The RFS (resource_facing_service) links directly to the resource.
            -- The CFS (customer_facing_service) links to the RFS via parent_service_id.
            SELECT r.name AS resource, r.nf_type,
                   rfs.name AS rfs_service,
                   cfs.name AS cfs_service, cfs.state,
                   p.name AS product, p.status AS product_status,
                   pt.name AS customer, pt.party_type,
                   ca.account_number
            FROM tmf_resource r
            JOIN tmf_service rfs ON rfs.realising_resource_id = r.id
                AND rfs.service_type = 'RESOURCE_FACING_SERVICE'
            JOIN tmf_service cfs ON cfs.parent_service_id = rfs.id
                AND cfs.service_type = 'CUSTOMER_FACING_SERVICE'
            JOIN tmf_product p ON p.realising_service_id = cfs.id
            JOIN tmf_product_offering po2 ON p.product_offering_id = po2.id
            JOIN tmf_product_order po ON po.product_offering_id = po2.id
            JOIN tmf_customer_account ca ON po.customer_account_id = ca.id
            JOIN tmf_party pt ON ca.party_id = pt.id
            ORDER BY r.name
        """,
        "expected_non_empty": True,
        "validates": "Full SID Resource→Service→Product→Customer vertical slice traceability",
    },
    {
        "id": "CQ-TMF09",
        "question": "Which service orders are incomplete, and what product orders triggered them?",
        "priority": "High",
        "sparql_equiv": (
            "SELECT ?serviceOrder ?state ?productOrder WHERE { "
            "?serviceOrder a :ServiceOrder ; :hasState ?state "
            "FILTER(?state NOT IN ('Complete','Cancelled')) "
            "?productOrder a :ProductOrder ; :triggeredServiceOrder ?serviceOrder }"
        ),
        "sql": """
            SELECT so.order_iri AS service_order,
                   so.order_date, so.order_type,
                   so.state AS so_state,
                   po.order_iri AS product_order,
                   po.state AS po_state,
                   ss.name AS service_spec
            FROM tmf_service_order so
            LEFT JOIN tmf_product_order po ON so.product_order_id = po.id
            LEFT JOIN tmf_service_spec ss ON so.service_spec_id = ss.id
            WHERE so.state NOT IN ('Complete','Cancelled')
            ORDER BY so.order_date
        """,
        "expected_non_empty": False,
        "validates": "TMF641 ServiceOrder lifecycle, ProductOrder→ServiceOrder link",
    },
    # ── Phase 2B CQs ─────────────────────────────────────────────────────
    {
        "id": "CQ-TMF10",
        "question": "Which trouble tickets are open or in-progress, what resources or services are affected, and which have breached SLA?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?ticket ?severity ?resource ?service ?sla_violated WHERE { "
            "?ticket a :TroubleTicket ; :hasStatus ?status "
            "FILTER(?status NOT IN ('Resolved','Closed','Cancelled')) "
            "OPTIONAL { ?ticket :affectsResource ?resource } "
            "OPTIONAL { ?ticket :affectsService ?service } "
            "OPTIONAL { ?ticket :slaViolated ?sla_violated } }"
        ),
        "sql": """
            SELECT tt.ticket_iri, tt.ticket_type, tt.severity, tt.priority,
                   tt.status, tt.category,
                   r.name AS affected_resource, r.nf_type,
                   s.name AS affected_service,
                   al.perceived_severity AS alarm_severity,
                   tt.sla_violated, tt.submitted_at
            FROM tmf_trouble_ticket tt
            LEFT JOIN tmf_resource r ON tt.affected_resource_id = r.id
            LEFT JOIN tmf_service s ON tt.affected_service_id = s.id
            LEFT JOIN tmf_alarm al ON tt.related_alarm_id = al.id
            WHERE tt.status NOT IN ('Resolved','Closed','Cancelled')
            ORDER BY
              CASE tt.severity
                WHEN '1-Critical' THEN 1 WHEN '2-High' THEN 2
                WHEN '3-Medium' THEN 3 ELSE 4
              END
        """,
        "expected_non_empty": True,
        "validates": "TMF621 TroubleTicket lifecycle, resource and service fault linkage, SLA breach tracking",
    },
    {
        "id": "CQ-TMF11",
        "question": "Which network slice profiles are active, what are their SLA parameters, and which resource instances back them?",
        "priority": "High",
        "sparql_equiv": (
            "SELECT ?profile ?sliceType ?latency ?reliability ?resource WHERE { "
            "?profile a :NetworkSliceProfile ; :sliceType ?sliceType ; "
            ":latencyTargetMs ?latency ; :reliabilityTarget ?reliability . "
            "OPTIONAL { ?profile :backedByResource ?resource } "
            "FILTER(?profile :lifecycleStatus 'Active') }"
        ),
        "sql": """
            SELECT nsp.profile_iri, nsp.name AS profile_name,
                   nsp.slice_type, nsp.sst, nsp.sd,
                   nsp.max_dl_throughput, nsp.max_ul_throughput,
                   nsp.latency_target_ms, nsp.reliability_target,
                   nsp.max_devices, nsp.lifecycle_status,
                   r.name AS resource_name, r.operational_state,
                   a.name AS covered_by_sla
            FROM tmf_network_slice_profile nsp
            LEFT JOIN tmf_resource r ON nsp.resource_id = r.id
            LEFT JOIN tmf_agreement a ON nsp.agreement_id = a.id
            WHERE nsp.lifecycle_status = 'Active'
            ORDER BY nsp.slice_type
        """,
        "expected_non_empty": True,
        "validates": "TMF645 NetworkSliceProfile, 3GPP S-NSSAI parameters, Resource-Slice linkage",
    },
    {
        "id": "CQ-TMF12",
        "question": "Which service quality reports show SLA non-compliance, and what metrics breached their thresholds?",
        "priority": "Critical",
        "sparql_equiv": (
            "SELECT ?report ?service ?agreement ?score WHERE { "
            "?report a :ServiceQualityReport ; :slaCompliant false ; "
            ":overallQualityScore ?score ; "
            ":coversService ?service ; :coversAgreement ?agreement }"
        ),
        "sql": """
            SELECT sqr.report_iri, sqr.report_type,
                   sqr.period_start, sqr.period_end,
                   sqr.overall_quality_score, sqr.sla_compliant,
                   sqr.quality_metrics,
                   s.name AS service_name,
                   a.name AS agreement_name, a.valid_until
            FROM tmf_service_quality_report sqr
            LEFT JOIN tmf_service s ON sqr.service_id = s.id
            LEFT JOIN tmf_agreement a ON sqr.agreement_id = a.id
            WHERE sqr.sla_compliant = 0
            ORDER BY sqr.overall_quality_score ASC
        """,
        "expected_non_empty": True,
        "validates": "TMF657 ServiceQualityReport, SLA compliance tracking, KQI threshold breach",
    },
    {
        "id": "CQ-TMF13",
        "question": "Which customer bills are outstanding or disputed, and what is the total amount due per account?",
        "priority": "High",
        "sparql_equiv": (
            "SELECT ?bill ?account ?amount ?state ?disputed WHERE { "
            "?bill a :CustomerBill ; :billedAccount ?account ; "
            ":amountDue ?amount ; :billState ?state . "
            "OPTIONAL { ?bill :disputed ?disputed } "
            "FILTER(?state NOT IN ('Settled','Cancelled')) }"
        ),
        "sql": """
            SELECT cb.bill_number, cb.bill_type, cb.bill_date,
                   cb.payment_due_date, cb.amount_due, cb.tax_amount,
                   cb.currency_code, cb.state, cb.disputed,
                   cb.dispute_reason,
                   ca.account_number, ca.name AS account_name,
                   p.name AS party_name
            FROM tmf_customer_bill cb
            JOIN tmf_customer_account ca ON cb.customer_account_id = ca.id
            JOIN tmf_party p ON ca.party_id = p.id
            WHERE cb.state NOT IN ('Settled','Cancelled')
            ORDER BY cb.payment_due_date ASC
        """,
        "expected_non_empty": True,
        "validates": "TMF678 CustomerBill, outstanding invoices and dispute tracking",
    },
]

# ── SID Ontology Turtle Generator ──────────────────────────────────────────

BASE_IRI   = "https://ontology.example.com/tmf/"
PROV       = "http://www.w3.org/ns/prov#"
OWL_NS     = "http://www.w3.org/2002/07/owl#"
RDFS_NS    = "http://www.w3.org/2000/01/rdf-schema#"
SKOS_NS    = "http://www.w3.org/2004/02/skos/core#"
XSD_NS     = "http://www.w3.org/2001/XMLSchema#"
TMF_NS     = "https://www.tmforum.org/sid/"
ETOM_NS    = "https://www.tmforum.org/etom/"

TMF_PREFIXES = f"""\
@prefix :       <{BASE_IRI}> .
@prefix tmf:    <{TMF_NS}> .
@prefix etom:   <{ETOM_NS}> .
@prefix owl:    <{OWL_NS}> .
@prefix rdfs:   <{RDFS_NS}> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:    <{XSD_NS}> .
@prefix skos:   <{SKOS_NS}> .
@prefix prov:   <{PROV}> .
@prefix dcterms:<http://purl.org/dc/terms/> .
"""


def generate_sid_hierarchy(output_dir: str):
    """Generate OWL Turtle file representing the SID class hierarchy."""
    os.makedirs(output_dir, exist_ok=True)
    lines = [
        TMF_PREFIXES,
        f'<{BASE_IRI}sid/>\n'
        f'  a owl:Ontology ;\n'
        f'  rdfs:label "TM Forum SID-Aligned Ontology" ;\n'
        f'  rdfs:comment "OWL 2 representation of the TM Forum Information Framework (SID) v23.0 domains and ABEs." ;\n'
        f'  dcterms:source "https://www.tmforum.org/open-digital-architecture/information-framework-sid/" ;\n'
        f'  owl:versionInfo "23.0" .\n',
        "\n# ── Annotation Properties ──────────────────────────────────────────\n",
        ":sidDomain a owl:AnnotationProperty ;\n"
        "  rdfs:label \"SID Domain\" ;\n"
        '  rdfs:comment "The TM Forum SID domain this class belongs to." .\n',
        ":sidABE a owl:AnnotationProperty ;\n"
        "  rdfs:label \"SID ABE\" ;\n"
        '  rdfs:comment "The SID Aggregate Business Entity (ABE) this class maps to." .\n',
        ":tmfApiId a owl:AnnotationProperty ;\n"
        "  rdfs:label \"TMF Open API ID\" ;\n"
        '  rdfs:comment "The primary TM Forum Open API that manages instances of this class." .\n',
        ":tmfApiVersion a owl:AnnotationProperty ;\n"
        "  rdfs:label \"TMF API Version\" .\n\n",
    ]

    for domain, classes in SID_DOMAINS.items():
        lines.append(f"# ── SID Domain: {domain} {'─'*(44-len(domain))}\n")
        for cls, (parent, desc, api_id, abe) in classes.items():
            parent_str = f":{parent}" if parent else "owl:Thing"
            block = [
                f":{cls}",
                f"  a owl:Class ;",
                f"  rdfs:subClassOf {parent_str} ;",
                f'  rdfs:label "{cls}" ;',
                f'  rdfs:comment "{desc}" ;',
                f'  :sidDomain "{domain}" ;',
                f'  :sidABE "{abe}" ;',
            ]
            if api_id:
                api = TMF_API_MAP.get(api_id, {})
                block.append(f'  :tmfApiId "{api_id}" ;')
                block.append(f'  :tmfApiVersion "{api.get("version","")}" ;')
            # Close
            block[-1] = block[-1][:-1] + " ."
            lines.append("\n".join(block) + "\n")
        lines.append("\n")

    # Add 5G-specific subclasses
    lines.append("# ── 5G Network Function Subclasses (3GPP TS 23.501) ─────────────────\n")
    nf_types = [
        ("AMF", "Access and Mobility Function — handles UE registration, mobility, and connection management."),
        ("SMF", "Session Management Function — handles PDU session establishment and IP address assignment."),
        ("UPF", "User Plane Function — handles user data forwarding, QoS enforcement, and traffic reporting."),
        ("PCF", "Policy Control Function — provides policy rules for session and service data flows."),
        ("UDM", "Unified Data Management — manages subscriber data and authentication credentials."),
        ("AUSF", "Authentication Server Function — provides EAP-based authentication for 5G subscribers."),
        ("NRF", "Network Repository Function — NF service registration and discovery."),
        ("NEF", "Network Exposure Function — exposes 5G network capabilities to external applications."),
        ("gNB", "5G NR gNodeB — base station for 5G New Radio access network."),
    ]
    for nf, desc in nf_types:
        lines.append(
            f":{nf}NetworkFunction\n"
            f"  a owl:Class ;\n"
            f"  rdfs:subClassOf :NetworkFunction ;\n"
            f'  rdfs:label "{nf}" ;\n'
            f'  rdfs:comment "{desc}" ;\n'
            f'  :sidDomain "Resource" ;\n'
            f'  :sidABE "Logical Resource" ;\n'
            f'  :tmfApiId "TMF639" .\n\n'
        )

    # Add Alarm subclasses (ITU-T X.733 / TMF642)
    lines.append("# ── Alarm Subclasses (ITU-T X.733 / TMF642) ─────────────────────────\n")
    alarm_types = [
        ("CommunicationsAlarm", "Failures in communication paths, interfaces, or protocols."),
        ("EquipmentAlarm", "Hardware faults in network equipment or servers."),
        ("EnvironmentalAlarm", "Physical environment issues: temperature, power, humidity."),
        ("ProcessingErrorAlarm", "Software errors, process failures, or configuration faults."),
        ("QualityOfServiceAlarm", "KPI breaches: packet loss, latency, throughput, availability."),
        ("SecurityViolation", "Security policy violations or unauthorised access attempts."),
    ]
    for at, desc in alarm_types:
        lines.append(
            f":{at}\n"
            f"  a owl:Class ;\n"
            f"  rdfs:subClassOf :Alarm ;\n"
            f'  rdfs:label "{at}" ;\n'
            f'  rdfs:comment "{desc}" ;\n'
            f'  :sidDomain "Resource" ;\n'
            f'  :sidABE "Resource Trouble" ;\n'
            f'  :tmfApiId "TMF642" .\n\n'
        )
    # Add Alarm as a DomainEvent subclass
    lines.insert(4,
        "\n:Alarm\n"
        "  a owl:Class ;\n"
        "  rdfs:subClassOf :DomainEvent ;\n"
        '  rdfs:label "Alarm" ;\n'
        '  rdfs:comment "A network fault event per TMF642 / ITU-T X.733." ;\n'
        '  :sidDomain "Resource" ;\n'
        '  :sidABE "Resource Trouble" ;\n'
        '  :tmfApiId "TMF642" .\n\n'
    )

    path = os.path.join(output_dir, "tmf-sid-hierarchy.ttl")
    with open(path, "w") as f:
        f.write("".join(lines))
    print(f"  ✓ SID OWL hierarchy     → {path}")
    total = sum(len(c) for c in SID_DOMAINS.values()) + len(nf_types) + len(alarm_types) + 1
    print(f"    SID classes: {total}  |  Domains: {len(SID_DOMAINS)}  |  Open APIs mapped: {len(TMF_API_MAP)}")


def _tmf_href(api_id: str, resource_id: str, base_url: str = "https://gtc.example.com") -> str:
    """Build a TMF-compliant href following /{apiRoot}/{resource}/{id} pattern."""
    info = TMF_API_MAP.get(api_id, {})
    url_pattern = info.get("url_pattern", f"/tmf-api/{api_id.lower()}/v4/{api_id.lower()}")
    # Strip trailing slash from url_pattern, append /resource_id
    return f"{base_url}{url_pattern.rstrip('/')}/{resource_id}"


def generate_tmf_jsonld(output_dir: str):
    """Generate TMF-aligned JSON-LD context and sample payloads."""
    os.makedirs(output_dir, exist_ok=True)

    # TMF JSON-LD context — adds TMF namespace on top of the generic context
    # Includes TMF630 meta-attributes: @baseType, @schemaLocation, @referredType, href
    context = {
        "@context": {
            "@vocab": BASE_IRI,
            "tmf": TMF_NS,
            "etom": ETOM_NS,
            "xsd": XSD_NS,
            "prov": PROV,
            "skos": SKOS_NS,
            # PROV-O shorthands
            "generatedBy": {"@id": "prov:wasGeneratedBy", "@type": "@id"},
            "generatedAt": {"@id": "prov:generatedAtTime", "@type": "xsd:dateTime"},
            "associatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
            # TMF630 meta-attributes (required on all TmfEntity instances)
            "href": {"@id": f"{BASE_IRI}href", "@type": "xsd:anyURI"},
            "@baseType": {"@id": f"{BASE_IRI}baseType", "@type": "xsd:string"},
            "@schemaLocation": {"@id": f"{BASE_IRI}schemaLocation", "@type": "xsd:anyURI"},
            "@referredType": {"@id": f"{BASE_IRI}referredType", "@type": "xsd:string"},
            # TMF SID class shorthands
            "Resource": {"@id": f"{BASE_IRI}Resource"},
            "NetworkFunction": {"@id": f"{BASE_IRI}NetworkFunction"},
            "NetworkSlice": {"@id": f"{BASE_IRI}NetworkSlice"},
            "Service": {"@id": f"{BASE_IRI}Service"},
            "CustomerFacingService": {"@id": f"{BASE_IRI}CustomerFacingService"},
            "ResourceFacingService": {"@id": f"{BASE_IRI}ResourceFacingService"},
            "Product": {"@id": f"{BASE_IRI}Product"},
            "Party": {"@id": f"{BASE_IRI}Party"},
            "Alarm": {"@id": f"{BASE_IRI}Alarm"},
            "PerformanceIndicator": {"@id": f"{BASE_IRI}PerformanceIndicator"},
            "Agreement": {"@id": f"{BASE_IRI}Agreement"},
            # TMF SID property shorthands
            "operationalState": {"@id": f"{BASE_IRI}hasOperationalState", "@type": "xsd:string"},
            "adminState": {"@id": f"{BASE_IRI}hasAdminState", "@type": "xsd:string"},
            "nfType": {"@id": f"{BASE_IRI}hasNfType", "@type": "xsd:string"},
            "perceivedSeverity": {"@id": f"{BASE_IRI}hasPerceivedSeverity", "@type": "xsd:string"},
            "alarmState": {"@id": f"{BASE_IRI}hasAlarmState", "@type": "xsd:string"},
            "probableCause": {"@id": f"{BASE_IRI}hasProbableCause", "@type": "xsd:string"},
            "specificProblem": {"@id": f"{BASE_IRI}hasSpecificProblem", "@type": "xsd:string"},
            "serviceState": {"@id": f"{BASE_IRI}hasServiceState", "@type": "xsd:string"},
            "confidence": {"@id": f"{BASE_IRI}hasConfidenceScore", "@type": "xsd:decimal"},
            "derivedBy": {"@id": f"{BASE_IRI}derivationMethod", "@type": "xsd:string"},
            "sourceRef": {"@id": f"{BASE_IRI}sourceRef", "@type": "xsd:anyURI"},
            "kpiType": {"@id": f"{BASE_IRI}kpiType", "@type": "xsd:string"},
            "breachIndicator": {"@id": f"{BASE_IRI}breachIndicator", "@type": "xsd:boolean"},
            "thresholdHigh": {"@id": f"{BASE_IRI}thresholdHigh", "@type": "xsd:decimal"},
            "sidDomain": {"@id": f"{BASE_IRI}sidDomain", "@type": "xsd:string"},
            "tmfApiId": {"@id": f"{BASE_IRI}tmfApiId", "@type": "xsd:string"},
            # Phase 2B — additional SID class shorthands
            "TroubleTicket": {"@id": f"{BASE_IRI}TroubleTicket"},
            "NetworkSliceProfile": {"@id": f"{BASE_IRI}NetworkSliceProfile"},
            "ServiceQualityReport": {"@id": f"{BASE_IRI}ServiceQualityReport"},
            "GeographicSite": {"@id": f"{BASE_IRI}GeographicSite"},
            "CustomerBill": {"@id": f"{BASE_IRI}CustomerBill"},
            "ProductOfferingQualification": {"@id": f"{BASE_IRI}ProductOfferingQualification"},
            "EventSubscription": {"@id": f"{BASE_IRI}EventSubscription"},
            "ConflictEvent": {"@id": f"{BASE_IRI}ConflictEvent"},
            # Phase 2B property shorthands
            "ticketType": {"@id": f"{BASE_IRI}hasTicketType", "@type": "xsd:string"},
            "ticketStatus": {"@id": f"{BASE_IRI}hasTicketStatus", "@type": "xsd:string"},
            "sliceType": {"@id": f"{BASE_IRI}hasSliceType", "@type": "xsd:string"},
            "sst": {"@id": f"{BASE_IRI}hasSst", "@type": "xsd:integer"},
            "latencyTargetMs": {"@id": f"{BASE_IRI}latencyTargetMs", "@type": "xsd:decimal"},
            "slaCompliant": {"@id": f"{BASE_IRI}slaCompliant", "@type": "xsd:boolean"},
            "qualityScore": {"@id": f"{BASE_IRI}overallQualityScore", "@type": "xsd:decimal"},
            "billState": {"@id": f"{BASE_IRI}hasBillState", "@type": "xsd:string"},
            "amountDue": {"@id": f"{BASE_IRI}amountDue", "@type": "xsd:decimal"},
            "callbackUrl": {"@id": f"{BASE_IRI}callbackUrl", "@type": "xsd:anyURI"},
            "eventType": {"@id": f"{BASE_IRI}eventType", "@type": "xsd:string"},
            "conflictType": {"@id": f"{BASE_IRI}conflictType", "@type": "xsd:string"},
            "resolutionTier": {"@id": f"{BASE_IRI}resolutionTier", "@type": "xsd:integer"},
            # PROV-O wasInvalidatedBy (conflict resolution)
            "wasInvalidatedBy": {"@id": "prov:wasInvalidatedBy", "@type": "@id"},
            "invalidatedAt": {"@id": "prov:invalidatedAtTime", "@type": "xsd:dateTime"},
        }
    }
    ctx_path = os.path.join(output_dir, "tmf-context.json")
    with open(ctx_path, "w") as f:
        json.dump(context, f, indent=2)
    print(f"  ✓ TMF JSON-LD context   → {ctx_path}")

    tmf639_info = TMF_API_MAP["TMF639"]
    tmf642_info = TMF_API_MAP["TMF642"]

    # Sample TMF642 Alarm payload — includes TMF630 meta-attributes and href
    alarm_payload = {
        "@context": f"{BASE_IRI}jsonld/tmf-context.json",
        "@type": ["Alarm", "CommunicationsAlarm"],
        "@baseType": "Alarm",
        "@schemaLocation": tmf642_info["schema_location"],
        "@id": "https://gtc.example.com/alarms/ALM-20260410-001",
        "href": _tmf_href("TMF642", "ALM-20260410-001"),
        "alarmType": "CommunicationsAlarm",
        "perceivedSeverity": "Critical",
        "alarmState": "Cleared",
        "probableCause": "transmissionError",
        "specificProblem": "gNB 043 lost uplink connectivity to AMF — packet loss 18.7%",
        "sourceResource": {
            "@type": "NetworkFunction",
            "@referredType": "NetworkFunction",
            "@id": "https://gtc.example.com/resources/gnb-043",
            "href": _tmf_href("TMF639", "gnb-043"),
            "name": "gNB Site 043",
            "nfType": "gNB",
            "operationalState": "Disabled",
            "adminState": "Locked",
            "sidDomain": "Resource",
            "tmfApiId": "TMF639"
        },
        "generatedAt": "2026-04-10T02:14:00Z",
        "generatedBy": {
            "@type": "Party",
            "@referredType": "Party",
            "@id": "https://gtc.example.com/parties/ml-monitor-agent",
            "href": _tmf_href("TMF632", "ml-monitor-agent"),
            "name": "ML Monitor Agent"
        },
        "_tmf": {
            "apiId": "TMF642",
            "apiVersion": tmf642_info["version"],
            "sidDomain": "Resource",
            "sidABE": "Resource Trouble",
            "etomProcess": "1.4.4 Alarm Surveillance"
        },
        "_validation": {
            "shacl_gate": "tmf-shapes.ttl#AlarmShape",
            "status": "PASS"
        }
    }
    alarm_path = os.path.join(output_dir, "sample-tmf642-alarm-payload.json")
    with open(alarm_path, "w") as f:
        json.dump(alarm_payload, f, indent=2)
    print(f"  ✓ TMF642 alarm payload  → {alarm_path}")

    # Sample TMF639 Resource inventory payload — includes TMF630 meta-attributes and href
    resource_payload = {
        "@context": f"{BASE_IRI}jsonld/tmf-context.json",
        "@type": ["Resource", "NetworkFunction"],
        "@baseType": "Resource",
        "@schemaLocation": tmf639_info["schema_location"],
        "@id": "https://gtc.example.com/resources/amf-east-01",
        "href": _tmf_href("TMF639", "amf-east-01"),
        "name": "AMF East 01",
        "nfType": "AMF",
        "operationalState": "Enabled",
        "adminState": "Unlocked",
        "resourceSpecification": {
            "@type": "ResourceSpecification",
            "@referredType": "ResourceSpecification",
            "@id": "https://gtc.example.com/catalog/spec/amf-5g-v2",
            "href": _tmf_href("TMF634", "amf-5g-v2"),
            "name": "AMF 5G Specification",
            "version": "2.0"
        },
        "place": {
            "@type": "GeographicPlace",
            "@referredType": "GeographicPlace",
            "@id": "https://gtc.example.com/places/dc-east",
            "href": _tmf_href("TMF673", "dc-east"),
            "name": "Data Centre East"
        },
        "resourceRelationship": [
            {
                "relationshipType": "relies-on",
                "resource": {
                    "@referredType": "NetworkFunction",
                    "@id": "https://gtc.example.com/resources/nrf-east-01",
                    "href": _tmf_href("TMF639", "nrf-east-01"),
                }
            }
        ],
        "_tmf": {
            "apiId": "TMF639",
            "apiVersion": tmf639_info["version"],
            "sidDomain": "Resource",
            "sidABE": "Logical Resource"
        }
    }
    res_path = os.path.join(output_dir, "sample-tmf639-resource-payload.json")
    with open(res_path, "w") as f:
        json.dump(resource_payload, f, indent=2)
    print(f"  ✓ TMF639 resource payload → {res_path}")

    # MCP tool definitions with TMF semantic bindings
    # outputSchema includes TMF630 meta-attributes on all response objects
    tmf630_meta_properties = {
        "href":            {"type": "string", "format": "uri", "description": "TMF-compliant self href /{apiRoot}/{resource}/{id}"},
        "@baseType":       {"type": "string", "description": "TMF630: base type of this resource"},
        "@schemaLocation": {"type": "string", "format": "uri", "description": "TMF630: JSON schema URL for this resource"},
        "@referredType":   {"type": "string", "description": "TMF630: concrete type when used as a reference"},
    }
    tmf_tools = [
        {
            "name": "get_network_function_status",
            "description": "Returns the operational and administrative state of a 5G network function (TMF639).",
            "x-semantic-context": f"{BASE_IRI}jsonld/tmf-context.json",
            "x-tmf-api": "TMF639",
            "x-sid-class": f"{BASE_IRI}NetworkFunction",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "nf_iri": {"type": "string", "description": "IRI of the network function resource"},
                    "nf_type": {"type": "string", "enum": ["AMF","SMF","UPF","gNB","PCF","UDM","NRF"]}
                },
                "required": ["nf_iri"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    **tmf630_meta_properties,
                    "operationalState": {"type": "string"},
                    "adminState": {"type": "string"},
                    "nfType": {"type": "string"},
                },
                "required": ["href", "@baseType", "@schemaLocation", "operationalState", "adminState"]
            }
        },
        {
            "name": "raise_alarm",
            "description": "Records a network alarm with ITU-T X.733 attributes and PROV-O provenance (TMF642).",
            "x-semantic-context": f"{BASE_IRI}jsonld/tmf-context.json",
            "x-tmf-api": "TMF642",
            "x-sid-class": f"{BASE_IRI}Alarm",
            "x-shacl-gate": f"{BASE_IRI}shapes/tmf-shapes.ttl#AlarmShape",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alarm_type": {"type": "string", "enum": ["CommunicationsAlarm","EquipmentAlarm","QualityOfServiceAlarm","ProcessingErrorAlarm","EnvironmentalAlarm","SecurityViolation"]},
                    "perceived_severity": {"type": "string", "enum": ["Critical","Major","Minor","Warning","Indeterminate"]},
                    "probable_cause": {"type": "string"},
                    "specific_problem": {"type": "string"},
                    "source_resource_iri": {"type": "string"},
                    "raised_by_iri": {"type": "string"},
                    "raised_at": {"type": "string", "format": "date-time"}
                },
                "required": ["alarm_type","perceived_severity","source_resource_iri","raised_by_iri","raised_at"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    **tmf630_meta_properties,
                    "alarmState": {"type": "string"},
                    "perceivedSeverity": {"type": "string"},
                },
                "required": ["href", "@baseType", "@schemaLocation", "alarmState"]
            }
        },
        {
            "name": "record_kpi",
            "description": "Records a KPI measurement or ML-derived metric with PROV-O provenance (SID ResourcePerformance / TMF688).",
            "x-semantic-context": f"{BASE_IRI}jsonld/tmf-context.json",
            "x-tmf-api": "TMF688",
            "x-sid-class": f"{BASE_IRI}PerformanceIndicator",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "resource_iri": {"type": "string"},
                    "kpi_type": {"type": "string", "enum": ["AVAILABILITY","LATENCY","PACKET_LOSS","THROUGHPUT","SIGNAL_STRENGTH","CAPACITY","ML_CONFIDENCE","PSI_SCORE","DRIFT_SCORE"]},
                    "numeric_value": {"type": "number"},
                    "unit_of_measure": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "derivation": {"type": "string", "enum": ["MEASURED","INFERRED","IMPORTED","SYNTHESIZED"]},
                    "source_ref": {"type": "string"},
                    "observed_at": {"type": "string", "format": "date-time"},
                    "recorded_by_iri": {"type": "string"}
                },
                "required": ["resource_iri","kpi_type","numeric_value","confidence","derivation","observed_at","recorded_by_iri"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    **tmf630_meta_properties,
                    "kpiType": {"type": "string"},
                    "numericValue": {"type": "number"},
                    "breachIndicator": {"type": "boolean"},
                },
                "required": ["href", "@baseType", "@schemaLocation", "kpiType"]
            }
        },
    ]
    tools_path = os.path.join(output_dir, "tmf-mcp-tools.json")
    with open(tools_path, "w") as f:
        json.dump({"mcp_tools": tmf_tools}, f, indent=2)
    print(f"  ✓ TMF MCP tools         → {tools_path}")


def generate_tmf_api_coverage(intro, output_dir: str):
    """Generate CSV showing which TMF Open APIs are covered by the schema tables."""
    os.makedirs(output_dir, exist_ok=True)
    rows = []
    try:
        meta = intro.conn.execute(
            "SELECT DISTINCT tmf_api_id, tmf_api_version, tmf_entity_name, sid_domain, sid_abe, table_name "
            "FROM ontology_metadata WHERE tmf_api_id IS NOT NULL ORDER BY tmf_api_id"
        ).fetchall()
    except Exception:
        meta = []

    covered = {r[0] for r in meta}
    for api_id, info in TMF_API_MAP.items():
        row = {
            "tmf_api_id": api_id,
            "api_name": info["name"],
            "version": info["version"],
            "sid_class": info["sid_class"],
            "sid_domain": info["sid_domain"],
            "url_pattern": info["url_pattern"],
            "covered_in_schema": "YES" if api_id in covered else "NO",
            "schema_table": "",
            "entity_name": "",
        }
        for r in meta:
            if r[0] == api_id:
                row["schema_table"] = r[5]
                row["entity_name"] = r[2] or ""
                break
        rows.append(row)

    coverage_pct = round(len(covered) / len(TMF_API_MAP) * 100)
    path = os.path.join(output_dir, "tmf_api_coverage.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  ✓ TMF API coverage      → {path}")
    print(f"    APIs mapped: {len(covered)}/{len(TMF_API_MAP)} ({coverage_pct}%)")


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 3 · Sprint S16–S18
#  TMF630 Parts 4 & 7 — Async Task resource + Bulk Import/Export operations
# ═══════════════════════════════════════════════════════════════════════════

# TMF630 Part 4 — Task resource schema (async long-running operations)
TMF630_TASK_SQL = """
CREATE TABLE IF NOT EXISTS tmf_task (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             TEXT NOT NULL UNIQUE,
    task_type           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'inProgress',
    creation_date       TEXT,
    completion_date     TEXT,
    percent_progress    INTEGER DEFAULT 0,
    task_resource_ref   TEXT,
    task_error          TEXT,
    related_entity_id   TEXT,
    related_entity_type TEXT,
    requested_by        TEXT,
    external_id         TEXT,
    href                TEXT,
    base_type           TEXT DEFAULT 'Task',
    schema_location     TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT
);

INSERT OR IGNORE INTO ontology_metadata
  (table_name, semantic_type, sensitivity_tier, label, description,
   sid_domain, sid_abe, tmf_api_id, tmf_api_version, tmf_entity_name)
VALUES
  ('tmf_task','Entity','Internal',
   'TMF Task',
   'TMF630 Part 4 — asynchronous long-running operation resource',
   'Common','TaskManagement','TMF630','5.0','Task');
"""

# TMF630 Part 7 — Bulk operations (ImportJob / ExportJob)
TMF630_BULK_SQL = """
CREATE TABLE IF NOT EXISTS tmf_import_job (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    import_job_id       TEXT NOT NULL UNIQUE,
    content_type        TEXT NOT NULL,
    source_uri          TEXT,
    creation_date       TEXT,
    completion_date     TEXT,
    status              TEXT DEFAULT 'running',
    error_log           TEXT,
    path                TEXT,
    url                 TEXT,
    href                TEXT,
    base_type           TEXT DEFAULT 'ImportJob',
    schema_location     TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tmf_export_job (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    export_job_id       TEXT NOT NULL UNIQUE,
    content_type        TEXT NOT NULL,
    query               TEXT,
    path                TEXT,
    url                 TEXT,
    creation_date       TEXT,
    completion_date     TEXT,
    status              TEXT DEFAULT 'running',
    error_log           TEXT,
    href                TEXT,
    base_type           TEXT DEFAULT 'ExportJob',
    schema_location     TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO ontology_metadata
  (table_name, semantic_type, sensitivity_tier, label, description,
   sid_domain, sid_abe, tmf_api_id, tmf_api_version, tmf_entity_name)
VALUES
  ('tmf_import_job','Entity','Internal',
   'TMF Import Job',
   'TMF630 Part 7 — bulk resource import operation',
   'Common','BulkOperations','TMF630','5.0','ImportJob'),
  ('tmf_export_job','Entity','Internal',
   'TMF Export Job',
   'TMF630 Part 7 — bulk resource export operation',
   'Common','BulkOperations','TMF630','5.0','ExportJob');
"""

# OWL classes for TMF630 Task + Bulk resources
TMF630_TASK_OWL = """\
# ── TMF630 Part 4 — Task Resource ─────────────────────────────────────────

:TmfTask
  a owl:Class ;
  rdfs:subClassOf :TmfEntity ;
  rdfs:label "TMF Task" ;
  rdfs:comment "TMF630 Part 4: asynchronous long-running operation. Enables async task management in ODA-compliant deployments." ;
  skos:prefLabel "Task" ;
  skos:altLabel "TMF Task Resource" ;
  :sensitivityTier :Internal .

:taskId          a owl:DatatypeProperty ; rdfs:domain :TmfTask ; rdfs:range xsd:string ; rdfs:label "Task ID" .
:taskType        a owl:DatatypeProperty ; rdfs:domain :TmfTask ; rdfs:range xsd:string ; rdfs:label "Task Type" .
:percentProgress a owl:DatatypeProperty ; rdfs:domain :TmfTask ; rdfs:range xsd:integer ; rdfs:label "Percent Progress" .
:taskError       a owl:DatatypeProperty ; rdfs:domain :TmfTask ; rdfs:range xsd:string ; rdfs:label "Task Error" .
:taskStatus      a owl:DatatypeProperty ; rdfs:domain :TmfTask ;
  rdfs:range xsd:string ;
  rdfs:label "Task Status" ;
  rdfs:comment "Values: inProgress | completed | failed | cancelled" .

# ── TMF630 Part 7 — Bulk Import / Export ───────────────────────────────────

:TmfImportJob
  a owl:Class ;
  rdfs:subClassOf :TmfEntity ;
  rdfs:label "TMF Import Job" ;
  rdfs:comment "TMF630 Part 7: asynchronous bulk import of resource instances." ;
  skos:prefLabel "ImportJob" ;
  :sensitivityTier :Internal .

:TmfExportJob
  a owl:Class ;
  rdfs:subClassOf :TmfEntity ;
  rdfs:label "TMF Export Job" ;
  rdfs:comment "TMF630 Part 7: asynchronous bulk export of resource instances." ;
  skos:prefLabel "ExportJob" ;
  :sensitivityTier :Internal .

:importJobId  a owl:DatatypeProperty ; rdfs:domain :TmfImportJob ; rdfs:range xsd:string ; rdfs:label "Import Job ID" .
:exportJobId  a owl:DatatypeProperty ; rdfs:domain :TmfExportJob ; rdfs:range xsd:string ; rdfs:label "Export Job ID" .
:contentType  a owl:DatatypeProperty ; rdfs:domain :TmfEntity    ; rdfs:range xsd:string ; rdfs:label "Content Type" .
:sourceUri    a owl:DatatypeProperty ; rdfs:domain :TmfImportJob ; rdfs:range xsd:anyURI ; rdfs:label "Source URI" .
:exportQuery  a owl:DatatypeProperty ; rdfs:domain :TmfExportJob ; rdfs:range xsd:string ; rdfs:label "Export Query" .
:bulkJobStatus a owl:DatatypeProperty ; rdfs:domain :TmfEntity ;
  rdfs:range xsd:string ;
  rdfs:label "Bulk Job Status" ;
  rdfs:comment "Values: running | succeeded | failed" .
"""

# SHACL shapes for TMF630 Task + Bulk
TMF630_TASK_SHACL = """\
# ── TMF630 Task SHACL Shape ────────────────────────────────────────────────

:TmfTaskShape
  a sh:NodeShape ;
  sh:targetClass :TmfTask ;
  rdfs:label "TMF Task Shape" ;

  sh:property [ sh:path :taskId       ; sh:minCount 1 ; sh:datatype xsd:string ; sh:severity sh:Violation ] ;
  sh:property [ sh:path :taskType     ; sh:minCount 1 ; sh:datatype xsd:string ; sh:severity sh:Violation ] ;
  sh:property [ sh:path :taskStatus   ; sh:minCount 1 ;
    sh:in ( "inProgress" "completed" "failed" "cancelled" ) ;
    sh:severity sh:Violation ] ;
  sh:property [ sh:path :percentProgress ; sh:datatype xsd:integer ;
    sh:minInclusive 0 ; sh:maxInclusive 100 ; sh:severity sh:Warning ] .

:TmfImportJobShape
  a sh:NodeShape ;
  sh:targetClass :TmfImportJob ;
  sh:property [ sh:path :importJobId  ; sh:minCount 1 ; sh:severity sh:Violation ] ;
  sh:property [ sh:path :contentType  ; sh:minCount 1 ; sh:severity sh:Violation ] ;
  sh:property [ sh:path :bulkJobStatus ; sh:in ( "running" "succeeded" "failed" ) ; sh:severity sh:Violation ] .

:TmfExportJobShape
  a sh:NodeShape ;
  sh:targetClass :TmfExportJob ;
  sh:property [ sh:path :exportJobId  ; sh:minCount 1 ; sh:severity sh:Violation ] ;
  sh:property [ sh:path :contentType  ; sh:minCount 1 ; sh:severity sh:Violation ] ;
  sh:property [ sh:path :bulkJobStatus ; sh:in ( "running" "succeeded" "failed" ) ; sh:severity sh:Violation ] .
"""

# MCP tools for TMF630 async operations
TMF630_TASK_MCP_TOOLS = [
    {
        "name": "create_task",
        "description": (
            "Create a TMF630 Part 4 async Task resource for a long-running operation. "
            "Returns the task_id and href for polling. "
            "Use poll_task_status to check completion."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "description": "Type of operation (e.g. 'resourceImport', 'ontologyValidation', 'schemaExport')."
                },
                "related_entity_id": {
                    "type": "string",
                    "description": "Optional ID of the resource this task operates on."
                },
                "related_entity_type": {
                    "type": "string",
                    "description": "Type of the related entity (e.g. 'TmfResource')."
                }
            },
            "required": ["task_type"]
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "href": {"type": "string"},
                "status": {"type": "string"},
                "@baseType": {"type": "string"},
                "@schemaLocation": {"type": "string"}
            }
        }
    },
    {
        "name": "poll_task_status",
        "description": "Poll the status of a TMF630 async Task by task_id. Returns current status and percent_progress.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id returned by create_task."}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "create_import_job",
        "description": (
            "TMF630 Part 7: Create a bulk ImportJob to ingest a batch of resource instances "
            "from a remote URI or uploaded file. Returns import_job_id for polling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content_type": {
                    "type": "string",
                    "enum": ["application/json", "text/csv", "application/ld+json", "text/turtle"],
                    "description": "MIME type of the import payload."
                },
                "source_uri": {
                    "type": "string",
                    "description": "URI of the remote file to import (https:// or file://)."
                }
            },
            "required": ["content_type"]
        }
    },
    {
        "name": "create_export_job",
        "description": (
            "TMF630 Part 7: Create a bulk ExportJob to export matching resource instances. "
            "Supports SPARQL/SQL filter query. Returns export_job_id and download URL when complete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content_type": {
                    "type": "string",
                    "enum": ["application/json", "text/csv", "application/ld+json", "text/turtle"],
                    "description": "Desired export format."
                },
                "query": {
                    "type": "string",
                    "description": "Optional SQL or SPARQL filter restricting exported records."
                }
            },
            "required": ["content_type"]
        }
    },
]

# TMF630 CQ tests for Task + Bulk resources
TMF630_TASK_CQS = [
    {
        "id": "CQ-TMF-14",
        "priority": "High",
        "question": "Which async tasks are currently in 'inProgress' state for more than 30 minutes?",
        "validates": "TmfTask lifecycle",
        "sql": "SELECT task_id, task_type, creation_date, percent_progress FROM tmf_task WHERE status='inProgress'",
        "expected_non_empty": False,
    },
    {
        "id": "CQ-TMF-15",
        "priority": "High",
        "question": "Which bulk ImportJobs failed in the last 24 hours?",
        "validates": "TmfImportJob lifecycle",
        "sql": "SELECT import_job_id, content_type, status, error_log, created_at FROM tmf_import_job WHERE status='failed'",
        "expected_non_empty": False,
    },
    {
        "id": "CQ-TMF-16",
        "priority": "Medium",
        "question": "What is the total number of completed ExportJobs per content_type this month?",
        "validates": "TmfExportJob aggregate",
        "sql": "SELECT content_type, COUNT(*) as total FROM tmf_export_job WHERE status='succeeded' GROUP BY content_type",
        "expected_non_empty": False,
    },
]


def provision_tmf630_task_tables(db_path: str):
    """Create tmf_task, tmf_import_job, tmf_export_job tables and seed ontology_metadata."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db_path)
    conn.executescript(TMF630_TASK_SQL)
    conn.executescript(TMF630_BULK_SQL)
    conn.commit()
    conn.close()
    print("  ✓ TMF630 Task + Bulk tables provisioned")


def generate_tmf630_task_owl(output_dir: str):
    """Append TMF630 Task/Bulk OWL classes to the SID hierarchy Turtle."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "tmf630-task-bulk.ttl")
    prefixes = """\
@prefix :     <https://ontology.example.com/enterprise/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .

"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(prefixes)
        f.write(TMF630_TASK_OWL)
        f.write("\n\n")
        f.write(TMF630_TASK_SHACL)
    print(f"  ✓ TMF630 Task/Bulk OWL  → {path}")


def generate_tmf630_mcp_tools(output_dir: str):
    """Write TMF630 async Task + Bulk MCP tool definitions."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "tmf630-task-mcp-tools.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mcp_tools": TMF630_TASK_MCP_TOOLS}, f, indent=2)
    print(f"  ✓ TMF630 Task MCP tools → {path}")


def run_tmf630_task_phase(db_path: str, out_path: str):
    """Run the full TMF630 Task + Bulk operations phase."""
    ont_dir  = os.path.join(out_path, "ontology")
    jsonld_dir = os.path.join(out_path, "jsonld")
    rpt_dir  = os.path.join(out_path, "reports")
    os.makedirs(rpt_dir, exist_ok=True)

    provision_tmf630_task_tables(db_path)
    generate_tmf630_task_owl(ont_dir)
    generate_tmf630_mcp_tools(jsonld_dir)

    # Run TMF630 Task CQ tests
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db_path)
    results = []
    passed = failed = 0
    for cq in TMF630_TASK_CQS:
        try:
            rows = conn.execute(cq["sql"]).fetchall()
            ok = (len(rows) > 0) == cq["expected_non_empty"]
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            status = "ERROR"
            rows = []
            failed += 1
        results.append({**cq, "status": status, "row_count": len(rows)})
        icon = "✓" if status == "PASS" else "✗"
        print(f"    {icon} {cq['id']} [{cq['priority']:8s}] {status}  — {cq['question'][:60]}")
    conn.close()

    print(f"  TMF630 Task CQs: {passed} passed, {failed} failed")

    import csv as _csv
    cq_path = os.path.join(rpt_dir, "tmf630_task_cq_results.csv")
    with open(cq_path, "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=["id","priority","status","question","validates","row_count"])
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in ["id","priority","status","question","validates","row_count"]})
    print(f"  ✓ TMF630 Task CQ results → {cq_path}")
