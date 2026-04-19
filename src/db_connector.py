"""
db_connector.py
────────────────
Database abstraction layer for the Ontology Toolkit.
Provides a unified interface over SQLite, PostgreSQL, MySQL, and SQL Server.

All four databases expose schema metadata through INFORMATION_SCHEMA
(SQL standard, supported by PostgreSQL, MySQL, SQL Server) or PRAGMA
(SQLite). This module normalises those differences behind a single
Connector interface consumed by db_introspector.py.

No external packages beyond stdlib are REQUIRED. Database-specific
drivers are imported lazily — only the driver for the selected backend
must be installed:

  SQLite      — stdlib sqlite3 (built-in, always available)
  PostgreSQL  — pip install psycopg2-binary
  MySQL       — pip install mysql-connector-python
  SQL Server  — pip install pyodbc  (requires ODBC driver 17 or 18)
  Oracle      — pip install oracledb  (thin client, no Oracle Client libs needed)
  Oracle ADB  — pip install oracledb  + wallet files from OCI console
  IBM DB2     — pip install ibm_db  (requires DB2 client libraries)

Connection string formats
─────────────────────────
SQLite:
  sqlite:///path/to/file.db
  sqlite:////absolute/path/to/file.db

PostgreSQL:
  postgresql://user:password@host:5432/dbname
  postgresql://user:password@host/dbname?sslmode=require

MySQL:
  mysql://user:password@host:3306/dbname

SQL Server:
  mssql://user:password@host/dbname?driver=ODBC+Driver+18+for+SQL+Server
  mssql://user:password@host:1433/dbname

Oracle / Oracle ADB:
  oracle://user:password@host:1521/service_name
  oracle://user:password@host:1521/service_name?mode=SYSDBA
  Oracle ADB (wallet):
  oracle://user:password@/service_name?wallet=/path/to/wallet&wallet_password=secret

IBM DB2:
  db2://user:password@host:50000/DATABASE
  db2://user:password@host:50000/DATABASE?schema=MYSCHEMA
"""

import re
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import urlparse, parse_qs, unquote


# ── Column metadata returned by every connector ──────────────────────────
class ColInfo:
    """Normalised column descriptor — same fields regardless of database."""
    def __init__(self, name: str, data_type: str, is_nullable: bool,
                 is_pk: bool, fk_table: Optional[str],
                 column_default: Optional[str] = None):
        self.name           = name
        self.data_type      = data_type     # normalised to UPPER, e.g. "TEXT", "INTEGER"
        self.is_nullable    = is_nullable
        self.is_pk          = is_pk
        self.fk_table       = fk_table      # None if not a FK; referenced table name if FK
        self.column_default = column_default

    def __repr__(self):
        return (f"ColInfo({self.name!r}, type={self.data_type}, pk={self.is_pk}, "
                f"fk→{self.fk_table or '—'}, nullable={self.is_nullable})")


# ── Abstract Connector ────────────────────────────────────────────────────
class Connector(ABC):
    """
    Unified interface for schema introspection and data querying
    across all supported databases.
    """

    @abstractmethod
    def get_tables(self) -> List[str]:
        """Return all user table names in the target schema/database."""
        ...

    @abstractmethod
    def get_columns(self, table: str) -> List[ColInfo]:
        """Return normalised column descriptors for a given table."""
        ...

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a SQL query and return rows as list of dicts."""
        ...

    @abstractmethod
    def execute_script(self, sql: str) -> None:
        """Execute a multi-statement SQL script (DDL/seed)."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the underlying connection."""
        ...

    @property
    @abstractmethod
    def dialect(self) -> str:
        """Return the SQL dialect name: 'sqlite', 'postgresql', 'mysql', 'mssql'."""
        ...

    def table_exists(self, table: str) -> bool:
        return table in self.get_tables()

    def get_row_count(self, table: str) -> int:
        try:
            rows = self.execute(f"SELECT COUNT(*) AS n FROM {self._quote(table)}")
            return rows[0]["n"] if rows else 0
        except Exception:
            return 0

    def get_distinct_values(self, table: str, column: str, limit: int = 20) -> List:
        try:
            rows = self.execute(
                f"SELECT DISTINCT {self._quote(column)} AS v "
                f"FROM {self._quote(table)} "
                f"WHERE {self._quote(column)} IS NOT NULL "
                f"LIMIT {limit}"
            )
            return [r["v"] for r in rows]
        except Exception:
            return []

    def get_sample_rows(self, table: str, limit: int = 3) -> List[Dict]:
        try:
            return self.execute(f"SELECT * FROM {self._quote(table)} LIMIT {limit}")
        except Exception:
            return []

    def _quote(self, identifier: str) -> str:
        """Quote an identifier with the appropriate dialect character."""
        if self.dialect == "mssql":
            return f"[{identifier}]"
        elif self.dialect in ("postgresql", "mysql"):
            return f'"{identifier}"'
        else:  # sqlite
            return f'"{identifier}"'


