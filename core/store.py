"""Data layer: SQLite time series. One connection shared by the MQTT thread and the API, behind a lock."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from contract.schema import Reading
from core.domain import baseline

SCHEMA = """
CREATE TABLE IF NOT EXISTS reading (
  crew_id TEXT NOT NULL, signal TEXT NOT NULL, ts TEXT NOT NULL,
  value REAL NOT NULL, source TEXT NOT NULL, provenance TEXT NOT NULL,
  PRIMARY KEY (crew_id, signal, ts));
CREATE TABLE IF NOT EXISTS reject (
  id INTEGER PRIMARY KEY, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  topic TEXT, payload TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def q(self, sql: str, *args) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def add(self, r: Reading) -> None:
        # ts stored as UTC ISO text so it sorts as text. REPLACE: QoS 1 may deliver a message twice.
        self.q("INSERT OR REPLACE INTO reading VALUES (?,?,?,?,?,?)", r.crew_id, r.signal,
               r.ts.astimezone(timezone.utc).isoformat(), r.value, r.source, r.provenance)

    def reject(self, topic: str | None, payload: str, error: str) -> None:
        self.q("INSERT INTO reject (topic, payload, error) VALUES (?,?,?)", topic, payload, error)

    def count(self, table: str = "reading") -> int:
        return self.q(f"SELECT COUNT(*) FROM {table}")[0][0]

    def crews(self) -> list[str]:
        return [r[0] for r in self.q("SELECT DISTINCT crew_id FROM reading ORDER BY 1")]

    def clear(self, crew_id: str) -> None:
        self.q("DELETE FROM reading WHERE crew_id = ?", crew_id)

    def latest(self, crew_id: str, until: str = "9999") -> dict[str, dict]:
        """Newest reading per signal at or before `until` (UTC ISO text)."""
        # SQLite returns the other columns from the row that holds MAX(ts)
        rows = self.q("SELECT signal, value, provenance, MAX(ts) AS ts FROM reading"
                      " WHERE crew_id = ? AND ts <= ? GROUP BY signal", crew_id, until)
        return {r["signal"]: dict(r) for r in rows}

    def series(self, crew_id: str, signal: str, since: str) -> list[dict]:
        return [dict(r) for r in self.q("SELECT ts, value, provenance FROM reading WHERE crew_id = ? AND signal = ?"
                                         " AND ts >= ? ORDER BY ts", crew_id, signal, since)]

    def total(self, crew_id: str, signal: str) -> float:
        return self.q("SELECT COALESCE(SUM(value), 0) FROM reading WHERE crew_id = ? AND signal = ?",
                      crew_id, signal)[0][0]

    def span(self, crew_id: str) -> tuple[str | None, str | None]:
        return tuple(self.q("SELECT MIN(ts), MAX(ts) FROM reading WHERE crew_id = ?", crew_id)[0])

    def setting(self, key: str, default: str) -> str:
        rows = self.q("SELECT value FROM setting WHERE key = ?", key)
        return rows[0][0] if rows else default

    def set_setting(self, key: str, value: str) -> None:
        self.q("INSERT OR REPLACE INTO setting VALUES (?, ?)", key, value)

    def baselines(self, crew_id: str, days: int) -> dict[str, tuple[float, float]]:
        """Mean and spread per signal over the crew member's first `days` days; {} until those days have passed."""
        first, last = self.span(crew_id)
        if first is None:
            return {}
        cutoff = (datetime.fromisoformat(first) + timedelta(days=days)).isoformat()
        if last < cutoff:
            return {}
        values: dict[str, list[float]] = {}
        for r in self.q("SELECT signal, value FROM reading WHERE crew_id = ? AND ts < ?", crew_id, cutoff):
            values.setdefault(r["signal"], []).append(r["value"])
        return {s: b for s, v in values.items() if (b := baseline(v))}
