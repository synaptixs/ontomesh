"""
src/ontology_diff.py — T2.4
───────────────────────────
Semantic ontology diff + change-impact analysis.

Two ontology versions go in; one report comes out with three
sections:

  - **Structural diff.** Axioms added, removed, or renamed —
    computed via rdflib graph subtraction on the asserted
    triples only.
  - **Semantic diff.** Closure entailments gained or lost —
    computed by running the T2.1 reasoner over both versions
    and diffing the *derived* (not asserted) ``rdfs:subClassOf``
    and ``owl:equivalentClass`` triples.
  - **Change-impact analysis.** For every changed class or
    property, scan downstream artefacts (SPARQL queries, SHACL
    shapes, generated Cypher / GraphQL files, the wizard
    session) for references to the IRI so the reviewer can
    estimate blast radius before merging.

The "semantic" half is the interesting one: a reviewer reading a
plain ``git diff`` sees text moved, not *what the meaning
changed to*. Removing a single ``owl:disjointWith`` axiom can
silently invalidate dozens of downstream entailments — only the
T2.1 reasoner reveals which.

Public API
──────────
    report = diff_ontologies(old_path, new_path)
    html   = render_diff_html(report)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


# ── Result dataclasses ───────────────────────────────────────────────────


@dataclass
class StructuralDiff:
    added_classes:    List[str] = field(default_factory=list)
    removed_classes:  List[str] = field(default_factory=list)
    added_properties: List[str] = field(default_factory=list)
    removed_properties: List[str] = field(default_factory=list)
    added_axioms:     List[Tuple[str, str, str]] = field(default_factory=list)
    removed_axioms:   List[Tuple[str, str, str]] = field(default_factory=list)
    renamed_classes:  List[Tuple[str, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.added_classes, self.removed_classes,
            self.added_properties, self.removed_properties,
            self.added_axioms, self.removed_axioms,
            self.renamed_classes,
        ])


@dataclass
class SemanticDiff:
    gained_subclass:    List[Tuple[str, str]] = field(default_factory=list)
    lost_subclass:      List[Tuple[str, str]] = field(default_factory=list)
    gained_equivalent:  List[Tuple[str, str]] = field(default_factory=list)
    lost_equivalent:    List[Tuple[str, str]] = field(default_factory=list)
    new_unsatisfiable:  List[str] = field(default_factory=list)
    resolved_unsatisfiable: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.gained_subclass, self.lost_subclass,
            self.gained_equivalent, self.lost_equivalent,
            self.new_unsatisfiable, self.resolved_unsatisfiable,
        ])


@dataclass
class AffectedFile:
    path:        str
    references:  List[str] = field(default_factory=list)
    kind:        str = "unknown"        # "sparql" / "shacl" / "cypher" / "graphql" / "session"


@dataclass
class ImpactReport:
    affected_files: List[AffectedFile] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.affected_files


@dataclass
class OntologyDiffReport:
    structural: StructuralDiff
    semantic:   SemanticDiff
    impact:     ImpactReport
    old_path:   str = ""
    new_path:   str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "structural": {
                "added_classes":    self.structural.added_classes,
                "removed_classes":  self.structural.removed_classes,
                "added_properties": self.structural.added_properties,
                "removed_properties": self.structural.removed_properties,
                "added_axioms":     [list(t) for t in self.structural.added_axioms],
                "removed_axioms":   [list(t) for t in self.structural.removed_axioms],
                "renamed_classes":  [list(t) for t in self.structural.renamed_classes],
            },
            "semantic": {
                "gained_subclass":    [list(t) for t in self.semantic.gained_subclass],
                "lost_subclass":      [list(t) for t in self.semantic.lost_subclass],
                "gained_equivalent":  [list(t) for t in self.semantic.gained_equivalent],
                "lost_equivalent":    [list(t) for t in self.semantic.lost_equivalent],
                "new_unsatisfiable":  self.semantic.new_unsatisfiable,
                "resolved_unsatisfiable": self.semantic.resolved_unsatisfiable,
            },
            "impact": {
                "affected_files": [
                    {"path": f.path, "references": f.references, "kind": f.kind}
                    for f in self.impact.affected_files
                ],
            },
            "old_path": self.old_path,
            "new_path": self.new_path,
        }


# ── Structural diff ──────────────────────────────────────────────────────


def _load_graph(path: str):
    """rdflib.Graph from a Turtle / OWL file. Raises if rdflib missing
    or the file can't be parsed — neither case has a sensible default."""
    import rdflib
    g = rdflib.Graph()
    fmt = _guess_format(path)
    g.parse(path, format=fmt)
    return g