# ── SQLite Connector ──────────────────────────────────────────────────────
class SQLiteConnector(Connector):
    """
    SQLite connector. Uses PRAGMA statements for schema introspection.
    """
    # System tables never shown in ontology output
    SYSTEM_TABLES = {"ontology_metadata", "semantic_loss_log",
                     "sqlite_sequence", "sqlite_master"}

    def __init__(self, db_path: str):
        import sqlite3
        if not os.path.exists(db_path) and not db_path.startswith(":memory:"):
            raise FileNotFoundError(f"SQLite database not found: {db_path}")
        self.db_path = db_path
        self._sqlite3 = sqlite3
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    @property
    def dialect(self) -> str:
        return "sqlite"

    def get_tables(self) -> List[str]:
        rows = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r["name"] for r in rows if r["name"] not in self.SYSTEM_TABLES]

    def get_columns(self, table: str) -> List[ColInfo]:
        # FK map
        fk_rows = self.conn.execute(
            f"PRAGMA foreign_key_list({table})"
        ).fetchall()
        fk_map = {fk["from"]: fk["table"] for fk in fk_rows}

        # Column info
        col_rows = self.conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        result = []
        for row in col_rows:
            name    = row["name"]
            dtype   = (row["type"] or "TEXT").split("(")[0].upper()
            is_pk   = bool(row["pk"])
            notnull = bool(row["notnull"]) or is_pk
            result.append(ColInfo(
                name=name,
                data_type=dtype,
                is_nullable=not notnull,
                is_pk=is_pk,
                fk_table=fk_map.get(name),
                column_default=row["dflt_value"],
            ))
        return result

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cur = self.conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def execute_script(self, sql: str) -> None:
        self.conn.executescript(sql)

    def close(self) -> None:
        self.conn.close()


# ── PostgreSQL Connector ──────────────────────────────────────────────────
class PostgreSQLConnector(Connector):
    """
    PostgreSQL connector. Uses INFORMATION_SCHEMA for schema introspection.
    Requires: pip install psycopg2-binary
    """
    SYSTEM_TABLES = {"ontology_metadata", "semantic_loss_log"}

    def __init__(self, host: str, port: int, dbname: str,
                 user: str, password: str, schema: str = "public",
                 sslmode: str = "prefer"):
        try:
            import psycopg2
            import psycopg2.extras
            self._pg = psycopg2
            self._extras = psycopg2.extras
        except ImportError:
            raise ImportError(
                "PostgreSQL support requires psycopg2-binary.\n"
                "Install with: pip install psycopg2-binary"
            )
        self.schema = schema
        self.conn = psycopg2.connect(
            host=host, port=port, dbname=dbname,
            user=user, password=password, sslmode=sslmode
        )
        self.conn.autocommit = True

    @property
    def dialect(self) -> str:
        return "postgresql"

    def get_tables(self) -> List[str]:
        rows = self.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            (self.schema,)
        )
        return [r["table_name"] for r in rows
                if r["table_name"] not in self.SYSTEM_TABLES]

    def get_columns(self, table: str) -> List[ColInfo]:
        # Column info from INFORMATION_SCHEMA
        col_rows = self.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position",
            (self.schema, table)
        )

        # Primary keys via pg_constraint
        pk_rows = self.execute(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_schema = %s AND tc.table_name = %s",
            (self.schema, table)
        )
        pk_cols = {r["column_name"] for r in pk_rows}

        # Foreign keys via INFORMATION_SCHEMA REFERENTIAL_CONSTRAINTS
        fk_rows = self.execute(
            "SELECT kcu.column_name, ccu.table_name AS foreign_table "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = tc.constraint_name "
            "  AND ccu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "  AND tc.table_schema = %s AND tc.table_name = %s",
            (self.schema, table)
        )
        fk_map = {r["column_name"]: r["foreign_table"] for r in fk_rows}

        result = []
        for row in col_rows:
            name  = row["column_name"]
            dtype = _pg_to_generic(row["data_type"])
            is_pk = name in pk_cols
            result.append(ColInfo(
                name=name,
                data_type=dtype,
                is_nullable=(row["is_nullable"] == "YES") and not is_pk,
                is_pk=is_pk,
                fk_table=fk_map.get(name),
                column_default=row["column_default"],
            ))
        return result

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self.conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return [dict(r) for r in cur.fetchall()]
            return []

    def execute_script(self, sql: str) -> None:
        """Split on semicolons and execute each statement."""
        with self.conn.cursor() as cur:
            for stmt in _split_sql(sql):
                if stmt.strip():
                    cur.execute(stmt)

    def get_distinct_values(self, table: str, column: str, limit: int = 20) -> List:
        try:
            rows = self.execute(
                f'SELECT DISTINCT "{column}" AS v FROM "{self.schema}"."{table}" '
                f'WHERE "{column}" IS NOT NULL LIMIT {limit}'
            )
            return [r["v"] for r in rows]
        except Exception:
            return []

    def get_sample_rows(self, table: str, limit: int = 3) -> List[Dict]:
        try:
            return self.execute(
                f'SELECT * FROM "{self.schema}"."{table}" LIMIT {limit}'
            )
        except Exception:
            return []

    def close(self) -> None:
        self.conn.close()


