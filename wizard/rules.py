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
@prefix :     <https://ontology.example.com/enterprise/> .
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
    """Apply defaults, ensure an id, lowercase the kind. If a SHACL rule
    carries a slot-fill `meta` block (target_class + conditions +
    assertion), compile it to Turtle and write the result into `body` so
    downstream validation/export sees a single source of truth.
    """
    out = dict(rule)
    out["kind"] = (out.get("kind") or "").strip().lower()
    out["label"] = (out.get("label") or "").strip()
    out["body"] = out.get("body", "")
    out["enabled"] = bool(out.get("enabled", True))
    out["meta"] = out.get("meta") or {}
    # #2 — Plain-English summary, populated lazily by /api/rules/summarise.
    # Persisted on the rule so reviewers always see the English first.
    out["nl_summary"] = (out.get("nl_summary") or "").strip()
    # Slot-fill SHACL: derive `body` from `meta` when present so the
    # builder is the source of truth, the textarea is the rendered form.
    if out["kind"] == "shacl" and out["meta"]:
        try:
            out["body"] = compile_slots(out["meta"], rule_id=out.get("id") or "rule")
        except Exception as exc:  # noqa: BLE001 — surface error in body
            out["body"] = f"# slot-fill compile error: {exc}\n" + (out.get("body") or "")
    if not out.get("id"):
        out["id"] = slugify(out["label"]) or f"rule-{abs(hash(out['body'])) % 10**6}"
    return out


# ── Slot-fill SHACL compiler (suggestion #3) ─────────────────────────────


_OPS = {"=", "!=", ">=", ">", "<=", "<", "regex", "in", "not_null", "exists"}


def compile_slots(meta: dict, *, rule_id: str = "rule") -> str:
    """Compile a slot-fill spec into a SHACL `sh:NodeShape` Turtle
    fragment. The spec shape is::

        {
          "target_class": ":Site",
          "conditions": [
            {"path": ":hosts/:status", "op": "=", "value": "OUTAGE"},
            {"path": ":hasIncident",   "op": "exists"},
          ],
          "assertion": {"path": ":hasIncident", "value": True}
        }

    Operators map to SHACL property-shape constraints:
        =        → sh:hasValue
        !=       → sh:not [ sh:hasValue ... ]
        >=, >    → sh:minInclusive / sh:minExclusive
        <=, <    → sh:maxInclusive / sh:maxExclusive
        regex    → sh:pattern
        in       → sh:in (value must be a list)
        exists   → sh:minCount 1
        not_null → sh:minCount 1

    The compiler validates the structure (raises ValueError on bad ops
    or empty target_class) but stays purely syntactic — it does not
    consult the ontology vocabulary, so callers can compile freely
    before any ontology has been generated.
    """
    target_class = (meta.get("target_class") or "").strip()
    if not target_class:
        raise ValueError("target_class is required")
    conditions = meta.get("conditions") or []
    assertion = meta.get("assertion") or {}
    if not (assertion.get("path") and "value" in assertion):
        raise ValueError("assertion.path and assertion.value are required")

    shape_iri = f":{slugify(rule_id).replace('-', '_')}_shape"
    lines = [
        f"# Slot-fill SHACL rule (rule-id={rule_id})",
        f"{shape_iri}",
        "  a sh:NodeShape ;",
        f"  sh:targetClass {target_class} ;",
    ]

    # ── Conditions → sh:condition blocks (one per condition) ──
    for c in conditions:
        path = (c.get("path") or "").strip()
        op = (c.get("op") or "=").strip()
        if not path:
            raise ValueError("condition.path is required")
        if op not in _OPS:
            raise ValueError(f"unknown operator '{op}' "
                             f"(allowed: {sorted(_OPS)})")
        prop_block = _condition_to_property_shape(path, op, c.get("value"))
        lines.append(f"  sh:condition [ sh:property [ {prop_block} ] ] ;")

    # ── Assertion → sh:rule [ sh:TripleRule ... ] ──
    a_path  = (assertion.get("path") or "").strip()
    a_value = _format_term(assertion.get("value"),
                           assertion.get("value_kind"))
    lines.append("  sh:rule [")
    lines.append("    a sh:TripleRule ;")
    lines.append("    sh:subject sh:this ;")
    lines.append(f"    sh:predicate {a_path} ;")
    lines.append(f"    sh:object {a_value} ;")
    lines.append("  ] .")
    return "\n".join(lines) + "\n"


def _condition_to_property_shape(path: str, op: str, value) -> str:
    """Render the inner constraint that goes inside `sh:property [ ... ]`."""
    parts = [f"sh:path {path}"]
    if op == "=":
        parts.append(f"sh:hasValue {_format_term(value)}")
    elif op == "!=":
        parts.append(f"sh:not [ sh:hasValue {_format_term(value)} ]")
    elif op == ">=":
        parts.append(f"sh:minInclusive {_format_term(value, numeric=True)}")
    elif op == ">":
        parts.append(f"sh:minExclusive {_format_term(value, numeric=True)}")
    elif op == "<=":
        parts.append(f"sh:maxInclusive {_format_term(value, numeric=True)}")
    elif op == "<":
        parts.append(f"sh:maxExclusive {_format_term(value, numeric=True)}")
    elif op == "regex":
        parts.append(f"sh:pattern {_format_string(value)}")
    elif op == "in":
        if not isinstance(value, list):
            raise ValueError("'in' operator requires a list value")
        rendered = " ".join(_format_term(v) for v in value)
        parts.append(f"sh:in ( {rendered} )")
    elif op in ("exists", "not_null"):
        parts.append("sh:minCount 1")
    return " ; ".join(parts)