def _guess_format(path: str) -> str:
    low = (path or "").lower()
    if low.endswith((".ttl", ".turtle")):
        return "turtle"
    if low.endswith((".owl", ".rdf")):
        return "xml"
    if low.endswith(".nt"):
        return "nt"
    if low.endswith(".jsonld"):
        return "json-ld"
    return "turtle"


def _asserted_classes(graph) -> Set[str]:
    import rdflib
    OWL = rdflib.namespace.OWL
    RDF = rdflib.namespace.RDF
    return {str(s) for s in graph.subjects(RDF.type, OWL.Class)
            if isinstance(s, rdflib.URIRef)}


def _asserted_properties(graph) -> Set[str]:
    import rdflib
    OWL = rdflib.namespace.OWL
    RDF = rdflib.namespace.RDF
    props: Set[str] = set()
    for pt in (OWL.ObjectProperty, OWL.DatatypeProperty,
               OWL.AnnotationProperty, RDF.Property):
        for s in graph.subjects(RDF.type, pt):
            if isinstance(s, rdflib.URIRef):
                props.add(str(s))
    return props


def structural_diff(old_path: str, new_path: str) -> StructuralDiff:
    old = _load_graph(old_path)
    new = _load_graph(new_path)

    old_classes = _asserted_classes(old)
    new_classes = _asserted_classes(new)
    old_props   = _asserted_properties(old)
    new_props   = _asserted_properties(new)

    # Triple-level diff for axioms beyond simple membership.
    old_triples = {(str(s), str(p), str(o)) for s, p, o in old}
    new_triples = {(str(s), str(p), str(o)) for s, p, o in new}

    return StructuralDiff(
        added_classes=sorted(new_classes - old_classes),
        removed_classes=sorted(old_classes - new_classes),
        added_properties=sorted(new_props - old_props),
        removed_properties=sorted(old_props - new_props),
        added_axioms=sorted(new_triples - old_triples),
        removed_axioms=sorted(old_triples - new_triples),
        renamed_classes=_detect_renames(old_classes, new_classes,
                                         old, new),
    )


def _detect_renames(old_classes: Set[str], new_classes: Set[str],
                    old_graph, new_graph) -> List[Tuple[str, str]]:
    """Conservative rename detection. Two classes 'A' and 'B' are
    considered a rename when:
    - A is in old_classes and not in new_classes.
    - B is in new_classes and not in old_classes.
    - The rdfs:label or rdfs:subClassOf signature of A in the old
      graph equals B's in the new graph.

    False negatives (missed renames) are cheap — we just show them
    as add+remove. False positives (claiming a rename that isn't)
    would mislead the reviewer; we keep the bar high."""
    import rdflib
    RDFS = rdflib.namespace.RDFS
    candidates: List[Tuple[str, str]] = []

    def _signature(g, iri: str) -> Tuple[str, ...]:
        uri = rdflib.URIRef(iri)
        labels = sorted(str(o) for o in g.objects(uri, RDFS.label))
        supers = sorted(str(o) for o in g.objects(uri, RDFS.subClassOf)
                        if isinstance(o, rdflib.URIRef))
        return (",".join(labels), ",".join(supers))

    only_old = old_classes - new_classes
    only_new = new_classes - old_classes
    if not only_old or not only_new:
        return []
    old_sigs = {iri: _signature(old_graph, iri) for iri in only_old}
    new_sigs = {iri: _signature(new_graph, iri) for iri in only_new}
    used_new: Set[str] = set()
    for old_iri, sig in old_sigs.items():
        if sig == ("", ""):
            continue
        for new_iri, new_sig in new_sigs.items():
            if new_iri in used_new:
                continue
            if sig == new_sig:
                candidates.append((old_iri, new_iri))
                used_new.add(new_iri)
                break
    return sorted(candidates)


# ── Semantic diff ───────────────────────────────────────────────────────


def semantic_diff(old_path: str, new_path: str,
                  *, reasoner: Optional[str] = None) -> SemanticDiff:
    """Run the T2.1 reasoner over both versions; diff the *derived*
    (not asserted) hierarchy."""
    from reasoners import get_reasoner
    r = get_reasoner(reasoner)

    old_res = r.classify(old_path)
    new_res = r.classify(new_path)

    old_sub = set(old_res.derived_subclass)
    new_sub = set(new_res.derived_subclass)
    old_eq  = set(old_res.derived_equivalent)
    new_eq  = set(new_res.derived_equivalent)

    old_inc = r.check_consistency(old_path)
    new_inc = r.check_consistency(new_path)
    old_unsat = set(old_inc.unsat_classes)
    new_unsat = set(new_inc.unsat_classes)

    return SemanticDiff(
        gained_subclass=sorted(new_sub - old_sub),
        lost_subclass=sorted(old_sub - new_sub),
        gained_equivalent=sorted(new_eq - old_eq),
        lost_equivalent=sorted(old_eq - new_eq),
        new_unsatisfiable=sorted(new_unsat - old_unsat),
        resolved_unsatisfiable=sorted(old_unsat - new_unsat),
    )


