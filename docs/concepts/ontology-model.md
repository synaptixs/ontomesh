# Ontology model

!!! info "Stub — fills in over coming releases"

    A focused overview of the OWL/SHACL/PROV-O/SKOS surface Ontomesh produces.

## Quick map

| Construct | Role in Ontomesh |
|---|---|
| `owl:Class` | Every domain entity is an OWL class |
| `owl:ObjectProperty` | Relationships and events |
| `owl:DatatypeProperty` | Entity attributes |
| `sh:NodeShape` | Constraints (cardinality, type, regex, severity) |
| `prov:Activity` | Each phase run as a PROV activity |
| `prov:wasDerivedFrom` | Lineage between inferred and asserted triples |
| `skos:Concept` | Controlled vocabulary entries |
| `:sensitivityTier` (custom) | Per-class data-sensitivity declaration |

See [`output/ontology/<domain>.ttl`](https://github.com/synaptixs/ontomesh) for a real example after a wizard run.
