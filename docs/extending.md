# Extending the toolkit

Recipes for adding semantic loss rules, CQ tests, database backends, OWL/SHACL/JSON-LD customisations, and industry templates.

---

## 7. Extending the toolkit

### Add a semantic loss rule

Edit `_detect_semantic_loss()` in `src/mapping_generator.py`. Each rule appends a dict with `severity`, `table`, `column`, `loss_type`, `description`, and `remediation`.

### Add a competency question test

Add an entry to `COMPETENCY_QUESTIONS` in `src/cq_tester.py`:

```python
{
    "id": "CQ-010",
    "question": "Which patients have an active care plan?",
    "priority": "Critical",
    "sparql_equiv": "SELECT ?p WHERE { ?cp a :CarePlan ; :assignedTo ?p ; :status 'Active' }",
    "sql": "SELECT p.name FROM care_plans cp JOIN patients p ON cp.patient_id = p.id WHERE cp.status = 'Active'",
    "expected_non_empty": True,
    "validates": "CarePlan-Patient relationship, lifecycle status",
}
```

### Add a new database backend

Subclass `Connector` in `src/db_connector.py`. Implement `get_tables()`, `get_columns()`, `execute()`, `execute_script()`. Add a type normalisation function and register the scheme in `create_connector()`.

### Customise OWL generation

Edit `_class_block()` or `_data_property_block()` in `src/ontology_generator.py`.

### Add a SHACL constraint

Extend `_node_shape()` in `src/shacl_generator.py`.

### Extend the JSON-LD context

Add terms to `_build_context()` in `src/jsonld_generator.py`.

### Add an industry template

Add an entry to `INDUSTRY_TEMPLATES` in `onboard.py`:

```python
"energy": {
    "domain_name": "Energy Operations",
    "domain_description": "Grid asset management, meter reading, outage response, and customer billing.",
    "entities": ["Grid Asset", "Meter", "Customer", "Outage"],
    "events": ["Fault", "Restoration", "Maintenance", "Meter Read"],
    "relationships": [
        ("Outage", "affects", "Grid Asset"),
        ("Meter", "installed at", "Customer"),
    ],
    "cqs": [
        "Which grid assets are currently faulted?",
        "Which customers are affected by an active outage?",
    ],
}
```

---

