"""
wizard.importer — file-import pipeline (issue #16, step 1: JSON only).

Public entry point:

    parse_and_validate(raw_bytes: bytes, *,
                       fmt: str = "auto",
                       dialect: str = "auto",
                       existing_session: dict | None = None,
                       filename: str | None = None) -> ImportResult

Returns a structured response the wizard renders in its review modal:

    {
      "session":     <normalized wizard-session dict>,
      "errors":      [...]   # blocking — user must fix the file
      "warnings":    [...]   # advisory — user can accept and move on
      "suggestions": [...]   # opt-in fixes (sensitivity tiers, soft-FKs, …)
      "stats":       {entities, events, relationships, cqs,
                      comment_coverage, ...}
      "diff":        {added, replaced, removed}    # vs existing session
      "format":      "json-wizard" | "json-cli" | "json-schema" | "sql"
    }

Step 1 supports JSON in three shapes:

  1. wizard-session  — what /api/session POSTs / what /api/template returns
                       (top-level `domain` + `entities` + `events` + `relationships`
                        + `competency_questions`)
  2. cli-session     — what onboard.py writes to projects/<slug>/session.json
                       (top-level `domain_name` + `entities` + `relationships` + `cqs`,
                        with entity records carrying `is_event`)
  3. schema          — a thin {tables: [...]} shape for users coming from data
                       catalogs / dbt / OpenAPI — currently parsed best-effort

SQL parsing (sqlglot) lands in step 3 of the issue; this file leaves the
hooks in place but raises NotImplementedError until then.

Validation tiers (consistent across both JSON and SQL paths):

  errors      — blocking. `Result.ok` is False; UI cannot Accept.
  warnings    — advisory. `Result.ok` is True but UI should surface them.
  suggestions — opt-in. UI shows them as checkbox list, user picks.

No bytes are persisted by this module — the route in wizard/app.py decides
when to write the normalized session to disk (only on user Accept).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ── Heuristic config ──────────────────────────────────────────────────────

#: Substrings that bump a column / entity into Confidential when it has
#: no explicit sensitivity tier set. Conservative — false positives are
#: just suggestions the user can reject in the review modal.
PII_HINTS_CONFIDENTIAL = (
    "email", "phone", "mobile", "address", "dob", "birth", "ssn",
    "social", "passport", "national_id", "license", "tax_id",
    "credit_card", "iban", "bic", "account_number",
    "patient", "diagnosis", "medication",
    "salary", "income", "compensation",
    "geolocation", "lat_long", "ip_address",
)

#: Stronger signals that warrant Restricted (rather than Confidential).
PII_HINTS_RESTRICTED = (
    "password", "secret", "private_key", "api_key", "token", "session_key",
    "card_cvv", "cvv2", "pin",
)

#: Naming patterns that suggest an entity is event-shaped. Conservative
#: by design — false positives would silently move common-domain entities
#: (Transaction, Ticket, …) into the Events bucket. We only fire on:
#:   - clear suffix forms (`_log`, `_audit`, `_history`, …) — strong signal;
#:   - words that are nouns-of-occurrence in any domain (`event`, `incident`,
#:     `alarm`, `alert`) — fire even bare.
EVENT_NAME_HINTS = (
    "_event", "_events",
    "_log", "_logs",
    "_history",
    "_audit", "_audits",
    "_journal",
    "event", "incident", "alarm", "alert",
)

#: IRI-unsafe characters in entity / relationship identifiers. Names are
#: required to be safely embeddable in the generated OWL IRI.
IRI_UNSAFE = re.compile(r"[\s<>\"'`{}|\\^\[\]]")


# ── SQL → XSD data-type map ───────────────────────────────────────────────
# Keys are upper-case sqlglot DataType.Type names. The mapping is
# deliberately coarse — the goal is "good enough that the toolkit can
# pick a sensible OWL/XSD restriction"; downstream code can refine.

SQL_TO_XSD: Dict[str, str] = {
    # numeric
    "TINYINT":   "xsd:integer",  "SMALLINT": "xsd:integer",
    "INT":       "xsd:integer",  "INTEGER":  "xsd:integer",
    "BIGINT":    "xsd:integer",  "MEDIUMINT": "xsd:integer",
    "DECIMAL":   "xsd:decimal",  "NUMERIC":  "xsd:decimal",
    "FLOAT":     "xsd:float",    "DOUBLE":   "xsd:double",
    "REAL":      "xsd:double",
    "MONEY":     "xsd:decimal",  "SMALLMONEY": "xsd:decimal",
    # text
    "CHAR":      "xsd:string",   "NCHAR":    "xsd:string",
    "VARCHAR":   "xsd:string",   "NVARCHAR": "xsd:string",
    "TEXT":      "xsd:string",   "NTEXT":    "xsd:string",
    "CLOB":      "xsd:string",   "LONGTEXT": "xsd:string",
    "MEDIUMTEXT":"xsd:string",   "TINYTEXT": "xsd:string",
    "VARCHAR2":  "xsd:string",                          # Oracle
    "ENUM":      "xsd:string",
    "UUID":      "xsd:string",
    # temporal
    "DATE":      "xsd:date",
    "TIME":      "xsd:time",
    "TIMESTAMP": "xsd:dateTime",
    "DATETIME":  "xsd:dateTime", "DATETIME2": "xsd:dateTime",
    "DATETIMEOFFSET": "xsd:dateTime",
    "TIMESTAMPTZ":    "xsd:dateTime",
    "INTERVAL":  "xsd:duration",
    # boolean
    "BOOLEAN":   "xsd:boolean",
    "BOOL":      "xsd:boolean",
    "BIT":       "xsd:boolean",
    # binary / json / spatial
    "BINARY":    "xsd:base64Binary", "VARBINARY": "xsd:base64Binary",
    "BLOB":      "xsd:base64Binary", "BYTEA":    "xsd:base64Binary",
    "JSON":      "rdf:JSON",         "JSONB":    "rdf:JSON",
    "GEOMETRY":  "geo:wktLiteral",   "GEOGRAPHY": "geo:wktLiteral",
}


# ── Dialect sniff ─────────────────────────────────────────────────────────

def _detect_sql_dialect(raw_text: str) -> str:
    """Return a sqlglot-recognised dialect name from content cues, or "" for default."""
    head = raw_text[:8192].upper()
    if "JSONB" in head or "SERIAL " in head or "BIGSERIAL" in head:
        return "postgres"
    if "AUTO_INCREMENT" in head or "ENGINE=" in head or "TINYINT(" in head:
        return "mysql"
    if "NVARCHAR" in head or "IDENTITY(" in head or "[dbo]" in head.lower():
        return "tsql"            # SQL Server
    if "VARCHAR2" in head or "NUMBER(" in head or "NOCYCLE" in head:
        return "oracle"
    if "PRAGMA " in head or "AUTOINCREMENT" in head:
        return "sqlite"
    return ""                    # let sqlglot use its default


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class Issue:
    """A single error / warning / suggestion entry."""
    code: str             # short machine code, e.g. "ORPHAN_ENTITY"
    message: str          # human-readable
    location: Optional[str] = None    # e.g. "entities[3]" or "tables.orders.col 4"
    fix_hint: Optional[str] = None
    severity: str = "warning"         # error | warning | suggestion

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportResult:
    session: Dict[str, Any] = field(default_factory=dict)
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    suggestions: List[Issue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    diff: Dict[str, Any] = field(default_factory=dict)
    format: str = "unknown"

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "session":     self.session,
            "errors":      [i.to_dict() for i in self.errors],
            "warnings":    [i.to_dict() for i in self.warnings],
            "suggestions": [i.to_dict() for i in self.suggestions],
            "stats":       self.stats,
            "diff":        self.diff,
            "format":      self.format,
            "ok":          self.ok,
        }


# ── Format detection ──────────────────────────────────────────────────────

def _detect_format(raw: bytes, fmt_hint: str, filename: Optional[str]) -> str:
    """Resolve fmt='auto' → 'json' | 'sql' using filename then content."""
    if fmt_hint and fmt_hint != "auto":
        return fmt_hint.lower()
    if filename:
        low = filename.lower()
        if low.endswith(".json"):
            return "json"
        if low.endswith((".sql", ".ddl")):
            return "sql"
    # Content sniff — JSON files start with { or [ after whitespace.
    head = raw.lstrip()[:1]
    if head in (b"{", b"["):
        return "json"
    if re.search(rb"(?i)\bcreate\s+table\b", raw[:2048]):
        return "sql"
    return "json"  # default — JSON is the more forgiving parser


# ── JSON shape detection ──────────────────────────────────────────────────

def _detect_json_shape(doc: dict) -> str:
    """Pick which of the three JSON shapes we received."""
    if "tables" in doc and isinstance(doc["tables"], list):
        return "json-schema"
    if "domain" in doc and isinstance(doc["domain"], dict):
        return "json-wizard"
    if "domain_name" in doc:
        return "json-cli"
    # Fall through — treat as wizard shape with empty domain
    return "json-wizard"


# ── Normalisers — each shape → wizard session shape ──────────────────────

def _empty_wizard_session() -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "domain": {}, "entities": [], "events": [],
        "relationships": [], "competency_questions": [],
        "created_at": now, "updated_at": now,
    }


def _norm_wizard(doc: dict) -> Dict[str, Any]:
    """Already in wizard shape — defensive copy + fill defaults."""
    out = _empty_wizard_session()
    out["domain"] = dict(doc.get("domain") or {})
    out["entities"] = [dict(e) for e in (doc.get("entities") or [])]
    out["events"] = [dict(e) for e in (doc.get("events") or [])]
    out["relationships"] = [dict(r) for r in (doc.get("relationships") or [])]
    out["competency_questions"] = [
        dict(c) if isinstance(c, dict) else {"id": "", "question": str(c), "priority": "Medium"}
        for c in (doc.get("competency_questions") or [])
    ]
    return out


def _norm_cli(doc: dict) -> Dict[str, Any]:
    """onboard.py-style session → wizard shape.

    CLI session has entities + events flattened (one list with `is_event`)
    and CQs as plain strings. Wizard expects events as a separate list and
    CQs as objects.
    """
    out = _empty_wizard_session()
    out["domain"] = {
        "name":        doc.get("domain_name", ""),
        "description": doc.get("domain_description", ""),
        "base_iri":    doc.get("base_iri", ""),
        "industry":    doc.get("domain_slug", ""),
        "author":      doc.get("author", ""),
    }
    flat = doc.get("entities") or []
    out["entities"] = [
        {
            "name": e.get("name", ""),
            "label": e.get("label", e.get("name", "")),
            "description": e.get("description", ""),
            "sensitivity": e.get("sensitivity", "Internal"),
            "is_event": False,
            "properties": [],
            **({"table_name": e["table_name"]} if e.get("table_name") else {}),
        }
        for e in flat if not e.get("is_event")
    ]
    out["events"] = [
        {
            "name": e.get("name", ""),
            "label": e.get("label", e.get("name", "")),
            "description": e.get("description", ""),
        }
        for e in flat if e.get("is_event")
    ]
    out["relationships"] = [
        dict(r) for r in (doc.get("relationships") or [])
    ]
    out["competency_questions"] = [
        {"id": f"CQ-{i+1:02d}", "question": q, "priority": "Medium"}
        for i, q in enumerate(doc.get("cqs") or [])
    ]
    return out


def _norm_schema(doc: dict) -> Dict[str, Any]:
    """{tables: [...]} → wizard shape — best-effort."""
    out = _empty_wizard_session()
    out["domain"] = {
        "name":        doc.get("domain") or doc.get("name", ""),
        "description": doc.get("description", ""),
        "base_iri":    doc.get("base_iri", ""),
        "industry":    doc.get("industry", ""),
    }
    name_to_label = {}
    for t in doc.get("tables") or []:
        tname = t.get("name", "")
        if not tname:
            continue
        label = t.get("label") or _label_from_snake(tname)
        name_to_label[tname] = label
        is_event = _looks_like_event(tname)
        record = {
            "name": tname,
            "label": label,
            "description": t.get("description", ""),
            "sensitivity": t.get("sensitivity", "Internal"),
            "is_event": is_event,
            "properties": [
                {
                    "name": c.get("name", ""),
                    "type": c.get("type", "string"),
                    "description": c.get("description", ""),
                    "sensitivity": c.get("sensitivity"),
                    "required": bool(c.get("required") or c.get("not_null")),
                }
                for c in (t.get("columns") or []) if c.get("name")
            ],
        }
        if is_event:
            out["events"].append({"name": tname, "label": label, "description": record["description"]})
        else:
            out["entities"].append(record)

    # FK → relationships
    for t in doc.get("tables") or []:
        src = t.get("name", "")
        for fk in (t.get("foreign_keys") or []):
            tgt = fk.get("references_table") or fk.get("ref_table") or fk.get("references")
            if not tgt:
                continue
            out["relationships"].append({
                "from_entity": name_to_label.get(src, src),
                "label":       fk.get("label", "references"),
                "to_entity":   name_to_label.get(tgt, tgt),
            })
    return out


# ── Helpers ───────────────────────────────────────────────────────────────

def _label_from_snake(s: str) -> str:
    return " ".join(p.capitalize() for p in s.replace("-", "_").split("_") if p)


def _looks_like_event(name: str) -> bool:
    # Normalise so "Audit Log" matches the same hint as "audit_log".
    low = re.sub(r"[\s\-]+", "_", (name or "").lower())
    return any(h in low for h in EVENT_NAME_HINTS)


def _suggested_sensitivity(name: str) -> Optional[str]:
    """Return Restricted / Confidential / None based on naming heuristics."""
    low = (name or "").lower()
    if any(h in low for h in PII_HINTS_RESTRICTED):
        return "Restricted"
    if any(h in low for h in PII_HINTS_CONFIDENTIAL):
        return "Confidential"
    return None


# ── Validators (shared by all JSON shapes) ────────────────────────────────

def _validate_session(s: Dict[str, Any]) -> Tuple[List[Issue], List[Issue], List[Issue]]:
    """Walk the normalised wizard session and emit errors/warnings/suggestions."""
    errors: List[Issue] = []
    warnings: List[Issue] = []
    suggestions: List[Issue] = []

    domain = s.get("domain") or {}
    entities = s.get("entities") or []
    events = s.get("events") or []
    rels = s.get("relationships") or []
    cqs = s.get("competency_questions") or []

    # ── Errors ──────────────────────────────────────────────────────────

    if not (domain.get("name") or "").strip():
        errors.append(Issue(
            code="MISSING_DOMAIN_NAME",
            message="domain.name is empty — required for the OWL IRI namespace.",
            location="domain.name",
            fix_hint='Add a domain name like "Smart Building Operations" before importing.',
            severity="error",
        ))

    if not entities and not events:
        errors.append(Issue(
            code="NO_ENTITIES",
            message="No entities or events were found — the resulting ontology would be empty.",
            location="entities",
            fix_hint="Add at least one entity. Without entities the toolkit produces an empty graph.",
            severity="error",
        ))

    seen_labels: Dict[str, int] = {}
    label_to_kind: Dict[str, str] = {}
    for i, e in enumerate(entities):
        label = (e.get("label") or e.get("name") or "").strip()
        if not label:
            errors.append(Issue(
                code="ENTITY_NO_LABEL", severity="error",
                message=f"entities[{i}] has no name or label.",
                location=f"entities[{i}]",
                fix_hint="Every entity needs at least a name.",
            ))
            continue
        if label in seen_labels:
            errors.append(Issue(
                code="DUPLICATE_ENTITY", severity="error",
                message=f"Duplicate entity label '{label}' (also seen at entities[{seen_labels[label]}]).",
                location=f"entities[{i}]",
                fix_hint="Rename or remove one of the duplicates.",
            ))
        else:
            seen_labels[label] = i
            label_to_kind[label] = "entity"
        name = (e.get("name") or "").strip()
        if name and IRI_UNSAFE.search(name):
            errors.append(Issue(
                code="UNSAFE_ENTITY_NAME", severity="error",
                message=f"entities[{i}].name '{name}' contains characters that aren't safe inside an IRI.",
                location=f"entities[{i}].name",
                fix_hint="Use letters, digits, dots, dashes, underscores; no spaces or quotes.",
            ))

    for i, e in enumerate(events):
        label = (e.get("label") or e.get("name") or "").strip()
        if not label:
            errors.append(Issue(
                code="EVENT_NO_LABEL", severity="error",
                message=f"events[{i}] has no name or label.",
                location=f"events[{i}]",
            ))
            continue
        if label in seen_labels:
            errors.append(Issue(
                code="DUPLICATE_EVENT", severity="error",
                message=f"Event label '{label}' duplicates an entity label.",
                location=f"events[{i}]",
            ))
        else:
            seen_labels[label] = i
            label_to_kind[label] = "event"

    # Relationship endpoints must resolve
    for i, r in enumerate(rels):
        frm = (r.get("from_entity") or "").strip()
        to = (r.get("to_entity") or "").strip()
        if not frm or not to:
            errors.append(Issue(
                code="REL_INCOMPLETE", severity="error",
                message=f"relationships[{i}] missing endpoint(s).",
                location=f"relationships[{i}]",
                fix_hint="Each relationship needs from_entity, label, and to_entity.",
            ))
            continue
        if frm not in seen_labels:
            errors.append(Issue(
                code="REL_BAD_ENDPOINT", severity="error",
                message=f"relationships[{i}].from_entity '{frm}' is not a defined entity or event.",
                location=f"relationships[{i}].from_entity",
                fix_hint=f"Add '{frm}' as an entity, or rename the endpoint.",
            ))
        if to not in seen_labels:
            errors.append(Issue(
                code="REL_BAD_ENDPOINT", severity="error",
                message=f"relationships[{i}].to_entity '{to}' is not a defined entity or event.",
                location=f"relationships[{i}].to_entity",
                fix_hint=f"Add '{to}' as an entity, or rename the endpoint.",
            ))

    # ── Warnings ────────────────────────────────────────────────────────

    if not (domain.get("base_iri") or "").strip():
        warnings.append(Issue(
            code="MISSING_BASE_IRI",
            message="domain.base_iri not set — the toolkit will pick a default.",
            location="domain.base_iri",
            fix_hint='Set a stable IRI like "https://ontology.example.com/<your-domain>/".',
        ))

    if not cqs:
        warnings.append(Issue(
            code="NO_CQS",
            message="No competency questions defined — the governance scorecard will be weak.",
            location="competency_questions",
            fix_hint="Add 5–8 questions your ontology should answer.",
        ))

    if not rels and len(entities) > 1:
        warnings.append(Issue(
            code="NO_RELATIONSHIPS",
            message=f"{len(entities)} entities but no relationships — the resulting graph will be unconnected.",
            location="relationships",
            fix_hint="Add at least one relationship per entity pair that links in your real data.",
        ))

    # Per-entity quality checks
    in_edges: Dict[str, int] = {l: 0 for l in seen_labels}
    out_edges: Dict[str, int] = {l: 0 for l in seen_labels}
    for r in rels:
        f = r.get("from_entity"); t = r.get("to_entity")
        if f in out_edges: out_edges[f] += 1
        if t in in_edges:  in_edges[t]  += 1

    for i, e in enumerate(entities):
        label = (e.get("label") or e.get("name") or "").strip()
        if not label: continue
        if not (e.get("description") or "").strip():
            warnings.append(Issue(
                code="ENTITY_NO_DESCRIPTION",
                message=f"Entity '{label}' has no description.",
                location=f"entities[{i}].description",
                fix_hint="Add one sentence — the LLM grounding step uses it verbatim.",
            ))
        if in_edges.get(label, 0) == 0 and out_edges.get(label, 0) == 0 and rels:
            warnings.append(Issue(
                code="ORPHAN_ENTITY",
                message=f"Entity '{label}' has no relationships in or out.",
                location=f"entities[{i}]",
                fix_hint="Either connect it via a relationship or remove it.",
            ))

    # ── Suggestions ─────────────────────────────────────────────────────

    for i, e in enumerate(entities):
        label = (e.get("label") or e.get("name") or "").strip()
        current = e.get("sensitivity") or "Internal"
        suggested = _suggested_sensitivity(label) or _suggested_sensitivity(e.get("name", ""))
        if suggested and suggested != current:
            suggestions.append(Issue(
                code="SUGGEST_SENSITIVITY",
                message=f"Entity '{label}' looks like it carries {suggested.lower()}-tier data.",
                location=f"entities[{i}].sensitivity",
                fix_hint=f"Suggested: change sensitivity from {current} to {suggested}.",
                severity="suggestion",
            ))
        if not e.get("is_event") and _looks_like_event(label):
            suggestions.append(Issue(
                code="SUGGEST_EVENT",
                message=f"Entity '{label}' has an event-shaped name — consider marking it as an event.",
                location=f"entities[{i}].is_event",
                fix_hint="Move it to events with is_event=true so it becomes a subclass of Event.",
                severity="suggestion",
            ))
        # Per-property sensitivity suggestions
        for j, p in enumerate(e.get("properties") or []):
            if p.get("sensitivity"): continue
            sug = _suggested_sensitivity(p.get("name", ""))
            if sug:
                suggestions.append(Issue(
                    code="SUGGEST_PROPERTY_SENSITIVITY",
                    message=f"Property '{p.get('name')}' on '{label}' looks like {sug.lower()}-tier data.",
                    location=f"entities[{i}].properties[{j}].sensitivity",
                    fix_hint=f"Suggested sensitivity tier: {sug}.",
                    severity="suggestion",
                ))

    return errors, warnings, suggestions


def _stats(s: Dict[str, Any]) -> Dict[str, Any]:
    entities = s.get("entities") or []
    events = s.get("events") or []
    rels = s.get("relationships") or []
    cqs = s.get("competency_questions") or []
    described = sum(1 for e in entities if (e.get("description") or "").strip())
    total_props = sum(len(e.get("properties") or []) for e in entities)
    described_props = sum(
        1 for e in entities
        for p in (e.get("properties") or [])
        if (p.get("description") or "").strip()
    )
    coverage = round(described / max(len(entities), 1) * 100)
    prop_coverage = round(described_props / max(total_props, 1) * 100) if total_props else None
    return {
        "entities": len(entities),
        "events": len(events),
        "relationships": len(rels),
        "competency_questions": len(cqs),
        "entity_description_coverage_pct": coverage,
        "property_count": total_props,
        "property_description_coverage_pct": prop_coverage,
    }


def _diff(new: Dict[str, Any], existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare imported session to whatever is currently saved."""
    if not existing:
        return {
            "added":    {"entities": len(new.get("entities") or []),
                         "events": len(new.get("events") or []),
                         "relationships": len(new.get("relationships") or []),
                         "competency_questions": len(new.get("competency_questions") or [])},
            "replaced": {},
            "removed":  {},
            "domain_change": new.get("domain", {}).get("name"),
        }
    def _label_set(items, key="label"):
        return {(it.get(key) or it.get("name") or "") for it in items}

    new_e, old_e = _label_set(new.get("entities", [])), _label_set(existing.get("entities", []))
    new_v, old_v = _label_set(new.get("events", [])), _label_set(existing.get("events", []))
    return {
        "added":    {"entities": len(new_e - old_e),
                     "events": len(new_v - old_v)},
        "removed":  {"entities": len(old_e - new_e),
                     "events": len(old_v - new_v)},
        "replaced": {"entities": len(new_e & old_e),
                     "events": len(new_v & old_v)},
        "domain_change": (new.get("domain", {}).get("name") !=
                          existing.get("domain", {}).get("name")),
    }


