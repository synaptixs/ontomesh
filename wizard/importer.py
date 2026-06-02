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
    head = raw_text[:16384]
    head_u = head.upper()
    head_l = head.lower()
    # Postgres: includes patterns common to pg_dump output.
    if any(s in head_u for s in ("JSONB", "SERIAL ", "BIGSERIAL", "::REGCLASS")):
        return "postgres"
    if "NEXTVAL(" in head_u and ("'PUBLIC." in head_u or "'PG_" in head_u or "::REGCLASS" in head_u):
        return "postgres"
    if "SET SEARCH_PATH" in head_u or "OWNER TO" in head_u:
        return "postgres"
    # MySQL.
    if any(s in head_u for s in ("AUTO_INCREMENT", "ENGINE=", "TINYINT(")):
        return "mysql"
    # SQL Server: bracketed identifiers, IDENTITY, sp_*, NVARCHAR.
    if "NVARCHAR" in head_u or "IDENTITY(" in head_u:
        return "tsql"
    if "[dbo]" in head_l or "EXEC SP_" in head_u or head_l.startswith("use ["):
        return "tsql"
    # Oracle.
    if "VARCHAR2" in head_u or "NUMBER(" in head_u or "NOCYCLE" in head_u:
        return "oracle"
    # SQLite.
    if "PRAGMA " in head_u or "AUTOINCREMENT" in head_u:
        return "sqlite"
    return ""                    # let sqlglot use its default


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class Issue:
    """A single error / warning / suggestion entry.

    Suggestions also carry an ``apply`` payload describing how the
    frontend should mutate the session if the user clicks Accept on
    that row. Two flavours:

      • ``{"path": [..segments..], "value": <new value>}``
            simple setter — walks the path inside session and assigns.
      • ``{"op": "<name>", ...}``
            named operation — handled by a frontend dispatch table.

    Errors and warnings leave ``apply=None`` (no mechanical fix exists).
    """
    code: str             # short machine code, e.g. "ORPHAN_ENTITY"
    message: str          # human-readable
    location: Optional[str] = None    # e.g. "entities[3]" or "tables.orders.col 4"
    fix_hint: Optional[str] = None
    severity: str = "warning"         # error | warning | suggestion
    apply: Optional[Dict[str, Any]] = None

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
    # T1.4 — counters from the semantic-enhancement pass
    # (junctions_collapsed, fk_chains_found, cardinalities_added,
    # derived_classes). Empty when semantic enhancement didn't run.
    semantic_report: Dict[str, int] = field(default_factory=dict)

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
            "semantic_report": self.semantic_report,
        }


def _apply_semantic_enhancement(session: Dict[str, Any],
                                schema_doc: Dict[str, Any],
                                result: "ImportResult") -> Dict[str, Any]:
    """T1.4 — run :func:`wizard.importer_semantic.enhance_schema`
    when the input carries enough structure (tables + foreign keys).
    Failure is silent: the structural session is returned unchanged
    and the result's semantic_report stays empty."""
    try:
        from wizard.importer_semantic import enhance_schema      # noqa: E402
        enhanced, report = enhance_schema(session, schema_doc)
        result.semantic_report = report.as_dict()
        return enhanced
    except Exception:                                            # noqa: BLE001
        return session


# ── JSON Schema structural validation ────────────────────────────────────
# A formal JSON Schema lives at wizard/import_schema.json. It accepts the
# three shapes via oneOf and is loaded lazily so the importer can run on
# environments where the optional `jsonschema` package isn't installed —
# semantic checks in `_validate_session` run regardless.

import os as _os
import pathlib as _pathlib

_IMPORT_SCHEMA_PATH = _pathlib.Path(_os.path.dirname(__file__)) / "import_schema.json"
_IMPORT_SCHEMA_CACHE: Optional[Dict[str, Any]] = None