# ── Change-impact analysis ──────────────────────────────────────────────


_DEFAULT_SCAN_GLOBS = (
    "**/*.rq", "**/*.sparql",          # SPARQL queries
    "**/shapes/*.ttl", "**/*shapes*.ttl",
    "**/cypher/*.cypher",              # T1.5 outputs
    "**/graphql/*.graphql",
    "**/.wizard_session.json",
    "**/session.json",
)


def impact_analysis(diff: StructuralDiff,
                    scan_dirs: Sequence[str] = (),
                    *, globs: Sequence[str] = _DEFAULT_SCAN_GLOBS,
                    ) -> ImpactReport:
    """Scan ``scan_dirs`` for files referencing any class or property
    that appears in the structural diff. References are detected by
    *substring* — we don't try to parse SPARQL or SHACL semantically
    for this pass; the cost of a false-positive citation in the
    review UI is low.

    Returns an :class:`ImpactReport` with one ``AffectedFile`` per
    file that hits at least one diff IRI.
    """
    changed_iris: Set[str] = set()
    for grp in (diff.added_classes, diff.removed_classes,
                diff.added_properties, diff.removed_properties):
        changed_iris.update(grp)
    for old, new in diff.renamed_classes:
        changed_iris.add(old)
        changed_iris.add(new)
    if not changed_iris:
        return ImpactReport()
    # Also fold the local names (suffixes after the last '/' or '#'),
    # which is how SHACL / SPARQL typically reference classes.
    local_names = {_local_name(iri) for iri in changed_iris if iri}
    local_names -= {""}

    affected: List[AffectedFile] = []
    seen_paths: Set[str] = set()
    for root in scan_dirs:
        base = Path(root)
        if not base.exists():
            continue
        for pat in globs:
            for file_path in base.glob(pat):
                if not file_path.is_file():
                    continue
                key = str(file_path.resolve())
                if key in seen_paths:
                    continue
                try:
                    body = file_path.read_text(errors="replace")
                except Exception:                              # noqa: BLE001
                    continue
                refs: List[str] = []
                for iri in changed_iris:
                    if iri and iri in body:
                        refs.append(iri)
                for name in local_names:
                    if name and name in body:
                        if name not in refs:
                            refs.append(name)
                if not refs:
                    continue
                affected.append(AffectedFile(
                    path=str(file_path),
                    references=sorted(set(refs)),
                    kind=_classify_file(file_path),
                ))
                seen_paths.add(key)
    return ImpactReport(affected_files=affected)


def _local_name(iri: str) -> str:
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[-1]
    return iri


def _classify_file(path: Path) -> str:
    s = str(path).lower()
    if s.endswith((".rq", ".sparql")):
        return "sparql"
    if "shapes" in s or s.endswith("-shapes.ttl"):
        return "shacl"
    if s.endswith(".cypher"):
        return "cypher"
    if s.endswith(".graphql"):
        return "graphql"
    if s.endswith(".json"):
        return "session"
    return "unknown"


# ── Top-level ─────────────────────────────────────────────────────────


def diff_ontologies(old_path: str, new_path: str,
                    *, reasoner: Optional[str] = None,
                    scan_dirs: Sequence[str] = (),
                    ) -> OntologyDiffReport:
    """End-to-end. Computes structural + semantic + impact and
    returns a single :class:`OntologyDiffReport` ready for HTML
    rendering or audit-trail storage."""
    s = structural_diff(old_path, new_path)
    sem = semantic_diff(old_path, new_path, reasoner=reasoner)
    imp = impact_analysis(s, scan_dirs)
    return OntologyDiffReport(
        structural=s, semantic=sem, impact=imp,
        old_path=old_path, new_path=new_path,
    )


# ── HTML rendering ──────────────────────────────────────────────────────


