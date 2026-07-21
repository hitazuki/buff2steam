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
                CREATE TABLE IF NOT EXISTS items (
                    smis_id INTEGER PRIMARY KEY,
                    item_key TEXT NOT NULL UNIQUE,
                    appid INTEGER NOT NULL,
                    hash_name TEXT NOT NULL,
                    cn_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    smis_id INTEGER NOT NULL,
                    umo TEXT NOT NULL,
                    max_ratio REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(smis_id, umo)
                );
                CREATE INDEX IF NOT EXISTS idx_subscriptions_umo
                    ON subscriptions(umo);
                CREATE TABLE IF NOT EXISTS subscription_state (
                    smis_id INTEGER NOT NULL,
                    umo TEXT NOT NULL,
                    alert_active INTEGER NOT NULL DEFAULT 0,
                    qualifying_count INTEGER NOT NULL DEFAULT 0,
                    clearing_count INTEGER NOT NULL DEFAULT 0,
                    fetch_failures INTEGER NOT NULL DEFAULT 0,
                    health_alerted INTEGER NOT NULL DEFAULT 0,
                    last_ratio REAL,
                    last_signal_at TEXT,
                    pending_signal_key TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(smis_id, umo)
                );
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_key TEXT NOT NULL,
                    umo TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    next_attempt_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(signal_key, umo)
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_due
                    ON notification_outbox(status, next_attempt_at);
            """)

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()

    def count_items(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM items").fetchone()
        return int(row[0])

    def upsert_item(self, item: dict[str, Any]) -> dict[str, Any]:
        now = self._utcnow()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO items(
                    smis_id,item_key,appid,hash_name,cn_name,enabled,created_at,updated_at
                ) VALUES(?,?,?,?,?,1,?,?)
                ON CONFLICT(smis_id) DO UPDATE SET
                    item_key=excluded.item_key, appid=excluded.appid,
                    hash_name=excluded.hash_name, cn_name=excluded.cn_name,
                    enabled=1, updated_at=excluded.updated_at
            """, (
                int(item["smis_id"]), str(item["item_key"]), int(item["appid"]),
                str(item["name"]), str(item["name_zh"]), now, now,
            ))
        return self.get_item(int(item["smis_id"]))

    def get_item(self, smis_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE smis_id=?", (int(smis_id),)).fetchone()
        return dict(row) if row else None

    def list_items(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM items"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY cn_name COLLATE NOCASE, smis_id"
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]

    def resolve_items(self, query: str) -> list[dict[str, Any]]:
        query = query.strip()
        if query.isdigit():
            item = self.get_item(int(query))
            return [item] if item else []
        pattern = f"%{query.lower()}%"
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT * FROM items
                WHERE lower(hash_name) LIKE ? OR lower(cn_name) LIKE ?
                ORDER BY
                    CASE WHEN lower(hash_name)=? OR lower(cn_name)=? THEN 0 ELSE 1 END,
                    cn_name COLLATE NOCASE, smis_id
            """, (pattern, pattern, query.lower(), query.lower())).fetchall()
        return [dict(row) for row in rows]

    def upsert_subscription(self, smis_id: int, umo: str, max_ratio: float) -> dict[str, Any]:
        now = self._utcnow()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO subscriptions(smis_id,umo,max_ratio,created_at,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(smis_id,umo) DO UPDATE SET
                    max_ratio=excluded.max_ratio, updated_at=excluded.updated_at
            """, (int(smis_id), umo, float(max_ratio), now, now))
        return self.get_subscription(smis_id, umo)

    def get_subscription(self, smis_id: int, umo: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT s.*, i.item_key, i.appid, i.hash_name, i.cn_name
                FROM subscriptions s JOIN items i USING(smis_id)
                WHERE s.smis_id=? AND s.umo=?
            """, (int(smis_id), umo)).fetchone()
        return dict(row) if row else None

    def list_subscriptions(
        self, *, umo: str | None = None, smis_id: int | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if umo is not None:
            clauses.append("s.umo=?")
            params.append(umo)
        if smis_id is not None:
            clauses.append("s.smis_id=?")
            params.append(int(smis_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(f"""
                SELECT s.*, i.item_key, i.appid, i.hash_name, i.cn_name
                FROM subscriptions s JOIN items i USING(smis_id)
                {where} ORDER BY i.cn_name COLLATE NOCASE, s.umo
            """, params).fetchall()
        return [dict(row) for row in rows]

    def delete_subscription(self, smis_id: int, umo: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE smis_id=? AND umo=?", (int(smis_id), umo)
            )
            conn.execute(
                "DELETE FROM subscription_state WHERE smis_id=? AND umo=?", (int(smis_id), umo)
            )
            conn.execute(
                "DELETE FROM notification_outbox WHERE status='pending' AND umo=? "
                "AND signal_key LIKE ?",
                (umo, f"%:smis:{int(smis_id)}:%"),
            )
            remaining = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE smis_id=?", (int(smis_id),)
            ).fetchone()[0]
            if not remaining:
                conn.execute("DELETE FROM items WHERE smis_id=?", (int(smis_id),))
            return cursor.rowcount > 0

    def get_subscription_state(self, smis_id: int, umo: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT * FROM subscription_state WHERE smis_id=? AND umo=?
            """, (int(smis_id), umo)).fetchone()
        state = dict(DEFAULT_STATE)
        if row:
            state.update(dict(row))
        state.update({"smis_id": int(smis_id), "umo": umo})
        return state

    def update_subscription_state(self, smis_id: int, umo: str, **changes: Any) -> dict[str, Any]:
        state = self.get_subscription_state(smis_id, umo)
        for key, value in changes.items():
            if key not in DEFAULT_STATE:
                raise KeyError(f"未知订阅状态字段: {key}")
            state[key] = value
        now = self._utcnow()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO subscription_state(
                    smis_id,umo,alert_active,qualifying_count,clearing_count,
                    fetch_failures,health_alerted,last_ratio,last_signal_at,
                    pending_signal_key,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(smis_id,umo) DO UPDATE SET
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
                int(smis_id), umo, int(state["alert_active"]), state["qualifying_count"],
                state["clearing_count"], state["fetch_failures"],
                int(state["health_alerted"]), state["last_ratio"], state["last_signal_at"],
                state["pending_signal_key"], now,
            ))
        return self.get_subscription_state(smis_id, umo)

    def enqueue_notification(
        self, signal_key: str, umo: str, event_type: str, title: str, content: str
    ) -> bool:
        now = self._utcnow()
        with self.connect() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO notification_outbox(
                    signal_key,umo,event_type,title,content,status,attempts,
                    next_attempt_at,created_at
                ) VALUES(?,?,?,?,?,'pending',0,?,?)
            """, (signal_key, umo, event_type, title, content, now, now))
            return cursor.rowcount > 0

    def due_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        now = self._utcnow()
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT * FROM notification_outbox
                WHERE status='pending' AND next_attempt_at<=?
                ORDER BY id LIMIT ?
            """, (now, int(limit))).fetchall()
        return [dict(row) for row in rows]

    def mark_notification_sent(self, notification_id: int) -> None:
        now = self._utcnow()
        with self.connect() as conn:
            conn.execute("""
                UPDATE notification_outbox SET status='sent', sent_at=?, last_error=NULL
                WHERE id=?
            """, (now, int(notification_id)))

    def mark_notification_failed(self, notification_id: int, error: str) -> None:
        from datetime import timedelta

        with self.connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM notification_outbox WHERE id=?", (int(notification_id),)
            ).fetchone()
            attempts = int(row[0] if row else 0) + 1
            delay = min(60 * (2 ** min(attempts - 1, 5)), 1800)
            next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            conn.execute("""
                UPDATE notification_outbox
                SET attempts=?, last_error=?, next_attempt_at=? WHERE id=?
            """, (attempts, error[:1000], next_attempt, int(notification_id)))

    def outbox_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM notification_outbox GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def backup(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.path)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination

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
