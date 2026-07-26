"""
db_introspector.py
──────────────────
Reads the relational database schema and the ontology_metadata
control table. Produces a normalised TableModel and ColumnModel
that every downstream generator consumes.

Database backends: SQLite, PostgreSQL, MySQL, SQL Server.
All schema introspection is routed through db_connector.py — no
direct sqlite3 calls remain in this module.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from db_connector import Connector, ColInfo, create_connector, SQLiteConnector


BASE_IRI = "https://ontology.example.com/enterprise/"
SHAPES_IRI = "https://ontology.example.com/shapes/enterprise/"
VOCAB_IRI = "https://ontology.example.com/vocab/enterprise/"
ORG_DOMAIN = "ontology.example.com"

# Tables managed by the toolkit itself — excluded from ontology generation
SYSTEM_TABLES = {
    "ontology_metadata",
    "semantic_loss_log",
    "sqlite_sequence",
    "sqlite_master",
}

# Generic type → XSD datatype mapping
# These are normalised types produced by db_connector type maps
XSD_MAP = {
    "INTEGER":  "xsd:integer",
    "INT":      "xsd:integer",
    "REAL":     "xsd:decimal",
    "NUMERIC":  "xsd:decimal",
    "TEXT":     "xsd:string",
    "BLOB":     "xsd:base64Binary",
    "BOOLEAN":  "xsd:boolean",
    "FLOAT":    "xsd:decimal",
    "DOUBLE":   "xsd:decimal",
    "DECIMAL":  "xsd:decimal",
    "BIGINT":   "xsd:integer",
    "SMALLINT": "xsd:integer",
    "VARCHAR":  "xsd:string",
    "CHAR":     "xsd:string",
    "DATE":     "xsd:date",
    "DATETIME": "xsd:dateTime",
    "TIMESTAMP":"xsd:dateTime",
}

# Column name patterns → semantic hints
SEMANTIC_HINTS = {
    r"_iri$":        "xsd:anyURI",
    r"_at$":         "xsd:dateTime",
    r"_date$":       "xsd:date",
    r"confidence":   "xsd:decimal",
    r"_score$":      "xsd:decimal",
    r"active$":      "xsd:boolean",
    r"^is_":         "xsd:boolean",
    r"_id$":         "owl:ObjectProperty",   # FK → object property
    r"^id$":         "IDENTITY",             # PK → skip as data prop
}


@dataclass
class ColumnModel:
    table_name: str
    name: str
    sqlite_type: str    # now holds the normalised generic type (INTEGER, TEXT, etc.)
    is_pk: bool
    is_fk: bool
    fk_references: Optional[str]        # "table.column"
    not_null: bool
    default_value: Optional[str]
    # From ontology_metadata
    label: Optional[str] = None
    description: Optional[str] = None
    semantic_type: Optional[str] = None  # xsd type or owl hint
    sensitivity_tier: str = "Internal"
    cq_coverage: List[str] = field(default_factory=list)
    # ── Phase A: object-property characteristics ──────────────
    is_transitive: bool = False
    is_symmetric: bool = False
    is_functional: bool = False
    is_inverse_functional: bool = False
    inverse_of: Optional[str] = None  # counterpart property name (lowerCamel)

    @property
    def class_name(self):
        return snake_to_camel(self.name)

    @property
    def property_name(self):
        return snake_to_lower_camel(self.name)

    @property
    def is_object_property(self):
        # Explicit xsd: metadata overrides the `_id$` heuristic — authors
        # can mark columns like `external_id` as plain string identifiers.
        if self.semantic_type and self.semantic_type.startswith("xsd:"):
            return False
        return (self.is_fk or
                self.semantic_type == "owl:ObjectProperty" or
                (self.name.endswith("_id") and not self.is_pk))

    @property
    def effective_xsd_type(self):
        if self.semantic_type and self.semantic_type.startswith("xsd:"):
            return self.semantic_type
        # Infer from column name patterns
        for pattern, hint in SEMANTIC_HINTS.items():
            if re.search(pattern, self.name, re.IGNORECASE):
                if hint.startswith("xsd:"):
                    return hint
        return XSD_MAP.get(self.sqlite_type.split("(")[0].upper(), "xsd:string")

    @property
    def effective_label(self):
        return self.label or snake_to_label(self.name)


@dataclass
class TableModel:
    name: str
    columns: List[ColumnModel]
    pk_columns: List[str]
    fk_map: Dict[str, str]       # column_name → referenced_table
    # From ontology_metadata
    semantic_type: Optional[str] = None    # OWL class name
    label: Optional[str] = None
    description: Optional[str] = None
    sensitivity_tier: str = "Internal"
    is_event_class: bool = False
    skos_pref_label: Optional[str] = None
    skos_alt_labels: List[str] = field(default_factory=list)
    cq_coverage: List[str] = field(default_factory=list)
    # ── Phase A: class-level axiom signals ─────────────────────
    disjoint_group: Optional[str] = None     # shared name → AllDisjointClasses
    has_key_columns: List[str] = field(default_factory=list)  # → owl:hasKey

    @property
    def class_name(self):
        return self.semantic_type or snake_to_camel(self.name)

    @property
    def effective_label(self):
        return self.label or snake_to_label(self.name)

    @property
    def class_iri(self):
        return f"{BASE_IRI}{self.class_name}"

    @property
    def shape_iri(self):
        return f"{SHAPES_IRI}{self.class_name}Shape"

    @property
    def non_pk_columns(self):
        return [c for c in self.columns if not c.is_pk]

    @property
    def data_properties(self):
        return [c for c in self.non_pk_columns
                if not c.is_object_property and
                re.search(r"^id$", c.name, re.IGNORECASE) is None]

    @property
    def object_properties(self):
        return [c for c in self.non_pk_columns if c.is_object_property]


# ── Helpers ──────────────────────────────────────────────────────────────

def snake_to_camel(s: str) -> str:
    """assets → Asset, domain_events → DomainEvent"""
    return "".join(w.capitalize() for w in s.split("_"))


def snake_to_lower_camel(s: str) -> str:
    """asset_type_id → assetTypeId"""
    parts = s.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


def snake_to_label(s: str) -> str:
    """asset_type_id → Asset Type Id"""
    return " ".join(w.capitalize() for w in s.split("_"))


def value_to_local_name(s: str) -> str:
    """Mint a Turtle-safe IRI local name from an arbitrary *data* value.

    ``snake_to_camel`` splits on underscores only, which is fine for SQL
    identifiers but not for column *values* — a status of "In Progress"
    produced ``:TroubleTicketStatusIn progress``, an IRI containing a
    space, which makes the whole file unparseable.

    Splits on every non-alphanumeric run, so "In Progress", "in-progress"
    and "in_progress" all mint ``InProgress``. Returns "" when the value
    contains nothing usable, so callers can skip it rather than emit a
    malformed IRI.
    """
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", s or "") if p]
    if not parts:
        return ""
    out = []
    for p in parts:
        # SQL enum values are conventionally SHOUTED (INCIDENT,
        # COMPLIANCE_AUDIT). Preserving that case verbatim produced
        # :INCIDENTEvent and :COMPLIANCEAUDITEvent. An all-caps run is
        # folded before capitalising; mixed-case input (inProgress) is left
        # alone so intentional camelCase survives.
        if p.isupper():
            p = p.lower()
        out.append(p[:1].upper() + p[1:])
    return "".join(out)


# ── Introspector ─────────────────────────────────────────────────────────

class DBIntrospector:
    def __init__(self, db_path_or_connector, connection_string: str = None):
        """
        Accepts either:
          - A file path string (SQLite, backward-compatible)
          - A connection string URL: "postgresql://...", "mysql://...", "mssql://..."
          - An already-constructed Connector instance
        """
        if isinstance(db_path_or_connector, Connector):
            self._connector = db_path_or_connector
            self.db_path = getattr(db_path_or_connector, "db_path", "")
        elif isinstance(db_path_or_connector, str):
            raw = connection_string or db_path_or_connector
            if "://" in raw:
                self._connector = create_connector(raw)
            else:
                # Legacy: plain file path → SQLite
                if not os.path.exists(db_path_or_connector):
                    raise FileNotFoundError(f"Database not found: {db_path_or_connector}")
                self._connector = SQLiteConnector(db_path_or_connector)
            self.db_path = db_path_or_connector
        else:
            raise TypeError(f"Expected path string or Connector, got {type(db_path_or_connector)}")

        # Expose raw connection for backward-compat callers that use self.conn.execute()
        self.conn = self._connector

        self._metadata_cache: Dict[str, Dict] = {}
        self._col_metadata_cache: Dict[str, Dict] = {}
        self._load_metadata()

    def _load_metadata(self):
        try:
            rows = self._connector.execute("SELECT * FROM ontology_metadata")
        except Exception:
            return
        for row in rows:
            if row["target_type"] == "TABLE":
                self._metadata_cache[row["table_name"]] = dict(row)
            elif row["target_type"] == "COLUMN":
                key = f"{row['table_name']}.{row['column_name']}"
                self._col_metadata_cache[key] = dict(row)

    def _get_fk_map(self, table: str) -> Dict[str, str]:
        cols = self._connector.get_columns(table)
        return {c.name: c.fk_table for c in cols if c.fk_table}

    def _get_columns(self, table: str, fk_map: Dict) -> List[ColumnModel]:
        col_infos = self._connector.get_columns(table)
        models = []
        for ci in col_infos:
            col_meta = self._col_metadata_cache.get(f"{table}.{ci.name}", {})
            cq = [x.strip() for x in col_meta.get("cq_coverage", "").split(",")
                  if x.strip()] if col_meta.get("cq_coverage") else []
            models.append(ColumnModel(
                table_name=table,
                name=ci.name,
                sqlite_type=ci.data_type,   # normalised generic type
                is_pk=ci.is_pk,
                is_fk=ci.fk_table is not None,
                fk_references=f"{ci.fk_table}.id" if ci.fk_table else None,
                not_null=(not ci.is_nullable) or ci.is_pk,
                default_value=ci.column_default,
                label=col_meta.get("label"),
                description=col_meta.get("description"),
                semantic_type=col_meta.get("semantic_type"),
                sensitivity_tier=col_meta.get("sensitivity_tier", "Internal"),
                cq_coverage=cq,
                is_transitive=bool(col_meta.get("is_transitive", 0)),
                is_symmetric=bool(col_meta.get("is_symmetric", 0)),
                is_functional=bool(col_meta.get("is_functional", 0)),
                is_inverse_functional=bool(col_meta.get("is_inverse_functional", 0)),
                inverse_of=col_meta.get("inverse_of"),
            ))
        return models

    def get_tables(self) -> List[str]:
        return self._connector.get_tables()

    def _infer_key_columns(self, table: str) -> List[str]:
        """Columns under a UNIQUE constraint, as owl:hasKey candidates.

        Surrogate auto-increment `id` primary keys are excluded: they carry
        no domain meaning, so keying on them says nothing useful. Only
        SQLite is introspected today; other backends return no candidates
        rather than a wrong guess.
        """
        conn = getattr(self._connector, "conn", None)
        if conn is None or not hasattr(conn, "execute"):
            return []
        try:
            indexes = list(conn.execute(f"PRAGMA index_list({table})"))
        except Exception:
            return []
        keys: List[str] = []
        for idx in indexes:
            # (seq, name, unique, origin, partial)
            if not (len(idx) > 2 and idx[2]):
                continue
            try:
                cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx[1]})")]
            except Exception:
                continue
            if not cols or any(c is None for c in cols):
                continue
            if all(c == "id" for c in cols):
                continue
            keys.extend(c for c in cols if c not in keys)
        return keys

    def introspect_table(self, table: str) -> TableModel:
        meta = self._metadata_cache.get(table, {})
        fk_map = self._get_fk_map(table)   # now delegates to connector
        columns = self._get_columns(table, fk_map)
        pk_cols = [c.name for c in columns if c.is_pk]

        alt_labels = []
        if meta.get("skos_alt_labels"):
            alt_labels = [x.strip() for x in meta["skos_alt_labels"].split(",") if x.strip()]

        cq = []
        if meta.get("cq_coverage"):
            cq = [x.strip() for x in meta["cq_coverage"].split(",") if x.strip()]

        has_key_cols: List[str] = []
        if meta.get("has_key_columns"):
            has_key_cols = [x.strip() for x in meta["has_key_columns"].split(",") if x.strip()]
        else:
            # Derive owl:hasKey from UNIQUE constraints when no author has
            # declared one. The ontology_metadata columns that drive the
            # advanced axioms are populated in no shipped database, so this
            # code path had never produced a single owl:hasKey — the schema
            # already states the identity, it was simply never read.
            #
            # A UNIQUE constraint is a genuine identity claim, so this is
            # sound. Transitivity and inverses are *not* inferred: a
            # self-referencing FK named `parent_org_id` means "direct
            # parent", and asserting owl:TransitiveProperty over it would
            # manufacture relationships the data does not contain.
            has_key_cols = self._infer_key_columns(table)

        return TableModel(
            name=table,
            columns=columns,
            pk_columns=pk_cols,
            fk_map=fk_map,
            semantic_type=meta.get("semantic_type"),
            label=meta.get("label"),
            description=meta.get("description"),
            sensitivity_tier=meta.get("sensitivity_tier", "Internal"),
            is_event_class=bool(meta.get("is_event_class", 0)),
            skos_pref_label=meta.get("skos_pref_label"),
            skos_alt_labels=alt_labels,
            cq_coverage=cq,
            disjoint_group=meta.get("disjoint_group"),
            has_key_columns=has_key_cols,
        )

    def introspect_all(self) -> List[TableModel]:
        return [self.introspect_table(t) for t in self.get_tables()]

    def get_sample_rows(self, table: str, limit: int = 3) -> List[Dict]:
        return self._connector.get_sample_rows(table, limit)

    def get_distinct_values(self, table: str, column: str) -> List:
        return self._connector.get_distinct_values(table, column)

    def close(self):
        self._connector.close()
