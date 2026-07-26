# Ontology model

What the toolkit actually emits, why each construct is there, and how to read it.

The short version: you get an **OWL 2 DL** ontology with real class expressions, a
**SHACL** shape set, a **PROV-O** provenance chain, and — if you run `--phase abox`
— **instance data** that the schema can describe.

---

## The five files

A generation run writes these into `output/ontology/`. They import each other, so
load them together.

| File | Contains | Load it when |
|---|---|---|
| `enterprise.ttl` | The TBox: classes, properties, restrictions, keys | Always |
| `events.ttl` | Event subclasses as **defined classes** | Always |
| `provenance.ttl` | PROV-O profile: Entity / Activity / Agent roles | You care about lineage |
| `dimensions.ttl` | Time, quantity and participation patterns | You query dates, measurements or roles |
| `instances.ttl` | The ABox: individuals materialised from your rows | You want data, not just a schema |

```bash
python toolkit.py --phase all --db db/enterprise.db --out output
```

---

## Classes

Every table becomes an `owl:Class` under `:DomainEntity`, or under `:DomainEvent`
when the table is flagged as an event class.

```turtle
:Asset
  a owl:Class ;
  rdfs:subClassOf :DomainEntity ;
  rdfs:label "Asset" ;
  rdfs:comment "A physical or logical resource managed by the organization." ;
  :sensitivityTier :Internal ;
  owl:hasKey ( :hasExternalId ) ;
  rdfs:subClassOf [ a owl:Restriction ;
                    owl:onProperty :hasName ;
                    owl:minCardinality "1"^^xsd:nonNegativeInteger ] .
```

Three things to notice:

- **`owl:hasKey`** is derived from `UNIQUE` constraints in your schema. It says
  *this value identifies the thing* — two records sharing an `external_id` are the
  same asset. Surrogate auto-increment `id` columns are deliberately skipped;
  they carry no domain meaning.
- **`NOT NULL` becomes an `owl:Restriction`**, not a bare `owl:minCardinality` on
  the property. A cardinality outside a restriction is not an axiom at all — OWL
  tools drop it or reject the file.
- **`:sensitivityTier`** annotates every class and data property, and is carried
  onto individuals too, so tier-gated retrieval can filter on the record rather
  than only on its type.

## Defined classes — where reasoning actually happens

Event subclasses are not bare labels. They are **defined** by the discriminator
value that produces them, so a reasoner can classify into them:

```turtle
:IncidentEvent
  a owl:Class ;
  rdfs:subClassOf :DomainEvent ;
  owl:equivalentClass [
    a owl:Class ;
    owl:intersectionOf (
      :DomainEvent
      [ a owl:Restriction ;
        owl:onProperty :hasEventType ;
        owl:hasValue "INCIDENT" ]
    )
  ] .
```

Which means this works:

```python
import rdflib, owlrl
g = rdflib.Graph()
for f in ("enterprise", "events"):
    g.parse(f"output/ontology/{f}.ttl", format="turtle")

NS = rdflib.Namespace("https://ontology.example.com/enterprise/")
g.add((NS.e1, rdflib.RDF.type, NS.DomainEvent))
g.add((NS.e1, NS.hasEventType, rdflib.Literal("INCIDENT")))

owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
# :e1 is now inferred to be an :IncidentEvent
```

## Properties

**Naming is mechanical and predictable**, which matters when you write queries:

| Source | Becomes | Example |
|---|---|---|
| A data column | `has` + CamelCase | `event_type` → `:hasEventType` |
| A foreign key | lowerCamel, trailing `_id` stripped | `asset_id` → `:asset` |
| An FK with a qualifier | the qualifier survives | `asset_type_id` → `:assetType` |

There is **one** naming function behind all of this, shared by the ontology, the
mapping workbook and the ABox, so the three cannot drift apart.

### Domains use a union, not a repeat

A property used on several classes gets **one** declaration with a union domain:

```turtle
:hasCreatedAt
  a owl:DatatypeProperty ;
  rdfs:domain [ a owl:Class ;
                owl:unionOf ( :Agent :Alarm :Asset … ) ] ;
  rdfs:range xsd:dateTime .
```

!!! warning "Why this matters"

    Multiple `rdfs:domain` axioms on one property **conjoin** in OWL — they mean
    the intersection, not the union. Declaring a property once per table gave
    `:hasCreatedAt` 43 separate domains, so loading a single record with a
    timestamp inferred it was all 43 classes at once. The union class is the
    correct idiom for "used on any of these".

### Semantic aliases

Some relations have a better name than the schema can derive. Those are declared
equivalent, so **either name is valid**:

```turtle
:refersToAsset     owl:equivalentProperty :asset .
:derivationMethod  owl:equivalentProperty :hasDerivationMethod .
```

Instance data carries the structural name; a reasoner treats them as one property.

---

## Provenance (`provenance.ttl` + ABox)

PROV-O requires an **Activity** between an Entity and its Agent. A foreign key
like `recorded_by` gives you the endpoints but not the middle, so the toolkit
reifies one activity per record:

```turtle
<…/ObservationRecord/1>
  a :ObservationRecord , prov:Entity ;
  prov:wasGeneratedBy <…/ObservationRecordDerivation/1> ;
  prov:wasAttributedTo <…/Agent/3> ;
  prov:generatedAtTime "2026-04-15T09:12:00"^^xsd:dateTime .

<…/ObservationRecordDerivation/1>
  a :DerivationActivity ;
  prov:wasAssociatedWith <…/Agent/3> ;
  prov:generated <…/ObservationRecord/1> .
```

So the standard PROV traversal works:

