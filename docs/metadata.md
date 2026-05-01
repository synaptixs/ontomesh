# Metadata control + semantic loss

How the `ontology_metadata` table drives generation and how the toolkit reports semantic loss when ontology coverage is incomplete. For higher-level integration see [integrate.md](integrate.md).

---

## 3. Semantic metadata control table

The `ontology_metadata` table is the semantic control plane. It annotates your existing schema without modifying operational tables.

### Table-level annotation

```sql
INSERT INTO ontology_metadata (
    target_type, table_name, semantic_type, label, description,
    sensitivity_tier, is_event_class, skos_pref_label, skos_alt_labels, cq_coverage
) VALUES (
    'TABLE', 'patients', 'Patient',
    'Patient', 'A person receiving healthcare services.',
    'Confidential', 0,
    'Patient', 'Service User,Client',
    'CQ-001,CQ-002,CQ-003'
);
```

### Column-level annotation

```sql
INSERT INTO ontology_metadata (
    target_type, table_name, column_name,
    semantic_type, label, description, sensitivity_tier, cq_coverage
) VALUES (
    'COLUMN', 'patients', 'date_of_birth',
    'xsd:date', 'Date of Birth',
    'Patient date of birth.',
    'Restricted', 'CQ-001'
);
```

### Field reference

| Field | Required | Description | Example |
|---|---|---|---|
| `target_type` | Yes | TABLE or COLUMN | TABLE |
| `table_name` | Yes | Physical table name | patients |
| `column_name` | COLUMN only | Physical column name | date_of_birth |
| `semantic_type` | Recommended | OWL class name or xsd type | Patient, xsd:date |
| `label` | Recommended | Human-readable label (rdfs:label) | Patient |
| `description` | Recommended | One-sentence description (rdfs:comment) | A person receiving... |
| `sensitivity_tier` | Recommended | Public, Internal, Confidential, or Restricted | Confidential |
| `is_event_class` | No | 1 if this table models domain events | 1 |
| `skos_pref_label` | No | Preferred term for the SKOS vocabulary | Patient |
| `skos_alt_labels` | No | Comma-separated synonyms | Service User,Client |
| `cq_coverage` | No | Comma-separated CQ IDs this entity supports | CQ-001,CQ-003 |

### TMF-specific annotation columns

| Field | Description | Example |
|---|---|---|
| `sid_domain` | SID domain name | Resource, Service, EngagedParty |
| `sid_abe` | SID Aggregate Business Entity | Logical Resource, Party |
| `tmf_api_id` | Primary TMF Open API | TMF639, TMF632 |
| `tmf_api_version` | API version | v5.0 |
| `tmf_entity_name` | Canonical TMF entity name | LogicalResource, Party |
| `etom_process` | Primary eTOM Level-2 process | 1.1.1 Resource Provisioning |

---

## 4. Semantic loss detection

Phase 4 runs seven automated heuristics. Findings go to `semantic_loss_report.csv` and the `semantic_loss_log` table. Set `resolved = 1` on fixed findings — they will not re-appear on re-run.

| Rule | Severity | What it detects |
|---|---|---|
| STATUS_AS_EVENT | HIGH | A status column exists but no event table records transitions |
| IMPLICIT_ACTOR | CRITICAL | An event table has no FK to an agent or party table |
| OVERLOADED_TYPE | MEDIUM | A type discriminator column has no OWL subclass hint |
| MISSING_TIMESTAMP | HIGH | An event table has no timestamp column |
| FLOATING_VALUE | HIGH | An observation table stores a value with no confidence score |
| MISSING_SOURCE_REF | MEDIUM | An observation table has no source reference column |
| MISSING_METADATA | LOW | A table has no ontology_metadata entry |

STATUS_AS_EVENT is reclassified from HIGH to LOW for SID/TMF lifecycle tables where the eTOM state machine governs the status field by design.

---