def _format_term(value, value_kind: str = None, *, numeric: bool = False) -> str:
    """Render a Python value as a Turtle term. Object IRIs come in as
    qnames (`:Foo`) or angle-bracketed full IRIs and are passed through
    verbatim; literals are quoted/typed appropriately.
    """
    if value is None:
        return '""'
    if value_kind == "iri" or _looks_like_iri(value):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if numeric or isinstance(value, (int, float)):
        try:
            return str(value if isinstance(value, (int, float)) else float(value))
        except (TypeError, ValueError):
            pass
    return _format_string(value)


def _format_string(value) -> str:
    """Quote a string literal for Turtle, escaping the few characters
    that matter for a one-line literal."""
    s = "" if value is None else str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def _looks_like_iri(value) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if s.startswith("<") and s.endswith(">"):
        return True
    # qname like ":Foo" or "ex:Bar"; reject things like "1.0" or "a b".
    if re.fullmatch(r"[A-Za-z_][\w-]*?:[A-Za-z_][\w-]*", s):
        return True
    if s.startswith(":") and re.fullmatch(r":[A-Za-z_][\w-]*", s):
        return True
    return False


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


# ── Test-fire preview (suggestion #6) ────────────────────────────────────


@dataclass
class PreviewResult:
    ok: bool
    rule_id: str
    kind: str
    derived: List[Tuple[str, str, str]]
    lineage: List[dict]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    engine_status: str = "PASS"
    duration_ms: int = 0
    abox_path: Optional[str] = None
    derived_count: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "rule_id": self.rule_id, "kind": self.kind,
            "derived": self.derived, "lineage": self.lineage,
            "errors": self.errors, "warnings": self.warnings,
            "engine_status": self.engine_status,
            "duration_ms": self.duration_ms,
            "abox_path": self.abox_path,
            "derived_count": self.derived_count,
        }


def preview_rule(rule: dict, *,
                 ontology_path: Optional[str] = None,
                 abox_path: Optional[str] = None,
                 abox_text: Optional[str] = None) -> PreviewResult:
    """Run a single rule against a small workspace and return the
    derived triples + per-triple lineage.

    Strategy: write the rule's compiled body to the engine-appropriate
    location inside a tempdir, then call ``materializer.materialize`` so
    we reuse Phase B's plumbing (lineage emission, sensitivity audit,
    etc.) instead of re-implementing the engines here.

    Args:
        rule: A rule dict — kind / label / body / meta.
        ontology_path: Path to the asserted ontology (TBox). If absent,
            an empty ontology is used so authors can preview rules
            before generating any TTL.
        abox_path: Optional override for the synthetic ABox file. The
            default is `templates/preview_abox.ttl`.
        abox_text: Inline ABox Turtle (takes precedence over abox_path).
    """
    import tempfile
    import time
    from pathlib import Path as _P

    rule = normalise_rule(rule)
    rule_id = rule["id"]
    kind = rule["kind"]

    res = validate_rule(rule)
    if not res.ok:
        return PreviewResult(
            ok=False, rule_id=rule_id, kind=kind, derived=[],
            lineage=[], errors=res.errors, engine_status="FAIL",
        )

    # Resolve inputs.
    if ontology_path is None or not os.path.isfile(ontology_path):
        # Fall back to a one-line empty ontology so rdflib doesn't trip.
        empty_dir = tempfile.mkdtemp(prefix="rule-preview-empty-")
        ontology_path = os.path.join(empty_dir, "empty.ttl")
        _P(ontology_path).write_text(SHACL_PREFIXES + "\n# (no asserted axioms)\n")

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_abox = os.path.join(here, "templates", "preview_abox.ttl")

    workspace = tempfile.mkdtemp(prefix="rule-preview-")
    abox_resolved: Optional[str] = None
    if abox_text:
        abox_resolved = os.path.join(workspace, "abox.ttl")
        _P(abox_resolved).write_text(abox_text)
    elif abox_path and os.path.isfile(abox_path):
        abox_resolved = abox_path
    elif os.path.isfile(default_abox):
        abox_resolved = default_abox

    # Place the rule artefact where Phase B looks for it.
    extra_ontology: List[str] = []
    shapes_path: Optional[str] = None
    sparql_rules_dir: Optional[str] = None

    if kind == "shacl":
        shapes_dir = os.path.join(workspace, "shapes")
        os.makedirs(shapes_dir, exist_ok=True)
        shapes_path = os.path.join(shapes_dir, "rule.ttl")
        _P(shapes_path).write_text(SHACL_PREFIXES + "\n" + rule["body"])
    elif kind == "sparql":
        sparql_rules_dir = os.path.join(workspace, "sparql_rules")
        os.makedirs(sparql_rules_dir, exist_ok=True)
        _P(os.path.join(sparql_rules_dir, f"{rule_id}.rq")).write_text(rule["body"])
    elif kind == "owl":
        owl_extra = os.path.join(workspace, "owl_axioms.ttl")
        _P(owl_extra).write_text(OWL_PREFIXES + "\n" + rule["body"])
        extra_ontology.append(owl_extra)

    # Run.
    sys_src = os.path.join(here, "src")
    if sys_src not in os.sys.path:
        os.sys.path.insert(0, sys_src)
    from materializer import materialize  # late import — keeps module light

    out_dir = os.path.join(workspace, "out")
    os.makedirs(out_dir, exist_ok=True)
    started = time.perf_counter()
    result = materialize(
        ontology_path, out_dir,
        shapes_path=shapes_path,
        data_graph_paths=[abox_resolved] if abox_resolved else [],
        sparql_rules_dir=sparql_rules_dir,
        extra_ontology_paths=extra_ontology,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)

    # Pick the engine that ran this rule.
    engine_name = {"shacl": "shacl", "sparql": "sparql", "owl": "owl-rl"}.get(kind, "owl-rl")
    engine = next((e for e in result.engines if e.name == engine_name), None)
    if engine is None:
        return PreviewResult(
            ok=False, rule_id=rule_id, kind=kind, derived=[], lineage=[],
            errors=[f"engine '{engine_name}' missing from materializer result"],
            engine_status="FAIL", duration_ms=duration_ms, abox_path=abox_resolved,
        )

    derived: List[Tuple[str, str, str]] = []
    lineage: List[dict] = []
    for rec in engine.lineage:
        s, p, o = rec.triple
        derived.append((str(s), str(p), str(o)))
        lineage.append({
            "subject": str(s), "predicate": str(p), "object": str(o),
            "rule": rec.rule_id, "engine": rec.engine,
            "bindings": rec.bindings,
            "premises": [[str(a), str(b), str(c)] for a, b, c in rec.premises],
        })

    return PreviewResult(
        ok=engine.status != "FAIL",
        rule_id=rule_id,
        kind=kind,
        derived=derived,
        lineage=lineage,
        errors=[engine.message] if engine.status == "FAIL" else [],
        warnings=[engine.message] if engine.status == "PASS" and not derived else [],
        engine_status=engine.status,
        duration_ms=duration_ms,
        abox_path=abox_resolved,
        derived_count=len(derived),
    )


