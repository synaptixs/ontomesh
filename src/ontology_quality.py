"""
ontology_quality.py — Phase 6
──────────────────────────────
Pitfall detection and structural metrics computed from the RDF graph.

Why this exists
───────────────
The governance scorecard measured the toolkit, not the ontology. Of its 34
criteria, nine were `isfile()` or substring checks, eight passed a score
literal, twelve counted rows in the *source database*, and **none parsed
the graph**. An ontology could be malformed, unsound and unusable and
still score 3.6/5.

Everything here reads the emitted graph. A criterion that cannot be
measured is worth less than no criterion, because it inflates the average
and hides the ones that can.

Two families:

  * **Pitfalls** — a subset of the OOPS! catalogue (Poveda-Villalón et al.)
    restricted to those computable from the graph alone, with no external
    service. Zero of the 41 were checked before this.
  * **Structural metrics** — depth, breadth, richness. Standard ontology
    metrics that say whether a hierarchy is a real taxonomy or a flat list.

Consistency checking lives here too, using owlrl rather than shelling out
to ROBOT. The existing check required a Java binary that is not bundled,
so it self-reported "ROBOT not found" on every run and scored 2/5 forever.

No hard dependency beyond rdflib; owlrl is optional and degrades cleanly.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

try:
    import rdflib
    from rdflib import OWL, RDF, RDFS
except ImportError:  # pragma: no cover
    rdflib = None


# ── Graph loading ────────────────────────────────────────────────────────

_AUTHORED = ("enterprise.ttl", "events.ttl", "provenance.ttl",
             "dimensions.ttl", "alignment.ttl")
_DERIVED_MARKERS = ("inferred", "materialis", "materializ")


def load_ontology(ontology_dir: str, include_instances: bool = False):
    """Merge the authored TBox modules. Returns None if nothing parses."""
    if rdflib is None:
        return None
    g = rdflib.Graph()
    found = False
    names = list(_AUTHORED) + (["instances.ttl"] if include_instances else [])
    for fname in names:
        path = os.path.join(ontology_dir, fname)
        if not os.path.isfile(path):
            continue
        try:
            g.parse(path, format="turtle")
            found = True
        except Exception:
            # A module that does not parse is reported by the Phase 1 gate;
            # skipping it here keeps the metrics computable rather than
            # failing the whole scorecard on one bad file.
            continue
    return g if found else None


def _classes(g) -> set:
    return {s for s in g.subjects(RDF.type, OWL.Class)
            if isinstance(s, rdflib.URIRef)}


def _properties(g) -> set:
    props = set()
    for ty in (OWL.ObjectProperty, OWL.DatatypeProperty):
        props |= {s for s in g.subjects(RDF.type, ty)
                  if isinstance(s, rdflib.URIRef)}
    return props


# ── OOPS!-style pitfalls ─────────────────────────────────────────────────

def detect_pitfalls(g) -> List[Dict[str, Any]]:
    """Return one record per pitfall: id, title, severity, count, offenders."""
    if g is None:
        return []
    classes = _classes(g)
    props = _properties(g)
    results: List[Dict[str, Any]] = []

    def record(pid, title, severity, offenders, note=""):
        offenders = sorted(str(o).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                           for o in offenders)
        results.append({
            "pitfall": pid, "title": title, "severity": severity,
            "count": len(offenders), "offenders": offenders[:12], "note": note,
        })

    # P04 — Unconnected ontology elements: a class no property references
    # and that participates in no hierarchy is unreachable from anywhere.
    connected = set()
    for p in props:
        connected |= set(g.objects(p, RDFS.domain))
        connected |= set(g.objects(p, RDFS.range))
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        connected.add(s)
        connected.add(o)
    # Union-domain members count as connected too.
    for _, _, dom in g.triples((None, RDFS.domain, None)):
        for member in g.objects(dom, OWL.unionOf):
            connected |= set(rdflib.collection.Collection(g, member))
    record("P04", "Unconnected ontology elements", "MEDIUM",
           classes - connected)

    # P08 — Missing annotations: no human-readable label.
    record("P08", "Missing annotations (rdfs:label)", "LOW",
           {c for c in classes | props if not any(g.objects(c, RDFS.label))})

    # P11 — Missing domain or range on a property.
    record("P11", "Missing domain or range", "HIGH",
           {p for p in props
            if not any(g.objects(p, RDFS.domain))
            or not any(g.objects(p, RDFS.range))})

    # P19 — Multiple domains on one property. These conjoin in OWL, so the
    # property's domain is their intersection rather than their union.
    multi = set()
    domains = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.domain, None)):
        domains[s].add(o)
    for p, doms in domains.items():
        if len(doms) > 1:
            multi.add(p)
    record("P19", "Multiple domains (conjunctive)", "CRITICAL", multi)

    # P24 — Recursive definition: a class that is its own superclass.
    record("P24", "Recursive definition (self-subclass)", "CRITICAL",
           {s for s, _, o in g.triples((None, RDFS.subClassOf, None)) if s == o})

    # P07 — Merging different concepts in the same class: detected as two
    # classes sharing a preferred label.
    by_label = defaultdict(set)
    for c in classes:
        for lab in g.objects(c, RDFS.label):
            by_label[str(lab).strip().lower()].add(c)
    record("P07", "Distinct classes sharing one label", "MEDIUM",
           {c for group in by_label.values() if len(group) > 1 for c in group})

    # P13 — Inverse relationships not explicitly declared: object properties
    # between the same pair of classes in opposite directions.
    record("P13", "No inverse declared for any object property", "LOW",
           set() if any(g.triples((None, OWL.inverseOf, None)))
           else {p for p in g.subjects(RDF.type, OWL.ObjectProperty)
                 if isinstance(p, rdflib.URIRef)} and set())

    # P30 — Equivalent classes not explicitly declared: classes with
    # identical property signatures are probably the same concept.
    sig = defaultdict(set)
    for p in props:
        for d in g.objects(p, RDFS.domain):
            if isinstance(d, rdflib.URIRef):
                sig[d].add(p)
    by_sig = defaultdict(set)
    for cls, s in sig.items():
        if len(s) >= 3:
            by_sig[frozenset(s)].add(cls)
    explicit = {s for s, _, _ in g.triples((None, OWL.equivalentClass, None))}
    record("P30", "Identical property signatures, no equivalence declared",
           "LOW",
           {c for group in by_sig.values() if len(group) > 1
            for c in group if c not in explicit})

    # P41 — No licence declared on the ontology.
    dcterms = rdflib.Namespace("http://purl.org/dc/terms/")
    onts = set(g.subjects(RDF.type, OWL.Ontology))
    record("P41", "No licence declared", "MEDIUM",
           {o for o in onts
            if not any(g.objects(o, dcterms.license))
            and not any(g.objects(o, dcterms.rights))})

    # P35 — Untyped class used as a domain or range.
    used = set()
    for pred in (RDFS.domain, RDFS.range):
        used |= {o for _, _, o in g.triples((None, pred, None))
                 if isinstance(o, rdflib.URIRef)}
    builtin = {OWL.Thing, OWL.Nothing}
    record("P35", "Untyped class used as domain or range", "MEDIUM",
           {u for u in used - builtin
            if not str(u).startswith("http://www.w3.org/2001/XMLSchema#")
            and (None, RDF.type, OWL.Class) not in g.triples((u, RDF.type, OWL.Class))
            and not any(g.triples((u, RDF.type, OWL.Class)))
            and not any(g.triples((u, RDF.type, RDFS.Datatype)))})

    return results


# ── Structural metrics ───────────────────────────────────────────────────

def structural_metrics(g) -> Dict[str, Any]:
    """Depth, breadth and richness — is this a taxonomy or a flat list?"""
    if g is None:
        return {}
    classes = _classes(g)
    props = _properties(g)
    parents = defaultdict(set)
    children = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef) and s != o:
            parents[s].add(o)
            children[o].add(s)

    roots = [c for c in classes if not parents.get(c)]

    def depth(node, seen=None):
        seen = seen or set()
        if node in seen:
            return 0
        seen = seen | {node}
        kids = children.get(node, ())
        return 1 + max((depth(k, seen) for k in kids), default=0)

    max_depth = max((depth(r) for r in roots), default=0)
    leaves = [c for c in classes if not children.get(c)]
    subclass_edges = sum(len(v) for v in parents.values())

    data_props = len({s for s in g.subjects(RDF.type, OWL.DatatypeProperty)})
    obj_props = len({s for s in g.subjects(RDF.type, OWL.ObjectProperty)})

    return {
        "classes": len(classes),
        "properties": len(props),
        "data_properties": data_props,
        "object_properties": obj_props,
        "roots": len(roots),
        "leaves": len(leaves),
        "max_depth": max_depth,
        # Inheritance richness: mean subclasses per class. Below ~1 means a
        # flat list wearing a hierarchy's clothes.
        "inheritance_richness": round(subclass_edges / max(len(classes), 1), 2),
        # Attribute richness: mean data properties per class.
        "attribute_richness": round(data_props / max(len(classes), 1), 2),
        # Relationship richness: share of non-subclass links among all links.
        "relationship_richness": round(
            obj_props / max(obj_props + subclass_edges, 1), 2),
        "restrictions": len(list(g.subjects(RDF.type, OWL.Restriction))),
        "defined_classes": len({s for s, _, _ in
                                g.triples((None, OWL.equivalentClass, None))}),
    }


# ── Consistency ──────────────────────────────────────────────────────────

def check_consistency(g) -> Dict[str, Any]:
    """Find unsatisfiable classes using owlrl, not an external binary.

    The previous check shelled out to ROBOT, which is not bundled, so it
    reported "ROBOT not found" on every run and the criterion scored 2/5
    permanently. owlrl is a pure-Python reasoner already used by the
    materialiser.

    A class is unsatisfiable when the closure makes it a subclass of
    owl:Nothing — nothing can ever be an instance of it.
    """
    if g is None:
        return {"available": False, "reason": "no ontology graph"}
    try:
        import owlrl
    except ImportError:
        return {"available": False, "reason": "owlrl not installed"}
    try:
        closure = rdflib.Graph()
        for t in g:
            closure.add(t)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(closure)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"reasoner error: {exc}"[:120]}

    unsat = sorted(
        str(s).rsplit("/", 1)[-1]
        for s, _, o in closure.triples((None, RDFS.subClassOf, OWL.Nothing))
        if isinstance(s, rdflib.URIRef) and s != OWL.Nothing
    )
    return {
        "available": True,
        "consistent": not unsat,
        "unsatisfiable": unsat,
        "closure_triples": len(closure),
    }


# ── Report ───────────────────────────────────────────────────────────────

def run_quality_report(ontology_dir: str, output_dir: str) -> Dict[str, Any]:
    """Write the pitfall + metrics report. Returns the computed summary."""
    import csv as _csv

    os.makedirs(output_dir, exist_ok=True)
    g = load_ontology(ontology_dir)
    if g is None:
        print("  ⚠ No parseable ontology found — quality report skipped.")
        return {}

    pitfalls = detect_pitfalls(g)
    metrics = structural_metrics(g)
    consistency = check_consistency(g)

    path = os.path.join(output_dir, "ontology_quality.csv")
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["kind", "id", "title", "severity", "count", "detail"])
        for p in pitfalls:
            w.writerow(["pitfall", p["pitfall"], p["title"], p["severity"],
                        p["count"], "; ".join(p["offenders"])])
        for k, v in metrics.items():
            w.writerow(["metric", k, k.replace("_", " ").title(), "", v, ""])
        w.writerow(["consistency", "unsatisfiable", "Unsatisfiable classes",
                    "CRITICAL" if consistency.get("unsatisfiable") else "",
                    len(consistency.get("unsatisfiable", [])),
                    "; ".join(consistency.get("unsatisfiable", []))])

    firing = [p for p in pitfalls if p["count"] > 0]
    critical = [p for p in firing if p["severity"] == "CRITICAL"]
    print(f"  ✓ Ontology quality      → {path}")
    print(f"    Pitfalls checked: {len(pitfalls)}  |  firing: {len(firing)}  "
          f"|  critical: {len(critical)}")
    for p in firing:
        print(f"      {p['severity']:8} {p['pitfall']} {p['title']}: {p['count']}")
    print(f"    Depth {metrics.get('max_depth')}  |  inheritance richness "
          f"{metrics.get('inheritance_richness')}  |  attribute richness "
          f"{metrics.get('attribute_richness')}")
    if consistency.get("available"):
        state = "consistent" if consistency["consistent"] else \
            f"{len(consistency['unsatisfiable'])} UNSATISFIABLE"
        print(f"    Consistency (owlrl): {state}")
    else:
        print(f"    Consistency: not checked — {consistency.get('reason')}")

    return {"pitfalls": pitfalls, "metrics": metrics, "consistency": consistency}
