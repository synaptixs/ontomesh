"""Safety layer for reasoning search (§11 #10–#11).

End-users hit the engine directly, so generated queries must be safe by
construction. This module centralises the guards:

* **read-only** — single ``SELECT`` only; DDL/DML rejected; SQLite opened
  ``mode=ro`` with ``PRAGMA query_only`` and a statement timeout.
* **allow-list** — tables are checked by the compiler against the flavor's
  ``db_tables`` (passed through here for defense-in-depth).
* **sensitivity tiers** — columns/classes above the caller's ``max_tier`` are
  excluded or the request is blocked.
* **de-identification** — hook to mask flagged columns before they leave the host.
"""

from __future__ import annotations

import re
import time

__all__ = [
    "SafetyError", "TIER_ORDER", "tier_rank", "tier_ok",
    "assert_read_only", "enforce_limit", "safe_execute", "deidentify",
]


class SafetyError(ValueError):
    """A query or request violated a safety guard."""


# ── Sensitivity tiers (ascending restriction) ───────────────────────────────
TIER_ORDER = ["Public", "Internal", "Confidential", "Restricted"]


def tier_rank(tier: str | None) -> int:
    """Rank a tier; unknown/empty → most restrictive (fail closed)."""
    if not tier:
        return len(TIER_ORDER)
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return len(TIER_ORDER)


def tier_ok(element_tier: str | None, max_tier: str) -> bool:
    """True if an element at ``element_tier`` is allowed under ``max_tier``."""
    return tier_rank(element_tier) <= tier_rank(max_tier)


# ── Read-only SQL guards ─────────────────────────────────────────────────────
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|"
    r"revoke|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)


def assert_read_only(sql: str) -> None:
    """Raise `SafetyError` unless ``sql`` is a single read-only SELECT."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise SafetyError("multiple statements are not allowed")
    if not s.lower().startswith(("select", "with")):
        raise SafetyError("only SELECT queries are allowed")
    if _FORBIDDEN.search(s):
        raise SafetyError("query contains a forbidden (write/DDL) keyword")


def enforce_limit(sql: str, limit: int) -> str:
    """Ensure a row LIMIT is present."""
    return sql if re.search(r"\blimit\b", sql, re.IGNORECASE) else f"{sql} LIMIT {int(limit)}"


def safe_execute(db_path: str, sql: str, params: list, *, timeout_ms: int = 5000) -> list[dict]:
    """Run a guarded read-only SELECT against SQLite and return list-of-dicts.

    Defense-in-depth: ``assert_read_only`` + ``mode=ro`` URI + ``PRAGMA
    query_only`` + a wall-clock statement timeout via a progress handler.
    (Phase 1 covers SQLite; other backends route through ``src/db_connector``
    with the same guards in a later iteration.)
    """
    import sqlite3

    assert_read_only(sql)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + timeout_ms / 1000.0
        con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        try:
            return [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]
        except sqlite3.OperationalError as exc:
            raise SafetyError(f"query aborted (timeout or error): {exc}") from exc
    finally:
        con.close()


def deidentify(rows: list[dict], columns: set[str]) -> list[dict]:
    """Mask flagged columns (de-identification hook) before returning rows."""
    if not columns:
        return rows
    out = []
    for r in rows:
        out.append({k: ("•••" if k in columns else v) for k, v in r.items()})
    return out