# ── SQL parser (issue #16 step 3 — sqlglot AST → schema-shape dict) ─────

def _xsd_for(sql_type: str) -> str:
    base = sql_type.upper().split("(", 1)[0].strip()
    return SQL_TO_XSD.get(base, "xsd:string")


def _table_name_to_label(name: str) -> str:
    # Strip schema-qualifier (e.g. "public.orders" → "orders").
    bare = (name or "").split(".")[-1]
    # Strip surrounding quotes / brackets ('"orders"', '[orders]').
    bare = re.sub(r"^[\"'\[`]|[\"'\]`]$", "", bare)
    return _label_from_snake(bare)


def _parse_sql(
    raw: bytes,
    *,
    dialect: str = "auto",
    existing_session: Optional[Dict[str, Any]] = None,
    filename: Optional[str] = None,
) -> ImportResult:
    """Parse a CREATE TABLE script into a schema-shape session via sqlglot."""
    result = ImportResult(format="sql")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        result.errors.append(Issue(
            code="ENCODING", severity="error",
            message=f"File is not valid UTF-8: {e}",
            fix_hint="Re-save the file as UTF-8.",
        ))
        return result

    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        result.errors.append(Issue(
            code="SQLGLOT_MISSING", severity="error",
            message="SQL import requires the `sqlglot` package.",
            fix_hint="Install with: pip install sqlglot   (or: pip install -r requirements-advanced.txt)",
        ))
        return result

    resolved_dialect = dialect.lower() if dialect and dialect != "auto" else _detect_sql_dialect(text)
    try:
        trees = sqlglot.parse(text, dialect=resolved_dialect or None)
    except Exception as e:                           # broad — sqlglot raises ParseError, TokenError, etc.
        result.errors.append(Issue(
            code="SQL_PARSE", severity="error",
            message=f"Could not parse SQL: {e.__class__.__name__}: {e}",
            fix_hint=("Check syntax; if the file is dialect-specific, try passing "
                      "dialect=postgres|mysql|tsql|oracle|sqlite explicitly."),
        ))
        return result

    tables: List[Dict[str, Any]] = []
    for stmt in (trees or []):
        if not isinstance(stmt, exp.Create):
            continue
        kind = (stmt.args.get("kind") or "").upper()
        if kind != "TABLE":
            continue

        tnode = stmt.find(exp.Table)
        if tnode is None:
            continue
        tname_full = tnode.sql()                     # may include schema
        tname_bare = tnode.name                      # just the table identifier
        if not tname_bare:
            continue

        cols: List[Dict[str, Any]] = []
        pk_cols: List[str] = []
        fks: List[Dict[str, str]] = []

        schema = stmt.find(exp.Schema)
        if schema:
            for el in schema.expressions:
                # ── column ────────────────────────────────────────────
                if isinstance(el, exp.ColumnDef):
                    cname = el.name
                    kind_ = el.args.get("kind")
                    type_sql = kind_.sql() if kind_ else ""
                    not_null = False
                    is_pk_col = False
                    constraints = el.args.get("constraints") or []
                    for cs in constraints:
                        kn = cs.kind.__class__.__name__ if cs.kind else ""
                        if kn == "NotNullColumnConstraint":
                            not_null = True
                        elif kn == "PrimaryKeyColumnConstraint":
                            is_pk_col = True
                            pk_cols.append(cname)
                        elif kn == "Reference":
                            # Inline `REFERENCES other(col)` clause.
                            ref_table = cs.kind.find(exp.Table)
                            ref_col = None
                            ids = cs.kind.find_all(exp.Identifier)
                            ids = list(ids)
                            # last identifier inside Reference is usually the column name
                            if ref_table and ids:
                                ref_col = ids[-1].name
                            if ref_table:
                                fks.append({
                                    "column":             cname,
                                    "references_table":   ref_table.name,
                                    "references_column":  ref_col or "id",
                                })
                    cols.append({
                        "name":        cname,
                        "type":        type_sql or "TEXT",
                        "xsd_type":    _xsd_for(type_sql),
                        "required":    not_null or is_pk_col,
                        "primary_key": is_pk_col,
                        "description": "",
                    })
                # ── table-level PRIMARY KEY (a, b) ───────────────────
                elif isinstance(el, exp.PrimaryKey):
                    for x in el.expressions:
                        nm = x.name if hasattr(x, "name") else x.sql()
                        if nm: pk_cols.append(nm)
                # ── table-level FOREIGN KEY (col) REFERENCES t (col) ─
                elif isinstance(el, exp.ForeignKey):
                    src_cols = [x.name for x in el.expressions if hasattr(x, "name")]
                    ref = el.args.get("reference")
                    ref_table = None; ref_cols: List[str] = []
                    if ref is not None:
                        rtab = ref.find(exp.Table)
                        if rtab is not None:
                            ref_table = rtab.name
                        ref_cols = [x.name for x in ref.find_all(exp.Identifier)
                                    if hasattr(x, "name") and x.name and x.name != ref_table]
                    if ref_table and src_cols:
                        for i, sc in enumerate(src_cols):
                            fks.append({
                                "column":            sc,
                                "references_table":  ref_table,
                                "references_column": ref_cols[i] if i < len(ref_cols) else "id",
                            })

        tables.append({
            "name":         tname_bare,
            "label":        _table_name_to_label(tname_bare),
            "description":  "",
            "columns":      cols,
            "primary_key":  pk_cols or None,
            "foreign_keys": fks,
            "schema_qualified_name": tname_full,
        })

    if not tables:
        result.errors.append(Issue(
            code="NO_TABLES", severity="error",
            message="No CREATE TABLE statements were found in the SQL file.",
            fix_hint="The importer reads CREATE TABLE only — drop indexes, views, and stored procs are skipped.",
        ))
        return result

    schema_doc = {
        "domain":   _label_from_snake(filename.rsplit(".", 1)[0]) if filename else "Imported Schema",
        "description": f"Imported from {filename or 'SQL DDL'} ({resolved_dialect or 'default'} dialect).",
        "tables":   tables,
    }
    session = _norm_schema(schema_doc)
    result.session = session

    errors, warnings, suggestions = _validate_session(session)
    result.errors.extend(errors)
    result.warnings.extend(warnings)
    result.suggestions.extend(suggestions)
    result.stats = _stats(session)
    result.stats["sql_dialect"] = resolved_dialect or "(default)"
    result.stats["table_count"] = len(tables)
    result.diff = _diff(session, existing_session)
    return result


