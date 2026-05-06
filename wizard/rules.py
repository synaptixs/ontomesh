"""
wizard/rules.py — Phase C
─────────────────────────
Rule authoring, validation, and serialisation for the Ontology Studio's
"Rules" step. Rules live alongside other session data in `session.rules`
(a JSON list) and are emitted to disk just before Phase B's `--phase
reason` consumes them:

    SHACL  rules  →  output/shapes/rules.ttl       (sh:rule blocks)
    SPARQL rules  →  output/sparql_rules/<id>.rq   (one file per rule)
    OWL    axioms →  ontology_metadata flags       (Phase A — done)

A rule is the small dict literal used by the API and the session store:

    {
        "id":      "rule-impact-via-hierarchy",
        "kind":    "shacl" | "sparql" | "owl",
        "label":   "If a network element's parent fails, mark it impacted",
        "industry": "telecom",      # optional — used for starter library
        "body":    "<turtle | sparql | json-spec>",
        "enabled": True,
    }

Every rule is validated *before* it is saved: SHACL rules must parse and
run against an empty data graph, SPARQL rules must prepare without
exceptions, and OWL axioms must produce a parseable Turtle fragment.
Authors never see a "saved-broken" rule.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from rdflib import Graph
from rdflib.plugins.sparql import prepareQuery


SHACL_PREFIXES = """\
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
"""

OWL_PREFIXES = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
"""


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


# ── ID normalisation ─────────────────────────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(label: str) -> str:
    return _SLUG_RE.sub("-", label.lower()).strip("-") or "rule"


def normalise_rule(rule: dict) -> dict:
    """Apply defaults, ensure an id, lowercase the kind."""
    out = dict(rule)
    out["kind"] = (out.get("kind") or "").strip().lower()
    out["label"] = (out.get("label") or "").strip()
    out["body"] = out.get("body", "")
    out["enabled"] = bool(out.get("enabled", True))
    if not out.get("id"):
        out["id"] = slugify(out["label"]) or f"rule-{abs(hash(out['body'])) % 10**6}"
    return out


# ── Validation ───────────────────────────────────────────────────────────


def validate_rule(rule: dict) -> ValidationResult:
    rule = normalise_rule(rule)
    kind = rule["kind"]
    body = rule["body"]
    if not body or not body.strip():
        return ValidationResult(False, errors=["Rule body is empty"])
    if kind == "shacl":
        return _validate_shacl(body)
    if kind == "sparql":
        return _validate_sparql(body)
    if kind == "owl":
        return _validate_owl(body)
    return ValidationResult(False, errors=[f"Unknown rule kind '{kind}'"])


def _validate_shacl(body: str) -> ValidationResult:
    # Always prepend the standard prefixes — rdflib silently accepts
    # duplicate declarations and the body may use any of them implicitly.
    text = SHACL_PREFIXES + "\n" + body
    g = Graph()
    try:
        g.parse(data=text, format="turtle")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(False, errors=[f"SHACL Turtle parse error: {exc}"])

    # Smoke-execute against an empty data graph in advanced mode — this
    # ensures sh:rule blocks (sh:TripleRule / sh:SPARQLRule) are well-formed.
    try:
        import pyshacl
        empty = Graph()
        pyshacl.validate(
            data_graph=empty, shacl_graph=g,
            advanced=True, inplace=True, inference="none", debug=False,
        )
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(False, errors=[f"SHACL execution error: {exc}"])

    warnings = []
    from rdflib import URIRef
    SH = URIRef("http://www.w3.org/ns/shacl#rule")
    if not list(g.triples((None, SH, None))):
        warnings.append("Shapes graph parses but contains no `sh:rule` "
                        "constructs — only `sh:property` validations.")
    return ValidationResult(True, warnings=warnings)


def _validate_sparql(body: str) -> ValidationResult:
    try:
        q = prepareQuery(body)
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(False, errors=[f"SPARQL parse error: {exc}"])
    # Confirm CONSTRUCT — SELECT/ASK/UPDATE wouldn't materialise triples.
    if getattr(q.algebra, "name", "") != "ConstructQuery":
        return ValidationResult(
            False,
            errors=["Only CONSTRUCT queries are accepted as materialisation "
                    "rules. Use SHACL `sh:rule` for assertional rules."],
        )
    # Smoke-execute against an empty graph — surfaces variable/typo issues.
    try:
        Graph().query(q)
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(False, errors=[f"SPARQL execution error: {exc}"])
    return ValidationResult(True)


def _validate_owl(body: str) -> ValidationResult:
    text = OWL_PREFIXES + "\n" + body
    g = Graph()
    try:
        g.parse(data=text, format="turtle")
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(False, errors=[f"OWL Turtle parse error: {exc}"])
    if len(g) == 0:
        return ValidationResult(False, errors=["OWL fragment produced no triples"])
    return ValidationResult(True)


