from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import MarketSnapshot


DEFAULT_STATE = {
    "alert_active": 0,
    "qualifying_count": 0,
    "clearing_count": 0,
    "fetch_failures": 0,
    "health_alerted": 0,
    "last_ratio": None,
    "last_signal_at": None,
    "pending_signal_key": None,
}


class MonitorStorage:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    smis_id INTEGER NOT NULL,
                    appid INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    name_zh TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    buff_sell_price REAL,
                    buff_sell_num INTEGER,
                    steam_sell_price REAL,
                    steam_sell_num INTEGER,
                    steam_transaction_quantity INTEGER,
                    buff_to_steam_ratio REAL,
                    UNIQUE(source, item_key, observed_at, kind)
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_item_time
                    ON market_snapshots(item_key, observed_at DESC);
                CREATE TABLE IF NOT EXISTS monitor_state (
                    item_key TEXT PRIMARY KEY,
                    alert_active INTEGER NOT NULL DEFAULT 0,
                    qualifying_count INTEGER NOT NULL DEFAULT 0,
                    clearing_count INTEGER NOT NULL DEFAULT 0,
                    fetch_failures INTEGER NOT NULL DEFAULT 0,
                    health_alerted INTEGER NOT NULL DEFAULT 0,
                    last_ratio REAL,
                    last_signal_at TEXT,
                    pending_signal_key TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    message TEXT,
                    attempted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notification_signal
                    ON notification_events(signal_key, success);
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    def save_snapshots(self, snapshots: list[MarketSnapshot]) -> int:
        if not snapshots:
            return 0
        rows = []
        for s in snapshots:
            rows.append((
                s.source, s.item_key, s.smis_id, s.appid, s.name, s.name_zh,
                s.observed_at.isoformat(), s.source_updated_at.isoformat(), s.kind,
                s.buff_sell_price, s.buff_sell_num, s.steam_sell_price,
                s.steam_sell_num, s.steam_transaction_quantity,
                s.ratio(),
            ))
        with self.connect() as conn:
            before = conn.total_changes
            conn.executemany("""
                INSERT OR IGNORE INTO market_snapshots (
                    source,item_key,smis_id,appid,name,name_zh,observed_at,
                    source_updated_at,kind,buff_sell_price,buff_sell_num,
                    steam_sell_price,steam_sell_num,steam_transaction_quantity,
                    buff_to_steam_ratio
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
            return conn.total_changes - before

    def get_metadata(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else None

    def set_metadata(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO metadata(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, value, now))

    def get_state(self, item_key: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM monitor_state WHERE item_key=?", (item_key,)).fetchone()
        state = dict(DEFAULT_STATE)
        if row:
            state.update(dict(row))
        state["item_key"] = item_key
        return state

    def update_state(self, item_key: str, **changes: Any) -> dict[str, Any]:
        state = self.get_state(item_key)
        for key, value in changes.items():
            if key not in DEFAULT_STATE:
                raise KeyError(f"未知监控状态字段: {key}")
            state[key] = value
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO monitor_state(
                    item_key,alert_active,qualifying_count,clearing_count,
                    fetch_failures,health_alerted,last_ratio,last_signal_at,
                    pending_signal_key,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(item_key) DO UPDATE SET
                    alert_active=excluded.alert_active,
                    qualifying_count=excluded.qualifying_count,
                    clearing_count=excluded.clearing_count,
                    fetch_failures=excluded.fetch_failures,
                    health_alerted=excluded.health_alerted,
                    last_ratio=excluded.last_ratio,
                    last_signal_at=excluded.last_signal_at,
                    pending_signal_key=excluded.pending_signal_key,
                    updated_at=excluded.updated_at
            """, (
                item_key, int(state["alert_active"]), state["qualifying_count"],
                state["clearing_count"], state["fetch_failures"],
                int(state["health_alerted"]), state["last_ratio"],
                state["last_signal_at"], state["pending_signal_key"], now,
            ))
        return self.get_state(item_key)

    def history_ratios(self, item_key: str) -> list[float]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT buff_to_steam_ratio FROM market_snapshots
                WHERE item_key=? AND kind='history' AND buff_to_steam_ratio IS NOT NULL
                ORDER BY observed_at
            """, (item_key,)).fetchall()
        return [float(row[0]) for row in rows]

    def latest_snapshot(self, item_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT * FROM market_snapshots WHERE item_key=? AND kind='current'
                ORDER BY observed_at DESC LIMIT 1
            """, (item_key,)).fetchone()
        return dict(row) if row else None

    def recent_current(self, item_key: str, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT * FROM market_snapshots WHERE item_key=? AND kind='current'
                ORDER BY observed_at DESC LIMIT ?
            """, (item_key, limit)).fetchall()
        return [dict(row) for row in rows]

    def record_notification(self, signal_key: str, event_type: str, success: bool, message: str) -> None:
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO notification_events(signal_key,event_type,success,message,attempted_at)
                VALUES(?,?,?,?,?)
            """, (
                signal_key, event_type, int(success), message,
                datetime.now(timezone.utc).isoformat(),
            ))

    def was_notification_sent(self, signal_key: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT 1 FROM notification_events WHERE signal_key=? AND success=1 LIMIT 1
            """, (signal_key,)).fetchone()
        return row is not None
