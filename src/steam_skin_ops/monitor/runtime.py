from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from .manager import MonitoringManager

logger = logging.getLogger(__name__)


class ServiceRuntime:
    def __init__(
        self, manager: MonitoringManager, interval_seconds: int = 1800,
        backup_dir: Path = Path("./data/backups"),
    ) -> None:
        self.manager = manager
        self.interval_seconds = max(1, interval_seconds)
        self.backup_dir = Path(backup_dir)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.started_at: str | None = None
        self.last_cycle_at: str | None = None
        self.last_cycle_ok: bool | None = None
        self.last_error: str | None = None
        self.last_backup_date: date | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.thread = threading.Thread(target=self._run, name="steam-skin-ops-monitor", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                results = self.manager.run_cycle()
                self.last_cycle_ok = all(result.get("success", True) for result in results)
                self.last_error = None
                today = datetime.now().date()
                if self.last_backup_date != today:
                    self.manager.backup(self.backup_dir)
                    self.last_backup_date = today
            except Exception as exc:
                self.last_cycle_ok = False
                self.last_error = str(exc)
                logger.exception("监控周期执行失败")
            finally:
                self.last_cycle_at = datetime.now(timezone.utc).isoformat()
            self.stop_event.wait(self.interval_seconds)

    def status(self) -> dict:
        return {
            "running": bool(self.thread and self.thread.is_alive()),
            "started_at": self.started_at,
            "last_cycle_at": self.last_cycle_at,
            "last_cycle_ok": self.last_cycle_ok,
            "last_error": self.last_error,
            "items": self.manager.storage.count_rule_items(),
            "rules": len(self.manager.storage.list_rules()),
            "outbox": self.manager.storage.outbox_counts(),
        }
