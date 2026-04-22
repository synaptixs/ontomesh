# Cross-Enterprise Ontology Interoperability Protocol — W3C CG Report

**Status:** Community Group Draft Report
**Editor:** Ontology Toolkit Working Group
**Date:** 2026-04-22
**This version:** https://ontology.example.com/federation/specs/1.0/
**Previous version:** —
**Reference implementation:** `federation/` module of the Ontology Toolkit v2.0

---

## Abstract

This document specifies a minimal, deployable protocol for two or more
enterprises to exchange ontology-mediated data while preserving sovereignty
over their own semantic schemas. It defines:

1. a *capability manifest* format that declares the ontology, exposed
   classes, sensitivity tiers, and required inbound SHACL shapes;
2. a bilateral *trust-bootstrap handshake* that establishes a
   cryptographically signed federation agreement;
3. *federation query patterns* that extend SPARQL 1.1 federated query
   semantics with sensitivity-tier enforcement;
4. *conformance criteria* for each of the above.

The protocol deliberately assumes no central authority — a pure Ed25519
keypair exchange between the two parties is the only trust primitive.

## 1. Status of this document

This draft is published as a W3C Community Group Report to solicit
implementation feedback. It is not a Recommendation of the W3C Membership.

## 2. Terminology

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, MAY are to be interpreted
as described in [RFC 2119] and [RFC 8174].

* **Enterprise** — the party hosting and governing its own ontology.
* **Partner** — an Enterprise that another Enterprise has federated with.
* **Capability Manifest** — the signed JSON-LD document published at the
  partner's well-known URI.
* **Federated Query** — a SPARQL 1.1 query that names one or more partner
  endpoints via `SERVICE <iri>` and is dispatched through the boundary gate.
* **Boundary** — the software layer that validates every triple returned
  from a partner endpoint.

## 3. Capability manifest (normative)

### 3.1 Media type and discovery

A Capability Manifest MUST be served as `application/ld+json` at a
`.well-known` URI derived from the Enterprise's root domain. The
recommended location is:

```
https://<enterprise-root>/.well-known/ontology-capability.jsonld
```

### 3.2 JSON-LD schema

Every manifest MUST contain exactly these properties (additional terms MAY
be present under implementation-specific prefixes):

| Property              | Cardinality | Type         | Meaning |
|-----------------------|-------------|--------------|---------|
| `@context`            | 1           | JSON-LD map  | Must include `fed: https://ontology.example.com/federation/` |
| `@id`                 | 1           | IRI          | Enterprise IRI (signer) |
| `@type`               | 1           | IRI          | MUST be `fed:CapabilityManifest` |
| `fed:manifestVersion` | 1           | xsd:string   | Semver of the manifest grammar |
| `fed:ontologyIri`     | 1           | IRI          | The ontology being exposed |
| `fed:exposedClasses`  | ≥1          | IRI[]        | Whitelist of OWL classes |
| `fed:exposedProperties` | 0..1      | IRI[]        | Whitelist of OWL properties |
| `fed:sensitivityByClass` | 0..1     | map          | class IRI → `"Public"\|"Internal"\|"Confidential"` |
| `fed:inboundShapes`   | 0..1        | IRI[]        | SHACL shape IRIs inbound queries must match |
| `fed:signerIri`       | 1           | IRI          | Identity the manifest is signed under |
| `fed:publicKey`       | 1           | xsd:string   | Ed25519 public key (URL-safe base-64, unpadded) |
| `fed:signatureAlgorithm` | 1        | xsd:string   | MUST be `"Ed25519"` |
| `fed:validFrom`       | 1           | xsd:dateTime | Manifest validity start |
| `fed:validUntil`      | 1           | xsd:dateTime | Manifest validity end (≤ 365 days from `validFrom`) |
| `fed:signature`       | 1           | xsd:string   | Ed25519 signature (URL-safe base-64, unpadded) |
| `fed:payloadSha256`   | 1           | xsd:string   | SHA-256 hex digest of the signed payload |

Sensitivity tiers MUST NOT include `"Restricted"` — that tier is
non-federable by definition.

### 3.3 Canonical signing bytes

The signed payload is the JSON serialisation of the manifest with the
`fed:signature` and `fed:payloadSha256` keys omitted, sorted
alphabetically, with compact separators (`(",", ":")`), encoded as UTF-8.
Conforming implementations MUST produce identical bytes across platforms.

## 4. Trust-bootstrap handshake (normative)

The following state machine governs every bilateral relationship. Each
transition MUST be appended to an immutable ledger (`fed:TrustLedger`).

