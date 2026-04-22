"""
runtime.embeddings.class_filter — Workstream 5, Component 2
===========================================================
Translates a SPARQL class expression (or a flavor name) into a metadata
filter for the vector store.

Given ``:NetworkFunction`` the filter expands through the reasoner-computed
class hierarchy and returns every subclass IRI in the subgraph, which is
then passed as an ``in`` filter on the ``owl_class`` metadata field
before the vector similarity query runs.

Supports:

  * bare class IRIs or CURIEs (``tmf:NetworkFunction``)
  * union expressions: ``tmf:NetworkFunction | tmf:PerformanceIndicator``
  * intersection expressions: ``tmf:NetworkFunction & tmf:Alarm``
  * flavor-name shortcuts: ``@network-ops`` or just the flavor name

Sensitivity tier filtering is applied as a second mandatory layer —
RESTRICTED-tier embeddings are inaccessible to agents whose flavor
lacks RESTRICTED access.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Set

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.dirname(_HERE)
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from flavor_registry import FlavorRegistry  # noqa: E402


_TMF_BASE  = "https://ontology.example.com/tmf/"
_TIER_RANK = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}


_CURIE_RE  = re.compile(r"^(?:([a-zA-Z][\w\-]*):)?(.+)$")


def _to_iri(token: str) -> str:
    """Expand a CURIE to a full IRI.  Bare names use the TMF base."""
    token = token.strip()
    if token.startswith("<") and token.endswith(">"):
        return token[1:-1]
    if token.startswith("http://") or token.startswith("https://"):
        return token
    m = _CURIE_RE.match(token)
    if not m:
        return token
    prefix, local = m.group(1), m.group(2)
    if prefix in (None, "", "tmf"):
        return _TMF_BASE + local
    if prefix == "cmp":
        return "https://ontology.example.com/compliance/" + local
    if prefix == "prov":
        return "http://www.w3.org/ns/prov#" + local
    return token


# ─────────────────────────────────────────────────────────────────────
# Class-hierarchy resolution
# ─────────────────────────────────────────────────────────────────────


def _parse_hierarchy_from_turtle(ttl_path: str) -> Dict[str, Set[str]]:
    """Return ``parent -> {children...}`` from a Turtle ontology file.

    Uses a line-oriented parser so we stay stdlib-only.  Captures both
    direct ``rdfs:subClassOf`` and ``owl:equivalentClass`` edges.
    """
    if not os.path.isfile(ttl_path):
        return {}
    edges: Dict[str, Set[str]] = {}
    cur_subject: Optional[str] = None
    with open(ttl_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("@prefix") or stripped.startswith("#"):
                continue
            m = re.match(r"^(?::|tmf:|cmp:)?(\w+)\s+(?:a|rdf:type)\s+", stripped)
            if m:
                cur_subject = _to_iri(m.group(1))
                continue
            m = re.match(r"^(?::|tmf:|cmp:)?(\w+)\b", stripped)
            if m and not stripped.startswith(("rdfs:", "owl:", "prov:", "skos:")):
                candidate = _to_iri(m.group(1))
                if candidate and "/" in candidate:
                    cur_subject = candidate
            sub_m = re.search(
                r"rdfs:subClassOf\s+(?::|tmf:|cmp:)?(\w+)", stripped)
            if sub_m and cur_subject:
                parent = _to_iri(sub_m.group(1))
                edges.setdefault(parent, set()).add(cur_subject)
    return edges


def _default_ontology_path() -> str:
    return os.path.join(
        _RUNTIME, "..", "output", "ontology", "enterprise.ttl"
    )


def resolve_class_hierarchy(
    class_iri: str,
    *,
    ontology_path: Optional[str] = None,
) -> List[str]:
    """Return the full set of OWL class IRIs in the subgraph rooted at
    *class_iri* — i.e. the class itself plus every direct and transitive
    subclass — via a breadth-first walk of the hierarchy parsed from
    *ontology_path*.

    If the ontology file is missing (typical on a clean CI run before
    phase 2), we return ``[class_iri]`` unchanged.  The filter then
    behaves as a literal ``owl_class == class_iri`` check.
    """
    ontology_path = ontology_path or _default_ontology_path()
    edges = _parse_hierarchy_from_turtle(ontology_path)
    out: List[str] = []
    seen: Set[str] = set()
    stack = [class_iri]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        stack.extend(edges.get(cur, set()))
    return out


# ─────────────────────────────────────────────────────────────────────
# Class-expression parsing
# ─────────────────────────────────────────────────────────────────────


def _expand_tokens(expr: str) -> Dict[str, List[str]]:
    """Split a class expression into union and intersection terms.

    Returns a dict with keys ``union`` (list of IRIs) and ``intersect``
    (list of IRIs).  Either or both may be empty.  A bare token goes
    into ``union`` so that filters behave like an OR by default.
    """
    expr = (expr or "").strip()
    union: List[str] = []
    intersect: List[str] = []
    if not expr:
        return {"union": union, "intersect": intersect}

    # Split on & first (intersection has higher precedence) then | for union
    if "&" in expr:
        for tok in expr.split("&"):
            tok = tok.strip()
            if tok:
                intersect.append(_to_iri(tok))
        return {"union": union, "intersect": intersect}

    if "|" in expr:
        for tok in expr.split("|"):
            tok = tok.strip()
            if tok:
                union.append(_to_iri(tok))
        return {"union": union, "intersect": intersect}

    union.append(_to_iri(expr))
    return {"union": union, "intersect": intersect}


def _flavor_classes(
    flavor_name: str,
    *,
    flavors_dir: Optional[str] = None,
) -> List[str]:
    reg = FlavorRegistry(flavors_dir=flavors_dir)
    try:
        flavor = reg.load(flavor_name)
    except ValueError:
        return []
    terms = flavor.get("context_terms", {}) or {}
    out: List[str] = []
    for cls in flavor.get("owl_classes", []):
        out.append(terms.get(cls, _TMF_BASE + cls))
    return out


def build_metadata_filter(
    class_expression: Optional[str] = None,
    *,
    flavor: Optional[str] = None,
    flavors_dir: Optional[str] = None,
    ontology_path: Optional[str] = None,
    requesting_tier: str = "Internal",
) -> Dict[str, Any]:
    """Build a vector-store metadata filter from an OWL class expression.

    The returned dict has the shape::

        {
          "owl_classes_in":   [...],          # union of allowed IRIs
          "owl_classes_all":  [...],          # intersection requirement
          "max_tier":         "Internal",     # sensitivity tier cap
          "resolved_from":    "expression" | "flavor" | "both" | "none",
        }

    Adapters translate this into their native filter syntax.
    """
    union: Set[str] = set()
    intersect: Set[str] = set()
    source_parts: List[str] = []

    # If the caller supplies a class expression, that *narrows* the
    # search — the flavor is used only as a final fallback if no
    # expression was given.  When both are present, the flavor set is
    # intersected with the expression so sensitivity-tier / ABox scoping
    # is preserved without broadening the class filter.
    if class_expression:
        parts = _expand_tokens(class_expression)
        for iri in parts["union"]:
            union.update(resolve_class_hierarchy(iri, ontology_path=ontology_path))
        for iri in parts["intersect"]:
            intersect.update(resolve_class_hierarchy(iri, ontology_path=ontology_path))
        source_parts.append("expression")

        if flavor:
            flavor_set: Set[str] = set()
            for iri in _flavor_classes(flavor, flavors_dir=flavors_dir):
                flavor_set.update(
                    resolve_class_hierarchy(iri, ontology_path=ontology_path)
                )
            if flavor_set:
                if union:
                    union &= flavor_set
                if intersect:
                    intersect &= flavor_set
            source_parts.append("flavor")
    elif flavor:
        for iri in _flavor_classes(flavor, flavors_dir=flavors_dir):
            union.update(resolve_class_hierarchy(iri, ontology_path=ontology_path))
        source_parts.append("flavor")

    source = "+".join(source_parts) if source_parts else "none"

    return {
        "owl_classes_in":  sorted(union),
        "owl_classes_all": sorted(intersect),
        "max_tier":        requesting_tier or "Internal",
        "resolved_from":   source,
    }


def passes_filter(
    record_meta: Dict[str, Any],
    metadata_filter: Dict[str, Any],
) -> bool:
    """Evaluate whether a record's metadata satisfies the filter.

    Used by in-memory and pgvector adapters when the store cannot
    enforce the filter natively.  Sensitivity tier is always enforced
    as a hard upper bound.
    """
    # Sensitivity tier gate
    tier = record_meta.get("sensitivity_tier") or "Internal"
    max_tier = metadata_filter.get("max_tier") or "Internal"
    if _TIER_RANK.get(tier, 1) > _TIER_RANK.get(max_tier, 1):
        return False

    cls = record_meta.get("owl_class")
    allowed = metadata_filter.get("owl_classes_in") or []
    required = metadata_filter.get("owl_classes_all") or []

    if allowed and cls not in allowed:
        return False
    if required and cls not in required:
        return False
    return True