def _load_import_schema() -> Optional[Dict[str, Any]]:
    global _IMPORT_SCHEMA_CACHE
    if _IMPORT_SCHEMA_CACHE is not None:
        return _IMPORT_SCHEMA_CACHE
    if not _IMPORT_SCHEMA_PATH.exists():
        return None
    try:
        with _IMPORT_SCHEMA_PATH.open() as f:
            _IMPORT_SCHEMA_CACHE = json.load(f)
    except (OSError, json.JSONDecodeError):
        _IMPORT_SCHEMA_CACHE = None
    return _IMPORT_SCHEMA_CACHE


def _jsonschema_validate(doc: Dict[str, Any]) -> List["Issue"]:
    """Return SCHEMA_VIOLATION Issue records, or [] if validation passes
    or jsonschema isn't available.

    Per-error pointer (`location`) follows JSON Pointer convention so the
    review modal can highlight the offending field; the `oneOf` matcher
    is run by jsonschema itself and the *best-fitting branch's* errors
    are surfaced (avoids the noise where every `oneOf` branch contributes).
    """
    schema = _load_import_schema()
    if schema is None:
        return []
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return []                              # optional dep — skip silently
    out: List["Issue"] = []
    try:
        validator = Draft202012Validator(schema)
    except Exception:                          # malformed schema file — fail open
        return []
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if not errors:
        return []
    # When the top-level oneOf doesn't match, jsonschema returns a single
    # "is not valid under any of the given schemas" error with sub-errors
    # under .context. Pick the branch with the FEWEST sub-errors — that's
    # the shape the user *probably* meant — and surface only its issues.
    primary = errors[0]
    if primary.validator == "oneOf" and getattr(primary, "context", None):
        ctx = sorted(primary.context, key=lambda e: (len(list(e.absolute_path)), e.message))
        # Group by branch (schema_path[1] = which oneOf member)
        branches: Dict[Any, List] = {}
        for sub in ctx:
            key = sub.schema_path[1] if len(sub.schema_path) > 1 else None
            branches.setdefault(key, []).append(sub)
        # Pick the branch with the fewest errors → most likely intended shape.
        best = min(branches.values(), key=len)
        errors = best
    for err in errors[:25]:                    # cap — modal unusable beyond ~25
        ptr = "/" + "/".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
        out.append(Issue(
            code="SCHEMA_VIOLATION",
            severity="error",
            message=f"JSON Schema: {err.message}",
            location=ptr,
            fix_hint="The file's structure doesn't match any of the three accepted shapes "
                     "(wizard-session, CLI session, or {tables: [...]}). Check the field type and required keys.",
        ))
    return out


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