# ── MySQL Connector ───────────────────────────────────────────────────────
class MySQLConnector(Connector):
    """
    MySQL / MariaDB connector. Uses INFORMATION_SCHEMA for schema introspection.
    Requires: pip install mysql-connector-python
    """
    SYSTEM_TABLES = {"ontology_metadata", "semantic_loss_log"}

    def __init__(self, host: str, port: int, database: str,
                 user: str, password: str):
        try:
            import mysql.connector
            self._mysql = mysql.connector
        except ImportError:
            raise ImportError(
                "MySQL support requires mysql-connector-python.\n"
                "Install with: pip install mysql-connector-python"
            )
        self.database = database
        self.conn = mysql.connector.connect(
            host=host, port=port, database=database,
            user=user, password=password,
            use_pure=True, autocommit=True
        )

    @property
    def dialect(self) -> str:
        return "mysql"

    def get_tables(self) -> List[str]:
        rows = self.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME",
            (self.database,)
        )
        return [r["TABLE_NAME"] for r in rows
                if r["TABLE_NAME"] not in self.SYSTEM_TABLES]

    def get_columns(self, table: str) -> List[ColInfo]:
        col_rows = self.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, "
            "COLUMN_KEY, COLUMN_DEFAULT "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (self.database, table)
        )
        fk_rows = self.execute(
            "SELECT kcu.COLUMN_NAME, kcu.REFERENCED_TABLE_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE kcu "
            "JOIN information_schema.TABLE_CONSTRAINTS tc "
            "  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
            "  AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA "
            "WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY' "
            "  AND kcu.TABLE_SCHEMA = %s AND kcu.TABLE_NAME = %s",
            (self.database, table)
        )
        fk_map = {r["COLUMN_NAME"]: r["REFERENCED_TABLE_NAME"] for r in fk_rows}

        result = []
        for row in col_rows:
            name  = row["COLUMN_NAME"]
            dtype = _mysql_to_generic(row["DATA_TYPE"])
            is_pk = row["COLUMN_KEY"] == "PRI"
            result.append(ColInfo(
                name=name,
                data_type=dtype,
                is_nullable=(row["IS_NULLABLE"] == "YES") and not is_pk,
                is_pk=is_pk,
                fk_table=fk_map.get(name),
                column_default=row["COLUMN_DEFAULT"],
            ))
        return result

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cur = self.conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
        cur.close()
        return rows

    def execute_script(self, sql: str) -> None:
        cur = self.conn.cursor()
        for stmt in _split_sql(sql):
            if stmt.strip():
                cur.execute(stmt)
        cur.close()

    def close(self) -> None:
        self.conn.close()


# ── SQL Server Connector ──────────────────────────────────────────────────
class SQLServerConnector(Connector):
    """
    Microsoft SQL Server connector. Uses INFORMATION_SCHEMA.
    Requires: pip install pyodbc  AND  ODBC Driver 17 or 18 for SQL Server.
    """
    SYSTEM_TABLES = {"ontology_metadata", "semantic_loss_log"}

    def __init__(self, host: str, port: int, database: str,
                 user: str, password: str, schema: str = "dbo",
                 driver: str = "ODBC Driver 18 for SQL Server"):
        try:
            import pyodbc
            self._pyodbc = pyodbc
        except ImportError:
            raise ImportError(
                "SQL Server support requires pyodbc.\n"
                "Install with: pip install pyodbc\n"
                "Also requires ODBC Driver 17 or 18 for SQL Server on the host OS."
            )
        self.schema   = schema
        self.database = database
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={host},{port};"
            f"DATABASE={database};"
            f"UID={user};PWD={password};"
            f"TrustServerCertificate=yes;"
        )
        self.conn = pyodbc.connect(conn_str, autocommit=True)

    @property
    def dialect(self) -> str:
        return "mssql"

    def get_tables(self) -> List[str]:
        rows = self.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME",
            (self.schema,)
        )
        return [r["TABLE_NAME"] for r in rows
                if r["TABLE_NAME"] not in self.SYSTEM_TABLES]

    def get_columns(self, table: str) -> List[ColInfo]:
        col_rows = self.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            (self.schema, table)
        )
        pk_rows = self.execute(
            "SELECT kcu.COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
            "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu "
            "  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
            "  AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA "
            "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' "
            "  AND tc.TABLE_SCHEMA = ? AND tc.TABLE_NAME = ?",
            (self.schema, table)
        )
        pk_cols = {r["COLUMN_NAME"] for r in pk_rows}

        fk_rows = self.execute(
            "SELECT kcu.COLUMN_NAME, ccu.TABLE_NAME AS FK_TABLE "
            "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
            "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu "
            "  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
            "  AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA "
            "JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu "
            "  ON ccu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
            "WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY' "
            "  AND tc.TABLE_SCHEMA = ? AND tc.TABLE_NAME = ?",
            (self.schema, table)
        )
        fk_map = {r["COLUMN_NAME"]: r["FK_TABLE"] for r in fk_rows}

        result = []
        for row in col_rows:
            name  = row["COLUMN_NAME"]
            dtype = _mssql_to_generic(row["DATA_TYPE"])
            is_pk = name in pk_cols
            result.append(ColInfo(
                name=name,
                data_type=dtype,
                is_nullable=(row["IS_NULLABLE"] == "YES") and not is_pk,
                is_pk=is_pk,
                fk_table=fk_map.get(name),
                column_default=row["COLUMN_DEFAULT"],
            ))
        return result

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            rows = []
        cur.close()
        return rows

    def execute_script(self, sql: str) -> None:
        """Split on GO or semicolons for SQL Server scripts."""
        cur = self.conn.cursor()
        for stmt in _split_sql(sql, go_delimiter=True):
            if stmt.strip():
                cur.execute(stmt)
        cur.close()

    def close(self) -> None:
        self.conn.close()


