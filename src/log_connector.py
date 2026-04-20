"""
log_connector.py — Phase 2A / S6–S8
─────────────────────────────────────
Structured log ingestion for the Ontology Engineering Toolkit.

Reads log files in four formats and converts each entry into an
ObservationRecord or DomainEvent row anchored to ontology_metadata
class names, storing results in the enterprise SQLite database.

Supported formats
  JSON-lines      — one JSON object per line
  syslog RFC5424  — <priority>version timestamp host app procid msgid msg
  CEF             — Common Event Format (ArcSight/security appliances)
  OpenTelemetry   — OTLP JSON trace/span records
  Plain regex     — user-supplied named-group regex

Output tables
  observations    — numeric/scalar metrics with confidence + PROV-O columns
  domain_events   — discrete domain events with agent link
  semantic_loss_log — rejected records with loss_type=REJECTED_AT_LOG_INGEST

CLI
  python3 toolkit.py --phase log --log-path /var/log/app.log
  python3 toolkit.py --phase log --log-path /var/log/*.log --format jsonl
  python3 toolkit.py --phase log --log-path /var/log/app.log --format syslog --dry-run
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

# Derivation method for all log-sourced records
_DERIVATION = "IMPORTED"
_AGENT_NAME = "log_connector"

# Syslog severity → confidence score mapping
_SYSLOG_CONFIDENCE = {
    0: 1.0,   # Emergency
    1: 1.0,   # Alert
    2: 0.95,  # Critical
    3: 0.90,  # Error
    4: 0.75,  # Warning
    5: 0.60,  # Notice
    6: 0.50,  # Informational
    7: 0.35,  # Debug
}

# CEF severity string → confidence
_CEF_CONFIDENCE = {
    "10": 1.0, "9": 1.0,            # Very-High
    "8": 0.90, "7": 0.85,           # High
    "6": 0.75, "5": 0.70,           # Medium
    "4": 0.60, "3": 0.55,           # Low
    "2": 0.40, "1": 0.35, "0": 0.30 # Very-Low / Unknown
}

# ── Parsed record dataclass ───────────────────────────────────────────────

class LogRecord:
    """Normalised intermediate representation of one log entry."""
    __slots__ = (
        "source_file", "line_no", "raw",
        "timestamp", "message", "severity",
        "host", "app", "pid",
        "fields",               # dict of extracted k/v pairs
        "entity_type",          # matched ontology class name (or None)
        "entity_id",            # external identifier of the matched entity
        "observation_value",    # numeric value if present
        "observation_unit",     # unit string if present
        "confidence",           # float 0.0–1.0
        "format",               # 'jsonl' | 'syslog' | 'cef' | 'otlp' | 'regex'
    )

    def __init__(self):
        self.source_file = ""
        self.line_no     = 0
        self.raw         = ""
        self.timestamp   = ""
        self.message     = ""
        self.severity    = ""
        self.host        = ""
        self.app         = ""
        self.pid         = ""
        self.fields: Dict = {}
        self.entity_type     = None
        self.entity_id       = None
        self.observation_value = None
        self.observation_unit  = None
        self.confidence        = 0.5
        self.format            = "unknown"

    def source_ref(self) -> str:
        return f"{self.source_file}:{self.line_no}"


# ── Format parsers ────────────────────────────────────────────────────────

# Syslog RFC5424:  <PRI>VERSION TIMESTAMP HOST APP PID MSGID MSG
_SYSLOG_RE = re.compile(
    r"^<(?P<pri>\d+)>(?P<ver>\d+)\s+"
    r"(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<app>\S+)\s+"
    r"(?P<pid>\S+)\s+(?P<msgid>\S+)\s+(?P<msg>.*)$"
)
# Fallback: BSD syslog  MMM DD HH:MM:SS host app[pid]: msg
_BSD_SYSLOG_RE = re.compile(
    r"^(?P<ts>\w{3}\s+\d+\s+[\d:]+)\s+(?P<host>\S+)\s+"
    r"(?P<app>\S+?)(?:\[(?P<pid>\d+)\])?:\s+(?P<msg>.*)$"
)
# CEF: CEF:version|device_vendor|device_product|device_version|sig_id|name|severity|extensions
_CEF_RE = re.compile(
    r"^(?:.*?)?CEF:(?P<ver>\d+)\|(?P<vendor>[^|]*)\|(?P<product>[^|]*)\|"
    r"(?P<dev_ver>[^|]*)\|(?P<sig_id>[^|]*)\|(?P<name>[^|]*)\|"
    r"(?P<severity>[^|]*)\|(?P<ext>.*)$"
)


def _parse_jsonl(line: str, lineno: int, path: str) -> Optional[LogRecord]:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    r = LogRecord()
    r.source_file = path
    r.line_no     = lineno
    r.raw         = line
    r.format      = "jsonl"
    r.fields      = d
    r.timestamp   = str(d.get("timestamp") or d.get("time") or d.get("ts") or d.get("@timestamp", ""))
    r.message     = str(d.get("message") or d.get("msg") or d.get("text", ""))
    r.severity    = str(d.get("level") or d.get("severity") or d.get("loglevel", "")).upper()
    r.host        = str(d.get("host") or d.get("hostname", ""))
    r.app         = str(d.get("service") or d.get("app") or d.get("source", ""))
    # Numeric observation value
    for key in ("value", "metric_value", "metric", "count", "duration_ms"):
        if key in d and d[key] is not None:
            try:
                r.observation_value = float(d[key])
                r.observation_unit  = str(d.get("unit", ""))
                break
            except (TypeError, ValueError):
                pass
    # Confidence from severity
    sev_map = {"CRITICAL": 0.95, "ERROR": 0.85, "WARNING": 0.70,
               "WARN": 0.70, "INFO": 0.55, "DEBUG": 0.35, "TRACE": 0.25}
    r.confidence = sev_map.get(r.severity, 0.50)
    return r


def _parse_syslog(line: str, lineno: int, path: str) -> Optional[LogRecord]:
    r = LogRecord()
    r.source_file = path
    r.line_no     = lineno
    r.raw         = line
    r.format      = "syslog"
    m = _SYSLOG_RE.match(line)
    if m:
        pri = int(m.group("pri"))
        severity_num = pri & 0x07
        r.timestamp  = m.group("ts")
        r.host       = m.group("host")
        r.app        = m.group("app")
        r.pid        = m.group("pid")
        r.message    = m.group("msg")
        r.severity   = str(severity_num)
        r.confidence = _SYSLOG_CONFIDENCE.get(severity_num, 0.50)
        return r
    m = _BSD_SYSLOG_RE.match(line)
    if m:
        r.timestamp = m.group("ts")
        r.host      = m.group("host")
        r.app       = m.group("app")
        r.pid       = m.group("pid") or ""
        r.message   = m.group("msg")
        r.confidence = 0.55
        return r
    # Plain text line fallback
    r.message    = line
    r.confidence = 0.40
    return r


def _parse_cef(line: str, lineno: int, path: str) -> Optional[LogRecord]:
    if "CEF:" not in line:
        return None
    r = LogRecord()
    r.source_file = path
    r.line_no     = lineno
    r.raw         = line
    r.format      = "cef"
    m = _CEF_RE.match(line)
    if not m:
        return None
    r.app      = m.group("product")
    r.severity = m.group("severity")
    r.message  = m.group("name")
    r.confidence = _CEF_CONFIDENCE.get(m.group("severity").strip(), 0.50)
    # Parse CEF extension key=value pairs
    ext = m.group("ext")
    for kv in re.finditer(r"(\w+)=((?:[^=\\]|\\.)*?)(?=\s+\w+=|$)", ext):
        r.fields[kv.group(1)] = kv.group(2).strip()
    r.timestamp  = r.fields.get("rt") or r.fields.get("end") or r.fields.get("start", "")
    r.host       = r.fields.get("dhost") or r.fields.get("shost", "")
    return r


def _parse_otlp(line: str, lineno: int, path: str) -> Optional[LogRecord]:
    """OpenTelemetry JSON span/trace record."""
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    if "traceId" not in d and "resourceSpans" not in d:
        return None
    r = LogRecord()
    r.source_file = path
    r.line_no     = lineno
    r.raw         = line
    r.format      = "otlp"
    r.fields      = d
    r.message     = d.get("name") or str(d.get("kind", "span"))
    # Duration as observation value (nanoseconds → ms)
    start = d.get("startTimeUnixNano")
    end   = d.get("endTimeUnixNano")
    if start and end:
        try:
            r.observation_value = (int(end) - int(start)) / 1_000_000
            r.observation_unit  = "ms"
        except (TypeError, ValueError):
            pass
    r.timestamp  = str(d.get("startTimeUnixNano", ""))
    r.confidence = 0.80  # OTLP is instrumented data — high confidence
    r.severity   = "INFO"
    return r


# ── Entity matcher ────────────────────────────────────────────────────────

class EntityMatcher:
    """
    Matches log record text against ontology class names loaded from
    ontology_metadata. Returns (class_name, entity_id) or (None, None).
    """

    def __init__(self, db_path: str):
        self._patterns: List[Tuple[re.Pattern, str]] = []
        self._load(db_path)

    def _load(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT DISTINCT semantic_type, table_name, label FROM ontology_metadata "
                "WHERE target_type='TABLE' AND semantic_type IS NOT NULL"
            ).fetchall()
            conn.close()
        except Exception:
            rows = []

        for semantic_type, table_name, label in rows:
            if not semantic_type:
                continue
            # Build pattern from class name, table name, and label
            candidates = {semantic_type, table_name, label}
            for c in candidates:
                if c:
                    escaped = re.escape(c.replace("_", " "))
                    pat = re.compile(
                        r"(?i)\b" + re.escape(c) + r"\b|" + escaped,
                        re.IGNORECASE
                    )
                    self._patterns.append((pat, semantic_type))

    def match(self, record: LogRecord) -> Tuple[Optional[str], Optional[str]]:
        text = f"{record.message} {record.app} {' '.join(str(v) for v in record.fields.values())}"
        for pat, class_name in self._patterns:
            if pat.search(text):
                # Try to extract an ID from fields
                entity_id = None
                for key in ("id", "entity_id", "asset_id", "resource_id", "node_id", "host"):
                    val = record.fields.get(key)
                    if val:
                        entity_id = str(val)
                        break
                if not entity_id:
                    entity_id = record.host or record.app or "unknown"
                return class_name, entity_id
        return None, None


# ── Ingestion pipeline ────────────────────────────────────────────────────

def _iter_records(
    log_path: str,
    fmt: str,
    custom_regex: Optional[str] = None,
) -> Iterator[LogRecord]:
    """Yield parsed LogRecord objects from log_path."""
    custom_re = re.compile(custom_regex) if custom_regex else None

    paths = sorted(glob.glob(log_path)) if "*" in log_path or "?" in log_path else [log_path]
    if not paths:
        print(f"  ⚠ No files matched: {log_path}")
        return

    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for lineno, raw in enumerate(fh, start=1):
                    line = raw.rstrip("\n\r")
                    if not line.strip():
                        continue
                    rec = None
                    if fmt == "jsonl":
                        rec = _parse_jsonl(line, lineno, path)
                    elif fmt == "syslog":
                        rec = _parse_syslog(line, lineno, path)
                    elif fmt == "cef":
                        rec = _parse_cef(line, lineno, path)
                    elif fmt == "otlp":
                        rec = _parse_otlp(line, lineno, path)
                    elif fmt == "auto":
                        # Detect format by content
                        if line.startswith("{"):
                            rec = _parse_jsonl(line, lineno, path) or _parse_otlp(line, lineno, path)
                        elif "CEF:" in line:
                            rec = _parse_cef(line, lineno, path)
                        else:
                            rec = _parse_syslog(line, lineno, path)
                    elif fmt == "regex" and custom_re:
                        m = custom_re.match(line)
                        if m:
                            rec = LogRecord()
                            rec.source_file = path
                            rec.line_no     = lineno
                            rec.raw         = line
                            rec.format      = "regex"
                            rec.fields      = m.groupdict()
                            rec.message     = rec.fields.get("message", line)
                            rec.timestamp   = rec.fields.get("timestamp", "")
                            rec.severity    = rec.fields.get("severity", "INFO").upper()
                            rec.confidence  = 0.60
                    if rec is not None:
                        yield rec
        except OSError as e:
            print(f"  ✗ Cannot read {path}: {e}")


def _ensure_system_agent(conn: sqlite3.Connection) -> int:
    """Return agent_id for the log_connector system agent, creating it if needed."""
    row = conn.execute(
        "SELECT id FROM agents WHERE name=? LIMIT 1", (_AGENT_NAME,)
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO agents (name, agent_type, description) VALUES (?, 'SYSTEM', ?)",
        (_AGENT_NAME, "Log ingestor — structured log to observation converter"),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _write_observation(conn: sqlite3.Connection, rec: LogRecord, agent_id: int) -> bool:
    """Insert one ObservationRecord row. Returns True on success."""
    try:
        conn.execute(
            """INSERT OR IGNORE INTO observations (
                observation_type, numeric_value, unit_of_measure,
                confidence_score, derivation_method, source_ref,
                recorded_by, observation_iri
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                rec.entity_type or "LogObservation",
                rec.observation_value,
                rec.observation_unit or "",
                rec.confidence,
                _DERIVATION,
                rec.source_ref(),
                agent_id,
                f"urn:log:{hash(rec.raw) & 0xFFFFFFFF:08x}",
            ),
        )
        return True
    except sqlite3.Error:
        return False


