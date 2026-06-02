"""
wizard/cq_translator.py — T3.3
──────────────────────────────
CQ → SPARQL auto-translation + zero-hit detection.

Competency questions land in the wizard as free text — *"What
customers placed orders in the last week?"* — and never get
tested against the actual ontology. That's a sharp gap: the
toolkit's whole pitch is "every claim is auditable", but the
domain-vocabulary contract (the CQs) sits unchecked.

T3.3 closes the loop:

  1. **Translate.** An LLM (via :mod:`wizard.proposal_namer`'s
     provider abstraction — same infrastructure as T1.1) sees
     the CQ + a *constrained* description of the ontology (class
     and property qnames only — no values, no raw data). It
     emits a SPARQL ``SELECT`` query.
  2. **Validate.** The query parses via rdflib; if syntax errors
     surface, the row is marked ``SYNTAX_ERROR``. If parsing
     succeeds we run it against the test corpus (the ontology
     itself, optionally augmented with sample instances). The
     run's row count becomes ``n_hits``.
  3. **Surface.** A CQ that yields zero hits is either a wrong
     question or a missing concept; the wizard's Step 5 surface
     renders it amber. The reviewer either edits the CQ or
     promotes a placeholder to a real class.

Design contract
───────────────
- LLMs only at the translation layer. The validation step is
  pure rdflib — no LLM in the loop once the SPARQL exists.
- Provider-abstracted via :mod:`wizard.proposal_namer.get_provider`.
  Same ``PROPOSAL_NAMER_PROVIDER`` env var as T1.1.
- Idempotent: same CQ + same ontology version → cached translation.

Public API
──────────
    result = translate_one(cq_text, ontology_path)
    out    = translate_all_competency_questions(conn, ontology_path)
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ── Result shape ─────────────────────────────────────────────────────────


@dataclass
class CqTranslationResult:
    cq_id:             str
    cq_text:           str
    sparql_query:      str
    source:            str = "mock"
    validation_status: str = "PENDING"
    n_hits:            int = 0
    error_message:     str = ""
    ontology_version:  Optional[str] = None
    generated_at:      Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cq_id":             self.cq_id,
            "cq_text":           self.cq_text,
            "sparql_query":      self.sparql_query,
            "source":            self.source,
            "validation_status": self.validation_status,
            "n_hits":            self.n_hits,
            "error_message":     self.error_message,
            "ontology_version":  self.ontology_version,
            "generated_at":      self.generated_at,
        }


@dataclass
class CqRunReport:
    translated:   int = 0
    cached:       int = 0
    failed:       int = 0
    zero_hits:    int = 0
    duration_s:   float = 0.0
    results:      List[CqTranslationResult] = field(default_factory=list)


# ── Ontology context extraction (privacy-preserving) ─────────────────────


def extract_ontology_context(ontology_path: str,
                             *, max_classes: int = 50,
                             max_properties: int = 50) -> Dict[str, Any]:
    """Pull the class + property qname lists from the ontology. We
    pass these to the LLM as *constraints* — the model knows the
    vocabulary it must reference. NO instance data, NO labels with
    PII risk, NO comments — pure schema.

    Returns ``{"classes": [...], "properties": [...], "prefixes": {...}}``.
    """
    out = {"classes": [], "properties": [], "prefixes": {}}
    try:
        import rdflib
    except ImportError:
        return out
    g = rdflib.Graph()
    try:
        g.parse(ontology_path,
                format="turtle" if ontology_path.endswith(".ttl") else None)
    except Exception:                                          # noqa: BLE001
        return out
    OWL = rdflib.namespace.OWL
    RDF = rdflib.namespace.RDF
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, rdflib.URIRef):
            out["classes"].append(_qname(s, g))
    for pt in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for s in g.subjects(RDF.type, pt):
            if isinstance(s, rdflib.URIRef):
                out["properties"].append(_qname(s, g))
    out["classes"] = sorted(set(out["classes"]))[:max_classes]
    out["properties"] = sorted(set(out["properties"]))[:max_properties]
    # Only include prefixes whose namespace is actually referenced
    # by an emitted qname — keeps the LLM prompt focused and the
    # mock-template SPARQL minimal.
    used_prefixes = set()
    for q in out["classes"] + out["properties"]:
        if ":" in q and not q.startswith("<"):
            used_prefixes.add(q.split(":", 1)[0])
    out["prefixes"] = {p: str(ns) for p, ns in g.namespaces()
                       if p in used_prefixes}
    return out


def _qname(uri, g) -> str:
    """qname for a URIRef. Returns ``prefix:local`` when a binding
    exists (including the empty ``:`` prefix that anchors most
    domain ontologies); falls back to a wrapped ``<full_iri>`` so
    the result is always valid SPARQL syntax."""
    try:
        prefix, _, local = g.compute_qname(uri, generate=False)
        if local:
            return f"{prefix}:{local}"
    except Exception:                                          # noqa: BLE001
        pass
    return f"<{uri}>"


# ── Prompt + parsing ────────────────────────────────────────────────────


_PROMPT_TEMPLATE = """You are translating a competency question (CQ) into a SPARQL SELECT query.

