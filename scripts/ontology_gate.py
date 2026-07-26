#!/usr/bin/env python3
"""Ontology quality gate — a ratchet over measurable artifact properties.

Phase 0 of ONTOLOGY_ROADMAP.md. The problem this solves: before this script,
nothing in CI could fail on a defective *ontology*. The SPARQL suite scored
zero-row queries as passes, several governance criteria were score literals,
and no step parsed the emitted Turtle. A green build carried no information.

This gate measures the artifact and compares against a committed baseline.
Each metric declares a direction:

    lower_is_better  — regressions raise the number (parse failures, unsound axioms)
    higher_is_better — progress raises the number (restrictions, CQ rows)

The gate fails when any metric moves the wrong way. It does NOT fail merely
because debt exists — that would leave the build red for weeks and train
everyone to ignore it. Existing debt is recorded in the baseline; each phase
of the roadmap tightens it via ``--update-baseline``.

Usage:
    python scripts/ontology_gate.py                    # check against baseline
    python scripts/ontology_gate.py --update-baseline  # re-record after a phase
    python scripts/ontology_gate.py --json             # machine-readable output
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

try:
    import rdflib
except ImportError:  # pragma: no cover - CI installs rdflib
    print("ontology_gate: rdflib is required (pip install rdflib)", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PATH = os.path.join(REPO_ROOT, "ontology_baseline.json")

LOWER_IS_BETTER = "lower_is_better"
HIGHER_IS_BETTER = "higher_is_better"

# Files that are reasoner *output*, not authored artifacts. Their axiom counts
# reflect the closure, not the generator, so they'd mask regressions upstream.
_DERIVED_MARKERS = ("inferred", "materialised", "materialized")


def _is_derived(path: str) -> bool:
    base = os.path.basename(path).lower()
    return any(m in base for m in _DERIVED_MARKERS)


def _nested_run_dirs(output_dir: str) -> List[str]:
    """Sibling *runs* nested inside the output dir (e.g. output/demo/).

    A run directory is identified by having its own `ontology/` subdir.
    These are independent generations against different databases; folding
    them into one corpus would count a single defect once per run and make
    the metric depend on which demos happen to be on disk. CI generates
    exactly one run, so the gate measures exactly one run.
    """
    nested = []
    try:
        for entry in sorted(os.listdir(output_dir)):
            candidate = os.path.join(output_dir, entry)
            if os.path.isdir(candidate) and os.path.isdir(
                os.path.join(candidate, "ontology")
            ):
                nested.append(os.path.abspath(candidate))
    except OSError:
        pass
    return nested


def _turtle_files(output_dir: str) -> List[str]:
    excluded = tuple(d + os.sep for d in _nested_run_dirs(output_dir))
    found = glob.glob(os.path.join(output_dir, "**", "*.ttl"), recursive=True)
    return sorted(
        p for p in found
        if not os.path.abspath(p).startswith(excluded)
    )


def _parse_all(paths: List[str]) -> Tuple[Dict[str, rdflib.Graph], List[Tuple[str, str]]]:
    """Parse each Turtle file. Returns (graphs_by_path, failures)."""
    graphs: Dict[str, rdflib.Graph] = {}
    failures: List[Tuple[str, str]] = []
    for p in paths:
        try:
            g = rdflib.Graph()
            g.parse(p, format="turtle")
            graphs[p] = g
        except Exception as exc:  # noqa: BLE001 - we report every parse error
            first_line = str(exc).splitlines()[0] if str(exc).splitlines() else str(exc)
            failures.append((os.path.relpath(p, REPO_ROOT), first_line[:160]))
    return graphs, failures


def _authored_graph(graphs: Dict[str, rdflib.Graph]) -> rdflib.Graph:
    """Merge only the authored (non-derived) graphs."""
    merged = rdflib.Graph()
    for path, g in graphs.items():
        if _is_derived(path):
            continue
        for triple in g:
            merged.add(triple)
    return merged


def _multi_domain(graph: rdflib.Graph) -> Tuple[int, int]:
    """Properties carrying more than one rdfs:domain. Returns (count, worst)."""
    domains: Dict[Any, set] = defaultdict(set)
    for s, _, o in graph.triples((None, rdflib.RDFS.domain, None)):
        domains[s].add(o)
    multi = {k: v for k, v in domains.items() if len(v) > 1}
    worst = max((len(v) for v in multi.values()), default=0)
    return len(multi), worst


def _alignment_unbound(graphs: Dict[str, rdflib.Graph]) -> int:
    """Alignment subjects that name no entity in the rest of the ontology."""
    align_paths = [p for p in graphs if os.path.basename(p) == "alignment.ttl"]
    if not align_paths:
        return 0
    known = set()
    for path, g in graphs.items():
        if os.path.basename(path) == "alignment.ttl" or _is_derived(path):
            continue
        known |= set(g.subjects())
    unbound = 0
    for path in align_paths:
        subjects = {s for s in graphs[path].subjects() if isinstance(s, rdflib.URIRef)}
        unbound += len([s for s in subjects if s not in known])
    return unbound


def _malformed_iris(graph: rdflib.Graph) -> int:
    """IRIs that are unusable: whitespace, or an unregistered bare scheme.

    Catches both known defects — ``:StatusIn progress`` (space in a prefixed
    name) and ``<fhir:MedicinalProduct>`` (the YAML prefix map is never
    expanded, so the CURIE ships as a literal IRI).
    """
    bad = set()
    known_schemes = ("http", "https", "urn", "file", "mailto", "doi", "ftp")
    for node in set(graph.all_nodes()) | set(graph.predicates()):
        if not isinstance(node, rdflib.URIRef):
            continue
        text = str(node)
        if any(ch.isspace() for ch in text):
            bad.add(text)
            continue
        scheme, sep, rest = text.partition(":")
        if sep and not rest.startswith("//") and scheme.lower() not in known_schemes:
            bad.add(text)
    return len(bad)


def _count_predicate_objects(graph: rdflib.Graph, predicate, obj) -> int:
    return sum(1 for _ in graph.triples((None, predicate, obj)))


def _cq_rows(output_dir: str) -> Tuple[int, int, int]:
    """(tests returning rows, failing tests, total) from the SPARQL CQ CSV."""
    csv_path = os.path.join(output_dir, "reports", "sparql_cq_test_results.csv")
    if not os.path.isfile(csv_path):
        return (0, 0, 0)
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    returning = sum(1 for r in rows if (r.get("row_count") or "0").strip() not in ("0", ""))
    failing = sum(1 for r in rows if (r.get("status") or "").strip() in ("FAIL", "ERROR"))
    return returning, failing, len(rows)


def collect(output_dir: str) -> Dict[str, Any]:
    paths = _turtle_files(output_dir)
    graphs, failures = _parse_all(paths)
    authored = _authored_graph(graphs)

    owl_ns = rdflib.OWL
    restrictions = _count_predicate_objects(authored, rdflib.RDF.type, owl_ns.Restriction)
    multi_count, multi_worst = _multi_domain(authored)
    thing_ranges = _count_predicate_objects(authored, rdflib.RDFS.range, owl_ns.Thing)
    cq_returning, cq_failing, cq_total = _cq_rows(output_dir)

    metrics = {
        "turtle_parse_failures":       len(failures),
        "multi_domain_properties":     multi_count,
        "worst_domain_count":          multi_worst,
        "alignment_subjects_unbound":  _alignment_unbound(graphs),
        "malformed_iris":              _malformed_iris(authored),
        "object_properties_ranged_at_thing": thing_ranges,
        "owl_restrictions":            restrictions,
        "cq_tests_returning_rows":     cq_returning,
        "cq_tests_failing":            cq_failing,
    }
    detail = {
        "turtle_files_scanned": len(paths),
        "turtle_files_parsed":  len(graphs),
        "cq_tests_total":       cq_total,
        "parse_failures":       failures,
    }
    return {"metrics": metrics, "detail": detail}


DIRECTIONS: Dict[str, str] = {
    "turtle_parse_failures":       LOWER_IS_BETTER,
    "multi_domain_properties":     LOWER_IS_BETTER,
    "worst_domain_count":          LOWER_IS_BETTER,
    "alignment_subjects_unbound":  LOWER_IS_BETTER,
    "malformed_iris":              LOWER_IS_BETTER,
    "object_properties_ranged_at_thing": LOWER_IS_BETTER,
    "owl_restrictions":            HIGHER_IS_BETTER,
    "cq_tests_returning_rows":     HIGHER_IS_BETTER,
    "cq_tests_failing":            LOWER_IS_BETTER,
}

# Metrics that must reach zero before the roadmap phase that owns them closes.
PHASE_OWNER = {
    "turtle_parse_failures":       "Phase 1",
    "malformed_iris":              "Phase 1",
    "alignment_subjects_unbound":  "Phase 1",
    "multi_domain_properties":     "Phase 2",
    "worst_domain_count":          "Phase 2",
    "object_properties_ranged_at_thing": "Phase 2",
    "owl_restrictions":            "Phase 3",
    "cq_tests_returning_rows":     "Phase 4",
    "cq_tests_failing":            "Phase 4",
}


def compare(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    """Return a list of regression messages (empty means the gate passes)."""
    problems: List[str] = []
    base_metrics = baseline.get("metrics", {})
    for name, value in current["metrics"].items():
        if name not in base_metrics:
            continue  # new metric — recorded on next --update-baseline
        prior = base_metrics[name]
        direction = DIRECTIONS.get(name, LOWER_IS_BETTER)
        if direction == LOWER_IS_BETTER and value > prior:
            problems.append(f"{name}: {prior} -> {value} (regressed; lower is better)")
        elif direction == HIGHER_IS_BETTER and value < prior:
            problems.append(f"{name}: {prior} -> {value} (regressed; higher is better)")
    return problems


def _render(current: Dict[str, Any], baseline: Dict[str, Any] | None) -> None:
    base_metrics = (baseline or {}).get("metrics", {})
    print("\n  Ontology gate — artifact metrics\n")
    print(f"    {'metric':<38} {'baseline':>9} {'current':>9}   owner")
    print(f"    {'-' * 38} {'-' * 9:>9} {'-' * 9:>9}   {'-' * 8}")
    for name, value in current["metrics"].items():
        prior = base_metrics.get(name, "—")
        owner = PHASE_OWNER.get(name, "")
        flag = ""
        if isinstance(prior, int):
            direction = DIRECTIONS.get(name, LOWER_IS_BETTER)
            if (direction == LOWER_IS_BETTER and value < prior) or (
                direction == HIGHER_IS_BETTER and value > prior
            ):
                flag = "  improved"
            elif value != prior:
                flag = "  REGRESSED"
        print(f"    {name:<38} {str(prior):>9} {value:>9}   {owner}{flag}")

    failures = current["detail"]["parse_failures"]
    if failures:
        print(f"\n    Turtle parse failures ({len(failures)}):")
        for path, err in failures:
            print(f"      ✗ {path}")
            print(f"          {err}")
    d = current["detail"]
    print(
        f"\n    {d['turtle_files_parsed']}/{d['turtle_files_scanned']} Turtle files parsed"
        f"  |  CQ tests: {current['metrics']['cq_tests_returning_rows']}/{d['cq_tests_total']} return rows"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Ontology artifact quality ratchet")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "output"),
                    help="output directory to scan (default: ./output)")
    ap.add_argument("--baseline", default=BASELINE_PATH, help="baseline JSON path")
    ap.add_argument("--update-baseline", action="store_true",
                    help="record current metrics as the new baseline")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    if not os.path.isdir(args.out):
        print(f"ontology_gate: output dir not found: {args.out}", file=sys.stderr)
        return 2

    current = collect(args.out)

    if args.update_baseline:
        payload = {
            "_comment": (
                "Ontology quality ratchet baseline. Regenerate with "
                "`python scripts/ontology_gate.py --update-baseline` after a roadmap "
                "phase lands. Never raise a lower_is_better number to make CI green."
            ),
            "metrics": current["metrics"],
            "directions": DIRECTIONS,
            "phase_owner": PHASE_OWNER,
        }
        with open(args.baseline, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        _render(current, payload)
        print(f"\n  ✓ Baseline written → {os.path.relpath(args.baseline, REPO_ROOT)}\n")
        return 0

    baseline: Dict[str, Any] | None = None
    if os.path.isfile(args.baseline):
        with open(args.baseline) as f:
            baseline = json.load(f)

    # In --json mode stdout must be valid JSON and nothing else: CI redirects
    # it to a file. The human verdict goes to stderr so both are usable.
    out = sys.stderr if args.json else sys.stdout
    if args.json:
        print(json.dumps(current, indent=2))
    else:
        _render(current, baseline)

    if baseline is None:
        print("\n  ⚠ No baseline found — run with --update-baseline to create one.\n",
              file=out)
        return 0

    problems = compare(current, baseline)
    if problems:
        print("\n  ✗ Ontology gate FAILED — the artifact regressed:\n", file=out)
        for p in problems:
            print(f"      • {p}", file=out)
        print(
            "\n    If this regression is intentional and understood, update the "
            "baseline\n    in the same commit so the change is reviewable.\n",
            file=out,
        )
        return 1

    print("\n  ✓ Ontology gate passed — no regression against baseline.\n", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
