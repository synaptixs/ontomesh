"""
src/vocabulary.py
─────────────────
Lift the asserted ontology into a small JSON-friendly catalog of
classes and properties, ready to drive UI affordances such as the
Phase C / F1 slot-fill rule builder, NL-rule prompts (#1), and the
rule-impact overlay (#7).

The parser is intentionally forgiving: any subject typed with one of
the recognised meta-classes (`owl:Class`, `owl:ObjectProperty`,
`owl:DatatypeProperty`, `rdf:Property`) is included. We collect
domain, range, and a parent-class chain so the front-end can scope
property pickers to the chosen target class.

The module exposes a tiny mtime-keyed cache so the endpoint stays
responsive on hosts with large ontologies — repeated calls reuse a
parsed graph as long as the source file's mtime hasn't moved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS


@dataclass
class ClassEntry:
    iri: str
    qname: str
    label: Optional[str]
    parents: List[str]

    def to_dict(self) -> dict:
        return {"iri": self.iri, "qname": self.qname,
                "label": self.label, "parents": self.parents}


@dataclass
class PropertyEntry:
    iri: str
    qname: str
    label: Optional[str]
    kind: str                  # "object" | "data" | "annotation" | "rdf"
    domain: List[str]
    range: List[str]

    def to_dict(self) -> dict:
        return {
            "iri": self.iri, "qname": self.qname, "label": self.label,
            "kind": self.kind, "domain": self.domain, "range": self.range,
        }


@dataclass
class Vocabulary:
    classes: List[ClassEntry] = field(default_factory=list)
    properties: List[PropertyEntry] = field(default_factory=list)
    base_iri: Optional[str] = None
    source: Optional[str] = None
    triple_count: int = 0

    def to_dict(self) -> dict:
        return {
            "base_iri": self.base_iri,
            "source": self.source,
            "triple_count": self.triple_count,
            "classes":    [c.to_dict() for c in self.classes],
            "properties": [p.to_dict() for p in self.properties],
        }


# ── Parser ───────────────────────────────────────────────────────────────


_PROP_KIND = {
    OWL.ObjectProperty:     "object",
    OWL.DatatypeProperty:   "data",
    OWL.AnnotationProperty: "annotation",
    RDF.Property:           "rdf",
}


def parse_vocabulary(ontology_path: str) -> Vocabulary:
    """Parse a Turtle ontology into a Vocabulary record."""
    if not os.path.isfile(ontology_path):
        return Vocabulary(source=ontology_path)
    g = Graph()
    g.parse(ontology_path, format="turtle")
    vocab = Vocabulary(source=ontology_path, triple_count=len(g))

    # Pick a default base IRI so qname rendering looks reasonable.
    for prefix, ns in g.namespaces():
        if prefix == "":
            vocab.base_iri = str(ns)
            break

    qname = lambda iri: _to_qname(iri, dict(g.namespaces()))

    # ── Classes ──
    class_iris = sorted({s for s, _, _ in g.triples((None, RDF.type, OWL.Class))
                         if isinstance(s, URIRef)},
                        key=str)
    for iri in class_iris:
        parents = [str(p) for _, _, p in g.triples((iri, RDFS.subClassOf, None))
                   if isinstance(p, URIRef)]
        vocab.classes.append(ClassEntry(
            iri=str(iri),
            qname=qname(iri),
            label=_first_label(g, iri),
            parents=parents,
        ))

    # ── Properties ──
    seen: set = set()
    for prop_type, kind in _PROP_KIND.items():
        for s, _, _ in g.triples((None, RDF.type, prop_type)):
            if not isinstance(s, URIRef) or s in seen:
                continue
            seen.add(s)
            domain = [str(d) for _, _, d in g.triples((s, RDFS.domain, None))
                      if isinstance(d, URIRef)]
            range_ = [str(r) for _, _, r in g.triples((s, RDFS.range, None))
                      if isinstance(r, URIRef)]
            vocab.properties.append(PropertyEntry(
                iri=str(s),
                qname=qname(s),
                label=_first_label(g, s),
                kind=kind,
                domain=domain,
                range=range_,
            ))
    vocab.properties.sort(key=lambda p: (p.kind, p.qname))
    return vocab


def _first_label(g: Graph, subject) -> Optional[str]:
    for _, _, lbl in g.triples((subject, RDFS.label, None)):
        return str(lbl)
    return None


def _to_qname(iri: URIRef, prefixes: Dict[str, URIRef]) -> str:
    """Render `iri` as `prefix:local` if a known namespace prefixes it,
    otherwise fall back to the local-name suffix.
    """
    s = str(iri)
    best_prefix = ""
    best_ns = ""
    for prefix, ns in prefixes.items():
        ns_s = str(ns)
        if s.startswith(ns_s) and len(ns_s) > len(best_ns):
            best_ns = ns_s
            best_prefix = prefix
    if best_ns:
        return f"{best_prefix}:{s[len(best_ns):]}"
    # Last-ditch: split on `#` then `/`.
    if "#" in s:
        return s.rsplit("#", 1)[1]
    return s.rsplit("/", 1)[-1]


# ── mtime cache ──────────────────────────────────────────────────────────


_cache: Dict[str, Tuple[float, Vocabulary]] = {}


def get_vocabulary(ontology_path: str) -> Vocabulary:
    """mtime-keyed cache around `parse_vocabulary`. Re-parses iff the
    file mtime has advanced since the last call.
    """
    abspath = os.path.abspath(ontology_path)
    if not os.path.isfile(abspath):
        return Vocabulary(source=abspath)
    mtime = os.path.getmtime(abspath)
    cached = _cache.get(abspath)
    if cached and cached[0] == mtime:
        return cached[1]
    vocab = parse_vocabulary(abspath)
    _cache[abspath] = (mtime, vocab)
    return vocab


def clear_cache() -> None:
    _cache.clear()


__all__ = [
    "ClassEntry",
    "PropertyEntry",
    "Vocabulary",
    "clear_cache",
    "get_vocabulary",
    "parse_vocabulary",
]
