"""
template_loader.py — Phase 3 · Sprint S14
──────────────────────────────────────────
Industry template loader and OWL/SHACL/SQL generator.

Reads a YAML industry template (from templates/) and generates:
  • SQLite schema (CREATE TABLE + INSERT INTO ontology_metadata)
  • OWL 2 class stubs (extends enterprise.ttl)
  • SHACL NodeShapes
  • CQ catalog (CSV)

Built-in templates:
  energy_utilities        telecom (existing)   healthcare (existing)
  logistics_supply_chain  government           finance (existing)
  insurance               pharmaceuticals

CLI:
  python3 toolkit.py --phase templates --template energy_utilities
  python3 toolkit.py --phase templates --template all
"""

from __future__ import annotations

import os
import csv
import yaml
from datetime import datetime, timezone
from typing import Any

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

BUILTIN_TEMPLATES = [
    "energy_utilities",
    "logistics_supply_chain",
    "government",
    "insurance",
    "pharmaceuticals",
]

BASE_IRI = "https://ontology.example.com/enterprise/"
NOW      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iter_properties(entity: dict) -> list[tuple[str, dict]]:
    """
    Return (prop_name, prop_def) pairs from an entity.
    Handles both dict format {name: def} and list format [{name: def}, ...].
    """
    props = entity.get("properties", {})
    if isinstance(props, dict):
        return list(props.items())
    if isinstance(props, list):
        pairs: list[tuple[str, dict]] = []
        for item in props:
            if isinstance(item, dict):
                for k, v in item.items():
                    pairs.append((k, v if isinstance(v, dict) else {}))
        return pairs
    return []


def list_templates() -> list[str]:
    names = []
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if fname.endswith(".yaml") or fname.endswith(".yml"):
            names.append(fname.rsplit(".", 1)[0])
    return names


def load_template(name: str) -> dict[str, Any]:
    for ext in (".yaml", ".yml"):
        path = os.path.join(TEMPLATES_DIR, name + ext)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(f"Template '{name}' not found in {TEMPLATES_DIR}")


def _py_type_to_sql(py_type: str) -> str:
    mapping = {
        "string": "TEXT",
        "integer": "INTEGER",
        "decimal": "REAL",
        "boolean": "INTEGER",
        "date": "TEXT",
        "datetime": "TEXT",
    }
    return mapping.get(py_type, "TEXT")


def _py_type_to_owl(py_type: str) -> str:
    mapping = {
        "string": "xsd:string",
        "integer": "xsd:integer",
        "decimal": "xsd:decimal",
        "boolean": "xsd:boolean",
        "date": "xsd:date",
        "datetime": "xsd:dateTime",
    }
    return mapping.get(py_type, "xsd:string")