def _suggested_description(col_name: str, col_type: str = "", entity_label: str = "") -> Optional[str]:
    """Heuristic one-line description for a column with no documentation.

    Strategy: pattern-match on the *suffix* of the snake-case name first
    (most informative — `_at`, `_id`, `_count`, `_url`, `_email`), then
    on the bare type, then fall back to a generic "<noun> of the <entity>"
    sentence. Returns None when nothing useful can be said.

    The output is conservative — better to say nothing than to fabricate
    a confident-sounding wrong description that the LLM grounding step
    would later quote verbatim.
    """
    if not col_name:
        return None
    n = col_name.lower().strip()
    t = (col_type or "").upper().split("(", 1)[0].strip()
    ent = (entity_label or "").strip()
    ent_low = ent.lower() if ent else "row"

    # Identifier-shaped columns
    if n in ("id", "uuid", "guid"):
        return f"Surrogate identifier for the {ent_low}." if ent else "Surrogate primary key."
    if n.endswith("_id") and n not in ("uuid",):
        target = n[:-3].replace("_", " ")
        return f"Foreign key reference to the {target} this {ent_low} belongs to."

    # Timestamp / date suffixes
    if n.endswith("_at") or n in ("created", "updated", "deleted"):
        verb = n.replace("_at", "").replace("_", " ").strip() or n
        return f"Timestamp at which this {ent_low} was {verb} (UTC)."
    if n.endswith("_on") or n.endswith("_date") or t in ("DATE",):
        return f"Calendar date associated with this {ent_low}."

    # Common bool / count / total / amount / name patterns
    if n.startswith("is_") or n.startswith("has_") or n in ("active", "enabled", "deleted"):
        return f"Flag indicating whether this {ent_low} is {n.replace('is_','').replace('has_','').replace('_',' ')}."
    if n.endswith("_count") or n in ("count",):
        thing = n[:-6].replace("_", " ") if n.endswith("_count") else "items"
        return f"Number of {thing} associated with this {ent_low}."
    if n in ("total", "subtotal", "amount", "balance", "price"):
        return f"Monetary {n} for this {ent_low}, in the smallest currency unit unless noted."
    if n.endswith("_amount") or n.endswith("_total"):
        return f"Monetary value associated with this {ent_low}."

    # Communication / web identifiers
    if "email" in n:           return f"Email address — primary contact for this {ent_low}."
    if "phone" in n or "mobile" in n: return f"Phone number — contact for this {ent_low}."
    if n.endswith("_url") or n == "url":   return f"URL associated with this {ent_low}."
    if n.endswith("_uri") or n == "uri":   return f"URI associated with this {ent_low}."
    if n.endswith("_ip")  or n == "ip_address": return f"IP address recorded for this {ent_low}."

    # Names / labels / descriptions / status
    if n in ("name", "full_name", "label", "title", "description"):
        return f"Human-readable {n.replace('_',' ')} for this {ent_low}."
    if n in ("status", "state", "kind", "type", "category"):
        return f"Classification {n} for this {ent_low}."

    # Type-only fallbacks
    if t in ("BOOLEAN", "BOOL", "BIT"):
        return f"Boolean flag attached to this {ent_low}."
    if t in ("JSON", "JSONB"):
        return f"JSON document attached to this {ent_low}."
    if t in ("TIMESTAMP", "TIMESTAMPTZ", "DATETIME", "DATETIME2"):
        return f"Timestamp recorded against this {ent_low} (UTC)."

    return None


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
                apply={"path": ["entities", i, "sensitivity"], "value": suggested},
            ))
        if not e.get("is_event") and _looks_like_event(label):
            suggestions.append(Issue(
                code="SUGGEST_EVENT",
                message=f"Entity '{label}' has an event-shaped name — consider marking it as an event.",
                location=f"entities[{i}].is_event",
                fix_hint="Move it to events with is_event=true so it becomes a subclass of Event.",
                severity="suggestion",
                apply={"op": "move_to_events", "entity_index": i,
                       "name": e.get("name", ""), "label": label,
                       "description": e.get("description", "")},
            ))
        # Per-property sensitivity + description suggestions
        for j, p in enumerate(e.get("properties") or []):
            if not p.get("sensitivity"):
                sug = _suggested_sensitivity(p.get("name", ""))
                if sug:
                    suggestions.append(Issue(
                        code="SUGGEST_PROPERTY_SENSITIVITY",
                        message=f"Property '{p.get('name')}' on '{label}' looks like {sug.lower()}-tier data.",
                        location=f"entities[{i}].properties[{j}].sensitivity",
                        fix_hint=f"Suggested sensitivity tier: {sug}.",
                        severity="suggestion",
                        apply={"path": ["entities", i, "properties", j, "sensitivity"], "value": sug},
                    ))
            # Suggested wording for any column lacking a description.
            # The LLM's grounding step uses descriptions verbatim — better
            # to surface a heuristic the user can edit than leave nothing.
            if not (p.get("description") or "").strip():
                sug_text = _suggested_description(p.get("name", ""), p.get("type", ""), label)
                if sug_text:
                    suggestions.append(Issue(
                        code="SUGGEST_DESCRIPTION",
                        message=f"Property '{p.get('name')}' on '{label}' has no description.",
                        location=f"entities[{i}].properties[{j}].description",
                        fix_hint=f"Suggested wording: \"{sug_text}\"",
                        severity="suggestion",
                        apply={"path": ["entities", i, "properties", j, "description"], "value": sug_text},
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


# ── SQL comment extraction (issue #16 step 4) ───────────────────────────
#
# sqlglot strips comments while parsing, so we run a parallel regex pass
# over the raw SQL to harvest column-level descriptions and attach them
# back to the parsed schema.  Four comment forms are supported, covering
# Postgres, MySQL, SQL Server, Oracle, and SQLite usage in the wild.

# `COMMENT ON COLUMN tab.col IS 'text';`  (Postgres / SQLite-friendly)
_RE_COMMENT_ON_COLUMN = re.compile(
    r"""COMMENT\s+ON\s+COLUMN\s+
        (?:(?P<schema>\w+)\s*\.\s*)?       # optional schema
        (?P<table>\w+)\s*\.\s*(?P<column>\w+)\s+
        IS\s+'(?P<text>(?:''|[^'])*)'\s*;""",
    re.IGNORECASE | re.VERBOSE,
)

# `COMMENT ON TABLE tab IS 'text';`
_RE_COMMENT_ON_TABLE = re.compile(
    r"""COMMENT\s+ON\s+TABLE\s+
        (?:(?P<schema>\w+)\s*\.\s*)?
        (?P<table>\w+)\s+
        IS\s+'(?P<text>(?:''|[^'])*)'\s*;""",
    re.IGNORECASE | re.VERBOSE,
)

# Inline MySQL column comment: `email VARCHAR(255) NOT NULL COMMENT 'text'`
_RE_INLINE_MYSQL_COMMENT = re.compile(
    r"""COMMENT\s+'(?P<text>(?:''|[^'])*)'""",
    re.IGNORECASE | re.VERBOSE,
)

# Match the start of a CREATE TABLE block so we can scan its body separately.
_RE_CREATE_TABLE = re.compile(
    r"""CREATE\s+(?:TEMP(?:ORARY)?\s+|GLOBAL\s+TEMPORARY\s+)?TABLE\s+
        (?:IF\s+NOT\s+EXISTS\s+)?
        (?:(?P<schema>\w+)\s*\.\s*)?
        (?P<table>"?[\w]+"?)\s*\(""",
    re.IGNORECASE | re.VERBOSE,
)

# Identify the column name on a column line — first identifier-looking word.
_RE_COLUMN_LINE = re.compile(r"^\s*(?P<col>\w+)\b")


def _extract_sql_comments(text: str) -> Dict[str, Dict[str, str]]:
    """Return {table_name: {col_name: comment_text}} where col_name='' is the table-level comment.

    Strategy: walk each CREATE TABLE body line by line. For every line that
    looks like a column declaration:
      - keep any `-- text` trailing the line as the column comment;
      - if the *previous* non-blank line was a `--` line, attach that too;
      - if the previous non-blank line was a `/* ... */`, attach it;
      - if the line itself contains an inline `COMMENT 'text'` clause
        (MySQL), attach that.
    Then post-process the entire script for `COMMENT ON COLUMN/TABLE`
    statements (Postgres) and merge them in (these win over inline).

    Comment unescape: doubled single-quotes ('') → single quote (').
    """
    out: Dict[str, Dict[str, str]] = {}

    def _unesc(s: str) -> str:
        return s.replace("''", "'").strip()

    def _set(table: str, col: str, text: str) -> None:
        if not table or text is None:
            return
        out.setdefault(table, {})
        # Don't overwrite a richer comment with an empty one.
        if col not in out[table] or out[table][col].strip() == "":
            out[table][col] = text

    # ── Pass 1: walk CREATE TABLE bodies line-by-line ───────────────────
    pos = 0
    while True:
        m = _RE_CREATE_TABLE.search(text, pos)
        if not m:
            break
        tname = m.group("table").strip().strip('"')
        # Find the matching closing paren by depth-walking from the `(`.
        depth = 0
        i = m.end() - 1            # the `(`
        body_start = m.end()
        body_end = body_start
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    body_end = i
                    break
            i += 1
        pos = max(body_end, m.end())
        body = text[body_start:body_end]
        prev_block_comment: Optional[str] = None
        prev_line_comment: Optional[str] = None
        for raw_line in body.split("\n"):
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            # Standalone /* ... */ on its own (single-line) line.
            block_only = re.match(r"^/\*\s*(.*?)\s*\*/\s*$", stripped, re.DOTALL)
            if block_only:
                prev_block_comment = block_only.group(1).strip()
                continue

            # Standalone -- line.
            if stripped.startswith("--"):
                prev_line_comment = stripped[2:].strip()
                continue

            # Otherwise it's (probably) a column declaration. First word is the name.
            cm = _RE_COLUMN_LINE.match(line)
            if not cm:
                prev_block_comment = prev_line_comment = None
                continue
            col_name = cm.group("col")
            # Skip table-level constraints (PRIMARY KEY, FOREIGN KEY, …).
            if col_name.upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK",
                                    "CONSTRAINT", "INDEX", "KEY"):
                prev_block_comment = prev_line_comment = None
                continue

            comment = None
            # Trailing `-- ...`
            tail = re.search(r"--\s*(.*?)\s*$", line)
            if tail:
                comment = tail.group(1).strip()
            # Inline MySQL `COMMENT 'text'`
            inline = _RE_INLINE_MYSQL_COMMENT.search(line)
            if inline:
                comment = _unesc(inline.group("text"))
            # Adjacent block / line comment from the previous statement
            if not comment:
                comment = prev_block_comment or prev_line_comment

            if comment:
                _set(tname, col_name, comment)
            prev_block_comment = prev_line_comment = None

    # ── Pass 2: COMMENT ON statements (anywhere in the script) ──────────
    for m in _RE_COMMENT_ON_TABLE.finditer(text):
        _set(m.group("table"), "", _unesc(m.group("text")))
    for m in _RE_COMMENT_ON_COLUMN.finditer(text):
        # Postgres COMMENT ON wins over inline forms — overwrite.
        out.setdefault(m.group("table"), {})[m.group("column")] = _unesc(m.group("text"))

    return out


# ── Soft-FK detection (issue #16 step 4) ────────────────────────────────
#
# A "soft FK" is a column whose name strongly suggests a foreign-key
# relationship to another table even though no `FOREIGN KEY` constraint
# was declared. Common in legacy schemas, MySQL ISAM tables, and ORMs
# that manage referential integrity in application code rather than DDL.
#
# Confidence scoring:
#   1.00  declared FK (always wins; emitted as a real relationship)
#   0.85  `<table>_id`     where <table> is an exact table name
#   0.75  `<table>_id`     where <table>+s / +es is a table name
#   0.60  `<table>_id`     where <table> is the singular of a table name
#                          ending in 's' or 'ies'
#
# Below 0.6 we don't emit — too noisy.

def _singularise(s: str) -> Optional[str]:
    if s.endswith("ies") and len(s) > 3:
        return s[:-3] + "y"
    if s.endswith("ses") and len(s) > 3:
        return s[:-2]
    if s.endswith("s") and len(s) > 1 and not s.endswith("ss"):
        return s[:-1]
    return None


def _pluralise(s: str) -> List[str]:
    out = []
    if s.endswith("y"):
        out.append(s[:-1] + "ies")
    if s.endswith(("s", "x", "z", "ch", "sh")):
        out.append(s + "es")
    out.append(s + "s")
    return out


def _detect_soft_fks(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a list of soft-FK suggestions:
        {from_table, from_column, to_table, confidence, basis}
    """
    table_names = {t["name"] for t in tables}
    # Build singular/plural index for matching.
    sing_to_table: Dict[str, str] = {}
    for nm in table_names:
        sing_to_table[nm] = nm
        s = _singularise(nm)
        if s:
            sing_to_table.setdefault(s, nm)
    sugs: List[Dict[str, Any]] = []
    for t in tables:
        declared_cols = {fk["column"] for fk in (t.get("foreign_keys") or [])}
        for c in t.get("columns", []):
            cname = c.get("name", "")
            if not cname or cname in declared_cols:
                continue
            low = cname.lower()
            if not low.endswith("_id"):
                continue
            stem = low[:-3]
            if stem == t["name"].lower():
                continue                   # self-pointer, e.g. parent_id; skip
            target = None; conf = 0.0; basis = ""
            if stem in table_names:
                target = stem; conf = 0.85; basis = "exact table-name match"
            elif any(p in table_names for p in _pluralise(stem)):
                target = next(p for p in _pluralise(stem) if p in table_names)
                conf = 0.75; basis = f"matches plural form '{target}'"
            elif stem in sing_to_table and sing_to_table[stem] != stem:
                target = sing_to_table[stem]
                conf = 0.60; basis = f"matches singularised table '{target}'"
            if target and conf >= 0.60:
                sugs.append({
                    "from_table":  t["name"],
                    "from_column": cname,
                    "to_table":    target,
                    "confidence":  conf,
                    "basis":       basis,
                })
    return sugs


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


def _fk_from_node(node, exp_module) -> List[Dict[str, str]]:
    """Resolve {column, references_table, references_column} dicts from a
    sqlglot ``ForeignKey`` node — used for inline CREATE columns,
    table-level constraints, and ALTER TABLE ADD CONSTRAINT alike.

    The reference's referenced table comes back schema-qualified for
    `public.customers` style names; we strip the schema prefix to match
    how we name tables in the parsed `tables` list.
    """
    src_cols = [x.name for x in node.expressions if hasattr(x, "name")]
    ref = node.args.get("reference")
    if not src_cols or ref is None:
        return []
    rtab = ref.find(exp_module.Table)
    if rtab is None:
        return []
    ref_table = rtab.name
    # Identifiers under the Reference: table-name first, then the
    # referenced column(s). Strip the table-name occurrence(s).
    ref_cols = [x.name for x in ref.find_all(exp_module.Identifier)
                if x.name and x.name != ref_table]
    out: List[Dict[str, str]] = []
    for i, sc in enumerate(src_cols):
        out.append({
            "column":            sc,
            "references_table":  ref_table,
            "references_column": ref_cols[i] if i < len(ref_cols) else "id",
        })
    return out


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
                    fks.extend(_fk_from_node(el, exp))
                # ── CONSTRAINT name PRIMARY KEY|FOREIGN KEY (Oracle) ─
                # sqlglot wraps named constraints in exp.Constraint;
                # the actual PrimaryKey / ForeignKey is nested inside.
                elif el.__class__.__name__ == "Constraint":
                    inner_pk = el.find(exp.PrimaryKey)
                    inner_fk = el.find(exp.ForeignKey)
                    if inner_pk:
                        for x in inner_pk.expressions:
                            nm = x.name if hasattr(x, "name") else x.sql()
                            if nm: pk_cols.append(nm)
                    if inner_fk:
                        fks.extend(_fk_from_node(inner_fk, exp))

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

    # ── Step 6: walk ALTER TABLE … ADD CONSTRAINT FOREIGN KEY ───────────
    # Standard pg_dump pattern is to declare the FK in a separate
    # ALTER TABLE block after every CREATE TABLE. Walk those and attach
    # to whichever table we already parsed.
    by_name = {t["name"]: t for t in tables}
    for stmt in (trees or []):
        if not isinstance(stmt, exp.Alter):
            continue
        atab = stmt.find(exp.Table)
        if atab is None or atab.name not in by_name:
            continue
        for fk_node in stmt.find_all(exp.ForeignKey):
            for fk in _fk_from_node(fk_node, exp):
                # Avoid duplicates if the same FK was also declared inline.
                if not any(
                    f.get("column") == fk["column"]
                    and f.get("references_table") == fk["references_table"]
                    for f in by_name[atab.name]["foreign_keys"]
                ):
                    by_name[atab.name]["foreign_keys"].append(fk)
        # ALTER TABLE … ADD CONSTRAINT pk_x PRIMARY KEY (col)
        for pk_node in stmt.find_all(exp.PrimaryKey):
            existing = by_name[atab.name].get("primary_key") or []
            if existing is None or by_name[atab.name].get("primary_key") is None:
                by_name[atab.name]["primary_key"] = []
            for x in pk_node.expressions:
                nm = x.name if hasattr(x, "name") else x.sql()
                if nm and nm not in by_name[atab.name]["primary_key"]:
                    by_name[atab.name]["primary_key"].append(nm)

    # ── Step 4: comment harvest + attach to columns / table description
    comments = _extract_sql_comments(text)
    described_cols = 0
    for t in tables:
        ctab = comments.get(t["name"], {})
        if ctab.get("") and not t.get("description"):
            t["description"] = ctab[""]
        for col in t["columns"]:
            txt = ctab.get(col["name"])
            if txt:
                col["description"] = txt
                described_cols += 1

    # ── Step 4: soft-FK suggestions (declared FKs always win) ───────────
    soft_fks = _detect_soft_fks(tables)

    schema_doc = {
        "domain":   _label_from_snake(filename.rsplit(".", 1)[0]) if filename else "Imported Schema",
        "description": f"Imported from {filename or 'SQL DDL'} ({resolved_dialect or 'default'} dialect).",
        "tables":   tables,
    }
    session = _norm_schema(schema_doc)
    # T1.4 — layer the semantic enhancements (junctions, FK chains,
    # cardinality, derived classes) on top of the structural pass.
    session = _apply_semantic_enhancement(session, schema_doc, result)
    result.session = session

    errors, warnings, suggestions = _validate_session(session)
    result.errors.extend(errors)
    result.warnings.extend(warnings)
    result.suggestions.extend(suggestions)

    # Attach soft-FK suggestions in the same Issue tier as sensitivity
    # / event suggestions so the UI's Suggestions tab renders them
    # uniformly. The basis + confidence ride along in fix_hint so
    # reviewers can sort by signal strength.
    for sf in soft_fks:
        from_label = _table_name_to_label(sf["from_table"])
        to_label   = _table_name_to_label(sf["to_table"])
        result.suggestions.append(Issue(
            code="SUGGEST_SOFT_FK",
            severity="suggestion",
            message=(f"'{sf['from_table']}.{sf['from_column']}' looks like a foreign key to "
                     f"'{sf['to_table']}' but no FOREIGN KEY constraint is declared."),
            location=f"tables.{sf['from_table']}.columns.{sf['from_column']}",
            fix_hint=(f"Confidence {sf['confidence']:.2f} — {sf['basis']}. "
                      f"Accept to add a relationship "
                      f"{from_label} → references → {to_label}."),
            apply={"op": "add_relationship",
                   "from_entity": from_label,
                   "label":       "references",
                   "to_entity":   to_label,
                   "confidence":  sf["confidence"]},
        ))

    result.stats = _stats(session)
    result.stats["sql_dialect"] = resolved_dialect or "(default)"
    result.stats["table_count"] = len(tables)
    total_cols = sum(len(t["columns"]) for t in tables)
    result.stats["column_count"] = total_cols
    result.stats["sql_column_description_coverage_pct"] = (
        round(described_cols / max(total_cols, 1) * 100) if total_cols else None
    )
    result.stats["soft_fk_count"] = len(soft_fks)
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

    # Structural schema validation (jsonschema) — runs before normalisation
    # so unknown shapes / type errors are caught with a precise pointer.
    # Optional dep: if jsonschema isn't installed, skip silently and rely
    # on the in-code semantic checks below.
    schema_errs = _jsonschema_validate(doc)
    result.errors.extend(schema_errs)
    if schema_errs:
        # Don't try to normalise an obviously-malformed doc — would crash.
        return result

    if shape == "json-wizard":
        session = _norm_wizard(doc)
    elif shape == "json-cli":
        session = _norm_cli(doc)
    elif shape == "json-schema":
        session = _norm_schema(doc)
        # T1.4 — semantic enhancements are only available for the
        # json-schema shape (the wizard/cli shapes don't carry raw
        # FK / view metadata).
        session = _apply_semantic_enhancement(session, doc, result)
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
