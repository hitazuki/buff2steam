from __future__ import annotations

import logging
import threading
import time

from .service import MonitorService

logger = logging.getLogger(__name__)


class MonitorRunner:
    def __init__(self, service: MonitorService, interval_seconds: int = 300) -> None:
        self.service = service
        self.interval_seconds = max(1, interval_seconds)
        self.stop_event = threading.Event()

    def _wait_for_next_cycle(self) -> None:
        """使用可被 Ctrl+C 打断的短睡眠，避免 Windows 长锁等待阻塞信号。"""
        deadline = time.monotonic() + self.interval_seconds
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.25, remaining))

    def run(self) -> None:
        logger.info("[Monitor] 长期监控启动，间隔 %d 秒；按 Ctrl+C 退出", self.interval_seconds)
        try:
            while not self.stop_event.is_set():
                self.service.run_once()
                self._wait_for_next_cycle()
        except KeyboardInterrupt:
            logger.info("[Monitor] 收到退出请求")
        finally:
            self.stop_event.set()
            logger.info("[Monitor] 已停止")
