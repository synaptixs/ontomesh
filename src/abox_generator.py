"""
abox_generator.py — Phase 4
────────────────────────────
Materialises an ABox (instance data) from the relational database, driven
by the logical→physical mapping workbook.

Why this exists
───────────────
Every generated ontology was TBox-only. There was no path from rows to
individuals — no R2RML, no RML, no OBDA — so `materialised.ttl` contained
the closure of the schema and nothing else, and all 43 SPARQL competency
questions returned zero rows. That is what the `PASS-STRUCTURAL` verdict
existed to paper over: a query returning nothing was scored as a pass
because there was nothing for it to find.

The mapping workbook (`output/mapping/logical_physical_map.csv`) already
*is* a mapping — class→table, property→column, plus the FK target class
for object properties. It was written as documentation and never executed.
This module executes it.

Sensitivity
───────────
Columns are gated by the tier recorded in the mapping. `Restricted` is
excluded by default: an ABox is a materialised copy of the data, so a
column nobody may read must not be silently duplicated into a Turtle file
that is easier to exfiltrate than the database it came from.

No external dependencies.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from db_introspector import BASE_IRI, snake_to_camel, value_to_local_name
from ontology_generator import object_property_name

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

TIER_ORDER = ["Public", "Internal", "Confidential", "Restricted"]

PREFIXES = f"""\
@prefix :     <{BASE_IRI}> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
"""

# Columns worth promoting to rdfs:label, in preference order. Competency
# questions ask for a human-readable name far more often than for a key.
_LABEL_COLUMNS = ("name", "label", "title", "code", "display_name",
                  "agent_iri", "external_id")


class MappingRow:
    __slots__ = ("cls", "prop", "kind", "table", "column", "target", "xsd", "tier", "required")

    def __init__(self, r: Dict[str, str]):
        self.cls = (r.get("ontology_class") or "").strip()
        self.prop = (r.get("ontology_property") or "").strip()
        self.kind = (r.get("property_type") or "").strip()
        self.table = (r.get("physical_table") or "").strip()
        self.column = (r.get("physical_column") or "").strip()
        # The workbook reuses one column for two things: the XSD datatype of
        # a data property, and "→ Class" for an object property's range.
        raw_type = (r.get("xsd_type") or "").strip()
        if raw_type.startswith("→"):
            self.target = raw_type.lstrip("→").strip()
            self.xsd = ""
        else:
            self.target = ""
            self.xsd = raw_type
        self.tier = (r.get("sensitivity_tier") or "Internal").strip()
        self.required = (r.get("required") or "").strip().upper() == "Y"


def _load_mapping(mapping_path: str) -> List[MappingRow]:
    if not os.path.isfile(mapping_path):
        return []
    with open(mapping_path, newline="") as f:
        return [MappingRow(r) for r in csv.DictReader(f)]


def _tier_allowed(tier: str, max_tier: str) -> bool:
    try:
        return TIER_ORDER.index(tier) <= TIER_ORDER.index(max_tier)
    except ValueError:
        # Unknown tier ranks most restrictive — fail closed.
        return False


def _escape(value: str) -> str:
    return (str(value)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", " ")
            .replace("\r", " "))


def _individual_iri(class_name: str, pk: object) -> str:
    """Mint a stable IRI for a row: <…/enterprise/ClassName/pk>.

    Written as a full IRI in angle brackets rather than a prefixed name.
    `/` is not legal in a Turtle PN_LOCAL, so `:Agent/1` makes the whole
    file unparseable — the same class of defect Phase 1 removed. The
    hierarchical form is also the conventional shape for an individual.

    The key is transliterated the way data values are, so one containing a
    space or punctuation cannot produce a broken IRI.
    """
    frag = value_to_local_name(str(pk)) or "unknown"
    return f"<{BASE_IRI}{class_name}/{frag}>"


def _literal(value: object, xsd_type: str) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    t = (xsd_type or "").strip()
    if t in ("xsd:integer", "xsd:int", "xsd:long"):
        try:
            return str(int(float(text)))
        except (TypeError, ValueError):
            return f'"{_escape(text)}"'
    if t in ("xsd:decimal", "xsd:double", "xsd:float"):
        try:
            return str(float(text))
        except (TypeError, ValueError):
            return f'"{_escape(text)}"'
    if t == "xsd:boolean":
        return "true" if text.lower() in ("1", "true", "yes", "y", "t") else "false"
    if t in ("xsd:dateTime", "xsd:date", "xsd:time", "xsd:duration",
             "xsd:anyURI", "xsd:base64Binary"):
        return f'"{_escape(text)}"^^{t}'
    return f'"{_escape(text)}"'


# Columns that record when a provenance-bearing record came into being,
# in preference order.
_GENERATED_AT_COLUMNS = ("observed_at", "recorded_at", "generated_at",
                         "asserted_at", "created_at")


def _prov_entity_classes(ontology_dir: str) -> set:
    """Classes the TBox aligns to prov:Entity.

    Read from the ontology rather than hardcoded, so declaring a new class
    `rdfs:subClassOf prov:Entity` is enough to make its records carry a
    provenance chain — no change here.
    """
    try:
        import rdflib
    except ImportError:
        return set()
    PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
    g = rdflib.Graph()
    found = False
    for fname in ("enterprise.ttl", "provenance.ttl"):
        path = os.path.join(ontology_dir, fname)
        if os.path.isfile(path):
            try:
                g.parse(path, format="turtle")
                found = True
            except Exception:
                pass
    if not found:
        return set()
    return {str(s).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            for s in g.subjects(rdflib.RDFS.subClassOf, PROV.Entity)}


def _prov_chain(class_name: str, key: object, row: Dict[str, object],
                allowed: List["MappingRow"],
                class_table: Dict[str, str]) -> Tuple[str, List[str]]:
    """Reify a record's provenance as a PROV-O chain.

    A flat foreign key ("this observation was recorded by agent 3") is not
    provenance a PROV-O consumer can traverse: `prov:wasGeneratedBy` links
    an Entity to an *Activity*, and the Agent hangs off the Activity via
    `prov:wasAssociatedWith`. The source carries the endpoints but not the
    Activity in between, so it is minted here — one per record, with a
    derived IRI so the chain is stable across runs.

    Returns (turtle block for the activity, extra statements for the
    record). Both are empty when the record names no agent, because
    inventing an activity with no responsible party would be fabricated
    provenance rather than materialised provenance.
    """
    agent_prop = next(
        (p for p in allowed
         if p.kind == "Object Property" and p.target
         and p.target in class_table
         and ("agent" in p.column.lower() or "recorded_by" in p.column.lower()
              or "initiated_by" in p.column.lower())),
        None,
    )
    if agent_prop is None:
        return "", []
    agent_value = row.get(agent_prop.column)
    if agent_value is None or str(agent_value).strip() == "":
        return "", []

    subject = _individual_iri(class_name, key)
    activity = _individual_iri(f"{class_name}Derivation", key)
    agent_iri = _individual_iri(agent_prop.target, agent_value)

    generated_at = None
    for col in _GENERATED_AT_COLUMNS:
        if row.get(col):
            generated_at = str(row[col])
            break

    record_statements = [
        "  a prov:Entity",
        f"  prov:wasGeneratedBy {activity}",
        f"  prov:wasAttributedTo {agent_iri}",
    ]
    if generated_at:
        record_statements.append(
            f'  prov:generatedAtTime "{_escape(generated_at)}"^^xsd:dateTime')

    activity_statements = [
        "  a :DerivationActivity",
        f"  prov:wasAssociatedWith {agent_iri}",
        f"  prov:generated {subject}",
    ]
    if generated_at:
        activity_statements.append(
            f'  prov:startedAtTime "{_escape(generated_at)}"^^xsd:dateTime')
    block = activity + "\n" + " ;\n".join(activity_statements) + " .\n"
    return block, record_statements


def _pk_column(connector, table: str) -> Optional[str]:
    """Primary-key column name, via the connector's row-dict interface."""
    try:
        info = connector.execute(f"PRAGMA table_info({table})")
    except Exception:
        return None
    for row in info:
        if isinstance(row, dict) and row.get("pk"):
            return row.get("name")
    return None


