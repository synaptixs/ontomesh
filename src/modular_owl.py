"""
modular_owl.py — Phase 3 · Sprint S15–S17
──────────────────────────────────────────
Modular OWL support for multi-team ontology authoring.

Features:
  1. owl:imports graph — builds a directed import graph from all .ttl modules
  2. Acyclicity check  — detects and reports import cycles (would break reasoners)
  3. IRI conflict detection — identifies the same IRI defined in multiple modules
  4. Per-module versioning — reads owl:versionInfo from each module
  5. Module manifest — writes output/ontology/modules.json with the full inventory

Produces:
  output/ontology/modules.json       — module manifest (IRIs, versions, imports, conflicts)
  output/ontology/master.ttl         — master ontology that owl:imports all modules

CLI:
  python3 toolkit.py --phase modular [--out output]
"""

from __future__ import annotations

import os
import re
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Turtle IRI extraction (no rdflib dep) ──────────────────────────────────

_IRI_RE     = re.compile(r'<([^>]+)>')
_PREFIX_RE  = re.compile(r'@prefix\s+(\w*):\s*<([^>]+)>\s*\.')
_IMPORTS_RE = re.compile(r'owl:imports\s+<([^>]+)>', re.MULTILINE)
_OWL_ONT_RE = re.compile(r'<([^>]+)>\s+a\s+owl:Ontology', re.MULTILINE)
_VERSION_RE = re.compile(r'owl:versionInfo\s+"([^"]+)"')
_VERSIONIRI_RE = re.compile(r'owl:versionIRI\s+<([^>]+)>')
_CLASS_DEF_RE  = re.compile(r'^(\S+|<[^>]+>)\s+a\s+owl:Class', re.MULTILINE)
_PROP_DEF_RE   = re.compile(r'^(\S+|<[^>]+>)\s+a\s+owl:(Datatype|Object|Annotation)Property', re.MULTILINE)


def _expand_iri(raw: str, prefixes: dict[str, str]) -> str:
    """Expand a prefixed name like :Foo or foaf:Agent to full IRI."""
    if raw.startswith("<") and raw.endswith(">"):
        return raw[1:-1]
    if ":" in raw:
        prefix, local = raw.split(":", 1)
        base = prefixes.get(prefix)
        if base:
            return base + local
    return raw


def _parse_module(path: str) -> dict:
    """
    Extract metadata from a Turtle file without a full RDF parser.
    Returns: {iri, version, version_iri, imports, classes, properties, prefixes}
    """
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # Collect prefix declarations
    prefixes: dict[str, str] = {}
    for prefix, ns in _PREFIX_RE.findall(src):
        prefixes[prefix] = ns

    # Ontology IRI
    ont_iris = _OWL_ONT_RE.findall(src)
    ont_iri  = ont_iris[0] if ont_iris else ""

    # Version
    ver_match = _VERSION_RE.search(src)
    version   = ver_match.group(1) if ver_match else "unknown"

    # Version IRI
    viri_match = _VERSIONIRI_RE.search(src)
    version_iri = viri_match.group(1) if viri_match else ""

    # Imports
    imports = _IMPORTS_RE.findall(src)

    # Class definitions
    raw_classes = _CLASS_DEF_RE.findall(src)
    classes: list[str] = []
    for rc in raw_classes:
        expanded = _expand_iri(rc.strip(), prefixes)
        if expanded and not expanded.startswith("owl:") and not expanded.startswith("rdfs:"):
            classes.append(expanded)

    # Property definitions
    raw_props = [m[0] for m in _PROP_DEF_RE.findall(src)]
    properties: list[str] = []
    for rp in raw_props:
        expanded = _expand_iri(rp.strip(), prefixes)
        if expanded:
            properties.append(expanded)

    return {
        "path":        path,
        "filename":    os.path.basename(path),
        "iri":         ont_iri,
        "version":     version,
        "version_iri": version_iri,
        "imports":     imports,
        "classes":     classes,
        "properties":  properties,
        "prefixes":    prefixes,
    }


# ── Cycle detection (DFS on import graph) ─────────────────────────────────