# ── Rule-impact coverage (suggestion #7) ─────────────────────────────────


def compute_coverage(rules: Sequence[dict], vocabulary: dict) -> dict:
    """For each class in ``vocabulary``, count which rules touch it.

    A rule "touches" a class when:
      • its slot-fill ``meta.target_class`` matches the class qname, or
      • its rendered body text contains the qname as a whole token.

    Returns::

        {
          ":Site": {
              "qname": ":Site",
              "label": "Site",
              "count": 3,
              "rule_ids": ["site-impact", "..."],
              "details": {
                  "by_target": ["site-impact"],
                  "by_body":   ["transitive-rollup", "..."],
              }
          },
          ...
        }

    Classes with zero rules are still present in the dict so the UI can
    render them in the cool end of the heat ramp.
    """
    classes = vocabulary.get("classes") or []
    rules = [normalise_rule(r) for r in (rules or [])]

    out: dict = {}
    for c in classes:
        qname = c.get("qname")
        if not qname:
            continue
        out[qname] = {
            "qname": qname,
            "label": c.get("label"),
            "count": 0,
            "rule_ids": [],
            "details": {"by_target": [], "by_body": []},
        }

    # Token-boundary matcher per qname so `:Site` doesn't get matched
    # inside `:SiteCategory`. We anchor on the qname's last char being
    # followed by a non-IRI character.
    import re as _re

    def _hits(body: str, qname: str) -> bool:
        # Escape the qname for regex; require a trailing boundary so
        # `:Site` doesn't match inside `:SiteCategory`.
        if not body:
            return False
        pattern = _re.escape(qname) + r"(?![A-Za-z0-9_-])"
        return _re.search(pattern, body) is not None

    for rule in rules:
        rid = rule["id"]
        body = rule.get("body") or ""
        target = (rule.get("meta") or {}).get("target_class") or ""
        for qname, entry in out.items():
            counted = False
            if target and target == qname:
                entry["details"]["by_target"].append(rid)
                counted = True
            if _hits(body, qname):
                entry["details"]["by_body"].append(rid)
                counted = True
            if counted and rid not in entry["rule_ids"]:
                entry["rule_ids"].append(rid)
                entry["count"] += 1
    return out


__all__ = [
    "PreviewResult",
    "ValidationResult",
    "compile_slots",
    "compute_coverage",
    "export_rules",
    "load_starter_library",
    "normalise_rule",
    "preview_rule",
    "slugify",
    "validate_rule",
    "validate_rules",
]