def generate_abox(intro, output_dir: str, mapping_path: str = "",
                  max_tier: str = "Confidential",
                  row_limit: int = 0) -> Dict[str, int]:
    """Materialise instances into `<output_dir>/ontology/instances.ttl`.

    Args:
        intro:        a DBIntrospector (its connection is read directly).
        output_dir:   run output root.
        mapping_path: mapping workbook; defaults to the run's own.
        max_tier:     highest sensitivity tier to materialise.
        row_limit:    per-table cap; 0 means no cap.
    """
    ont_dir = os.path.join(output_dir, "ontology")
    os.makedirs(ont_dir, exist_ok=True)
    mapping_path = mapping_path or os.path.join(
        output_dir, "mapping", "logical_physical_map.csv")

    rows = _load_mapping(mapping_path)
    if not rows:
        print(f"  ⚠ No mapping workbook at {mapping_path} — ABox skipped.")
        return {"individuals": 0, "triples": 0, "classes": 0}

    # The connector's execute() returns rows as dicts across every backend,
    # so the ABox is not tied to a raw sqlite3 cursor.
    connector = getattr(intro, "_connector", None)
    if connector is None or not hasattr(connector, "execute"):
        print("  ⚠ No usable database connection — ABox skipped.")
        return {"individuals": 0, "triples": 0, "classes": 0}

    # class → table, and the property rows belonging to each class.
    class_table: Dict[str, str] = {}
    class_tiers: Dict[str, str] = {}
    by_class: Dict[str, List[MappingRow]] = {}
    for r in rows:
        if r.kind == "OWL Class":
            class_table[r.cls] = r.table
            class_tiers[r.cls] = r.tier
        elif r.kind in ("Data Property", "Object Property"):
            by_class.setdefault(r.cls, []).append(r)

    lines: List[str] = [
        PREFIXES,
        f"\n<{BASE_IRI}instances/>\n"
        f"  a owl:Ontology ;\n"
        f"  owl:imports <{BASE_IRI}> ;\n"
        f'  rdfs:label "Enterprise ABox" ;\n'
        f'  rdfs:comment "Instance data materialised from the relational '
        f'source via the logical-physical mapping. Tier ceiling: {max_tier}." ;\n'
        f'  dcterms:created "{NOW}"^^xsd:dateTime .\n\n',
    ]

    prov_entity_classes = _prov_entity_classes(ont_dir)
    n_prov_activities = 0
    n_individuals = 0
    n_triples = 0
    n_classes = 0
    skipped_tiers: Dict[str, int] = {}

    for class_name, table in sorted(class_table.items()):
        props = by_class.get(class_name, [])
        if not props:
            continue
        pk = _pk_column(connector, table)
        if not pk:
            continue
        class_tier = class_tiers.get(class_name, "")

        wanted = [p for p in props if p.column and p.column != "(table)"]
        allowed = []
        for p in wanted:
            if _tier_allowed(p.tier, max_tier):
                allowed.append(p)
            else:
                skipped_tiers[p.tier] = skipped_tiers.get(p.tier, 0) + 1
        if not allowed:
            continue

        cols = [pk] + [p.column for p in allowed if p.column != pk]
        select = ", ".join(dict.fromkeys(cols))
        sql = f"SELECT {select} FROM {table}"
        if row_limit:
            sql += f" LIMIT {int(row_limit)}"
        try:
            data = connector.execute(sql)
        except Exception:
            continue
        if not data:
            continue

        n_classes += 1
        lines.append(f"# ── {class_name} ({len(data)} individuals) "
                     f"{'─' * max(0, 46 - len(class_name))}\n")

        for row in data:
            key = row.get(pk)
            if key is None:
                continue
            subject = _individual_iri(class_name, key)
            statements: List[str] = [f"  a :{class_name}"]
            # Individuals carry their class's sensitivity tier. The shapes
            # require :sensitivityTier on every node; validating them
            # against instances for the first time showed 243 of 370
            # violations were this one property. It is also independently
            # useful — tier-gated retrieval needs the tier on the record,
            # not only on the class.
            if class_tier:
                statements.append(f"  :sensitivityTier :{class_tier}")

            label = None
            for candidate in _LABEL_COLUMNS:
                if row.get(candidate):
                    label = str(row[candidate])
                    break
            if label:
                statements.append(f'  rdfs:label "{_escape(label)}"')

            # PROV-O chain for provenance-bearing records.
            prov_block = ""
            if class_name in prov_entity_classes:
                prov_block, prov_stmts = _prov_chain(
                    class_name, key, row, allowed, class_table)
                statements.extend(prov_stmts)

            for p in allowed:
                value = row.get(p.column)
                if value is None or str(value).strip() == "":
                    continue
                # Property IRIs are derived with the *ontology generator's*
                # own naming functions, not taken from the workbook's
                # `ontology_property` column.
                #
                # Those two disagree. For domain_events.asset_id the
                # workbook says `asset` while the TBox declares `assetOf`,
                # so an ABox built from the workbook would assert triples
                # against properties the ontology does not define — an
                # instance graph that its own schema cannot describe.
                # Deriving from the same function guarantees they agree.
                if p.kind == "Object Property":
                    if not p.target or p.target not in class_table:
                        continue
                    prop_iri = object_property_name(p.column)
                    statements.append(
                        f"  :{prop_iri} {_individual_iri(p.target, value)}")
                else:
                    lit = _literal(value, p.xsd)
                    if lit is None:
                        continue
                    prop_iri = f"has{snake_to_camel(p.column)}"
                    statements.append(f"  :{prop_iri} {lit}")

            n_individuals += 1
            n_triples += len(statements)
            lines.append(subject + "\n" + " ;\n".join(statements) + " .\n")
            if prov_block:
                n_prov_activities += 1
                lines.append(prov_block)
            lines.append("\n")

    path = os.path.join(ont_dir, "instances.ttl")
    with open(path, "w") as f:
        f.write("".join(lines))

    print(f"  ✓ ABox instances       → {path}")
    print(f"    {n_individuals} individuals across {n_classes} classes, "
          f"{n_triples} assertions  (tier ceiling: {max_tier})")
    if n_prov_activities:
        print(f"    PROV-O chains: {n_prov_activities} activities reified "
              f"(Entity -> Activity -> Agent)")
    if skipped_tiers:
        detail = ", ".join(f"{n} {tier}" for tier, n in sorted(skipped_tiers.items()))
        print(f"    Withheld above the tier ceiling: {detail}")

    return {"individuals": n_individuals, "triples": n_triples,
            "classes": n_classes, "prov_activities": n_prov_activities}


def run_abox(db_path: str, output_dir: str, max_tier: str = "Confidential",
             row_limit: int = 0) -> Dict[str, int]:
    """Phase entry point."""
    from db_introspector import DBIntrospector
    intro = DBIntrospector(db_path)
    return generate_abox(intro, output_dir, max_tier=max_tier, row_limit=row_limit)
