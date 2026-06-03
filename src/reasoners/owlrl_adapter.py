"""
src/reasoners/owlrl_adapter.py — T2.1
─────────────────────────────────────
Pure-Python OWL-RL reasoner using rdflib + ``owlrl``.

Why ship a third reasoner alongside ROBOT/HermiT and ROBOT/ELK?
- **Zero install.** No Java, no JAR, no docker. CI environments and
  every developer's laptop already has rdflib via ``pyshacl``.
- **Forward-chaining.** OWL 2 RL is tractable in polynomial time and
  gives us enough power for the three call sites that matter here:
  derived subclass / equivalent-class closures, inconsistency
  detection via ``owl:Nothing`` membership, and SHACL redundancy
  detection.

What we don't get vs. HermiT:
- No full DL reasoning. Some inconsistencies that need
  open-world reasoning may slip past.
- No "minimal unsatisfiable axiom set" — owlrl tells us *that*
  something's unsatisfiable but not *why*. We surface what
  classes / individuals are involved; the engineer reads the
  closure to debug.

Defensive about owlrl availability — ``available()`` returns
False when the package isn't installed; the registry then skips
this adapter without raising.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set, Tuple

from .base import Inconsistency, ReasonerResult, RedundancyFinding


@dataclass
class OwlrlReasoner:
    name: str = "owlrl"

    # ── Availability ────────────────────────────────────────────────────

    def available(self) -> bool:
        try:
            import owlrl                                            # noqa: F401
            import rdflib                                           # noqa: F401
            return True
        except ImportError:
            return False

    # ── Internals ───────────────────────────────────────────────────────

    def _materialise(self, ontology_path: str):
        """Forward-chain OWL-RL over the input. Returns the rdflib
        Graph with the closure expanded in-place."""
        import rdflib
        from owlrl import DeductiveClosure, OWLRL_Semantics
        g = rdflib.Graph()
        g.parse(ontology_path, format=self._guess_format(ontology_path))
        DeductiveClosure(OWLRL_Semantics).expand(g)
        return g

    @staticmethod
    def _guess_format(path: str) -> str:
        low = path.lower()
        if low.endswith((".ttl", ".turtle")):
            return "turtle"
        if low.endswith(".owl"):
            return "xml"
        if low.endswith(".rdf"):
            return "xml"
        if low.endswith((".nt", ".n3")):
            return "n3"
        if low.endswith(".jsonld"):
            return "json-ld"
        return "turtle"

    # ── classify ────────────────────────────────────────────────────────

    def classify(self, ontology_path: str,
                 *, output_path: Optional[str] = None,
                 ) -> ReasonerResult:
        if not self.available():
            return ReasonerResult(
                reasoner=self.name, status="SKIPPED",
                message=("owlrl / rdflib not installed; pip install "
                         "owlrl rdflib"),
            )
        t0 = time.perf_counter()
        try:
            g = self._materialise(ontology_path)
        except Exception as exc:                                    # noqa: BLE001
            return ReasonerResult(
                reasoner=self.name, status="ERROR",
                message=f"{type(exc).__name__}: {exc}",
            )

        import rdflib
        OWL = rdflib.namespace.OWL
        RDF = rdflib.namespace.RDF
        RDFS = rdflib.namespace.RDFS

        # Asserted vs derived subclass axioms. We re-parse a clean
        # copy to know what was asserted in the source file.
        asserted = rdflib.Graph()
        asserted.parse(ontology_path,
                       format=self._guess_format(ontology_path))
        asserted_sub = {(str(s), str(o))
                        for s, _, o in asserted.triples(
                            (None, RDFS.subClassOf, None))
                        if isinstance(s, rdflib.URIRef)
                        and isinstance(o, rdflib.URIRef)}
        derived_sub: List[Tuple[str, str]] = []
        for s, _, o in g.triples((None, RDFS.subClassOf, None)):
            if not isinstance(s, rdflib.URIRef) or not isinstance(o, rdflib.URIRef):
                continue
            key = (str(s), str(o))
            if key in asserted_sub:
                continue
            if str(o) == str(OWL.Thing):
                continue                            # uninteresting
            if str(s) == str(o):
                continue                            # reflexive
            derived_sub.append(key)

        derived_eq: List[Tuple[str, str]] = []
        seen_eq: Set[Tuple[str, str]] = set()
        for s, _, o in g.triples((None, OWL.equivalentClass, None)):
            if not isinstance(s, rdflib.URIRef) or not isinstance(o, rdflib.URIRef):
                continue
            pair = tuple(sorted((str(s), str(o))))
            if pair not in seen_eq:
                derived_eq.append(pair)
                seen_eq.add(pair)

        all_classes = {str(c) for c in g.subjects(RDF.type, OWL.Class)
                       if isinstance(c, rdflib.URIRef)}
        asserted_classes = {str(c) for c in asserted.subjects(
            RDF.type, OWL.Class) if isinstance(c, rdflib.URIRef)}

        if output_path:
            try:
                g.serialize(destination=output_path, format="turtle")
            except Exception:                                       # noqa: BLE001
                pass

        return ReasonerResult(
            reasoner=self.name, status="OK",
            derived_subclass=sorted(derived_sub),
            derived_equivalent=sorted(derived_eq),
            asserted_class_count=len(asserted_classes),
            derived_class_count=len(all_classes - asserted_classes),
            duration_s=time.perf_counter() - t0,
            derived_axioms_path=output_path,
        )

    # ── check_consistency ──────────────────────────────────────────────

    def check_consistency(self, ontology_path: str) -> Inconsistency:
        if not self.available():
            return Inconsistency(
                message="owlrl not installed; skipping consistency check",
            )
        try:
            g = self._materialise(ontology_path)
        except Exception as exc:                                    # noqa: BLE001
            return Inconsistency(message=f"closure failed: {exc}")

        import rdflib
        OWL = rdflib.namespace.OWL
        RDF = rdflib.namespace.RDF
        RDFS = rdflib.namespace.RDFS

        unsat: List[str] = []
        bad_individuals: List[str] = []
        # owl:Nothing has reflexive entailments in the OWL-RL closure
        # (e.g. owl:Nothing rdfs:subClassOf owl:Nothing) — we filter
        # it out so it never registers as a "finding."
        _NOTHING = str(OWL.Nothing)

        # 1. Classes proved equivalent to owl:Nothing → unsatisfiable.
        for s, _, _ in g.triples((None, OWL.equivalentClass, OWL.Nothing)):
            if isinstance(s, rdflib.URIRef) and str(s) != _NOTHING:
                unsat.append(str(s))
        for s, _, _ in g.triples((None, RDFS.subClassOf, OWL.Nothing)):
            if isinstance(s, rdflib.URIRef) and str(s) != _NOTHING:
                unsat.append(str(s))

        # 2. Individuals typed as owl:Nothing (forward-chained from
        # disjointness violations) → ontology is inconsistent.
        for s, _, _ in g.triples((None, RDF.type, OWL.Nothing)):
            if isinstance(s, rdflib.URIRef):
                bad_individuals.append(str(s))

        # 3. Direct check: any individual asserted as instance of
        # two disjoint classes? owlrl closes this into owl:Nothing
        # membership already, but we also surface the human-readable
        # pair for the build-gate error message.
        disjoint_pairs: List[Tuple[str, str]] = []
        for a, _, b in g.triples((None, OWL.disjointWith, None)):
            if isinstance(a, rdflib.URIRef) and isinstance(b, rdflib.URIRef):
                disjoint_pairs.append((str(a), str(b)))
        if disjoint_pairs:
            for a, b in disjoint_pairs:
                a_uri, b_uri = rdflib.URIRef(a), rdflib.URIRef(b)
                a_inst = {str(s) for s, _, _ in g.triples((None, RDF.type, a_uri))
                          if isinstance(s, rdflib.URIRef)}
                b_inst = {str(s) for s, _, _ in g.triples((None, RDF.type, b_uri))
                          if isinstance(s, rdflib.URIRef)}
                overlap = a_inst & b_inst
                for ind in overlap:
                    if ind not in bad_individuals:
                        bad_individuals.append(ind)
                    label = f"{ind} ∈ ({a} ⊓ {b}) but {a} owl:disjointWith {b}"
                    msg = label
                    return Inconsistency(
                        unsat_classes=sorted(set(unsat)),
                        individuals=sorted(set(bad_individuals)),
                        message=msg,
                        conflicting_axioms=[
                            f"{a} owl:disjointWith {b}",
                            f"{ind} rdf:type {a}",
                            f"{ind} rdf:type {b}",
                        ],
                    )

        return Inconsistency(
            unsat_classes=sorted(set(unsat)),
            individuals=sorted(set(bad_individuals)),
            message="" if (unsat or bad_individuals) else "consistent",
        )

    # ── detect_redundant_shacl ─────────────────────────────────────────

    def detect_redundant_shacl(self, ontology_path: str,
                               shapes_path: str,
                               ) -> List[RedundancyFinding]:
        if not self.available():
            return []
        try:
            import rdflib
        except ImportError:
            return []
        SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")

        try:
            g = self._materialise(ontology_path)
        except Exception:                                           # noqa: BLE001
            return []
        try:
            shapes = rdflib.Graph()
            shapes.parse(shapes_path,
                         format=self._guess_format(shapes_path))
        except Exception:                                           # noqa: BLE001
            return []

        findings: List[RedundancyFinding] = []
        RDFS = rdflib.namespace.RDFS

        # Iterate sh:NodeShape entries.
        for shape in shapes.subjects(rdflib.namespace.RDF.type, SH.NodeShape):
            target_class = next(shapes.objects(shape, SH.targetClass), None)
            if target_class is None:
                continue
            # sh:property entries inside the shape.
            for prop_node in shapes.objects(shape, SH.property):
                path  = next(shapes.objects(prop_node, SH.path),  None)
                cls   = next(shapes.objects(prop_node, getattr(SH, "class")), None)
                if path is None or cls is None:
                    continue
                # Is the SHACL claim "every <target_class>'s <path> is a
                # <cls>" already entailed by an rdfs:range declaration
                # in the closure?
                entailed_ranges = {str(o) for o in g.objects(path, RDFS.range)
                                    if isinstance(o, rdflib.URIRef)}
                if str(cls) in entailed_ranges:
                    findings.append(RedundancyFinding(
                        shape_iri=str(shape),
                        target_class=str(target_class),
                        constraint=f"sh:path={path} sh:class={cls}",
                        reason=(f"OWL entails rdfs:range({path}, {cls}); "
                                f"SHACL sh:class on this path is "
                                f"redundant."),
                    ))
        return findings


__all__ = ["OwlrlReasoner"]