# ── Public API ────────────────────────────────────────────────────────────

def parse_and_validate(
    raw: bytes,
    *,
    fmt: str = "auto",
    dialect: str = "auto",
    existing_session: Optional[Dict[str, Any]] = None,
    filename: Optional[str] = None,
) -> ImportResult:
    """Parse, validate, and return an ImportResult — never persists.

    SQL parsing is a stub at this point (raises a single error) so the
    JSON path can ship independently per the issue's sequencing.
    """
    fmt_resolved = _detect_format(raw, fmt, filename)
    result = ImportResult()

    if fmt_resolved == "sql":
        return _parse_sql(raw, dialect=dialect, existing_session=existing_session,
                          filename=filename)

    # JSON path
    try:
        text = raw.decode("utf-8-sig")
        doc = json.loads(text)
    except UnicodeDecodeError as e:
        result.format = "json"
        result.errors.append(Issue(
            code="ENCODING", severity="error",
            message=f"File is not valid UTF-8: {e}",
            fix_hint="Re-save the file as UTF-8.",
        ))
        return result
    except json.JSONDecodeError as e:
        result.format = "json"
        result.errors.append(Issue(
            code="INVALID_JSON", severity="error",
            message=f"Could not parse JSON at line {e.lineno}, column {e.colno}: {e.msg}",
            location=f"line {e.lineno}, col {e.colno}",
            fix_hint="Check for trailing commas, unquoted keys, or stray characters.",
        ))
        return result

    if not isinstance(doc, dict):
        result.format = "json"
        result.errors.append(Issue(
            code="ROOT_NOT_OBJECT", severity="error",
            message=f"Root must be a JSON object; got {type(doc).__name__}.",
            fix_hint="Wrap the content in {...} with a top-level domain or tables key.",
        ))
        return result

    shape = _detect_json_shape(doc)
    result.format = shape

    if shape == "json-wizard":
        session = _norm_wizard(doc)
    elif shape == "json-cli":
        session = _norm_cli(doc)
    elif shape == "json-schema":
        session = _norm_schema(doc)
    else:
        session = _empty_wizard_session()

    result.session = session
    errors, warnings, suggestions = _validate_session(session)
    result.errors.extend(errors)
    result.warnings.extend(warnings)
    result.suggestions.extend(suggestions)
    result.stats = _stats(session)
    result.diff = _diff(session, existing_session)
    return result