def _write_event(conn: sqlite3.Connection, rec: LogRecord, agent_id: int) -> bool:
    """Insert one DomainEvent row. Returns True on success."""
    try:
        conn.execute(
            """INSERT OR IGNORE INTO domain_events (
                event_type, title, description, status,
                source_ref, recorded_by, event_iri
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                rec.severity or "LOG_EVENT",
                rec.message[:120] if rec.message else "log event",
                rec.raw[:500],
                "Active",
                rec.source_ref(),
                agent_id,
                f"urn:event:{hash(rec.raw) & 0xFFFFFFFF:08x}",
            ),
        )
        return True
    except sqlite3.Error:
        return False


def _write_rejection(conn: sqlite3.Connection, rec: LogRecord, reason: str):
    try:
        conn.execute(
            """INSERT OR IGNORE INTO semantic_loss_log
               (table_name, column_name, loss_type, severity, description, remediation)
               VALUES (?,?,?,?,?,?)""",
            (
                "log_ingest",
                rec.source_ref(),
                "REJECTED_AT_LOG_INGEST",
                "LOW",
                f"{reason}: {rec.message[:120]}",
                "Review log format or entity matcher configuration.",
            ),
        )
    except sqlite3.Error:
        pass


# ── Public API ────────────────────────────────────────────────────────────

def ingest_logs(
    db_path: str,
    log_path: str,
    fmt: str = "auto",
    custom_regex: Optional[str] = None,
    dry_run: bool = False,
    output_dir: Optional[str] = None,
) -> Dict:
    """
    Main entry point.  Parse log_path, match entities, write DB rows.

    Args:
        db_path:       SQLite database path
        log_path:      Log file path or glob (e.g. /var/log/*.log)
        fmt:           Format hint: auto | jsonl | syslog | cef | otlp | regex
        custom_regex:  Named-group regex for fmt=regex
        dry_run:       Parse and report without writing to DB
        output_dir:    Where to write log_ingest_report.csv

    Returns:
        stats dict with counts for observations, events, rejections, errors
    """
    matcher = EntityMatcher(db_path)

    stats = {
        "observations": 0,
        "events": 0,
        "rejections": 0,
        "errors": 0,
        "total_lines": 0,
    }

    rows_obs  : List[Dict] = []
    rows_event: List[Dict] = []
    rows_rej  : List[Dict] = []

    for rec in _iter_records(log_path, fmt, custom_regex):
        stats["total_lines"] += 1
        entity_type, entity_id = matcher.match(rec)
        rec.entity_type = entity_type
        rec.entity_id   = entity_id

        # Decide: observation (has numeric value) vs event vs rejection
        if rec.observation_value is not None:
            rows_obs.append(rec)
        elif rec.severity in ("0", "1", "2", "3", "CRITICAL", "ALERT", "ERROR", "EMERGENCY",
                               "EMERG", "CRIT"):
            rows_event.append(rec)
        elif rec.message and len(rec.message) > 3:
            # Low-confidence log lines without numeric value → observations with null value
            if entity_type:
                rows_obs.append(rec)
            else:
                rows_rej.append((rec, "no entity match"))
        else:
            rows_rej.append((rec, "empty or too-short message"))

    # Count classified records regardless of dry_run
    stats["observations"] = len(rows_obs)
    stats["events"]       = len(rows_event)
    stats["rejections"]   = len(rows_rej)

    if not dry_run:
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            agent_id = _ensure_system_agent(conn)

            write_ok = write_fail = 0
            for rec in rows_obs:
                if _write_observation(conn, rec, agent_id):
                    write_ok += 1
                else:
                    write_fail += 1

            for rec in rows_event:
                if _write_event(conn, rec, agent_id):
                    write_ok += 1
                else:
                    write_fail += 1

            for rec, reason in rows_rej:
                _write_rejection(conn, rec, reason)

            conn.commit()
            conn.close()
            stats["errors"] = write_fail
        except sqlite3.Error as e:
            print(f"  ✗ Database error: {e}")
            stats["errors"] += 1

    # Write CSV report
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, "log_ingest_report.csv")
        all_rows = []
        for rec in rows_obs:
            all_rows.append({
                "outcome": "observation" if not dry_run else "dry_run_obs",
                "source_ref": rec.source_ref(),
                "format": rec.format,
                "entity_type": rec.entity_type or "",
                "entity_id": rec.entity_id or "",
                "confidence": rec.confidence,
                "message": rec.message[:100],
            })
        for rec in rows_event:
            all_rows.append({
                "outcome": "event" if not dry_run else "dry_run_event",
                "source_ref": rec.source_ref(),
                "format": rec.format,
                "entity_type": rec.entity_type or "",
                "entity_id": rec.entity_id or "",
                "confidence": rec.confidence,
                "message": rec.message[:100],
            })
        for rec, reason in rows_rej:
            all_rows.append({
                "outcome": "rejected",
                "source_ref": rec.source_ref(),
                "format": rec.format,
                "entity_type": "",
                "entity_id": "",
                "confidence": rec.confidence,
                "message": f"[{reason}] {rec.message[:80]}",
            })
        if all_rows:
            with open(report_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
                w.writeheader()
                w.writerows(all_rows)
            print(f"  ✓ Log ingest report     → {report_path}")

    return stats


# ── CLI runner (called by toolkit.py --phase log) ─────────────────────────

def run_log_ingest(
    db_path: str,
    out_path: str,
    log_path: str,
    fmt: str = "auto",
    custom_regex: Optional[str] = None,
    dry_run: bool = False,
):
    """Phase entry-point called from toolkit.py."""
    print(f"\n  Ingesting logs from: {log_path}  [format: {fmt}]")
    if dry_run:
        print("  (dry-run — no database writes)")

    stats = ingest_logs(
        db_path=db_path,
        log_path=log_path,
        fmt=fmt,
        custom_regex=custom_regex,
        dry_run=dry_run,
        output_dir=os.path.join(out_path, "reports"),
    )

    dry = " (dry-run)" if dry_run else ""
    print(
        f"  Log Ingest{dry}: {stats['total_lines']} lines  →  "
        f"{stats['observations']} observations, "
        f"{stats['events']} events, "
        f"{stats['rejections']} rejections, "
        f"{stats['errors']} errors"
    )
    return stats