The ontology you can reference uses these prefixes and classes / properties:

Prefixes:
{prefixes}

Classes:
{classes}

Properties:
{properties}

Competency question:
{cq}

Produce ONE SPARQL SELECT query that answers the CQ. Rules:
- Reference only classes / properties from the lists above.
- Use the prefixes declared above; declare any others you need at the top of the query.
- Return only the SELECT query (no preamble, no explanation).
- Prefer simple patterns over OPTIONAL / FILTER unless the CQ explicitly requires them.

Output ONLY the SPARQL SELECT query, nothing else.
"""


def _format_prompt(cq: str, ctx: Dict[str, Any]) -> str:
    prefix_lines = "\n".join(
        f"PREFIX {p}: <{ns}>" for p, ns in (ctx.get("prefixes") or {}).items()
        if p
    ) or "(no prefixes declared)"
    return _PROMPT_TEMPLATE.format(
        prefixes=prefix_lines,
        classes="\n".join(f"- {c}" for c in (ctx.get("classes") or []))
                 or "(none)",
        properties="\n".join(f"- {p}" for p in (ctx.get("properties") or []))
                   or "(none)",
        cq=cq,
    )


_SPARQL_FENCE = re.compile(r"```(?:sparql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_SELECT_RE = re.compile(r"\b(PREFIX\b[\s\S]*?)?SELECT\b[\s\S]+",
                         re.IGNORECASE)


def _extract_sparql(raw: str) -> str:
    """Pull the SPARQL out of an LLM response — tolerant of code
    fences, preambles, and trailing chatter."""
    if not raw:
        return ""
    m = _SPARQL_FENCE.search(raw)
    if m:
        return m.group(1).strip()
    m = _SELECT_RE.search(raw)
    if m:
        return m.group(0).strip()
    return raw.strip()


# ── Mock-friendly template (used when no LLM provider is set) ───────────


def _mock_sparql_for(cq: str, ctx: Dict[str, Any]) -> str:
    """Deterministic template SPARQL — useful for tests and as a
    no-provider fallback. Tries to pull a single class name out of
    the CQ to anchor the query.

    The query is prefixed with every namespace from the ontology
    so rdflib can resolve every qname it might reference."""
    classes = list(ctx.get("classes") or [])
    cls = classes[0] if classes else ":Thing"
    cq_lower = (cq or "").lower()
    for c in classes:
        local = c.split(":")[-1].lower()
        if local and local in cq_lower:
            cls = c
            break
    prefix_lines = "\n".join(
        f"PREFIX {p}: <{ns}>"
        for p, ns in (ctx.get("prefixes") or {}).items()
        if p
    )
    return (
        (prefix_lines + "\n" if prefix_lines else "")
        + "SELECT ?x WHERE {\n"
        + f"  ?x a {cls} .\n"
        + "}"
    )


# ── Translation ─────────────────────────────────────────────────────────


def translate_one(cq_text: str,
                  ontology_path: str,
                  *,
                  cq_id: str = "",
                  provider=None,
                  ontology_version: Optional[str] = None,
                  ) -> CqTranslationResult:
    """Generate + validate one CQ → SPARQL translation.

    ``provider`` is an :class:`wizard.proposal_namer.LLMProvider`
    or None. When None we fall back to the deterministic template
    SPARQL — useful for tests and as a no-provider mode."""
    ctx = extract_ontology_context(ontology_path)
    sparql = ""
    source = "mock"
    if provider is None:
        sparql = _mock_sparql_for(cq_text, ctx)
    else:
        prompt = _format_prompt(cq_text, ctx)
        try:
            raw = provider.complete(prompt, max_tokens=400, temperature=0.1)
            sparql = _extract_sparql(raw)
            source = provider.name
        except Exception as exc:                               # noqa: BLE001
            return CqTranslationResult(
                cq_id=cq_id, cq_text=cq_text, sparql_query="",
                source="error", validation_status="SYNTAX_ERROR",
                n_hits=0, error_message=str(exc),
                ontology_version=ontology_version,
                generated_at=_now_iso(),
            )

    return validate_translation(
        cq_id=cq_id, cq_text=cq_text, sparql=sparql, source=source,
        ontology_path=ontology_path,
        ontology_version=ontology_version,
    )


def validate_translation(*, cq_id: str, cq_text: str, sparql: str,
                         source: str, ontology_path: str,
                         ontology_version: Optional[str] = None,
                         test_data_path: Optional[str] = None,
                         ) -> CqTranslationResult:
    """Parse + run the SPARQL. Returns a populated result with
    ``validation_status`` set."""
    result = CqTranslationResult(
        cq_id=cq_id, cq_text=cq_text, sparql_query=sparql,
        source=source, ontology_version=ontology_version,
        generated_at=_now_iso(),
    )
    if not sparql:
        result.validation_status = "SYNTAX_ERROR"
        result.error_message = "empty SPARQL"
        return result
    try:
        import rdflib
    except ImportError:
        result.validation_status = "PENDING"
        result.error_message = "rdflib not installed"
        return result
    g = rdflib.Graph()
    try:
        g.parse(ontology_path,
                format="turtle" if ontology_path.endswith(".ttl") else None)
    except Exception as exc:                                   # noqa: BLE001
        result.validation_status = "SYNTAX_ERROR"
        result.error_message = f"ontology parse: {exc}"
        return result
    if test_data_path:
        try:
            g.parse(test_data_path,
                    format="turtle" if test_data_path.endswith(".ttl") else None)
        except Exception:                                      # noqa: BLE001
            pass  # missing/optional test data
    try:
        qres = g.query(sparql)
    except Exception as exc:                                   # noqa: BLE001
        result.validation_status = "SYNTAX_ERROR"
        result.error_message = str(exc)[:300]
        return result
    rows = list(qres)
    result.n_hits = len(rows)
    result.validation_status = "OK" if rows else "ZERO_HITS"
    return result


# ── Bulk translation ────────────────────────────────────────────────────


def translate_all_competency_questions(conn: sqlite3.Connection,
                                       ontology_path: str,
                                       cqs: Sequence[Dict[str, str]],
                                       *,
                                       provider=None,
                                       ontology_version: Optional[str] = None,
                                       force: bool = False,
                                       ) -> CqRunReport:
    """Translate every CQ in ``cqs``. Each entry is
    ``{"id": "CQ-01", "question": "..."}`` — same shape the wizard
    session uses. Idempotent: caches by ``(cq_id, ontology_version)``
    unless ``force=True``."""
    _ensure_schema(conn)
    report = CqRunReport()
    t0 = time.perf_counter()
    for cq in cqs:
        cq_id   = str(cq.get("id") or "")
        cq_text = str(cq.get("question") or "")
        if not cq_id or not cq_text:
            continue
        cached = _load_cached(conn, cq_id, ontology_version)
        if cached is not None and not force:
            report.cached += 1
            report.results.append(cached)
            continue
        result = translate_one(
            cq_text, ontology_path,
            cq_id=cq_id, provider=provider,
            ontology_version=ontology_version,
        )
        _persist(conn, result)
        if result.validation_status == "OK":
            report.translated += 1
        elif result.validation_status == "ZERO_HITS":
            report.zero_hits += 1
            report.translated += 1   # we still produced a query
        else:
            report.failed += 1
        report.results.append(result)
    report.duration_s = time.perf_counter() - t0
    return report


def _persist(conn: sqlite3.Connection,
             result: CqTranslationResult) -> None:
    conn.execute(
        "INSERT INTO cq_translations "
        "(cq_id, cq_text, sparql_query, source, validation_status, "
        " n_hits, error_message, ontology_version, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(cq_id, ontology_version) DO UPDATE SET "
        "  cq_text = excluded.cq_text, "
        "  sparql_query = excluded.sparql_query, "
        "  source = excluded.source, "
        "  validation_status = excluded.validation_status, "
        "  n_hits = excluded.n_hits, "
        "  error_message = excluded.error_message, "
        "  generated_at = excluded.generated_at",
        (result.cq_id, result.cq_text, result.sparql_query,
         result.source, result.validation_status, result.n_hits,
         result.error_message, result.ontology_version,
         result.generated_at),
    )
    conn.commit()


def _load_cached(conn: sqlite3.Connection, cq_id: str,
                 ontology_version: Optional[str],
                 ) -> Optional[CqTranslationResult]:
    row = conn.execute(
        "SELECT cq_text, sparql_query, source, validation_status, "
        "       n_hits, error_message, ontology_version, generated_at "
        "FROM cq_translations "
        "WHERE cq_id = ? AND COALESCE(ontology_version, '') = COALESCE(?, '')",
        (cq_id, ontology_version),
    ).fetchone()
    if not row:
        return None
    return CqTranslationResult(
        cq_id=cq_id, cq_text=row[0] or "", sparql_query=row[1] or "",
        source=row[2] or "mock", validation_status=row[3] or "PENDING",
        n_hits=int(row[4] or 0), error_message=row[5] or "",
        ontology_version=row[6], generated_at=row[7],
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='cq_translations'"
    ).fetchone() is None:
        from db.migrations.v3_cq_translations import migrate
        migrate(conn)


# ── Coverage analysis ──────────────────────────────────────────────────


@dataclass
class CqCoverageReport:
    """Which ontology classes / properties does each CQ exercise?

    The list of classes referenced by no CQ at all is the natural
    'dead vocabulary' indicator the roadmap §3.T3.3 talks about.
    """
    coverage:          Dict[str, List[str]] = field(default_factory=dict)
    unused_classes:    List[str] = field(default_factory=list)
    unused_properties: List[str] = field(default_factory=list)
    n_cqs:             int = 0


def analyse_coverage(results: Sequence[CqTranslationResult],
                     ontology_path: str) -> CqCoverageReport:
    """Walk each result's SPARQL; collect class / property tokens;
    invert to per-CQ coverage; report unused vocabulary."""
    ctx = extract_ontology_context(ontology_path)
    all_classes = set(ctx.get("classes") or [])
    all_props   = set(ctx.get("properties") or [])
    coverage: Dict[str, List[str]] = {}
    seen_classes: set = set()
    seen_props:   set = set()
    for r in results:
        refs: List[str] = []
        body = r.sparql_query or ""
        for c in all_classes:
            if c and c in body:
                refs.append(c)
                seen_classes.add(c)
        for p in all_props:
            if p and p in body:
                refs.append(p)
                seen_props.add(p)
        coverage[r.cq_id] = sorted(set(refs))
    return CqCoverageReport(
        coverage=coverage,
        unused_classes=sorted(all_classes - seen_classes),
        unused_properties=sorted(all_props - seen_props),
        n_cqs=len(results),
    )


# ── Helpers ─────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="seconds",
    )


__all__ = [
    "CqTranslationResult", "CqRunReport", "CqCoverageReport",
    "extract_ontology_context", "translate_one",
    "validate_translation", "translate_all_competency_questions",
    "analyse_coverage",
]
