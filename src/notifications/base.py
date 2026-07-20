from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotifyResult:
    success: bool
    message: str


class Notifier(ABC):
    @abstractmethod
    def send(self, title: str, content: str) -> NotifyResult:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def send(self, title: str, content: str) -> NotifyResult:
        logger.info("[通知] %s\n%s", title, content)
        return NotifyResult(True, "console")


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers

    def send(self, title: str, content: str) -> NotifyResult:
        results = [notifier.send(title, content) for notifier in self.notifiers]
        failures = [result.message for result in results if not result.success]
        if failures:
            return NotifyResult(False, "; ".join(failures))
        return NotifyResult(True, "; ".join(result.message for result in results))
