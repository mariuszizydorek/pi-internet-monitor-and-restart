"""Local SQLite store shared by every service."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from netwatch.timeutil import iso, parse_iso

SCHEMA = """
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS interface_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    iface TEXT NOT NULL,
    carrier INTEGER,
    operstate TEXT,
    wifi_ssid TEXT,
    wifi_signal_dbm INTEGER,
    ipv4 TEXT,
    dns_ok INTEGER NOT NULL,
    ping_ok INTEGER NOT NULL,
    fetch_ok INTEGER NOT NULL,
    internet_ok INTEGER NOT NULL,
    probes_json TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS router_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    gateway_ip TEXT,
    ping_ok INTEGER,
    rtt_ms REAL,
    deco_api_ok INTEGER,
    wan_status TEXT,
    client_count INTEGER,
    cpu_usage REAL,
    mem_usage REAL,
    model TEXT,
    firmware TEXT,
    detail_json TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS speed_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL,
    latency_ms REAL,
    detail_json TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS restart_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS restart_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_pulse_at TEXT,
    pulse_in_progress INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_iface_site_time
    ON interface_samples (site_id, iface, recorded_at);
CREATE INDEX IF NOT EXISTS idx_router_site_time
    ON router_checks (site_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_speed_site_time
    ON speed_samples (site_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_restart_site_time
    ON restart_events (site_id, recorded_at);
"""

SYNC_TABLES = (
    "interface_samples",
    "router_checks",
    "speed_samples",
    "restart_events",
)


@dataclass(frozen=True)
class RestartState:
    last_pulse_at: datetime | None
    pulse_in_progress: bool


def journal_mode() -> str:
    """WAL breaks when macOS and a Docker Desktop container share the file."""
    mode = os.environ.get("SQLITE_JOURNAL", "wal").strip().lower()
    if mode not in {"wal", "delete"}:
        return "wal"
    return mode


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(f"PRAGMA journal_mode={journal_mode()}")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO restart_state (id, last_pulse_at, pulse_in_progress) "
                "VALUES (1, NULL, 0)"
            )

    def insert_interface_sample(self, row: dict[str, Any]) -> int:
        return self._insert("interface_samples", row)

    def insert_router_check(self, row: dict[str, Any]) -> int:
        return self._insert("router_checks", row)

    def insert_speed_sample(self, row: dict[str, Any]) -> int:
        return self._insert("speed_samples", row)

    def insert_restart_event(self, row: dict[str, Any]) -> int:
        return self._insert("restart_events", row)

    def _insert(self, table: str, row: dict[str, Any]) -> int:
        columns = list(row)
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(columns)
        with self.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
            return int(cursor.lastrowid)

    def recent_observations(
        self, site_id: str, since: datetime
    ) -> list[tuple[datetime, str, bool]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT recorded_at, iface, internet_ok
                FROM interface_samples
                WHERE site_id = ? AND recorded_at >= ?
                ORDER BY recorded_at ASC
                """,
                (site_id, iso(since)),
            ).fetchall()
        return [(parse_iso(row["recorded_at"]), row["iface"], bool(row["internet_ok"])) for row in rows]

    def latest_interface(self, site_id: str, iface: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM interface_samples
                WHERE site_id = ? AND iface = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (site_id, iface),
            ).fetchone()

    def latest_router(self, site_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM router_checks
                WHERE site_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (site_id,),
            ).fetchone()

    def latest_speed(self, site_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM speed_samples
                WHERE site_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (site_id,),
            ).fetchone()

    def restart_state(self) -> RestartState:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM restart_state WHERE id = 1").fetchone()
        if row is None:
            return RestartState(None, False)
        last = parse_iso(row["last_pulse_at"]) if row["last_pulse_at"] else None
        return RestartState(last, bool(row["pulse_in_progress"]))

    def mark_pulse_started(self, moment: datetime) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE restart_state SET last_pulse_at = ?, pulse_in_progress = 1 WHERE id = 1",
                (iso(moment),),
            )

    def mark_pulse_finished(self) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE restart_state SET pulse_in_progress = 0 WHERE id = 1")

    def unsynced(self, table: str, limit: int = 100) -> list[dict[str, Any]]:
        if table not in SYNC_TABLES:
            raise ValueError(table)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE synced_at IS NULL ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_synced(self, table: str, row_ids: Iterable[int], moment: datetime) -> None:
        if table not in SYNC_TABLES:
            raise ValueError(table)
        ids = list(row_ids)
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE {table} SET synced_at = ? WHERE id IN ({marks})",
                [iso(moment), *ids],
            )

    def apply_retention(
        self,
        now: datetime,
        *,
        synced_retention_seconds: int,
        hard_retention_seconds: int,
        speed_retention_seconds: int,
        restart_retention_seconds: int,
    ) -> None:
        synced_cut = iso(now - timedelta(seconds=synced_retention_seconds))
        hard_cut = iso(now - timedelta(seconds=hard_retention_seconds))
        speed_cut = iso(now - timedelta(seconds=speed_retention_seconds))
        restart_cut = iso(now - timedelta(seconds=restart_retention_seconds))
        with self.connect() as conn:
            for table in ("interface_samples", "router_checks"):
                conn.execute(
                    f"DELETE FROM {table} WHERE synced_at IS NOT NULL AND recorded_at < ?",
                    (synced_cut,),
                )
                conn.execute(
                    f"DELETE FROM {table} WHERE recorded_at < ?",
                    (hard_cut,),
                )
            conn.execute("DELETE FROM speed_samples WHERE recorded_at < ?", (speed_cut,))
            conn.execute("DELETE FROM restart_events WHERE recorded_at < ?", (restart_cut,))