def validate_rules(rules: Sequence[dict]) -> Dict[str, ValidationResult]:
    """Validate a batch of rules. Returns id → result, plus a synthetic
    `__duplicate_ids__` entry if ids collide.
    """
    out: Dict[str, ValidationResult] = {}
    seen: Dict[str, int] = {}
    for r in rules:
        rid = normalise_rule(r)["id"]
        seen[rid] = seen.get(rid, 0) + 1
        out[rid] = validate_rule(r)
    duplicates = [rid for rid, n in seen.items() if n > 1]
    if duplicates:
        out["__duplicate_ids__"] = ValidationResult(
            False, errors=[f"Duplicate rule ids: {', '.join(duplicates)}"]
        )
    return out


# ── Serialisation ────────────────────────────────────────────────────────


def export_rules(rules: Sequence[dict], output_dir: str) -> Dict[str, object]:
    """Write enabled rules to disk where Phase B looks for them.

    Layout written:
        <out>/shapes/rules.ttl        — SHACL union (one file)
        <out>/sparql_rules/<id>.rq    — one CONSTRUCT per file
        <out>/owl_axioms.ttl          — OWL fragments (advisory; the
                                         generator merges them after
                                         phase 2 if present)

    Returns a dict with counts and the file paths actually written.
    """
    output_dir = os.path.abspath(output_dir)
    shapes_dir = os.path.join(output_dir, "shapes")
    sparql_dir = os.path.join(output_dir, "sparql_rules")
    os.makedirs(shapes_dir, exist_ok=True)
    os.makedirs(sparql_dir, exist_ok=True)

    shacl_rules: List[dict] = []
    sparql_rules: List[dict] = []
    owl_rules: List[dict] = []
    skipped: List[Tuple[str, str]] = []

    for raw in rules:
        rule = normalise_rule(raw)
        if not rule.get("enabled", True):
            continue
        result = validate_rule(rule)
        if not result.ok:
            skipped.append((rule["id"], "; ".join(result.errors)))
            continue
        if rule["kind"] == "shacl":
            shacl_rules.append(rule)
        elif rule["kind"] == "sparql":
            sparql_rules.append(rule)
        elif rule["kind"] == "owl":
            owl_rules.append(rule)

    shacl_path = os.path.join(shapes_dir, "rules.ttl")
    if shacl_rules:
        body = SHACL_PREFIXES + "\n"
        for r in shacl_rules:
            body += f"# Rule {r['id']}: {r['label']}\n"
            body += r["body"].strip() + "\n\n"
        Path(shacl_path).write_text(body)
    else:
        # Remove a stale rules.ttl from a prior run if no rules survive.
        if os.path.isfile(shacl_path):
            os.remove(shacl_path)
        shacl_path = None  # type: ignore[assignment]

    written_sparql: List[str] = []
    # Drop any prior .rq files we previously wrote to avoid orphans.
    for old in Path(sparql_dir).glob("*.rq"):
        old.unlink()
    for r in sparql_rules:
        target = os.path.join(sparql_dir, f"{r['id']}.rq")
        Path(target).write_text(r["body"].strip() + "\n")
        written_sparql.append(target)

    owl_path = os.path.join(output_dir, "owl_axioms.ttl")
    if owl_rules:
        body = OWL_PREFIXES + "\n"
        for r in owl_rules:
            body += f"# Rule {r['id']}: {r['label']}\n"
            body += r["body"].strip() + "\n\n"
        Path(owl_path).write_text(body)
    else:
        if os.path.isfile(owl_path):
            os.remove(owl_path)
        owl_path = None  # type: ignore[assignment]

    return {
        "shacl_path": shacl_path,
        "sparql_paths": written_sparql,
        "owl_path": owl_path,
        "counts": {
            "shacl": len(shacl_rules),
            "sparql": len(sparql_rules),
            "owl": len(owl_rules),
            "skipped": len(skipped),
        },
        "skipped": skipped,
    }


# ── Starter library loader ───────────────────────────────────────────────


def load_starter_library(library_dir: str, industry: Optional[str] = None
                         ) -> List[dict]:
    """Load `templates/rules/<industry>.yaml` (or all yamls if industry is
    None) and return a list of rule dicts ready to drop into a session.

    The YAML format is:

        industry: telecom
        rules:
          - id: rule-impact-via-hierarchy
            kind: shacl
            label: "..."
            body: |
              :ParentImpact a sh:NodeShape ; ...

    Missing files return an empty list — the loader never raises.
    """
    if not os.path.isdir(library_dir):
        return []
    try:
        import yaml
    except ImportError:
        return []

    paths: List[Path]
    if industry:
        paths = [Path(library_dir) / f"{industry}.yaml"]
    else:
        paths = sorted(Path(library_dir).glob("*.yaml"))

    rules: List[dict] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except Exception:  # noqa: BLE001
            continue
        for r in data.get("rules", []):
            r = dict(r)
            r.setdefault("industry", data.get("industry", p.stem))
            rules.append(normalise_rule(r))
    return rules


__all__ = [
    "ValidationResult",
    "export_rules",
    "load_starter_library",
    "normalise_rule",
    "slugify",
    "validate_rule",
    "validate_rules",
]