# ── Type normalisation maps ───────────────────────────────────────────────

def _pg_to_generic(pg_type: str) -> str:
    mapping = {
        "integer": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER",
        "serial": "INTEGER",  "bigserial": "INTEGER",
        "numeric": "REAL",    "decimal": "REAL",    "real": "REAL",
        "double precision": "REAL", "float": "REAL",
        "character varying": "TEXT", "varchar": "TEXT",
        "character": "TEXT",  "text": "TEXT",  "uuid": "TEXT",
        "boolean": "BOOLEAN",
        "date": "TEXT",       "timestamp without time zone": "TEXT",
        "timestamp with time zone": "TEXT", "timestamp": "TEXT",
        "jsonb": "TEXT",      "json": "TEXT",
        "bytea": "BLOB",
    }
    return mapping.get(pg_type.lower(), "TEXT")


def _mysql_to_generic(my_type: str) -> str:
    mapping = {
        "int": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER",
        "tinyint": "INTEGER", "mediumint": "INTEGER",
        "decimal": "REAL", "float": "REAL", "double": "REAL",
        "varchar": "TEXT", "char": "TEXT", "text": "TEXT",
        "mediumtext": "TEXT", "longtext": "TEXT",
        "tinytext": "TEXT", "enum": "TEXT", "set": "TEXT",
        "date": "TEXT", "datetime": "TEXT", "timestamp": "TEXT",
        "time": "TEXT", "year": "INTEGER",
        "blob": "BLOB", "longblob": "BLOB", "mediumblob": "BLOB",
        "tinyblob": "BLOB",
        "bit": "INTEGER", "boolean": "BOOLEAN", "bool": "BOOLEAN",
        "json": "TEXT",
    }
    return mapping.get(my_type.lower(), "TEXT")


def _mssql_to_generic(ms_type: str) -> str:
    mapping = {
        "int": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER",
        "tinyint": "INTEGER", "bit": "BOOLEAN",
        "decimal": "REAL", "numeric": "REAL", "float": "REAL",
        "real": "REAL", "money": "REAL", "smallmoney": "REAL",
        "nvarchar": "TEXT", "varchar": "TEXT", "char": "TEXT",
        "nchar": "TEXT", "text": "TEXT", "ntext": "TEXT",
        "uniqueidentifier": "TEXT", "xml": "TEXT",
        "date": "TEXT", "datetime": "TEXT", "datetime2": "TEXT",
        "smalldatetime": "TEXT", "datetimeoffset": "TEXT",
        "time": "TEXT",
        "binary": "BLOB", "varbinary": "BLOB", "image": "BLOB",
    }
    return mapping.get(ms_type.lower(), "TEXT")


# ── SQL script splitter ───────────────────────────────────────────────────

def _split_sql(sql: str, go_delimiter: bool = False) -> List[str]:
    """Split a multi-statement SQL script into individual statements."""
    if go_delimiter:
        # SQL Server: split on GO keyword (batch separator)
        parts = re.split(r'^\s*GO\s*$', sql, flags=re.MULTILINE | re.IGNORECASE)
    else:
        parts = sql.split(";")
    return [p.strip() for p in parts if p.strip()]


# ── Connection string parser ──────────────────────────────────────────────

def _parse_connection_string(conn_str: str) -> Dict[str, Any]:
    """Parse a connection URL into component parts."""
    parsed = urlparse(conn_str)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    host = parsed.hostname or "localhost"
    port = parsed.port
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    # Database name from path, stripping leading /
    database = (parsed.path or "").lstrip("/")

    return {
        "scheme":   parsed.scheme,
        "host":     host,
        "port":     port,
        "user":     user,
        "password": password,
        "database": database,
        "params":   params,
    }


# ── Factory function ──────────────────────────────────────────────────────


