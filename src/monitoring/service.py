from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from urllib.parse import quote

from src.notifications import Notifier, NotifyResult

from .models import HistoryStats, MarketSnapshot, StrategyContext, StrategyResult
from .smis_client import SmisClient
from .storage import MonitorStorage
from .strategy import Strategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorRunResult:
    success: bool
    strategy_result: StrategyResult | None = None
    notification_sent: bool = False
    message: str = ""


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def calculate_history_stats(values: list[float], current: float | None) -> HistoryStats:
    clean = [float(value) for value in values if value and value > 0]
    if not clean:
        return HistoryStats()
    percentile = None
    if current is not None:
        percentile = sum(value <= current for value in clean) / len(clean)
    return HistoryStats(
        count=len(clean),
        median=median(clean),
        percentile_10=_percentile(clean, 0.10),
        percentile_25=_percentile(clean, 0.25),
        current_percentile=percentile,
    )


class MonitorService:
    def __init__(
        self,
        item: dict,
        source: SmisClient,
        storage: MonitorStorage,
        strategy: Strategy,
        notifier: Notifier,
        history_days: int = 30,
        confirmations: int = 2,
        clear_confirmations: int = 2,
        health_failure_threshold: int = 3,
    ) -> None:
        self.item = item
        self.source = source
        self.storage = storage
        self.strategy = strategy
        self.notifier = notifier
        self.history_days = history_days
        self.confirmations = confirmations
        self.clear_confirmations = clear_confirmations
        self.health_failure_threshold = health_failure_threshold

    @property
    def item_key(self) -> str:
        return str(self.item["item_key"])

    def ensure_history(self) -> None:
        key = f"history_backfill:{self.item_key}:{self.history_days}"
        if self.storage.get_metadata(key) == "complete":
            return
        try:
            snapshots = self.source.fetch_history(self.item, self.history_days)
            inserted = self.storage.save_snapshots(snapshots)
            self.storage.set_metadata(key, "complete")
            logger.info("[Monitor] 历史回填完成：收到 %d 条，新增 %d 条", len(snapshots), inserted)
        except Exception as exc:
            logger.warning("[Monitor] 历史回填失败，本轮继续实时监控：%s", exc)

    def _history_stats(self, ratio: float | None) -> HistoryStats:
        return calculate_history_stats(self.storage.history_ratios(self.item_key), ratio)

    def _send(self, signal_key: str, event_type: str, title: str, content: str) -> NotifyResult:
        if self.storage.was_notification_sent(signal_key):
            return NotifyResult(True, "通知已发送，跳过去重")
        result = self.notifier.send(title, content)
        self.storage.record_notification(signal_key, event_type, result.success, result.message)
        return result

    def _format_signal(self, snapshot: MarketSnapshot, stats: HistoryStats) -> tuple[str, str]:
        ratio = snapshot.calculated_ratio or 0
        base = "https://smis.club/detail/1579"
        buff = "https://buff.163.com/goods/781534"
        steam = f"https://steamcommunity.com/market/listings/{snapshot.appid}/{quote(snapshot.name)}"
        stat_lines = []
        if stats.median is not None:
            stat_lines.append(f"30 天中位数：{stats.median:.2%}")
        if stats.percentile_10 is not None and stats.percentile_25 is not None:
            stat_lines.append(
                f"30 天 P10/P25：{stats.percentile_10:.2%} / {stats.percentile_25:.2%}"
            )
        if stats.current_percentile is not None:
            stat_lines.append(f"当前历史百分位：{stats.current_percentile:.1%}")
        title = f"【挂刀提醒】{snapshot.name_zh} {ratio:.2%}"
        lines = [
            f"<b>{html.escape(snapshot.name_zh)} / {html.escape(snapshot.name)}</b>",
            f"挂刀比例：<b>{ratio:.2%}</b>",
            f"BUFF 最低售价：¥{snapshot.buff_sell_price:.2f}（在售 {snapshot.buff_sell_num}）",
            f"Steam 售价：¥{snapshot.steam_sell_price:.2f}",
            f"Steam 预计到手：¥{snapshot.steam_net:.2f}",
            f"Steam 日成交量：{snapshot.steam_transaction_quantity}",
            *stat_lines,
            f"数据更新时间：{snapshot.source_updated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f'<a href="{base}">SMIS</a> | <a href="{buff}">BUFF</a> | <a href="{steam}">Steam</a>',
        ]
        return title, "<br>".join(lines)

    def _handle_failure(self, exc: Exception, dry_run: bool) -> None:
        if dry_run:
            return
        state = self.storage.get_state(self.item_key)
        failures = int(state["fetch_failures"]) + 1
        changes = {"fetch_failures": failures}
        if (
            failures >= self.health_failure_threshold
            and not state["health_alerted"]
        ):
            latest = self.storage.latest_snapshot(self.item_key)
            outage_anchor = latest["observed_at"] if latest else "startup"
            signal_key = f"health:{self.item_key}:down:{outage_anchor}"
            result = self._send(
                signal_key,
                "health_down",
                f"【监控异常】{self.item['name_zh']}",
                f"SMIS 行情连续 {failures} 轮获取失败：{html.escape(str(exc))}",
            )
            if result.success:
                changes["health_alerted"] = 1
        self.storage.update_state(self.item_key, **changes)

    def _handle_recovery(self, snapshot: MarketSnapshot, dry_run: bool) -> None:
        state = self.storage.get_state(self.item_key)
        changes: dict = {"fetch_failures": 0}
        if state["health_alerted"] and not dry_run:
            signal_key = f"health:{self.item_key}:recovered:{snapshot.observed_at.isoformat()}"
            result = self._send(
                signal_key,
                "health_recovered",
                f"【监控恢复】{self.item['name_zh']}",
                "SMIS 行情数据已恢复获取。",
            )
            if result.success:
                changes["health_alerted"] = 0
        if not dry_run:
            self.storage.update_state(self.item_key, **changes)

    def run_once(self, dry_run: bool = False) -> MonitorRunResult:
        self.ensure_history()
        try:
            snapshot = self.source.fetch_current(self.item)
            self.storage.save_snapshots([snapshot])
        except Exception as exc:
            self._handle_failure(exc, dry_run)
            logger.error("[Monitor] 实时行情获取失败：%s", exc)
            return MonitorRunResult(False, message=str(exc))

        stats = self._history_stats(snapshot.calculated_ratio)
        result = self.strategy.evaluate(StrategyContext(snapshot, history=stats))
        stale_reason = next((reason for reason in result.reasons if "数据时间" in reason), None)
        if stale_reason:
            self._handle_failure(RuntimeError(stale_reason), dry_run)
        else:
            self._handle_recovery(snapshot, dry_run)
        state = self.storage.get_state(self.item_key)
        logger.info(
            "[Monitor] %s BUFF ¥%.2f → Steam 到手 ¥%.2f，比例 %s，历史中位数 %s",
            snapshot.name_zh,
            snapshot.buff_sell_price,
            snapshot.steam_net,
            f"{result.ratio:.2%}" if result.ratio is not None else "无效",
            f"{stats.median:.2%}" if stats.median is not None else "暂无",
        )

        if dry_run:
            projected = int(state["qualifying_count"]) + 1 if result.eligible else 0
            message = (
                f"DRY-RUN：符合策略，正式运行计数将为 {projected}/{self.confirmations}"
                if result.eligible else "DRY-RUN：不符合策略：" + "；".join(result.reasons)
            )
            logger.info(message)
            return MonitorRunResult(True, result, False, message)

        notification_sent = False
        if result.eligible:
            qualifying = min(int(state["qualifying_count"]) + 1, self.confirmations)
            pending_key = state["pending_signal_key"] or (
                f"opportunity:{self.item_key}:{snapshot.observed_at.isoformat()}"
            )
            changes = {
                "qualifying_count": qualifying,
                "clearing_count": 0,
                "last_ratio": result.ratio,
                "pending_signal_key": pending_key,
            }
            if not state["alert_active"] and qualifying >= self.confirmations:
                title, content = self._format_signal(snapshot, stats)
                notify_result = self._send(pending_key, "opportunity", title, content)
                if notify_result.success:
                    changes.update({
                        "alert_active": 1,
                        "last_signal_at": snapshot.observed_at.isoformat(),
                        "pending_signal_key": None,
                    })
                    notification_sent = True
                else:
                    logger.error("[Monitor] 通知失败，将在下轮重试：%s", notify_result.message)
            self.storage.update_state(self.item_key, **changes)
        else:
            clearing = int(state["clearing_count"]) + 1 if state["alert_active"] else 0
            changes = {
                "qualifying_count": 0,
                "clearing_count": clearing,
                "last_ratio": result.ratio,
                "pending_signal_key": None,
            }
            if state["alert_active"] and clearing >= self.clear_confirmations:
                changes.update({"alert_active": 0, "clearing_count": 0})
                logger.info("[Monitor] 条件连续解除，监控已重新布防")
            self.storage.update_state(self.item_key, **changes)
        return MonitorRunResult(True, result, notification_sent)

    def status(self) -> tuple[dict, dict | None]:
        return self.storage.get_state(self.item_key), self.storage.latest_snapshot(self.item_key)
