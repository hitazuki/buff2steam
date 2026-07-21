from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from src.monitoring.models import MarketSnapshot, StrategyContext
from src.monitoring.service import calculate_history_stats
from src.monitoring.smis_client import SmisClient
from src.monitoring.storage import MonitorStorage
from src.monitoring.strategy import ThresholdStrategy
from src.notifications.astrbot import AstrBotNotifier

logger = logging.getLogger(__name__)


class ServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str, data: object = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.data = data


def item_from_row(row: dict) -> dict:
    return {
        "smis_id": int(row["smis_id"]),
        "item_key": str(row["item_key"]),
        "appid": int(row["appid"]),
        "name": str(row["hash_name"]),
        "name_zh": str(row["cn_name"]),
    }


class MonitoringManager:
    def __init__(
        self,
        storage: MonitorStorage,
        source: SmisClient,
        notifier: AstrBotNotifier,
        *,
        max_items: int = 20,
        quote_cache_seconds: int = 60,
        history_days: int = 30,
        confirmations: int = 2,
        clear_confirmations: int = 2,
        health_failure_threshold: int = 3,
        max_age_minutes: int = 15,
        min_buff_sell_num: int = 100,
        min_steam_volume: int = 1000,
    ) -> None:
        self.storage = storage
        self.source = source
        self.notifier = notifier
        self.max_items = max_items
        self.quote_cache_seconds = quote_cache_seconds
        self.history_days = history_days
        self.confirmations = confirmations
        self.clear_confirmations = clear_confirmations
        self.health_failure_threshold = health_failure_threshold
        self.max_age_minutes = max_age_minutes
        self.min_buff_sell_num = min_buff_sell_num
        self.min_steam_volume = min_steam_volume
        self._locks_guard = threading.Lock()
        self._item_locks: dict[int, threading.Lock] = {}

    def _lock_for(self, smis_id: int) -> threading.Lock:
        with self._locks_guard:
            return self._item_locks.setdefault(int(smis_id), threading.Lock())

    def list_items(self) -> list[dict]:
        result = []
        for item in self.storage.list_items():
            latest = self.storage.latest_snapshot(item["item_key"])
            result.append({**item, "latest": self._snapshot_row_to_dict(latest) if latest else None})
        return result

    def list_subscriptions(self, umo: str) -> list[dict]:
        rows = self.storage.list_subscriptions(umo=umo)
        for row in rows:
            row["max_ratio_percent"] = round(float(row["max_ratio"]) * 100, 2)
            row["state"] = self.storage.get_subscription_state(row["smis_id"], umo)
        return rows

    def add_subscription(self, umo: str, smis_id: int, max_ratio_percent: float) -> dict:
        self._validate_ratio(max_ratio_percent)
        item = self.storage.get_item(smis_id)
        if item is None:
            if self.storage.count_items() >= self.max_items:
                raise ServiceError(409, "item_limit", f"最多只能配置 {self.max_items} 个饰品")
            metadata = self.source.fetch_metadata(smis_id)
            item = self.storage.upsert_item(metadata)
        subscription = self.storage.upsert_subscription(
            smis_id, umo, float(max_ratio_percent) / 100
        )
        quote_data = self.quote(str(smis_id))
        return {"subscription": subscription, "quote": quote_data}

    def update_subscription(self, umo: str, smis_id: int, max_ratio_percent: float) -> dict:
        self._validate_ratio(max_ratio_percent)
        if not self.storage.get_subscription(smis_id, umo):
            raise ServiceError(404, "subscription_not_found", "当前会话未订阅该饰品")
        return self.storage.upsert_subscription(smis_id, umo, max_ratio_percent / 100)

    def remove_subscription(self, umo: str, smis_id: int) -> None:
        if not self.storage.delete_subscription(smis_id, umo):
            raise ServiceError(404, "subscription_not_found", "当前会话未订阅该饰品")

    @staticmethod
    def _validate_ratio(value: float) -> None:
        if value < 1 or value > 100:
            raise ServiceError(422, "invalid_ratio", "阈值百分比必须在 1 到 100 之间")

    def _resolve_one(self, query: str) -> dict:
        matches = self.storage.resolve_items(query)
        if not matches:
            raise ServiceError(404, "item_not_found", "未找到已配置的饰品")
        exact = [
            row for row in matches
            if query.casefold() in {str(row["hash_name"]).casefold(), str(row["cn_name"]).casefold()}
        ]
        if len(exact) == 1:
            return exact[0]
        if len(matches) > 1:
            candidates = [
                {"smis_id": row["smis_id"], "name": row["hash_name"], "name_zh": row["cn_name"]}
                for row in matches[:10]
            ]
            raise ServiceError(409, "ambiguous_item", "名称匹配到多个饰品", candidates)
        return matches[0]

    def quote(self, query: str) -> dict:
        item_row = self._resolve_one(query)
        item = item_from_row(item_row)
        latest = self.storage.latest_snapshot(item["item_key"])
        if latest and self._snapshot_age_seconds(latest) <= self.quote_cache_seconds:
            return self._quote_payload(item_row, latest, cached=True, stale=False)

        lock = self._lock_for(item["smis_id"])
        with lock:
            latest = self.storage.latest_snapshot(item["item_key"])
            if latest and self._snapshot_age_seconds(latest) <= self.quote_cache_seconds:
                return self._quote_payload(item_row, latest, cached=True, stale=False)
            try:
                snapshot = self.source.fetch_current(item)
                self.storage.save_snapshots([snapshot])
                row = self.storage.latest_snapshot(item["item_key"])
                return self._quote_payload(item_row, row, cached=False, stale=False)
            except Exception as exc:
                if latest:
                    payload = self._quote_payload(item_row, latest, cached=True, stale=True)
                    payload["warning"] = f"实时刷新失败，返回最近快照：{exc}"
                    return payload
                raise ServiceError(503, "source_unavailable", f"行情获取失败：{exc}") from exc

    @staticmethod
    def _snapshot_age_seconds(row: dict) -> float:
        observed = datetime.fromisoformat(str(row["observed_at"]))
        return max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())

    @staticmethod
    def _snapshot_row_to_dict(row: dict | None) -> dict | None:
        if not row:
            return None
        snapshot = MarketSnapshot(
            item_key=row["item_key"], smis_id=row["smis_id"], appid=row["appid"],
            name=row["name"], name_zh=row["name_zh"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            source_updated_at=datetime.fromisoformat(row["source_updated_at"]),
            buff_sell_price=row["buff_sell_price"], buff_sell_num=row["buff_sell_num"],
            steam_sell_price=row["steam_sell_price"], steam_sell_num=row["steam_sell_num"],
            steam_transaction_quantity=row["steam_transaction_quantity"],
            buff_to_steam_ratio=row["buff_to_steam_ratio"], kind=row["kind"], source=row["source"],
        )
        return {
            "observed_at": snapshot.observed_at.isoformat(),
            "source_updated_at": snapshot.source_updated_at.isoformat(),
            "buff_sell_price": snapshot.buff_sell_price,
            "buff_sell_num": snapshot.buff_sell_num,
            "steam_sell_price": snapshot.steam_sell_price,
            "steam_sell_num": snapshot.steam_sell_num,
            "steam_net": snapshot.steam_net,
            "steam_transaction_quantity": snapshot.steam_transaction_quantity,
            "ratio": snapshot.calculated_ratio,
        }

    def _quote_payload(self, item: dict, row: dict, *, cached: bool, stale: bool) -> dict:
        snapshot = self._snapshot_row_to_dict(row)
        return {
            "smis_id": int(item["smis_id"]), "appid": int(item["appid"]),
            "name": item["hash_name"], "name_zh": item["cn_name"],
            **snapshot, "cached": cached, "stale": stale,
            "links": {
                "smis": f"https://smis.club/detail/{int(item['smis_id'])}",
                "steam": f"https://steamcommunity.com/market/listings/{int(item['appid'])}/{quote(str(item['hash_name']))}",
            },
        }

    def _ensure_history(self, item: dict) -> None:
        key = f"history_backfill:{item['item_key']}:{self.history_days}"
        if self.storage.get_metadata(key) == "complete":
            return
        snapshots = self.source.fetch_history(item, self.history_days)
        self.storage.save_snapshots(snapshots)
        self.storage.set_metadata(key, "complete")

    def monitor_item(self, item_row: dict) -> dict:
        item = item_from_row(item_row)
        subscriptions = self.storage.list_subscriptions(smis_id=item["smis_id"])
        if not subscriptions:
            return {"smis_id": item["smis_id"], "skipped": True}
        try:
            try:
                self._ensure_history(item)
            except Exception as exc:
                logger.warning("历史回填失败 smis_id=%s: %s", item["smis_id"], exc)
            with self._lock_for(item["smis_id"]):
                snapshot = self.source.fetch_current(item)
                self.storage.save_snapshots([snapshot])
        except Exception as exc:
            self._handle_item_failure(item, subscriptions, exc)
            return {"smis_id": item["smis_id"], "success": False, "error": str(exc)}

        history = calculate_history_stats(
            self.storage.history_ratios(item["item_key"]), snapshot.calculated_ratio
        )
        for subscription in subscriptions:
            self._evaluate_subscription(item, snapshot, history, subscription)
        return {"smis_id": item["smis_id"], "success": True}

    def _evaluate_subscription(self, item: dict, snapshot: MarketSnapshot, history, sub: dict) -> None:
        smis_id, umo = int(item["smis_id"]), str(sub["umo"])
        state = self.storage.get_subscription_state(smis_id, umo)
        strategy = ThresholdStrategy(
            max_ratio=float(sub["max_ratio"]), max_age_minutes=self.max_age_minutes,
            min_buff_sell_num=self.min_buff_sell_num, min_steam_volume=self.min_steam_volume,
        )
        result = strategy.evaluate(StrategyContext(snapshot, history=history))
        stale_reason = next((reason for reason in result.reasons if "数据时间" in reason), None)
        changes = {"last_ratio": result.ratio}
        if stale_reason:
            changes.update(self._failure_changes(item, umo, state, RuntimeError(stale_reason)))
        else:
            changes["fetch_failures"] = 0
        if state["health_alerted"] and not stale_reason:
            signal = f"health:{item['item_key']}:recovered:{snapshot.observed_at.isoformat()}"
            self.storage.enqueue_notification(
                signal, umo, "health_recovered", f"【监控恢复】{item['name_zh']}",
                "SMIS 行情数据已恢复获取。",
            )
            changes["health_alerted"] = 0

        if result.eligible:
            qualifying = int(state["qualifying_count"]) + 1
            changes.update({"qualifying_count": qualifying, "clearing_count": 0})
            if not state["alert_active"] and qualifying >= self.confirmations:
                signal = f"opportunity:{item['item_key']}:{snapshot.observed_at.isoformat()}"
                title, content = self._format_alert(snapshot, sub, history)
                self.storage.enqueue_notification(signal, umo, "opportunity", title, content)
                changes.update({
                    "alert_active": 1, "last_signal_at": snapshot.observed_at.isoformat(),
                    "pending_signal_key": None,
                })
        else:
            clearing = int(state["clearing_count"]) + 1 if state["alert_active"] else 0
            changes.update({"qualifying_count": 0, "clearing_count": clearing})
            if state["alert_active"] and clearing >= self.clear_confirmations:
                changes.update({"alert_active": 0, "clearing_count": 0})
        self.storage.update_subscription_state(smis_id, umo, **changes)

    def _failure_changes(self, item: dict, umo: str, state: dict, exc: Exception) -> dict:
        failures = int(state["fetch_failures"]) + 1
        changes = {"fetch_failures": failures}
        if failures >= self.health_failure_threshold and not state["health_alerted"]:
            signal = f"health:{item['item_key']}:down:{failures}"
            self.storage.enqueue_notification(
                signal, umo, "health_down", f"【监控异常】{item['name_zh']}",
                f"SMIS 行情连续 {failures} 轮获取失败：{exc}",
            )
            changes["health_alerted"] = 1
        return changes

    def _handle_item_failure(self, item: dict, subscriptions: list[dict], exc: Exception) -> None:
        for sub in subscriptions:
            smis_id, umo = int(item["smis_id"]), str(sub["umo"])
            state = self.storage.get_subscription_state(smis_id, umo)
            changes = self._failure_changes(item, umo, state, exc)
            self.storage.update_subscription_state(smis_id, umo, **changes)

    @staticmethod
    def _format_alert(snapshot: MarketSnapshot, sub: dict, history) -> tuple[str, str]:
        ratio = snapshot.calculated_ratio or 0
        lines = [
            f"{snapshot.name_zh} / {snapshot.name}",
            f"挂刀比例：{ratio:.2%}（阈值 {float(sub['max_ratio']):.2%}）",
            f"BUFF 最低售价：¥{snapshot.buff_sell_price:.2f}（在售 {snapshot.buff_sell_num}）",
            f"Steam 售价：¥{snapshot.steam_sell_price:.2f}",
            f"Steam 预计到手：¥{snapshot.steam_net:.2f}",
            f"Steam 日成交量：{snapshot.steam_transaction_quantity}",
        ]
        if history.median is not None:
            lines.append(f"30 天中位数：{history.median:.2%}")
        lines.extend([
            f"数据更新时间：{snapshot.source_updated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"SMIS：https://smis.club/detail/{snapshot.smis_id}",
            f"Steam：https://steamcommunity.com/market/listings/{snapshot.appid}/{quote(snapshot.name)}",
        ])
        return f"【挂刀提醒】{snapshot.name_zh} {ratio:.2%}", "\n".join(lines)

    def dispatch_outbox(self) -> dict[str, int]:
        sent = failed = 0
        for message in self.storage.due_notifications():
            result = self.notifier.send_to(
                message["umo"], message["title"], message["content"]
            )
            if result.success:
                self.storage.mark_notification_sent(message["id"])
                sent += 1
            else:
                self.storage.mark_notification_failed(message["id"], result.message)
                failed += 1
        return {"sent": sent, "failed": failed}

    def run_cycle(self, max_workers: int = 4) -> list[dict]:
        items = [
            item for item in self.storage.list_items(enabled_only=True)
            if self.storage.list_subscriptions(smis_id=item["smis_id"])
        ]
        results: list[dict] = []
        if items:
            with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
                futures = [executor.submit(self.monitor_item, item) for item in items]
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        logger.exception("监控任务异常")
                        results.append({"success": False, "error": str(exc)})
        self.dispatch_outbox()
        return results

    def test_push(self, umo: str) -> None:
        result = self.notifier.send_to(
            umo, "【buff2steam】主动推送测试",
            f"服务链路正常。\n测试时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        )
        if not result.success:
            raise ServiceError(502, "push_failed", result.message)

    def backup(self, backup_dir: Path, retain: int = 7) -> Path:
        destination = backup_dir / f"monitor-{datetime.now().strftime('%Y%m%d')}.db"
        self.storage.backup(destination)
        backups = sorted(backup_dir.glob("monitor-*.db"), reverse=True)
        for old in backups[retain:]:
            old.unlink(missing_ok=True)
        return destination