# ── Oracle / Oracle ADB Connector ────────────────────────────────────────
class OracleConnector(Connector):
    """
    Oracle Database and Oracle Autonomous Database (ADB) connector.
    Uses python-oracledb in thin mode — no Oracle Instant Client required.

    Requires: pip install oracledb

    Standard Oracle:
        OracleConnector(host="host", port=1521, service_name="ORCLPDB1",
                        user="scott", password="tiger")

    Oracle ADB (mTLS wallet):
        OracleConnector(user="admin", password="...", service_name="myatp_high",
                        wallet_dir="/path/to/wallet",
                        wallet_password="wallet_password")

    System tables are filtered using ALL_TABLES / DBA_TABLES.
    Schema defaults to the connecting user's schema.
    Oracle type names are mapped to the generic type set.
    """
    SYSTEM_SCHEMAS = {
        "SYS", "SYSTEM", "OUTLN", "DIP", "ORACLE_OCM", "DBSNMP",
        "APPQOSSYS", "WMSYS", "EXFSYS", "CTXSYS", "ANONYMOUS",
        "XDB", "XS$NULL", "MDSYS", "ORDSYS", "ORDPLUGINS",
        "SI_INFORMTN_SCHEMA", "ORDDATA", "OLAPSYS", "MDDATA",
        "SPATIAL_WFS_ADMIN_USR", "LBACSYS", "GSMADMIN_INTERNAL",
        "GSMUSER", "GSMROOTUSER", "OJVMSYS", "AUDSYS", "DVF",
        "DVSYS", "REMOTE_SCHEDULER_AGENT", "FLOWS_FILES",
    }
    SYSTEM_TABLES = {"ONTOLOGY_METADATA", "SEMANTIC_LOSS_LOG"}

    def __init__(self, user: str, password: str, service_name: str,
                 host: str = None, port: int = 1521,
                 wallet_dir: str = None, wallet_password: str = None,
                 schema: str = None, mode: str = None):
        try:
            import oracledb
            self._ora = oracledb
        except ImportError:
            raise ImportError(
                "Oracle support requires oracledb.\n"
                "Install with: pip install oracledb\n"
                "No Oracle Instant Client is required (thin mode)."
            )

        self.schema = (schema or user).upper()
        self._user  = user.upper()

        if wallet_dir:
            # Oracle ADB — mTLS wallet connection (thin mode)
            self.conn = oracledb.connect(
                user=user, password=password,
                dsn=service_name,
                wallet_location=wallet_dir,
                wallet_password=wallet_password,
            )
        else:
            # Standard Oracle
            dsn = oracledb.makedsn(host, port, service_name=service_name)
            connect_kw = dict(user=user, password=password, dsn=dsn)
            if mode and mode.upper() == "SYSDBA":
                connect_kw["mode"] = oracledb.AUTH_MODE_SYSDBA
            self.conn = oracledb.connect(**connect_kw)

    @property
    def dialect(self) -> str:
        return "oracle"

    def get_tables(self) -> List[str]:
        rows = self.execute(
            "SELECT TABLE_NAME FROM ALL_TABLES "
            "WHERE OWNER = :schema ORDER BY TABLE_NAME",
            (self.schema,)
        )
        return [r["TABLE_NAME"] for r in rows
                if r["TABLE_NAME"] not in self.SYSTEM_TABLES]

    def get_columns(self, table: str) -> List[ColInfo]:
        # Column info
        col_rows = self.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, NULLABLE, DATA_DEFAULT "
            "FROM ALL_TAB_COLUMNS "
            "WHERE OWNER = :schema AND TABLE_NAME = :table "
            "ORDER BY COLUMN_ID",
            (self.schema, table.upper())
        )

        # Primary key columns
        pk_rows = self.execute(
            "SELECT acc.COLUMN_NAME FROM ALL_CONSTRAINTS ac "
            "JOIN ALL_CONS_COLUMNS acc "
            "  ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME "
            "  AND ac.OWNER = acc.OWNER "
            "WHERE ac.CONSTRAINT_TYPE = 'P' "
            "  AND ac.OWNER = :schema AND ac.TABLE_NAME = :table",
            (self.schema, table.upper())
        )
        pk_cols = {r["COLUMN_NAME"] for r in pk_rows}

        # Foreign key columns
        fk_rows = self.execute(
            "SELECT acc.COLUMN_NAME, acc2.TABLE_NAME AS FK_TABLE "
            "FROM ALL_CONSTRAINTS ac "
            "JOIN ALL_CONS_COLUMNS acc "
            "  ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME "
            "  AND ac.OWNER = acc.OWNER "
            "JOIN ALL_CONSTRAINTS ac2 "
            "  ON ac.R_CONSTRAINT_NAME = ac2.CONSTRAINT_NAME "
            "  AND ac.R_OWNER = ac2.OWNER "
            "JOIN ALL_CONS_COLUMNS acc2 "
            "  ON ac2.CONSTRAINT_NAME = acc2.CONSTRAINT_NAME "
            "  AND ac2.OWNER = acc2.OWNER "
            "WHERE ac.CONSTRAINT_TYPE = 'R' "
            "  AND ac.OWNER = :schema AND ac.TABLE_NAME = :table",
            (self.schema, table.upper())
        )
        fk_map = {r["COLUMN_NAME"]: r["FK_TABLE"] for r in fk_rows}

        result = []
        for row in col_rows:
            name  = row["COLUMN_NAME"]
            dtype = _oracle_to_generic(row["DATA_TYPE"])
            is_pk = name in pk_cols
            result.append(ColInfo(
                name=name,
                data_type=dtype,
                is_nullable=(row["NULLABLE"] == "Y") and not is_pk,
                is_pk=is_pk,
                fk_table=fk_map.get(name),
                column_default=row.get("DATA_DEFAULT"),
            ))
        return result

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        # Oracle uses positional bind variables by name (:name) or ? — normalise
        if params and "?" in sql:
            sql = re.sub(r"\?", lambda m, c=iter(range(1, 999)): f":{next(c)}", sql)
        cur.execute(sql, params)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            rows = []
        cur.close()
        return rows

    def execute_script(self, sql: str) -> None:
        """Execute a PL/SQL-compatible multi-statement script."""
        cur = self.conn.cursor()
        for stmt in _split_sql(sql):
            s = stmt.strip()
            if s:
                # Skip SQLite-specific statements
                if any(kw in s.upper() for kw in
                       ("PRAGMA", "SQLITE_", "AUTOINCREMENT")):
                    continue
                # Convert MySQL/SQLite AUTO_INCREMENT / INTEGER PRIMARY KEY
                s = re.sub(r"INTEGER PRIMARY KEY AUTOINCREMENT",
                           "NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY", s)
                try:
                    cur.execute(s)
                except Exception:
                    pass  # Skip incompatible DDL during cross-db seeding
        self.conn.commit()
        cur.close()

    def get_distinct_values(self, table: str, column: str, limit: int = 20) -> List:
        try:
            rows = self.execute(
                f"SELECT DISTINCT {column} AS v FROM {self.schema}.{table} "
                f"WHERE {column} IS NOT NULL AND ROWNUM <= :n",
                (limit,)
            )
            return [r["V"] for r in rows]
        except Exception:
            return []

    def get_sample_rows(self, table: str, limit: int = 3) -> List[Dict]:
        try:
            return self.execute(
                f"SELECT * FROM {self.schema}.{table} WHERE ROWNUM <= :n",
                (limit,)
            )
        except Exception:
            return []

    def close(self) -> None:
        self.conn.close()


