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

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD


PROV_NS = PROV
TOOLKIT_NS = Namespace("https://ontology.example.com/toolkit/materializer/")
SH = Namespace("http://www.w3.org/ns/shacl#")


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


@dataclass
class MaterializationResult:
    engines: List[EngineResult]
    materialised_path: str
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

    total_derived = sum(e.derived_triples for e in engine_results)

    # 5. Sensitivity audit + report
    warnings = _sensitivity_audit(base_graph, engine_results)
    report_path = os.path.join(output_dir, "materialisation_report.md")
    _write_report(report_path, engine_results, asserted_count,
                  materialised_count, total_derived, warnings)

    return MaterializationResult(
        engines=engine_results,
        materialised_path=materialised_path,
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

    work = Graph()
    _bind_prefixes(work)
    for t in base:
        work.add(t)
    before = set(work)

    try:
        # `advanced=True` enables sh:rule execution; `inplace=True` mutates
        # `work` so we can diff before/after to extract derived triples.
        pyshacl.validate(
            data_graph=work,
            shacl_graph=shapes,
            advanced=True,
            inplace=True,
            inference="none",  # OWL inference is engine 1's job
            debug=False,
        )
    except Exception as exc:  # noqa: BLE001
        return EngineResult(
            name="shacl", activity_iri=activity, output_path=None,
            derived_triples=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="FAIL", message=f"pyshacl rule execution failed: {exc}",
        )

    new_triples = set(work) - before
    derived = Graph()
    _bind_prefixes(derived)
    for t in new_triples:
        derived.add(t)
    _annotate_activity(derived, activity, "SHACL sh:rule materialisation",
                       "pyshacl advanced=True", rule_ids=rule_ids)
    derived.serialize(destination=output_path, format="turtle")

    return EngineResult(
        name="shacl", activity_iri=activity, output_path=output_path,
        derived_triples=len(new_triples),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="PASS",
        message=f"{len(new_triples)} triples from {len(rule_ids)} sh:rule(s)",
        rule_ids=rule_ids,
    )


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

    for rq_path in rule_files:
        rule_id = f"sparql:{rq_path.stem}"
        rule_ids.append(rule_id)
        try:
            query = rq_path.read_text(encoding="utf-8")
            result_graph = base.query(query).graph
            if result_graph is None:
                continue
            for t in result_graph:
                if t in base:
                    continue
                derived.add(t)
                total_new += 1
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
    )


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
    lines = [
        "# Materialisation Report\n\n",
        f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n",
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
    "MaterializationResult",
    "materialize",
]
