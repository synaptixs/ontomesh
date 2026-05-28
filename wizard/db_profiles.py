"""
wizard/db_profiles.py
─────────────────────
Connection-profile management for the Wizard's "Connect to database"
import path. Sister to ``wizard/importer.py`` (which handles file
imports) — the two end up writing the same session-shaped dict.

Three responsibilities:

1. **Vendor catalogue** (:data:`VENDORS`) declares which fields each
   driver needs (host / port / dbname / user / password / …) and which
   are required vs optional. The wizard UI renders this directly so
   adding a new vendor here surfaces in the browser without any UI
   change.

2. **Profile CRUD** — list / get / save / delete profiles in a new
   SQLite table ``db_connection_profiles``. Passwords are
   base64-obfuscated at rest. **This is not real encryption** — it's
   a "shoulder-surfer" defence so the value isn't legible in
   ``sqlite3 ... SELECT *``. Document this clearly to operators; the
   right home for secrets in production is a key store.

3. **Connection string assembly** — a profile + a vendor template
   produces the URL :func:`src.db_connector.create_connector`
   consumes. Keeping URL-construction here, in one place, means the
   UI and the CLI agree on the same shape.

The downstream introspection path (table walk → wizard session) lives
in a companion helper, :func:`introspect_to_session`, kept here for
proximity to the profile object that drives it.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote_plus


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


# ── Vendor metadata (DB1) ───────────────────────────────────────────────


def _field(name: str, label: str, *, required: bool = False,
           secret: bool = False, kind: str = "text",
           default: Any = None, hint: str = "") -> dict:
    """Sugar for declaring a vendor field schema."""
    return {
        "name": name, "label": label, "required": required,
        "secret": secret, "kind": kind, "default": default, "hint": hint,
    }


VENDORS: Dict[str, dict] = {
    "sqlite": {
        "label": "SQLite",
        "icon": "📁",
        "description": "A single file on disk. The toolkit's default; perfect for demos.",
        "fields": [
            _field("db_path", "Database file path", required=True,
                   hint="Absolute or relative path to the .db file."),
        ],
    },
    "postgresql": {
        "label": "PostgreSQL",
        "icon": "🐘",
        "description": "Postgres 11+ via psycopg2.",
        "fields": [
            _field("host",     "Host",     required=True, default="localhost"),
            _field("port",     "Port",     required=True, kind="number", default=5432),
            _field("dbname",   "Database", required=True),
            _field("user",     "Username", required=True),
            _field("password", "Password", required=True, secret=True),
            _field("sslmode",  "SSL mode", kind="select",
                   default="prefer",
                   hint="One of: disable / allow / prefer / require / verify-ca / verify-full"),
        ],
    },
    "mysql": {
        "label": "MySQL / MariaDB",
        "icon": "🐬",
        "description": "MySQL 5.7+ / MariaDB via mysql-connector-python.",
        "fields": [
            _field("host",     "Host",     required=True, default="localhost"),
            _field("port",     "Port",     required=True, kind="number", default=3306),
            _field("database", "Database", required=True),
            _field("user",     "Username", required=True),
            _field("password", "Password", required=True, secret=True),
        ],
    },
    "mssql": {
        "label": "SQL Server",
        "icon": "🪟",
        "description": "Microsoft SQL Server 2017+ via pyodbc.",
        "fields": [
            _field("host",     "Host",     required=True, default="localhost"),
            _field("port",     "Port",     required=True, kind="number", default=1433),
            _field("database", "Database", required=True),
            _field("user",     "Username", required=True),
            _field("password", "Password", required=True, secret=True),
            _field("driver",   "ODBC Driver",
                   default="ODBC Driver 18 for SQL Server",
                   hint="Driver name as registered with the ODBC manager"),
        ],
    },
    "oracle": {
        "label": "Oracle",
        "icon": "🅾",
        "description": "Oracle 19c+ / Autonomous DB via python-oracledb (thin mode).",
        "fields": [
            _field("user",         "Username",     required=True),
            _field("password",     "Password",     required=True, secret=True),
            _field("host",         "Host",         default="localhost",
                   hint="Leave empty when using a TNS wallet"),
            _field("port",         "Port",         kind="number", default=1521),
            _field("service_name", "Service name", required=True),
            _field("mode",         "Connect mode", kind="select", default="NORMAL",
                   hint="NORMAL / SYSDBA / SYSOPER"),
            _field("wallet",       "Wallet path",  kind="text",
                   hint="Optional — for Oracle Autonomous DB connections"),
            _field("wallet_password", "Wallet password", secret=True,
                   hint="Required when wallet path is set"),
        ],
    },
    "db2": {
        "label": "IBM DB2",
        "icon": "🔵",
        "description": "IBM DB2 11.5+ via ibm_db.",
        "fields": [
            _field("host",     "Host",     required=True, default="localhost"),
            _field("port",     "Port",     required=True, kind="number", default=50000),
            _field("database", "Database", required=True),
            _field("user",     "Username", required=True),
            _field("password", "Password", required=True, secret=True),
            _field("schema",   "Default schema",
                   hint="Optional — restricts introspection to this schema"),
            _field("security", "Security",  kind="select", default="",
                   hint="One of: '' (no TLS), 'SSL'"),
            _field("sslcertificate", "SSL certificate path",
                   hint="Required when security=SSL"),
        ],
    },
}


def vendor_list() -> List[dict]:
    """Return the vendor catalogue in stable order for the UI dropdown."""
    return [{"id": vid, **{k: v for k, v in spec.items() if k != "fields"},
             "fields": spec["fields"]}
            for vid, spec in VENDORS.items()]


def vendor_required_fields(vendor: str) -> List[str]:
    spec = VENDORS.get(vendor)
    if not spec:
        return []
    return [f["name"] for f in spec["fields"] if f.get("required")]


# ── Connection string assembly ─────────────────────────────────────────


def build_connection_string(vendor: str, config: dict) -> str:
    """Render `config` into the URL `src/db_connector.create_connector`
    consumes. Raises ValueError when required fields are missing."""
    spec = VENDORS.get(vendor)
    if not spec:
        raise ValueError(f"Unknown vendor: {vendor!r}")
    missing = [f["name"] for f in spec["fields"]
               if f.get("required") and not str(config.get(f["name"]) or "").strip()]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    def q(v): return quote_plus(str(v)) if v not in (None, "") else ""

    if vendor == "sqlite":
        path = str(config["db_path"]).strip()
        # Triple-slash for relative, quadruple for absolute.
        if path.startswith("/"):
            return f"sqlite:///{path}"
        return f"sqlite:///{path}"

    if vendor == "postgresql":
        url = (f"postgresql://{q(config['user'])}:{q(config['password'])}"
               f"@{config['host']}:{int(config.get('port') or 5432)}"
               f"/{q(config['dbname'])}")
        if config.get("sslmode"):
            url += f"?sslmode={config['sslmode']}"
        return url

    if vendor == "mysql":
        return (f"mysql://{q(config['user'])}:{q(config['password'])}"
                f"@{config['host']}:{int(config.get('port') or 3306)}"
                f"/{q(config['database'])}")

    if vendor == "mssql":
        url = (f"mssql://{q(config['user'])}:{q(config['password'])}"
               f"@{config['host']}:{int(config.get('port') or 1433)}"
               f"/{q(config['database'])}")
        if config.get("driver"):
            url += f"?driver={quote_plus(config['driver'])}"
        return url

    if vendor == "oracle":
        host = (config.get("host") or "").strip()
        port = int(config.get("port") or 1521)
        host_port = f"{host}:{port}" if host else ""
        url = (f"oracle://{q(config['user'])}:{q(config['password'])}"
               f"@{host_port}/{q(config['service_name'])}")
        params = []
        if config.get("mode") and config["mode"].upper() != "NORMAL":
            params.append(f"mode={config['mode']}")
        if config.get("wallet"):
            params.append(f"wallet={quote_plus(config['wallet'])}")
        if config.get("wallet_password"):
            params.append(f"wallet_password={q(config['wallet_password'])}")
        if params:
            url += "?" + "&".join(params)
        return url

    if vendor == "db2":
        url = (f"db2://{q(config['user'])}:{q(config['password'])}"
               f"@{config['host']}:{int(config.get('port') or 50000)}"
               f"/{q(config['database'])}")
        params = []
        if config.get("schema"):
            params.append(f"schema={quote_plus(config['schema'])}")
        if config.get("security"):
            params.append(f"security={config['security']}")
        if config.get("sslcertificate"):
            params.append(f"sslcertificate={quote_plus(config['sslcertificate'])}")
        if params:
            url += "?" + "&".join(params)
        return url

    raise ValueError(f"No URL template for vendor {vendor!r}")


# ── Password obfuscation ──────────────────────────────────────────────


_OBF_PREFIX = "obf:"


def _obfuscate(value: str) -> str:
    if not value:
        return ""
    return _OBF_PREFIX + base64.b64encode(value.encode("utf-8")).decode("ascii")


def _deobfuscate(value: str) -> str:
    if not value or not value.startswith(_OBF_PREFIX):
        return value
    try:
        return base64.b64decode(value[len(_OBF_PREFIX):]).decode("utf-8")
    except Exception:                           # noqa: BLE001
        return ""


def _secret_field_names(vendor: str) -> set:
    spec = VENDORS.get(vendor)
    if not spec:
        return set()
    return {f["name"] for f in spec["fields"] if f.get("secret")}


def _obfuscate_secrets(vendor: str, config: dict) -> dict:
    secrets = _secret_field_names(vendor)
    return {k: (_obfuscate(v) if k in secrets and isinstance(v, str) else v)
            for k, v in config.items()}


def _deobfuscate_secrets(vendor: str, config: dict) -> dict:
    secrets = _secret_field_names(vendor)
    return {k: (_deobfuscate(v) if k in secrets and isinstance(v, str) else v)
            for k, v in config.items()}


def _mask_secrets(vendor: str, config: dict) -> dict:
    """For listing — never expose the password value back to the UI."""
    secrets = _secret_field_names(vendor)
    return {k: ("●●●●●●" if k in secrets and v else v)
            for k, v in config.items()}


# ── Schema ─────────────────────────────────────────────────────────────


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS db_connection_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    vendor      TEXT NOT NULL,
    config_json TEXT NOT NULL,      -- vendor-config (passwords base64-obfuscated)
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_db_profiles_vendor ON db_connection_profiles(vendor);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_CREATE_SQL)
    conn.commit()


# ── Profile CRUD (DB2) ─────────────────────────────────────────────────


@dataclass
class Profile:
    id: Optional[int]
    name: str
    vendor: str
    config: dict             # plain (deobfuscated) config — never persist directly
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self, *, mask_secrets: bool = True) -> dict:
        cfg = _mask_secrets(self.vendor, self.config) if mask_secrets else self.config
        return {
            "id": self.id, "name": self.name, "vendor": self.vendor,
            "config": cfg,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


def list_profiles(conn: sqlite3.Connection) -> List[Profile]:
    ensure_schema(conn)
    out: List[Profile] = []
    for row in conn.execute(
        "SELECT id, name, vendor, config_json, created_at, updated_at "
        "FROM db_connection_profiles ORDER BY name"
    ):
        out.append(Profile(
            id=row[0], name=row[1], vendor=row[2],
            config=_deobfuscate_secrets(row[2], json.loads(row[3])),
            created_at=row[4], updated_at=row[5],
        ))
    return out


def get_profile(conn: sqlite3.Connection, profile_id: int) -> Optional[Profile]:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id, name, vendor, config_json, created_at, updated_at "
        "FROM db_connection_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    if not row:
        return None
    return Profile(
        id=row[0], name=row[1], vendor=row[2],
        config=_deobfuscate_secrets(row[2], json.loads(row[3])),
        created_at=row[4], updated_at=row[5],
    )


def save_profile(conn: sqlite3.Connection, *,
                 name: str, vendor: str, config: dict,
                 profile_id: Optional[int] = None) -> Profile:
    """Insert when ``profile_id`` is None, otherwise update.

    Raises ValueError on missing required fields or unknown vendor.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name is required")
    if vendor not in VENDORS:
        raise ValueError(f"Unknown vendor: {vendor!r}")
    # Validate required fields by attempting URL assembly.
    build_connection_string(vendor, config)

    ensure_schema(conn)
    obf = _obfuscate_secrets(vendor, config)
    cfg_json = json.dumps(obf, sort_keys=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if profile_id is None:
        cur = conn.execute(
            "INSERT INTO db_connection_profiles (name, vendor, config_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (name, vendor, cfg_json, now),
        )
        profile_id = cur.lastrowid
    else:
        conn.execute(
            "UPDATE db_connection_profiles SET name=?, vendor=?, config_json=?, updated_at=? "
            "WHERE id=?",
            (name, vendor, cfg_json, now, profile_id),
        )
    conn.commit()
    p = get_profile(conn, profile_id)
    assert p is not None
    return p


def delete_profile(conn: sqlite3.Connection, profile_id: int) -> bool:
    ensure_schema(conn)
    cur = conn.execute(
        "DELETE FROM db_connection_profiles WHERE id = ?", (profile_id,)
    )
    conn.commit()
    return cur.rowcount > 0


# ── Connection test + introspection (DB3) ─────────────────────────────


@dataclass
class TestResult:
    ok: bool
    vendor: str
    tables: int = 0
    sample_tables: List[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "vendor": self.vendor, "tables": self.tables,
            "sample_tables": self.sample_tables, "error": self.error,
            "duration_ms": self.duration_ms,
        }


def probe_connection(vendor: str, config: dict) -> TestResult:
    """Attempt to open a connection, count tables, return a small
    sample. Never raises — failures land in ``error``."""
    started = time.perf_counter()
    try:
        url = build_connection_string(vendor, config)
    except ValueError as exc:
        return TestResult(ok=False, vendor=vendor, error=str(exc))
    try:
        from db_connector import create_connector       # noqa: E402
    except ImportError as exc:                           # pragma: no cover
        return TestResult(ok=False, vendor=vendor,
                          error=f"db_connector not importable: {exc}")
    try:
        connector = create_connector(url)
    except Exception as exc:                            # noqa: BLE001
        return TestResult(
            ok=False, vendor=vendor,
            error=f"Could not connect: {type(exc).__name__}: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    try:
        tables = connector.get_tables()
    except Exception as exc:                            # noqa: BLE001
        return TestResult(
            ok=False, vendor=vendor,
            error=f"Connected but could not list tables: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        try:
            connector.close()
        except Exception:                               # noqa: BLE001
            pass
    return TestResult(
        ok=True, vendor=vendor, tables=len(tables),
        sample_tables=sorted(tables)[:12],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def introspect_to_session(vendor: str, config: dict,
                          *, domain_name: str = "",
                          base_iri: str = "") -> dict:
    """Walk every table and assemble a wizard-shaped session.

    Mirrors the JSON-schema importer's output shape so the same
    review modal handles both paths. Foreign keys become
    relationships; columns become per-entity property hints.

    Raises RuntimeError on connection/introspection failure with a
    user-readable message.
    """
    url = build_connection_string(vendor, config)
    try:
        from db_introspector import DBIntrospector       # noqa: E402
    except ImportError as exc:                            # pragma: no cover
        raise RuntimeError(f"db_introspector not importable: {exc}") from exc

    try:
        intro = DBIntrospector(url, connection_string=url)
    except Exception as exc:                              # noqa: BLE001
        raise RuntimeError(f"Could not connect: {exc}") from exc
    try:
        tables = intro.introspect_all()
    finally:
        intro.close()

    entities: List[dict] = []
    relationships: List[dict] = []
    for t in tables:
        # Hand-rolled property list — keep it small; the regular wizard
        # editor will let the user tune later.
        props: List[dict] = []
        for col in t.columns:
            if col.is_pk:
                continue
            if col.is_object_property:
                continue       # surfaced as a relationship below
            props.append({
                "name": col.name,
                "label": col.effective_label,
                "type": col.effective_xsd_type,
                "sensitivity": col.sensitivity_tier or "Internal",
            })
        entities.append({
            "name": t.name,
            "label": t.effective_label,
            "description": t.description or "",
            "sensitivity": t.sensitivity_tier or "Internal",
            "is_event": bool(t.is_event_class),
            "properties": props,
            "source": "db-import",
        })
        for col in t.columns:
            if col.is_fk and col.fk_references:
                ref_table = col.fk_references.split(".")[0]
                relationships.append({
                    "from_entity": t.effective_label,
                    "label": col.name.replace("_id", "").replace("_", " ").strip() or "references",
                    "to_entity": ref_table,
                    "source": "db-import",
                })

    return {
        "domain": {
            "name": domain_name or f"{vendor.title()} import",
            "description": f"Auto-imported from {vendor} — {len(tables)} tables.",
            "base_iri": base_iri or "https://ontology.example.com/import/",
        },
        "entities": entities,
        "events": [e for e in entities if e.get("is_event")],
        "relationships": relationships,
        "competency_questions": [],
        "rules": [],
        "_source": "db-import",
        "_vendor": vendor,
        "_imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


__all__ = [
    "Profile", "TestResult", "VENDORS",
    "build_connection_string",
    "delete_profile", "ensure_schema",
    "get_profile", "introspect_to_session",
    "list_profiles", "save_profile",
    "probe_connection", "vendor_list", "vendor_required_fields",
]