# ── IBM DB2 Connector ─────────────────────────────────────────────────────
class DB2Connector(Connector):
    """
    IBM DB2 (LUW — Linux, UNIX, Windows) connector.
    Also supports IBM Db2 on Cloud and Db2 Warehouse.

    Requires: pip install ibm_db ibm_db_dbi
    Also requires DB2 client libraries (ODBC/CLI driver from IBM).

    Connection string examples:
        db2://user:pass@host:50000/MYDB
        db2://user:pass@host:50000/MYDB?schema=MYSCHEMA
        db2://user:pass@host:50000/MYDB?security=SSL&sslcertificate=/path/cert.arm

    Schema introspection uses SYSCAT catalog views (DB2 standard).
    """
    SYSTEM_SCHEMAS = {
        "SYSIBM", "SYSCAT", "SYSSTAT", "SYSPUBLIC", "SYSIBMADM",
        "SYSTOOLS", "NULLID", "SQLJ",
    }
    SYSTEM_TABLES = {"ONTOLOGY_METADATA", "SEMANTIC_LOSS_LOG"}

    def __init__(self, host: str, port: int, database: str,
                 user: str, password: str, schema: str = None,
                 security: str = None, ssl_certificate: str = None):
        try:
            import ibm_db
            import ibm_db_dbi
            self._ibm_db     = ibm_db
            self._ibm_db_dbi = ibm_db_dbi
        except ImportError:
            raise ImportError(
                "DB2 support requires ibm_db and ibm_db_dbi.\n"
                "Install with: pip install ibm_db ibm_db_dbi\n"
                "Also requires IBM DB2 ODBC/CLI driver libraries on the host OS.\n"
                "Download from: https://www.ibm.com/support/pages/db2-odbc-cli-driver-download-and-installation-information"
            )

        self.schema   = (schema or user).upper()
        self.database = database.upper()

        conn_str = (
            f"DATABASE={database};"
            f"HOSTNAME={host};"
            f"PORT={port};"
            f"PROTOCOL=TCPIP;"
            f"UID={user};"
            f"PWD={password};"
        )
        if security == "SSL":
            conn_str += "SECURITY=SSL;"
            if ssl_certificate:
                conn_str += f"SSLServerCertificate={ssl_certificate};"

        self._ibm_conn = ibm_db.connect(conn_str, "", "")
        self.conn = ibm_db_dbi.Connection(self._ibm_conn)

    @property
    def dialect(self) -> str:
        return "db2"

    def get_tables(self) -> List[str]:
        rows = self.execute(
            "SELECT TABNAME FROM SYSCAT.TABLES "
            "WHERE TABSCHEMA = ? AND TYPE = 'T' "
            "ORDER BY TABNAME",
            (self.schema,)
        )
        return [r["TABNAME"] for r in rows
                if r["TABNAME"] not in self.SYSTEM_TABLES]

    def get_columns(self, table: str) -> List[ColInfo]:
        # Column info
        col_rows = self.execute(
            "SELECT COLNAME, TYPENAME, NULLS, DEFAULT "
            "FROM SYSCAT.COLUMNS "
            "WHERE TABSCHEMA = ? AND TABNAME = ? "
            "ORDER BY COLNO",
            (self.schema, table.upper())
        )

        # Primary key columns (via SYSCAT.KEYCOLUSE + TABCONST)
        pk_rows = self.execute(
            "SELECT k.COLNAME FROM SYSCAT.KEYCOLUSE k "
            "JOIN SYSCAT.TABCONST t "
            "  ON k.CONSTNAME = t.CONSTNAME "
            "  AND k.TABSCHEMA = t.TABSCHEMA "
            "  AND k.TABNAME = t.TABNAME "
            "WHERE t.TYPE = 'P' "
            "  AND k.TABSCHEMA = ? AND k.TABNAME = ?",
            (self.schema, table.upper())
        )
        pk_cols = {r["COLNAME"] for r in pk_rows}

        # Foreign key columns via SYSCAT.REFERENCES
        fk_rows = self.execute(
            "SELECT k.COLNAME, r.REFTABNAME AS FK_TABLE "
            "FROM SYSCAT.REFERENCES r "
            "JOIN SYSCAT.KEYCOLUSE k "
            "  ON r.CONSTNAME = k.CONSTNAME "
            "  AND r.TABSCHEMA = k.TABSCHEMA "
            "  AND r.TABNAME = k.TABNAME "
            "WHERE r.TABSCHEMA = ? AND r.TABNAME = ?",
            (self.schema, table.upper())
        )
        fk_map = {r["COLNAME"]: r["FK_TABLE"] for r in fk_rows}

        result = []
        for row in col_rows:
            name  = row["COLNAME"]
            dtype = _db2_to_generic(row["TYPENAME"])
            is_pk = name in pk_cols
            result.append(ColInfo(
                name=name,
                data_type=dtype,
                is_nullable=(row["NULLS"] == "Y") and not is_pk,
                is_pk=is_pk,
                fk_table=fk_map.get(name),
                column_default=row.get("DEFAULT"),
            ))
        return result

    def execute(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            rows = []
        cur.close()
        return rows

    def execute_script(self, sql: str) -> None:
        cur = self.conn.cursor()
        for stmt in _split_sql(sql):
            s = stmt.strip()
            if not s:
                continue
            if any(kw in s.upper() for kw in
                   ("PRAGMA", "SQLITE_", "AUTOINCREMENT")):
                continue
            # DB2 uses GENERATED ALWAYS AS IDENTITY for auto-increment
            s = re.sub(
                r"INTEGER PRIMARY KEY AUTOINCREMENT",
                "INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1) PRIMARY KEY",
                s, flags=re.IGNORECASE
            )
            try:
                cur.execute(s)
                self.conn.commit()
            except Exception:
                pass
        cur.close()

    def get_distinct_values(self, table: str, column: str, limit: int = 20) -> List:
        try:
            rows = self.execute(
                f"SELECT DISTINCT {column} AS V FROM {self.schema}.{table} "
                f"WHERE {column} IS NOT NULL FETCH FIRST {limit} ROWS ONLY"
            )
            return [r["V"] for r in rows]
        except Exception:
            return []

    def get_sample_rows(self, table: str, limit: int = 3) -> List[Dict]:
        try:
            return self.execute(
                f"SELECT * FROM {self.schema}.{table} FETCH FIRST {limit} ROWS ONLY"
            )
        except Exception:
            return []

    def close(self) -> None:
        self.conn.close()



def _oracle_to_generic(ora_type: str) -> str:
    t = ora_type.upper().split("(")[0].strip()
    mapping = {
        "NUMBER":          "REAL",
        "INTEGER":         "INTEGER",
        "INT":             "INTEGER",
        "SMALLINT":        "INTEGER",
        "BINARY_INTEGER":  "INTEGER",
        "PLS_INTEGER":     "INTEGER",
        "FLOAT":           "REAL",
        "DOUBLE PRECISION":"REAL",
        "BINARY_FLOAT":    "REAL",
        "BINARY_DOUBLE":   "REAL",
        "DECIMAL":         "REAL",
        "NUMERIC":         "REAL",
        "CHAR":            "TEXT",
        "NCHAR":           "TEXT",
        "VARCHAR2":        "TEXT",
        "NVARCHAR2":       "TEXT",
        "VARCHAR":         "TEXT",
        "LONG":            "TEXT",
        "CLOB":            "TEXT",
        "NCLOB":           "TEXT",
        "XMLTYPE":         "TEXT",
        "DATE":            "TEXT",
        "TIMESTAMP":       "TEXT",
        "TIMESTAMP WITH TIME ZONE":       "TEXT",
        "TIMESTAMP WITH LOCAL TIME ZONE": "TEXT",
        "INTERVAL YEAR TO MONTH":         "TEXT",
        "INTERVAL DAY TO SECOND":         "TEXT",
        "RAW":             "BLOB",
        "LONG RAW":        "BLOB",
        "BLOB":            "BLOB",
        "BFILE":           "BLOB",
        "ROWID":           "TEXT",
        "UROWID":          "TEXT",
        "BOOLEAN":         "BOOLEAN",
        "JSON":            "TEXT",
    }
    return mapping.get(t, "TEXT")


def _db2_to_generic(db2_type: str) -> str:
    t = db2_type.upper().split("(")[0].strip()
    mapping = {
        "INTEGER":          "INTEGER",
        "INT":              "INTEGER",
        "SMALLINT":         "INTEGER",
        "BIGINT":           "INTEGER",
        "DECIMAL":          "REAL",
        "NUMERIC":          "REAL",
        "FLOAT":            "REAL",
        "REAL":             "REAL",
        "DOUBLE":           "REAL",
        "DECFLOAT":         "REAL",
        "CHARACTER":        "TEXT",
        "CHAR":             "TEXT",
        "VARCHAR":          "TEXT",
        "LONG VARCHAR":     "TEXT",
        "CLOB":             "TEXT",
        "DBCLOB":           "TEXT",
        "GRAPHIC":          "TEXT",
        "VARGRAPHIC":       "TEXT",
        "LONG VARGRAPHIC":  "TEXT",
        "DATE":             "TEXT",
        "TIME":             "TEXT",
        "TIMESTAMP":        "TEXT",
        "BLOB":             "BLOB",
        "XML":              "TEXT",
        "BOOLEAN":          "BOOLEAN",
    }
    return mapping.get(t, "TEXT")


# ── SQL script splitter ───────────────────────────────────────────────────

def _split_sql(sql: str, go_delimiter: bool = False) -> List[str]:
    """Split a multi-statement SQL script into individual statements."""
    if go_delimiter:
        # SQL Server: split on GO keyword (batch separator)
        parts = re.split(r'^\s*GO\s*$', sql, flags=re.MULTILINE | re.IGNORECASE)
    else:
        parts = sql.split(";")
    return [p.strip() for p in parts if p.strip()]


# ── Connection string parser ──────────────────────────────────────────────

def _parse_connection_string(conn_str: str) -> Dict[str, Any]:
    """Parse a connection URL into component parts."""
    parsed = urlparse(conn_str)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    host = parsed.hostname or "localhost"
    port = parsed.port
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    # Database name from path, stripping leading /
    database = (parsed.path or "").lstrip("/")

    return {
        "scheme":   parsed.scheme,
        "host":     host,
        "port":     port,
        "user":     user,
        "password": password,
        "database": database,
        "params":   params,
    }


# ── Factory function ──────────────────────────────────────────────────────


def create_connector(connection_string: str) -> Connector:
    """
    Parse a connection string and return the appropriate Connector.

    Examples
    --------
    SQLite:
        create_connector("sqlite:///path/to/file.db")

    PostgreSQL:
        create_connector("postgresql://user:pass@localhost:5432/mydb")

    MySQL:
        create_connector("mysql://user:pass@localhost:3306/mydb")

    SQL Server:
        create_connector("mssql://user:pass@host/mydb")

    Oracle (standard):
        create_connector("oracle://user:pass@host:1521/service_name")

    Oracle ADB (wallet):
        create_connector("oracle://user:pass@/service_name?wallet=/path/to/wallet&wallet_password=secret")

    IBM DB2:
        create_connector("db2://user:pass@host:50000/DATABASE")
        create_connector("db2://user:pass@host:50000/DATABASE?schema=MYSCHEMA&security=SSL&sslcertificate=/path/cert.arm")
    """
    scheme = connection_string.split("://")[0].lower()

    if scheme == "sqlite":
        path = connection_string[len("sqlite:///"):]
        if not path:
            raise ValueError("SQLite connection string must include a path: sqlite:///path/to/file.db")
        return SQLiteConnector(path)

    p = _parse_connection_string(connection_string)

    if scheme in ("postgresql", "postgres", "pg"):
        return PostgreSQLConnector(
            host=p["host"],
            port=p["port"] or 5432,
            dbname=p["database"],
            user=p["user"],
            password=p["password"],
            sslmode=p["params"].get("sslmode", "prefer"),
        )

    if scheme == "mysql":
        return MySQLConnector(
            host=p["host"],
            port=p["port"] or 3306,
            database=p["database"],
            user=p["user"],
            password=p["password"],
        )

    if scheme in ("mssql", "sqlserver", "sql_server"):
        driver = p["params"].get("driver", "ODBC Driver 18 for SQL Server")
        schema = p["params"].get("schema", "dbo")
        return SQLServerConnector(
            host=p["host"],
            port=p["port"] or 1433,
            database=p["database"],
            user=p["user"],
            password=p["password"],
            schema=schema,
            driver=driver,
        )

    if scheme in ("oracle", "oracle+thin", "ora"):
        wallet_dir  = p["params"].get("wallet")
        wallet_pwd  = p["params"].get("wallet_password")
        schema      = p["params"].get("schema")
        mode        = p["params"].get("mode")
        # ADB with wallet: host is empty, service_name in the path
        host        = p["host"] if p["host"] else None
        return OracleConnector(
            host=host,
            port=p["port"] or 1521,
            service_name=p["database"],
            user=p["user"],
            password=p["password"],
            wallet_dir=wallet_dir,
            wallet_password=wallet_pwd,
            schema=schema,
            mode=mode,
        )

    if scheme in ("db2", "ibmdb2", "ibm_db2"):
        schema         = p["params"].get("schema")
        security       = p["params"].get("security")
        ssl_cert       = p["params"].get("sslcertificate")
        return DB2Connector(
            host=p["host"],
            port=p["port"] or 50000,
            database=p["database"],
            user=p["user"],
            password=p["password"],
            schema=schema,
            security=security,
            ssl_certificate=ssl_cert,
        )

    supported = "sqlite, postgresql, mysql, mssql, oracle, db2"
    raise ValueError(
        f"Unsupported database scheme: '{scheme}'.\n"
        f"Supported schemes: {supported}"
    )