def render_diff_html(report: OntologyDiffReport) -> str:
    """Compact HTML the wizard renders inline. Self-contained CSS so
    it works in any browser without external links."""
    s, sem, imp = report.structural, report.semantic, report.impact
    parts: List[str] = []
    parts.append("<!doctype html><meta charset='utf-8'>")
    parts.append("<style>"
                 "body{font:14px/1.5 -apple-system,sans-serif;"
                 "color:#0f172a;max-width:980px;margin:24px auto;padding:0 16px}"
                 "h1{font-size:22px;margin:0 0 6px}"
                 "h2{font-size:16px;margin:22px 0 6px;"
                 "border-bottom:1px solid #e5e7eb;padding-bottom:4px}"
                 ".add{color:#15803d}.rem{color:#b91c1c}.neutral{color:#475569}"
                 "ul{margin:6px 0 0 18px;padding:0}"
                 "li{margin:3px 0}"
                 "code{font-family:ui-monospace,monospace;background:#f1f5f9;"
                 "padding:1px 5px;border-radius:3px;font-size:12.5px}"
                 ".empty{color:#94a3b8;font-style:italic}"
                 "</style>")
    parts.append(f"<h1>Ontology diff</h1>")
    parts.append(f"<div class='neutral'>"
                 f"<code>{report.old_path}</code> "
                 f"→ <code>{report.new_path}</code></div>")

    parts.append("<h2>Structural</h2>")
    if s.is_empty():
        parts.append("<div class='empty'>No structural changes.</div>")
    else:
        parts.extend(_render_structural(s))

    parts.append("<h2>Semantic (entailment delta)</h2>")
    if sem.is_empty():
        parts.append("<div class='empty'>"
                     "No entailment changes detected by the reasoner.</div>")
    else:
        parts.extend(_render_semantic(sem))

    parts.append("<h2>Downstream impact</h2>")
    if imp.is_empty():
        parts.append("<div class='empty'>"
                     "No downstream files reference the changed IRIs.</div>")
    else:
        parts.append("<ul>")
        for f in imp.affected_files:
            refs = ", ".join(f"<code>{r}</code>" for r in f.references[:5])
            more = ("" if len(f.references) <= 5 else
                    f" <span class='neutral'>+{len(f.references)-5} more</span>")
            parts.append(
                f"<li><code>{f.path}</code> <span class='neutral'>"
                f"({f.kind})</span><br>"
                f"<span class='neutral'>references:</span> {refs}{more}</li>"
            )
        parts.append("</ul>")
    return "\n".join(parts)


def _render_structural(s: StructuralDiff) -> List[str]:
    bits: List[str] = []
    if s.renamed_classes:
        bits.append("<b class='neutral'>Renamed classes:</b><ul>")
        for old, new in s.renamed_classes:
            bits.append(f"<li><code class='rem'>{old}</code> → "
                        f"<code class='add'>{new}</code></li>")
        bits.append("</ul>")
    for label, items, cls in (
        ("Added classes",      s.added_classes,      "add"),
        ("Removed classes",    s.removed_classes,    "rem"),
        ("Added properties",   s.added_properties,   "add"),
        ("Removed properties", s.removed_properties, "rem"),
    ):
        if items:
            bits.append(f"<b class='neutral'>{label}:</b><ul>")
            for it in items[:20]:
                bits.append(f"<li class='{cls}'><code>{it}</code></li>")
            if len(items) > 20:
                bits.append(f"<li class='neutral'>+{len(items)-20} more</li>")
            bits.append("</ul>")
    return bits


def _render_semantic(sem: SemanticDiff) -> List[str]:
    bits: List[str] = []
    if sem.new_unsatisfiable:
        bits.append("<b class='rem'>New unsatisfiable classes:</b><ul>")
        for c in sem.new_unsatisfiable:
            bits.append(f"<li class='rem'><code>{c}</code></li>")
        bits.append("</ul>")
    if sem.resolved_unsatisfiable:
        bits.append("<b class='add'>Resolved unsatisfiability:</b><ul>")
        for c in sem.resolved_unsatisfiable:
            bits.append(f"<li class='add'><code>{c}</code></li>")
        bits.append("</ul>")
    if sem.gained_subclass:
        bits.append(f"<b class='add'>Gained subclass entailments "
                    f"({len(sem.gained_subclass)}):</b><ul>")
        for sub, sup in sem.gained_subclass[:20]:
            bits.append(f"<li class='add'><code>{sub}</code> ⊑ "
                        f"<code>{sup}</code></li>")
        bits.append("</ul>")
    if sem.lost_subclass:
        bits.append(f"<b class='rem'>Lost subclass entailments "
                    f"({len(sem.lost_subclass)}):</b><ul>")
        for sub, sup in sem.lost_subclass[:20]:
            bits.append(f"<li class='rem'><code>{sub}</code> ⊑ "
                        f"<code>{sup}</code></li>")
        bits.append("</ul>")
    return bits


__all__ = [
    "StructuralDiff", "SemanticDiff", "ImpactReport",
    "AffectedFile", "OntologyDiffReport",
    "structural_diff", "semantic_diff", "impact_analysis",
    "diff_ontologies", "render_diff_html",
]