def _detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """
    Detect cycles in a directed import graph.
    Returns list of cycles, where each cycle is a list of IRIs.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    parent: dict[str, Optional[str]] = {}
    cycles: list[list[str]] = []

    def dfs(node: str):
        color[node] = GRAY
        for neighbour in graph.get(node, []):
            if color[neighbour] == GRAY:
                cycle: list[str] = [neighbour]
                cur = node
                while cur != neighbour:
                    cycle.append(cur)
                    cur = parent.get(cur, "")
                    if not cur:
                        break
                cycle.append(neighbour)
                cycles.append(list(reversed(cycle)))
            elif color[neighbour] == WHITE:
                parent[neighbour] = node
                dfs(neighbour)
        color[node] = BLACK

    for node in list(graph.keys()):
        if color[node] == WHITE:
            dfs(node)
    return cycles


# ── IRI conflict detection ─────────────────────────────────────────────────

def _find_iri_conflicts(modules: list[dict]) -> dict[str, list[str]]:
    """
    Return a dict mapping IRI → list of module filenames where it is defined.
    Only entries with >1 module are conflicts.
    """
    iri_sources: dict[str, list[str]] = defaultdict(list)
    for mod in modules:
        fname = mod["filename"]
        for iri in mod["classes"] + mod["properties"]:
            iri_sources[iri].append(fname)
    return {iri: files for iri, files in iri_sources.items() if len(files) > 1}


# ── Master ontology writer ─────────────────────────────────────────────────

def _write_master_ttl(modules: list[dict], out_path: str) -> str:
    base_iri = "https://ontology.example.com/enterprise/"
    lines = [
        f"@prefix :    <{base_iri}> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "",
        f"<{base_iri}master>",
        "  a owl:Ontology ;",
        f'  owl:versionIRI <{base_iri}master/1.0.0> ;',
        '  owl:versionInfo "1.0.0" ;',
        '  rdfs:label "Enterprise Ontology — Master Module" ;',
        '  rdfs:comment "Auto-generated master ontology that owl:imports all modules." ;',
        f'  dcterms:created "{NOW}"^^xsd:dateTime ;',
        '  dcterms:creator "Ontology Toolkit Phase 3 — modular_owl.py" ;',
    ]
    for mod in modules:
        iri = mod.get("iri")
        if iri:
            lines.append(f"  owl:imports <{iri}> ;")
    # Replace trailing ; with .
    if lines[-1].endswith(";"):
        lines[-1] = lines[-1][:-1] + " ."
    lines.append("")

    master_path = os.path.join(out_path, "master.ttl")
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return master_path


# ── Main entry point ────────────────────────────────────────────────────────

def run_modular_owl(out_path: str) -> dict:
    """
    Scan all .ttl files in output/ontology/, build the import graph,
    detect cycles and IRI conflicts, write modules.json and master.ttl.
    """
    ont_dir = os.path.join(out_path, "ontology")
    if not os.path.isdir(ont_dir):
        print(f"  ⚠  {ont_dir} not found — run the pipeline first.")
        return {}

    ttl_files = sorted(
        f for f in os.listdir(ont_dir)
        if f.endswith(".ttl") and f != "master.ttl"
    )
    if not ttl_files:
        print("  ⚠  No Turtle modules found in output/ontology/")
        return {}

    print(f"  Scanning {len(ttl_files)} Turtle modules...")
    modules: list[dict] = []
    for fname in ttl_files:
        path = os.path.join(ont_dir, fname)
        mod  = _parse_module(path)
        modules.append(mod)
        ver = mod["version"]
        cls_count  = len(mod["classes"])
        prop_count = len(mod["properties"])
        print(f"    {fname:<45}  v{ver:<12}  {cls_count:>3} classes  {prop_count:>3} props")

    # Build import graph
    iri_to_mod: dict[str, dict] = {m["iri"]: m for m in modules if m["iri"]}
    import_graph: dict[str, list[str]] = {}
    for mod in modules:
        iri = mod["iri"]
        if iri:
            import_graph[iri] = mod["imports"]

    # Cycle detection
    cycles = _detect_cycles(import_graph)
    if cycles:
        print(f"\n  ✗ CYCLE DETECTED — {len(cycles)} import cycle(s):")
        for cycle in cycles:
            print(f"    → {' → '.join(cycle)}")
    else:
        print("  ✓ No import cycles detected.")

    # IRI conflicts
    conflicts = _find_iri_conflicts(modules)
    if conflicts:
        print(f"\n  ✗ IRI CONFLICTS — {len(conflicts)} IRI(s) defined in multiple modules:")
        for iri, files in list(conflicts.items())[:20]:
            print(f"    <{iri}>  in: {', '.join(files)}")
        if len(conflicts) > 20:
            print(f"    ... and {len(conflicts)-20} more")
    else:
        print("  ✓ No IRI conflicts detected.")

    # Write master.ttl
    master_path = _write_master_ttl(modules, ont_dir)
    print(f"  ✓ Master ontology → {master_path}")

    # Write manifest
    manifest = {
        "generated": NOW,
        "module_count": len(modules),
        "total_classes": sum(len(m["classes"]) for m in modules),
        "total_properties": sum(len(m["properties"]) for m in modules),
        "cycles_detected": len(cycles),
        "iri_conflicts": len(conflicts),
        "modules": [
            {
                "filename":    m["filename"],
                "iri":         m["iri"],
                "version":     m["version"],
                "version_iri": m["version_iri"],
                "imports":     m["imports"],
                "class_count": len(m["classes"]),
                "property_count": len(m["properties"]),
            }
            for m in modules
        ],
        "cycles": cycles,
        "conflicts": {iri: files for iri, files in list(conflicts.items())[:100]},
    }

    manifest_path = os.path.join(ont_dir, "modules.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"  ✓ Module manifest  → {manifest_path}")

    return manifest