```
          ┌────────── revoke ───────────┐
          ▼                              │
  PROPOSED ─ handshake ▶ HANDSHAKE_SENT ─ countersign ▶ COUNTERSIGNED
                                                         │
                                             test query  ▼
                                                        ACTIVE
                                                         │
                                             valid_until ▼
                                                        EXPIRED
```

### 4.1 Messages

* **MANIFEST_SENT** — Enterprise A signs its manifest and POSTs it to
  Enterprise B at the B-hosted handshake endpoint.
* **MANIFEST_RECEIVED** — B verifies A's manifest. If verification fails,
  the transition terminates and B MUST reply with a TMF630 Error resource
  carrying `code: fed.manifestInvalid`.
* **COUNTERSIGNED** — B attaches its own signed manifest and returns
  the bundle to A. The bundle constitutes the bilateral agreement.
* **ACTIVATED** — both parties run a probe query on a `Public`-tier
  class to verify live connectivity. On success both sides transition
  to `ACTIVE`.
* **REVOKED** — either party MAY unilaterally revoke at any time.

### 4.2 Expiry

Agreements MUST carry `valid_until`. Implementations MUST refuse queries
against a partner whose `trust_state ≠ ACTIVE`.

## 5. Federation query patterns (informative)

### 5.1 Minimal probe

```sparql
PREFIX fed: <https://ontology.example.com/federation/>
SELECT ?s WHERE {
  SERVICE <https://partner.example.com/sparql> {
    ?s a <https://ontology.example.com/tmf/NetworkFunction> ;
       fed:sensitivityTier "Public" .
  }
} LIMIT 1
```

### 5.2 Cross-domain KPI join

```sparql
PREFIX fed:  <https://ontology.example.com/federation/>
PREFIX tmf:  <https://ontology.example.com/tmf/>
SELECT ?remoteResource ?latency
WHERE {
  ?localService tmf:servesRemoteResource ?remoteResource .
  SERVICE <https://partner.example.com/sparql> {
    ?remoteResource tmf:performance/tmf:latencyMs ?latency ;
                    fed:sensitivityTier ?t .
    FILTER (?t IN ("Public", "Internal"))
  }
}
```

## 6. Sensitivity enforcement (normative SHACL profile)

Every triple returned from a partner MUST pass the SHACL node-shape
`fed:FederatedResultShape` (see Appendix A). The shape enforces:

1. `prov:wasAttributedTo` pointing at the partner IRI is present.
2. `fed:sensitivityTier` is one of the four enumerated values.
3. If `fed:sensitivityTier = "Restricted"`, the result MUST be rejected.
4. The result subject's `owl_class` is in the partner's
   `fed:exposedClasses` list.

Violations MUST be logged to the enterprise's semantic loss log with
`loss_type = FEDERATION_BOUNDARY_VIOLATION` and SHOULD be escalated to
the governance queue for review.

## 7. Conformance

A conforming implementation:

1. MUST publish a manifest matching §3.
2. MUST support the four handshake transitions of §4.
3. MUST enforce the SHACL shape of §6 on every inbound federated row.
4. MUST implement RFC 8032 Ed25519 signing/verification with
   byte-for-byte reproducible canonicalisation.
5. MUST maintain a tamper-evident trust ledger.
6. MUST reject queries naming an unregistered, expired, or revoked
   partner.

## 8. Security considerations

* Secret keys MUST be stored with filesystem permissions no wider than
  `0600` on POSIX-class systems.
* Manifest validity SHOULD NOT exceed 12 months.
* The handshake endpoint SHOULD be served over HTTPS with TLS 1.3.
* Partners SHOULD rotate signing keys at least annually.

## 9. References

* [RFC 2119] Bradner, *Key words for use in RFCs*, 1997.
* [RFC 8032] Josefsson & Liusvaara, *Edwards-Curve Digital Signature
  Algorithm (EdDSA)*, 2017.
* [RFC 8174] Leiba, *Ambiguity of Uppercase vs Lowercase in RFC 2119*.
* [SPARQL 1.1 Federated Query] W3C Recommendation, 2013.
* [SHACL] W3C Recommendation, 2017.
* [PROV-O] W3C Recommendation, 2013.

## Appendix A — normative SHACL profile

See `output/shapes/federation-shapes.ttl` in the reference implementation.
The normative IRI of the profile is
`https://ontology.example.com/federation/shapes/1.0`.

---

*Reference implementation © Ontology Toolkit contributors. Licensed
under the same terms as the toolkit repository.*