```sparql
SELECT ?obs ?agent WHERE {
  ?obs a :ObservationRecord ; prov:wasGeneratedBy ?activity .
  ?activity prov:wasAssociatedWith ?agent .
}
```

!!! note "Which classes get a chain"

    Any class declared `rdfs:subClassOf prov:Entity`. Align a new class to
    `prov:Entity` and its records get a provenance chain automatically — no code
    change. A chain is emitted **only** when the record names an agent; an
    activity with no responsible party would be invented provenance, not
    materialised provenance.

---

## Dimensions (`dimensions.ttl` + ABox)

Three things a relational schema flattens away.

### Time — valid vs transaction

Your database has both and does not distinguish them. The ontology does:

- **Valid time** — when the fact is true in the world. From `valid_from`,
  `effective_from`, `effective_until`.
- **Transaction time** — when the system recorded it. From `created_at`, or
  `prov:generatedAtTime` on provenance-bearing records.

```turtle
<…/Policy/4>
  :hasValidityPeriod <…/PolicyValidity/4> .

<…/PolicyValidity/4>
  a :TemporalExtent ;
  :validFrom "2024-01-01T00:00:00"^^xsd:dateTime ;
  time:hasBeginning [ a time:Instant ;
                      time:inXSDDateTime "2024-01-01T00:00:00"^^xsd:dateTime ] .
```

This is what makes an as-of question answerable: *"what did we believe was true
in March, as recorded before June?"*

!!! note "Nothing is invented"

    A record with no valid-time columns gets **no** validity period. Synthesising
    one from `created_at` would assert that a fact became true at the moment
    someone typed it in.

### Quantities — a number is not a measurement

`15` is meaningless without its unit. Where the source records a unit next to a
value, the two are reified together:

```turtle
<…/Observation/1>
  :hasQuantity <…/ObservationQuantity/1> .

<…/ObservationQuantity/1>
  a :QuantityValue ;
  :numericValue 18.7 ;
  :unitOfMeasure "percent" .
```

`:QuantityValue` is a subclass of `qudt:QuantityValue` and `:numericValue` a
subproperty of `qudt:numericValue`. Map `:unitOfMeasure` strings onto real
`qudt:Unit` IRIs once you know your unit vocabulary.

### Participation — who took part, and how

A junction table carrying event, agent *and role* is an n-ary relation. Flattened
to `:hasParticipant`, the role is lost. Reified, it survives:

```sparql
SELECT ?role ?agent WHERE {
  ?p a :Participation ;
     :participationIn ?event ;
     :participatingAgent ?agent ;
     :participationRole ?role .
}
# INITIATOR / OBSERVER / EXECUTOR …
```

---

## Instance data (`instances.ttl`)

```bash
# Default ceiling is Internal — conservative on purpose
python toolkit.py --phase abox --db db/enterprise.db --out output

# Raise it deliberately when you need Confidential columns materialised
python toolkit.py --phase abox --db db/enterprise.db --out output \
                  --max-tier Confidential
```

Individuals get hierarchical IRIs — `<…/enterprise/Asset/6>` — and carry their
class's sensitivity tier.

!!! danger "Tier gating is enforced on materialisation"

    An ABox is a **copy** of your data in a file that is far easier to move around
    than the database it came from. Columns above `--max-tier` are withheld.
    `Restricted` is excluded by default, and the run reports what it held back.

Materialisation is driven by `output/mapping/logical_physical_map.csv`, which maps
class → table and property → column. That workbook is generated for you, and it is
editable — that is the supported way to steer what gets materialised.

---

## Quality signals

Run `--phase quality` to write `output/reports/ontology_quality.csv`:

- **OOPS!-style pitfalls** — ten checks computed from the graph: unconnected
  elements, missing domain/range, conjunctive domains, recursive definitions,
  missing licence, and others.
- **Structural metrics** — depth, inheritance richness, attribute richness,
  restriction and defined-class counts. These tell you whether you have a real
  taxonomy or a flat list.
- **Consistency** — unsatisfiable classes, found with `owlrl` in-process. No
  external reasoner binary required.

See [Quality gates](../reference/quality-gates.md) for how these feed CI.

---

## Versioning and deprecation

Each module carries `owl:versionIRI`, `owl:versionInfo` and `dcterms:license`.
When a previous version exists, the new one adds `owl:priorVersion` and
`owl:backwardCompatibleWith`.

Entities that disappear are **not** silently deleted — they are retained as
tombstones so held IRIs still resolve:

```turtle
:RetiredWidget
  owl:deprecated true ;
  rdfs:comment "Deprecated: no longer produced by the source schema as of version 1.0.0." .
```

---

## Standards used

| Standard | Where it shows up |
|---|---|
| **OWL 2 DL** | Classes, restrictions, defined classes, `owl:hasKey`, union domains |
| **SHACL** | `shapes/enterprise-shapes.ttl`, `shapes/agent-gate.ttl` |
| **PROV-O** | `provenance.ttl` + reified chains in the ABox |
| **OWL-Time** | `time:Instant` / `time:Interval` in `dimensions.ttl` |
| **QUDT** | `:QuantityValue` alignment in `dimensions.ttl` |
| **SKOS** | `vocab/enterprise-skos.ttl` |
| **JSON-LD 1.1** | `jsonld/enterprise-context.json` |

!!! info "Profile"

    The emitted ontology is **OWL 2 DL**, driven by the union-class domains.
    `output/ontology/profile_recommendation.md` reports the detected profile and
    the constructs that determined it — computed by parsing the graph, so it
    reflects what was actually emitted rather than what was intended.
