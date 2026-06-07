"""SearchMemory — lightweight, self-contained recall/remember for searches.

A small SQLite-backed log of past reasoning-search turns. Conforms to the
engine's memory hook: ``recall(question, flavor=...)`` returns recent prior
turns (most recent first), and ``remember(record)`` persists a turn. Decoupled
from the heavier ObservationRecord store (AgentMemory) so the round-trip works
out of the box.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class SearchMemory:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS reasoning_search_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, flavor TEXT, "
                "question TEXT, answer TEXT, status TEXT)"
            )
            con.commit()
        finally:
            con.close()

    def remember(self, record: dict) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO reasoning_search_log (ts, flavor, question, answer, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (record.get("ts") or _now(), record.get("flavor"),
                 record.get("question"), record.get("answer"), record.get("status")),
            )
            con.commit()
        finally:
            con.close()

    def recall(self, question: str, flavor: str | None = None, limit: int = 5) -> list[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            sql = "SELECT question, answer, status, ts FROM reasoning_search_log WHERE 1=1"
            params: list = []
            if flavor:
                sql += " AND flavor = ?"
                params.append(flavor)
            # light relevance: prefer turns sharing a salient word with the question
            terms = [t for t in question.lower().split() if len(t) > 3][:4]
            if terms:
                sql += " AND (" + " OR ".join("LOWER(question) LIKE ?" for _ in terms) + ")"
                params += [f"%{t}%" for t in terms]
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()
