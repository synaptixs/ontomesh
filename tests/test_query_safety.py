"""Safety-layer tests for reasoning search (§11 #11)."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.reasoning_search import safety  # noqa: E402


@pytest.mark.parametrize("bad", [
    "DELETE FROM customer",
    "INSERT INTO customer VALUES (1)",
    "DROP TABLE customer",
    "UPDATE customer SET name='x'",
    "SELECT 1; DROP TABLE customer",      # multi-statement
    "PRAGMA table_info(customer)",
    "ATTACH DATABASE 'x' AS y",
])
def test_assert_read_only_blocks_writes_and_ddl(bad):
    with pytest.raises(safety.SafetyError):
        safety.assert_read_only(bad)


@pytest.mark.parametrize("ok", [
    "SELECT * FROM customer",
    "select name from customer where sla_tier = ?",
    "WITH t AS (SELECT 1) SELECT * FROM t",
])
def test_assert_read_only_allows_selects(ok):
    safety.assert_read_only(ok)  # no raise


def test_tier_ordering():
    assert safety.tier_ok("Public", "Internal")
    assert safety.tier_ok("Internal", "Internal")
    assert not safety.tier_ok("Confidential", "Internal")
    assert not safety.tier_ok("Restricted", "Internal")
    # unknown tier fails closed (treated as most restrictive)
    assert not safety.tier_ok("Mystery", "Internal")


def test_enforce_limit_adds_when_missing():
    assert safety.enforce_limit("SELECT * FROM t", 50).endswith("LIMIT 50")
    assert safety.enforce_limit("SELECT * FROM t LIMIT 5", 50).endswith("LIMIT 5")


def test_deidentify_masks_columns():
    rows = [{"name": "Acme", "ssn": "123-45-6789"}]
    out = safety.deidentify(rows, {"ssn"})
    assert out[0]["name"] == "Acme" and out[0]["ssn"] == "•••"


def test_safe_execute_readonly(tmp_path):
    db = tmp_path / "d.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE t (id INTEGER, v TEXT); INSERT INTO t VALUES (1,'a'),(2,'b');")
    con.commit(); con.close()

    rows = safety.safe_execute(str(db), "SELECT v FROM t WHERE id = ?", [2])
    assert rows == [{"v": "b"}]
    with pytest.raises(safety.SafetyError):
        safety.safe_execute(str(db), "DELETE FROM t", [])
