"""
materializer.py — Phase B (`--phase reason`)
─────────────────────────────────────────────
Runs three inference engines over the asserted ontology + ABox and writes
the derived triples to disk so downstream consumers (Insights, retrieval,
runtime gates) can read "the full picture" without re-reasoning.

Outputs (under `<out>/ontology/`):

  enterprise-inferred.ttl   — OWL-RL derivations (rdflib + owlrl)
  inferred-shacl.ttl        — pyshacl `sh:rule` outputs
  inferred-sparql.ttl       — SPARQL CONSTRUCT rule outputs
  materialised.ttl          — union of asserted + all derivations
  materialisation_report.md — triple counts, activity log, sensitivity audit

Each engine's output carries a top-level `prov:Activity` describing the
run, providing the lineage foundation that Phase D (explain) extends to
per-triple `prov:wasDerivedFrom` traces.

Engines:
    1. OWL-RL (rdflib + owlrl)            — always available
    2. pyshacl (advanced + sh:rule)       — always available
    3. SPARQL CONSTRUCT (rdflib)          — always available

ROBOT is *not* required here. Phase 2's reasoner.py keeps using ROBOT for
classification when present; Phase B uses pure-Python inference so the
toolkit always produces materialised triples regardless of host setup.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rdflib import BNode, Graph, Literal, Namespace, URIRef, Variable
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD


PROV_NS = PROV
TOOLKIT_NS = Namespace("https://ontology.example.com/toolkit/materializer/")
SH = Namespace("http://www.w3.org/ns/shacl#")


@dataclass
class LineageRecord:
    """Per-derived-triple provenance: which rule fired, with what bindings."""
    triple: Tuple[Any, Any, Any]
    rule_id: str
    engine: str
    bindings: Dict[str, str] = field(default_factory=dict)
    premises: List[Tuple[Any, Any, Any]] = field(default_factory=list)


@dataclass
class EngineResult:
    name: str                       # "owl-rl" | "shacl" | "sparql"
    activity_iri: URIRef
    output_path: Optional[str]
    derived_triples: int
    duration_ms: int
    status: str                     # PASS | SKIPPED | FAIL
    message: str = ""
    rule_ids: List[str] = field(default_factory=list)
    lineage: List[LineageRecord] = field(default_factory=list)


@dataclass
class MaterializationResult:
    engines: List[EngineResult]
    materialised_path: str
    lineage_path: str
    report_path: str
    total_derived: int
    asserted_count: int
    materialised_count: int
    sensitivity_warnings: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(e.status == "FAIL" for e in self.engines):
            return "FAIL"
        if all(e.status == "SKIPPED" for e in self.engines):
            return "SKIPPED"
        return "PASS"


# ── Public entrypoint ────────────────────────────────────────────────────


def materialize(
    ontology_path: str,
    output_dir: str,
    *,
    shapes_path: Optional[str] = None,
    data_graph_paths: Optional[Sequence[str]] = None,
    sparql_rules_dir: Optional[str] = None,
    extra_ontology_paths: Optional[Sequence[str]] = None,
) -> MaterializationResult:
    """Run all three engines and write the four output files.

    Args:
        ontology_path: TBox + asserted ABox in Turtle (typically
            `output/ontology/enterprise.ttl`).
        output_dir: directory to write derived files into. Created if
            absent.
        shapes_path: optional SHACL shapes file. If present, advanced-mode
            pyshacl is invoked (executes any `sh:rule` definitions).
        data_graph_paths: extra ABox files to load alongside the
            ontology — typically empty for schema-only runs.
        sparql_rules_dir: directory of `.rq` files containing SPARQL
            CONSTRUCT queries. Each file becomes one rule; the file name
            (sans extension) is used as the rule id.
        extra_ontology_paths: additional Turtle modules to merge into the
            base graph (e.g. `events.ttl`, `provenance.ttl`).
    """
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    base_graph = _load_base_graph(
        ontology_path, extra_ontology_paths or [], data_graph_paths or []
    )
    asserted_count = len(base_graph)

    engine_results: List[EngineResult] = []

    # 1. OWL-RL inference
    owl_path = os.path.join(output_dir, "enterprise-inferred.ttl")
    engine_results.append(_run_owl_rl(base_graph, owl_path))

    # 2. SHACL rules
    shacl_path = os.path.join(output_dir, "inferred-shacl.ttl")
    engine_results.append(_run_shacl_rules(base_graph, shapes_path, shacl_path))

    # 3. SPARQL CONSTRUCTs
    sparql_path = os.path.join(output_dir, "inferred-sparql.ttl")
    engine_results.append(_run_sparql_constructs(base_graph, sparql_rules_dir, sparql_path))

    # 4. Build materialised.ttl
    materialised_path = os.path.join(output_dir, "materialised.ttl")
    materialised_count = _write_materialised(
        ontology_path, extra_ontology_paths or [],
        engine_results, materialised_path
    )

    # 4b. Build materialised-lineage.ttl (Phase D — explain foundation).
    lineage_path = os.path.join(output_dir, "materialised-lineage.ttl")
    _write_lineage(engine_results, lineage_path)

    total_derived = sum(e.derived_triples for e in engine_results)

    # 5. Sensitivity audit + report
    warnings = _sensitivity_audit(base_graph, engine_results)
    report_path = os.path.join(output_dir, "materialisation_report.md")
    _write_report(report_path, engine_results, asserted_count,
                  materialised_count, total_derived, warnings)

    return MaterializationResult(
        engines=engine_results,
        materialised_path=materialised_path,
        lineage_path=lineage_path,
        report_path=report_path,
        total_derived=total_derived,
        asserted_count=asserted_count,
        materialised_count=materialised_count,
        sensitivity_warnings=warnings,
    )


# ── Engine 1: OWL-RL ─────────────────────────────────────────────────────


def _run_owl_rl(base: Graph, output_path: str) -> EngineResult:
    activity = _activity_iri("owl-rl")
    started = time.perf_counter()
    try:
        import owlrl
    except ImportError:
        return EngineResult(
            name="owl-rl", activity_iri=activity, output_path=None,
            derived_triples=0, duration_ms=0, status="SKIPPED",
            message="owlrl not installed",
        )

    derived = Graph()
    _bind_prefixes(derived)
    work = Graph()
    _bind_prefixes(work)
    for s, p, o in base:
        work.add((s, p, o))

    before = set(work)
    try:
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(work)
    except Exception as exc:  # noqa: BLE001 — engine can throw on weird input
        return EngineResult(
            name="owl-rl", activity_iri=activity, output_path=None,
            derived_triples=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="FAIL", message=f"OWL-RL expansion failed: {exc}",
        )

    new_triples = set(work) - before
    for t in new_triples:
        derived.add(t)

    # OWL-RL doesn't surface per-rule premises — the closure is bulk.
    # We still emit one LineageRecord per derived triple so that the
    # Viewer's Materialised tab can show *which engine* produced it.
    lineage = [
        LineageRecord(triple=t, rule_id="owl-rl:closure", engine="owl-rl")
        for t in new_triples
    ]

    _annotate_activity(derived, activity, "OWL-RL deductive closure",
                       "rdflib + owlrl", rule_ids=["OWL-RL-Semantics"])
    derived.serialize(destination=output_path, format="turtle")

    return EngineResult(
        name="owl-rl", activity_iri=activity, output_path=output_path,
        derived_triples=len(new_triples),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="PASS",
        message=f"{len(new_triples)} triples inferred via OWL-RL",
        rule_ids=["OWL-RL-Semantics"],
        lineage=lineage,
    )


# ── Engine 2: SHACL rules ────────────────────────────────────────────────


def _run_shacl_rules(base: Graph, shapes_path: Optional[str],
                     output_path: str) -> EngineResult:
    activity = _activity_iri("shacl")
    started = time.perf_counter()

    if not shapes_path or not os.path.isfile(shapes_path):
        return EngineResult(
            name="shacl", activity_iri=activity, output_path=None,
            derived_triples=0, duration_ms=0, status="SKIPPED",
            message="No SHACL shapes provided",
        )

    try:
        import pyshacl
    except ImportError:
        return EngineResult(
            name="shacl", activity_iri=activity, output_path=None,
            derived_triples=0, duration_ms=0, status="SKIPPED",
            message="pyshacl not installed",
        )

    shapes = Graph()
    try:
        shapes.parse(shapes_path, format="turtle")
    except Exception as exc:  # noqa: BLE001
        return EngineResult(
            name="shacl", activity_iri=activity, output_path=None,
            derived_triples=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="FAIL", message=f"Shapes graph could not be parsed: {exc}",
        )

    rule_ids = _collect_rule_ids(shapes)

    # Run each rule-bearing shape *in isolation* so we can attribute the
    # new triples it produces to the correct rule id. Shapes with no
    # `sh:rule` are skipped.
    derived_total: List[Tuple[Any, Any, Any]] = []
    lineage: List[LineageRecord] = []
    accumulator = Graph()
    _bind_prefixes(accumulator)
    for t in base:
        accumulator.add(t)

    shape_subjects = sorted({s for s, _p, _o in shapes.triples((None, SH.rule, None))},
                            key=str)
    if not shape_subjects:
        # No rules at all — nothing to do, but emit a (deliberately empty)
        # activity block so consumers see the engine ran.
        derived_g = Graph()
        _bind_prefixes(derived_g)
        _annotate_activity(derived_g, activity, "SHACL sh:rule materialisation",
                           "pyshacl advanced=True", rule_ids=[])
        derived_g.serialize(destination=output_path, format="turtle")
        return EngineResult(
            name="shacl", activity_iri=activity, output_path=output_path,
            derived_triples=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="PASS",
            message="No sh:rule definitions in shapes graph",
            rule_ids=[],
        )

    for shape in shape_subjects:
        rule_id = "shacl:" + (str(shape).rsplit("/", 1)[-1].rsplit("#", 1)[-1])
        # Build a single-shape graph that carries this shape and its
        # transitively-referenced blank nodes.
        single = _isolate_shape(shapes, shape)
        before = set(accumulator)
        try:
            pyshacl.validate(
                data_graph=accumulator, shacl_graph=single,
                advanced=True, inplace=True,
                inference="none", debug=False,
            )
        except Exception as exc:  # noqa: BLE001
            # Continue with other shapes; record but don't kill the engine.
            lineage.append(LineageRecord(
                triple=(URIRef("urn:shacl-error"), URIRef("urn:msg"),
                        Literal(str(exc))),
                rule_id=rule_id, engine="shacl",
            ))
            continue
        new = set(accumulator) - before
        for t in new:
            derived_total.append(t)
            # Capture the focusNode (the subject) as a coarse "premise":
            # SHACL rules fire per focus, so the subject is the trigger.
            premises = [(t[0], RDF.type, OWL.Thing)] if isinstance(t[0], URIRef) else []
            lineage.append(LineageRecord(
                triple=t, rule_id=rule_id, engine="shacl",
                bindings={"focusNode": _term_to_str(t[0])},
                premises=premises,
            ))

    derived = Graph()
    _bind_prefixes(derived)
    for t in derived_total:
        derived.add(t)
    _annotate_activity(derived, activity, "SHACL sh:rule materialisation",
                       "pyshacl advanced=True", rule_ids=rule_ids)
    derived.serialize(destination=output_path, format="turtle")

    return EngineResult(
        name="shacl", activity_iri=activity, output_path=output_path,
        derived_triples=len(derived_total),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="PASS",
        message=f"{len(derived_total)} triples from {len(rule_ids)} sh:rule(s)",
        rule_ids=rule_ids,
        lineage=lineage,
    )


def _isolate_shape(shapes: Graph, shape: Any) -> Graph:
    """Return a small graph containing `shape` plus every blank-node
    reachable from it. Used so we can run each shape in isolation."""
    single = Graph()
    _bind_prefixes(single)
    seen: set = set()
    stack = [shape]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for s, p, o in shapes.triples((node, None, None)):
            single.add((s, p, o))
            if isinstance(o, BNode) and o not in seen:
                stack.append(o)
    # Carry over prefix bindings.
    for prefix, ns in shapes.namespaces():
        single.bind(prefix, ns, replace=True)
    return single


def _collect_rule_ids(shapes: Graph) -> List[str]:
    ids: List[str] = []
    for shape, _, rule in shapes.triples((None, SH.rule, None)):
        rule_id = str(shape).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        ids.append(f"shacl:{rule_id}")
    return sorted(set(ids))


# ── Engine 3: SPARQL CONSTRUCT ──────────────────────────────────────────


def _run_sparql_constructs(base: Graph, rules_dir: Optional[str],
                           output_path: str) -> EngineResult:
    activity = _activity_iri("sparql")
    started = time.perf_counter()

    if not rules_dir or not os.path.isdir(rules_dir):
        return EngineResult(
            name="sparql", activity_iri=activity, output_path=None,
            derived_triples=0, duration_ms=0, status="SKIPPED",
            message="No SPARQL rules directory provided",
        )

    rule_files = sorted(Path(rules_dir).glob("*.rq"))
    if not rule_files:
        return EngineResult(
            name="sparql", activity_iri=activity, output_path=None,
            derived_triples=0, duration_ms=0, status="SKIPPED",
            message=f"No .rq files in {rules_dir}",
        )

    derived = Graph()
    _bind_prefixes(derived)
    rule_ids: List[str] = []
    failures: List[str] = []
    total_new = 0
    lineage: List[LineageRecord] = []

    for rq_path in rule_files:
        rule_id = f"sparql:{rq_path.stem}"
        rule_ids.append(rule_id)
        try:
            query = rq_path.read_text(encoding="utf-8")
            new_triples, rule_lineage = _construct_with_lineage(
                base, query, rule_id
            )
            for t in new_triples:
                if t in base:
                    continue
                derived.add(t)
                total_new += 1
            lineage.extend(rule_lineage)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{rule_id}: {exc}")

    _annotate_activity(derived, activity, "SPARQL CONSTRUCT rules",
                       "rdflib SPARQL engine", rule_ids=rule_ids)
    derived.serialize(destination=output_path, format="turtle")

    status = "FAIL" if failures and total_new == 0 else "PASS"
    msg = f"{total_new} triples from {len(rule_ids)} CONSTRUCT rule(s)"
    if failures:
        msg += f"; {len(failures)} rule(s) failed: {'; '.join(failures)[:200]}"
    return EngineResult(
        name="sparql", activity_iri=activity, output_path=output_path,
        derived_triples=total_new,
        duration_ms=int((time.perf_counter() - started) * 1000),
        status=status, message=msg, rule_ids=rule_ids,
        lineage=lineage,
    )


def _construct_with_lineage(base: Graph, query: str, rule_id: str
                            ) -> Tuple[List[Tuple[Any, Any, Any]], List[LineageRecord]]:
    """Run a CONSTRUCT query and capture per-triple lineage.

    Strategy: rewrite the CONSTRUCT block to ``SELECT *`` so we can read
    the variable bindings that satisfied each row. For every row we
    substitute the bindings into the original CONSTRUCT template (taken
    from rdflib's parsed algebra) and emit one LineageRecord per
    template triple. Any literal triples in the template (those without
    variables) are still attributed to the rule on every match.

    Premises are extracted from the WHERE clause's basic graph patterns
    by substituting the bindings — best-effort, but sufficient for the
    reified `prov:wasDerivedFrom` foundation.
    """
    from rdflib.plugins.sparql import prepareQuery

    prep = prepareQuery(query)
    template = list(prep.algebra.get("template", []) or [])
    where_atoms = _extract_where_bgps(prep.algebra)

    # Rewrite CONSTRUCT { ... } → SELECT * { ... } so we can iterate the
    # bindings. Use the parsed query's projection-variable list instead of
    # `SELECT *` to avoid surfacing internal variables.
    var_set: List[Variable] = []
    for s, p, o in template:
        for term in (s, p, o):
            if isinstance(term, Variable) and term not in var_set:
                var_set.append(term)
    for atom in where_atoms:
        for term in atom:
            if isinstance(term, Variable) and term not in var_set:
                var_set.append(term)
    # Fallback: if we couldn't find any vars (rare), just run the original.
    if not var_set:
        result_graph = base.query(query).graph
        triples = list(result_graph) if result_graph is not None else []
        return triples, [
            LineageRecord(t, rule_id, "sparql", {}, []) for t in triples
        ]

    select_text = re.sub(
        r"CONSTRUCT\s*\{[^{}]*\}",
        "SELECT " + " ".join(f"?{v}" for v in var_set),
        query, count=1, flags=re.IGNORECASE | re.DOTALL,
    )

    triples_out: List[Tuple[Any, Any, Any]] = []
    lineage: List[LineageRecord] = []
    try:
        rows = base.query(select_text)
    except Exception:
        # Regex rewrite failed (nested braces, etc.) — fall back to running
        # the CONSTRUCT directly without per-triple lineage.
        result_graph = base.query(query).graph
        triples = list(result_graph) if result_graph is not None else []
        return triples, [
            LineageRecord(t, rule_id, "sparql", {}, []) for t in triples
        ]

    for row in rows:
        bindings: Dict[Variable, Any] = {}
        for var, val in zip(rows.vars, row):
            if val is not None:
                bindings[var] = val
        for s, p, o in template:
            triple = tuple(bindings.get(t, t) if isinstance(t, Variable) else t
                           for t in (s, p, o))
            if any(isinstance(t, Variable) for t in triple):
                # Unbound variable in this row — skip.
                continue
            triples_out.append(triple)
            premises = []
            for atom in where_atoms:
                premise = tuple(
                    bindings.get(t, t) if isinstance(t, Variable) else t
                    for t in atom
                )
                if not any(isinstance(t, Variable) for t in premise):
                    premises.append(premise)
            lineage.append(LineageRecord(
                triple=triple, rule_id=rule_id, engine="sparql",
                bindings={str(k): _term_to_str(v) for k, v in bindings.items()},
                premises=premises,
            ))
    return triples_out, lineage


def _extract_where_bgps(algebra) -> List[Tuple[Any, Any, Any]]:
    """Walk the parsed algebra tree and return every basic graph pattern.

    Used to surface the WHERE atoms a binding row satisfied so we can
    write them as `toolkit:premises` on each derivation.
    """
    out: List[Tuple[Any, Any, Any]] = []
    stack = [algebra]
    while stack:
        node = stack.pop()
        if hasattr(node, "name") and node.name == "BGP":
            for triple in node.get("triples", []) or []:
                out.append(tuple(triple))
        # CompValue exposes its children via .iteritems / .values
        try:
            for v in dict(node).values():
                if hasattr(v, "name"):
                    stack.append(v)
                elif isinstance(v, (list, tuple)):
                    for item in v:
                        if hasattr(item, "name"):
                            stack.append(item)
        except Exception:
            continue
    return out


def _term_to_str(term: Any) -> str:
    if isinstance(term, URIRef):
        return str(term)
    if isinstance(term, Literal):
        return str(term)
    if isinstance(term, BNode):
        return f"_:{term}"
    return str(term)


# ── materialised.ttl assembly ────────────────────────────────────────────


def _write_materialised(ontology_path: str, extras: Sequence[str],
                        engine_results: Sequence[EngineResult],
                        out_path: str) -> int:
    g = Graph()
    _bind_prefixes(g)
    g.parse(ontology_path, format="turtle")
    for extra in extras:
        if extra and os.path.isfile(extra):
            try:
                g.parse(extra, format="turtle")
            except Exception:  # noqa: BLE001 — never let this kill the run
                pass
    for er in engine_results:
        if er.output_path and os.path.isfile(er.output_path):
            try:
                g.parse(er.output_path, format="turtle")
            except Exception:  # noqa: BLE001
                pass

    # Top-level provenance summary block: one prov:Activity per engine.
    materialisation = TOOLKIT_NS["materialisation/" + _stamp()]
    g.add((materialisation, RDF.type, PROV.Activity))
    g.add((materialisation, RDFS.label, Literal("Phase B materialisation run")))
    g.add((materialisation, PROV.endedAtTime,
           Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))
    for er in engine_results:
        g.add((materialisation, PROV.wasInformedBy, er.activity_iri))

    g.serialize(destination=out_path, format="turtle")
    return len(g)


# ── Phase D: per-triple lineage (reified statements) ────────────────────


def _write_lineage(engine_results: Sequence[EngineResult], out_path: str) -> int:
    """Write one rdf:Statement per derived triple with its
    `prov:wasDerivedFrom` block. Returns triple count for diagnostics."""
    g = Graph()
    _bind_prefixes(g)
    for er in engine_results:
        for rec in er.lineage:
            stmt = BNode()
            s, p, o = rec.triple
            g.add((stmt, RDF.type, RDF.Statement))
            g.add((stmt, RDF.subject, s if isinstance(s, (URIRef, BNode, Literal)) else Literal(str(s))))
            g.add((stmt, RDF.predicate, p if isinstance(p, URIRef) else Literal(str(p))))
            g.add((stmt, RDF.object, o if isinstance(o, (URIRef, BNode, Literal)) else Literal(str(o))))
            derivation = BNode()
            g.add((stmt, PROV.wasDerivedFrom, derivation))
            g.add((derivation, TOOLKIT_NS.rule, Literal(rec.rule_id)))
            g.add((derivation, TOOLKIT_NS.engine, Literal(rec.engine)))
            g.add((derivation, PROV.wasGeneratedBy, er.activity_iri))
            if rec.bindings:
                g.add((derivation, TOOLKIT_NS.bindings,
                       Literal(json.dumps(rec.bindings, sort_keys=True),
                               datatype=XSD.string)))
            for prem_s, prem_p, prem_o in rec.premises:
                premise_bnode = BNode()
                g.add((derivation, TOOLKIT_NS.premise, premise_bnode))
                g.add((premise_bnode, RDF.type, RDF.Statement))
                g.add((premise_bnode, RDF.subject, prem_s))
                g.add((premise_bnode, RDF.predicate, prem_p))
                g.add((premise_bnode, RDF.object, prem_o))
    g.serialize(destination=out_path, format="turtle")
    return len(g)


def explain_triple(lineage_path: str, subject: str, predicate: str,
                   obj: str) -> List[Dict[str, Any]]:
    """Look up reified-statement records for a given triple. Used by the
    wizard's `/api/explain` endpoint to power the Materialised tab.

    Returns a list of dicts (one per derivation): {rule, engine,
    bindings, premises}. An empty list means the triple is asserted (no
    lineage block exists for it) — the caller should display "asserted".
    """
    if not os.path.isfile(lineage_path):
        return []
    g = Graph()
    g.parse(lineage_path, format="turtle")
    s = URIRef(subject)
    p = URIRef(predicate)
    o = _parse_term(obj)

    out: List[Dict[str, Any]] = []
    for stmt in g.subjects(RDF.type, RDF.Statement):
        if (stmt, RDF.subject, s) not in g: continue
        if (stmt, RDF.predicate, p) not in g: continue
        if (stmt, RDF.object, o) not in g: continue
        for _, _, deriv in g.triples((stmt, PROV.wasDerivedFrom, None)):
            rule = next(g.objects(deriv, TOOLKIT_NS.rule), None)
            engine = next(g.objects(deriv, TOOLKIT_NS.engine), None)
            bindings = next(g.objects(deriv, TOOLKIT_NS.bindings), None)
            try:
                bindings_obj = json.loads(str(bindings)) if bindings else {}
            except Exception:
                bindings_obj = {}
            premises = []
            for _, _, prem in g.triples((deriv, TOOLKIT_NS.premise, None)):
                ps = next(g.objects(prem, RDF.subject), None)
                pp = next(g.objects(prem, RDF.predicate), None)
                po = next(g.objects(prem, RDF.object), None)
                if ps and pp and po:
                    premises.append([str(ps), str(pp), str(po)])
            out.append({
                "rule": str(rule) if rule else None,
                "engine": str(engine) if engine else None,
                "bindings": bindings_obj,
                "premises": premises,
            })
    return out


def _parse_term(text: str) -> Any:
    text = text.strip()
    if text.startswith('"'):
        # Best-effort literal parsing — strip quotes, leave datatype/lang alone.
        end = text.rfind('"')
        return Literal(text[1:end])
    if text.startswith("<") and text.endswith(">"):
        return URIRef(text[1:-1])
    return URIRef(text)


# ── Sensitivity-tier audit ───────────────────────────────────────────────


def _sensitivity_audit(base: Graph,
                       engine_results: Sequence[EngineResult]) -> List[str]:
    """Flag inferred subClassOf edges where the inferred subclass has a
    weaker sensitivity tier than its inferred parent.

    A full Phase B implementation would also rewrite the inferred tier
    to the maximum of all premise tiers. For now we surface warnings so
    operators can decide; the rewrite belongs with Phase D's full
    explanation graph (we do not have per-triple premise data yet).
    """
    tier_rank = {
        "Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3,
    }
    sens = URIRef("https://ontology.example.com/enterprise/sensitivityTier")

    base_tier: Dict[URIRef, str] = {}
    for s, _p, o in base.triples((None, sens, None)):
        if isinstance(o, URIRef):
            base_tier[s] = o.split("/")[-1]

    warnings: List[str] = []
    for er in engine_results:
        if not er.output_path or not os.path.isfile(er.output_path):
            continue
        derived = Graph()
        try:
            derived.parse(er.output_path, format="turtle")
        except Exception:  # noqa: BLE001
            continue
        for s, _p, o in derived.triples((None, RDFS.subClassOf, None)):
            if not (isinstance(s, URIRef) and isinstance(o, URIRef)):
                continue
            child = base_tier.get(s)
            parent = base_tier.get(o)
            if not child or not parent:
                continue
            if tier_rank.get(child, 0) < tier_rank.get(parent, 0):
                warnings.append(
                    f"[{er.name}] inferred {s.n3()} rdfs:subClassOf {o.n3()} — "
                    f"child tier '{child}' is weaker than parent '{parent}'"
                )
    return warnings


# ── Report ───────────────────────────────────────────────────────────────


def _write_report(path: str, engines: Sequence[EngineResult],
                  asserted: int, materialised: int, total_derived: int,
                  warnings: Sequence[str]) -> None:
    blowup = (materialised / asserted) if asserted else 0.0
    lineage_count = sum(len(e.lineage) for e in engines)
    lines = [
        "# Materialisation Report\n\n",
        f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n",
        f"Lineage records (Phase D): **{lineage_count:,}**\n\n",
        "## Triple counts\n\n",
        "| Source | Triples |\n",
        "|--------|--------:|\n",
        f"| Asserted (input) | {asserted:,} |\n",
        f"| Total derived | {total_derived:,} |\n",
        f"| **Materialised (asserted ⊕ derived)** | **{materialised:,}** |\n",
        f"| Blow-up ratio | {blowup:.2f}× |\n\n",
        "## Engine activity\n\n",
        "| Engine | Status | Derived | Duration | Rules |\n",
        "|--------|--------|--------:|---------:|------:|\n",
    ]
    for e in engines:
        lines.append(
            f"| {e.name} | {e.status} | {e.derived_triples:,} | "
            f"{e.duration_ms} ms | {len(e.rule_ids)} |\n"
        )
    lines.append("\n")
    for e in engines:
        if e.message:
            lines.append(f"- **{e.name}**: {e.message}\n")
    if warnings:
        lines.append("\n## ⚠ Sensitivity warnings\n\n")
        lines.append(
            "Inferred subclass relationships where the child carries a *weaker* "
            "sensitivity tier than the parent. Operators should review and "
            "either tighten the child's tier or flag the rule as benign.\n\n"
        )
        for w in warnings:
            lines.append(f"- {w}\n")
    if blowup > 5:
        lines.append(
            "\n## ⚠ Materialisation blow-up\n\n"
            f"The materialised graph is {blowup:.1f}× the asserted size. "
            "Inspect the derivation rules — a bad transitive ⊕ symmetric "
            "combination can multiply triples without bound.\n"
        )
    with open(path, "w") as f:
        f.writelines(lines)


# ── Helpers ──────────────────────────────────────────────────────────────


def _activity_iri(engine: str) -> URIRef:
    return TOOLKIT_NS[f"activity/{engine}/{_stamp()}"]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _bind_prefixes(g: Graph) -> None:
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("prov", PROV)
    g.bind("xsd", XSD)
    g.bind("toolkit", TOOLKIT_NS)
    g.bind("sh", SH)


def _annotate_activity(derived: Graph, activity: URIRef, label: str,
                       engine_label: str, rule_ids: Sequence[str]) -> None:
    derived.add((activity, RDF.type, PROV.Activity))
    derived.add((activity, RDFS.label, Literal(label)))
    derived.add((activity, RDFS.comment, Literal(f"Engine: {engine_label}")))
    derived.add((activity, PROV.endedAtTime,
                 Literal(datetime.now(timezone.utc).isoformat(),
                         datatype=XSD.dateTime)))
    for rid in rule_ids:
        derived.add((activity, PROV.used, Literal(rid)))


def _load_base_graph(ontology_path: str, extras: Sequence[str],
                     data_paths: Sequence[str]) -> Graph:
    g = Graph()
    _bind_prefixes(g)
    g.parse(ontology_path, format="turtle")
    for path in list(extras) + list(data_paths):
        if path and os.path.isfile(path):
            try:
                g.parse(path, format="turtle")
            except Exception:  # noqa: BLE001
                pass
    return g


__all__ = [
    "EngineResult",
    "LineageRecord",
    "MaterializationResult",
    "explain_triple",
    "materialize",
]