def generate_sql_schema(tmpl: dict[str, Any]) -> str:
    lines: list[str] = []
    industry = tmpl.get("industry", "unknown")
    label    = tmpl.get("label", industry)
    lines.append(f"-- Industry template: {label}")
    lines.append(f"-- Generated {NOW} by Ontology Toolkit Phase 3\n")

    for entity in tmpl.get("entities", []):
        table_name = entity["name"].lower()
        cols: list[str] = [f"  id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for prop_name, prop_def in _iter_properties(entity):
            if isinstance(prop_def, dict):
                sql_type = _py_type_to_sql(prop_def.get("type", "string"))
                not_null = " NOT NULL" if prop_def.get("required") else ""
                cols.append(f"  {prop_name} {sql_type}{not_null}")
            else:
                cols.append(f"  {prop_name} TEXT")
        cols.append(f"  created_at TEXT DEFAULT (datetime('now'))")
        cols.append(f"  updated_at TEXT")
        lines.append(f"CREATE TABLE IF NOT EXISTS {table_name} (")
        lines.append(",\n".join(cols))
        lines.append(");\n")

        tier = entity.get("sensitivity", "Internal")
        desc = entity.get("description", "")[:200].replace("'", "''")
        ent_label = entity.get("label", entity["name"])
        lines.append(
            f"INSERT OR IGNORE INTO ontology_metadata "
            f"(table_name, class_name, semantic_type, sensitivity_tier, label, description) "
            f"VALUES ('{table_name}', '{entity['name']}', 'Entity', '{tier}', "
            f"'{ent_label}', '{desc}');\n"
        )

    return "\n".join(lines)


def _build_prefix_map(tmpl: dict[str, Any]) -> dict[str, str]:
    """Flatten a template's `external_alignments:` into {prefix: namespace}.

    The YAML carries this map (``[{idmp: https://…}, {fhir: http://…}]``)
    but nothing read it, so CURIEs like ``fhir:MedicinalProduct`` were
    written verbatim inside angle brackets.
    """
    prefix_map: dict[str, str] = {}
    for entry in tmpl.get("external_alignments") or []:
        if isinstance(entry, dict):
            for prefix, namespace in entry.items():
                if prefix and namespace:
                    prefix_map[str(prefix)] = str(namespace)
    return prefix_map


def _expand_curie(value: str, prefix_map: dict[str, str]) -> str | None:
    """Expand ``prefix:local`` to an absolute IRI, or None if impossible."""
    if not value:
        return None
    if value.startswith(("http://", "https://", "urn:")):
        return value
    prefix, sep, local = value.partition(":")
    if not sep or prefix not in prefix_map:
        return None
    return f"{prefix_map[prefix]}{local}"


def generate_owl_module(tmpl: dict[str, Any]) -> str:
    industry  = tmpl.get("industry", "unknown")
    label     = tmpl.get("label", industry)
    base_iri  = tmpl.get("base_iri", f"{BASE_IRI}{industry}/")
    prefix_map = _build_prefix_map(tmpl)
    unexpanded: list[str] = []
    module_props: dict[str, dict] = {}
    prefixes  = f"""\
@prefix :      <{BASE_IRI}> .
@prefix ind:   <{base_iri}> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
"""
    lines: list[str] = [prefixes, f"""
<{base_iri}>
  a owl:Ontology ;
  owl:versionIRI <{base_iri}1.0.0> ;
  owl:imports <{BASE_IRI}> ;
  rdfs:label "{label} Ontology Module" ;
  rdfs:comment "{tmpl.get('description','').strip()}" ;
  dcterms:created "{NOW}"^^xsd:dateTime ;
  dcterms:creator "Ontology Toolkit Phase 3 — auto-generated from template" .

"""]

    for entity in tmpl.get("entities", []):
        class_name  = entity["name"]
        parent      = entity.get("parent", "owl:Thing")
        ent_label   = entity.get("label", class_name)
        ent_desc    = entity.get("description", "").strip()
        tier        = entity.get("sensitivity", "Internal")
        equiv_items = []
        for k in ("cim_equivalent", "fhir_equivalent", "idmp_equivalent",
                  "dcat_equivalent", "schema_equivalent", "acord_equivalent",
                  "foaf_equivalent", "org_equivalent", "inspire_equivalent",
                  "gs1_equivalent"):
            v = entity.get(k)
            if v:
                equiv_items.append(v)

        # Module-local terms are minted in the module's own namespace via
        # `ind:`. The prefix was already declared but never used: every
        # class and property went into the shared enterprise namespace, so
        # `expiry_date` declared by insurance, logistics and pharmaceuticals
        # collided on one IRI that then carried three conjunctive domains.
        lines.append(f"ind:{class_name}")
        lines.append(f"  a owl:Class ;")
        if parent and parent != "owl:Thing":
            lines.append(f"  rdfs:subClassOf ind:{parent} ;")
        lines.append(f'  rdfs:label "{ent_label}" ;')
        if ent_desc:
            lines.append(f'  rdfs:comment "{ent_desc}" ;')
        for eq in equiv_items:
            expanded = _expand_curie(eq, prefix_map)
            if expanded is None:
                # An unexpandable CURIE would ship as <fhir:MedicinalProduct>
                # — an IRI with an unregistered scheme that dereferences to
                # nothing and misrepresents the ontology as standards-aligned.
                # Drop it and say so rather than emit it.
                unexpanded.append(eq)
                continue
            lines.append(f"  owl:equivalentClass <{expanded}> ;")
        lines.append(f"  :sensitivityTier :{tier} .")
        lines.append("")

        # Properties are collected across entities and emitted once, below.
        # Emitting per-entity re-declared a shared property name (a module's
        # `product_id` used on three entities) with one rdfs:domain each,
        # and multiple domains conjoin.
        for prop_name, prop_def in _iter_properties(entity):
            if not isinstance(prop_def, dict):
                continue
            cols = module_props.setdefault(prop_name, {
                "def": prop_def, "classes": [], "tiers": [],
            })
            cols["classes"].append(class_name)
            cols["tiers"].append(tier)

    _TIER_ORDER = ["Public", "Internal", "Confidential", "Restricted"]
    for prop_name, info in module_props.items():
        prop_def = info["def"]
        classes = sorted(set(info["classes"]))
        fk = prop_def.get("fk")
        xsd_type = _py_type_to_owl(prop_def.get("type", "string"))
        lines.append(f"ind:{prop_name}")
        lines.append("  a owl:ObjectProperty ;" if fk
                     else "  a owl:DatatypeProperty ;")
        if len(classes) == 1:
            lines.append(f"  rdfs:domain ind:{classes[0]} ;")
        else:
            members = " ".join(f"ind:{c}" for c in classes)
            lines.append("  rdfs:domain [ a owl:Class ;")
            lines.append(f"                owl:unionOf ( {members} ) ] ;")
        lines.append(f"  rdfs:range ind:{fk} ;" if fk
                     else f"  rdfs:range {xsd_type} ;")
        lines.append(f'  rdfs:label "{prop_name.replace("_", " ").title()}" ;')
        desc = prop_def.get("description", "")
        if desc:
            lines.append(f'  rdfs:comment "{desc}" ;')
        tier = "Public"
        for t in info["tiers"]:
            if t in _TIER_ORDER and _TIER_ORDER.index(t) > _TIER_ORDER.index(tier):
                tier = t
        lines.append(f"  :sensitivityTier :{tier} .")
        lines.append("")

    if unexpanded:
        lines.append(
            "# ── Dropped alignments ─────────────────────────────────────\n"
            "# These CURIEs had no matching prefix under the template's\n"
            "# `external_alignments:` map, so no absolute IRI could be\n"
            "# formed. Add the prefix to the template and re-run."
        )
        for curie in sorted(set(unexpanded)):
            lines.append(f"#   {curie}")
        lines.append("")

    return "\n".join(lines)


def generate_cq_catalog(tmpl: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for cq in tmpl.get("competency_questions", []):
        rows.append({
            "cq_id":      cq.get("id", ""),
            "priority":   cq.get("priority", "Medium"),
            "question":   cq.get("question", ""),
            "industry":   tmpl.get("industry", ""),
            "validates":  "",
        })
    return rows


def run_templates(out_path: str, template_name: str = "all") -> dict[str, list[str]]:
    """
    Generate SQL schema + OWL module + CQ catalog for one or all templates.
    Returns dict mapping template name → list of generated file paths.
    """
    if template_name == "all":
        names = list_templates()
        if not names:
            print("  ⚠  No templates found in templates/")
            return {}
    else:
        names = [template_name]

    results: dict[str, list[str]] = {}
    ont_dir = os.path.join(out_path, "ontology")
    rpt_dir = os.path.join(out_path, "reports")
    os.makedirs(ont_dir, exist_ok=True)
    os.makedirs(rpt_dir, exist_ok=True)

    for name in names:
        try:
            tmpl = load_template(name)
        except FileNotFoundError as e:
            print(f"  ⚠  {e}")
            continue

        label = tmpl.get("label", name)
        print(f"\n  Template: {label}")
        generated: list[str] = []

        owl_path = os.path.join(ont_dir, f"{name}.ttl")
        with open(owl_path, "w", encoding="utf-8") as f:
            f.write(generate_owl_module(tmpl))
        print(f"    ✓ OWL module → {owl_path}")
        generated.append(owl_path)

        cq_rows = generate_cq_catalog(tmpl)
        if cq_rows:
            cq_path = os.path.join(rpt_dir, f"cq_{name}.csv")
            with open(cq_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(cq_rows[0].keys()))
                w.writeheader()
                w.writerows(cq_rows)
            print(f"    ✓ CQ catalog  → {cq_path}")
            generated.append(cq_path)

        results[name] = generated

    total = sum(len(v) for v in results.values())
    print(f"\n  Generated {total} artifacts for {len(results)} templates.")
    return results
