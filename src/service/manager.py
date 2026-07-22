from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from urllib.parse import quote

from src.monitoring.models import MarketSnapshot
from src.monitoring.models import steam_net_amount
from src.monitoring.smis_client import SmisClient
from src.monitoring.storage import MonitorStorage
from src.notifications.astrbot import AstrBotNotifier

logger = logging.getLogger(__name__)
RULE_TYPES = {"ratio", "t7", "platform", "steam"}


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
        confirmations: int = 2,
        clear_confirmations: int = 2,
        health_failure_threshold: int = 3,
    ) -> None:
        self.storage = storage
        self.source = source
        self.notifier = notifier
        self.max_items = max_items
        self.quote_cache_seconds = quote_cache_seconds
        self.confirmations = confirmations
        self.clear_confirmations = clear_confirmations
        self.health_failure_threshold = health_failure_threshold
        self._locks_guard = threading.Lock()
        self._item_locks: dict[int, threading.Lock] = {}

    def _lock_for(self, smis_id: int) -> threading.Lock:
        with self._locks_guard:
            return self._item_locks.setdefault(int(smis_id), threading.Lock())

    def list_items(self) -> list[dict]:
        result = []
        active_ids = {int(rule["smis_id"]) for rule in self.storage.list_rules()}
        for item in self.storage.list_items():
            if int(item["smis_id"]) not in active_ids:
                continue
            latest = self.storage.latest_snapshot(item["item_key"])
            result.append({**item, "latest": self._snapshot_row_to_dict(latest) if latest else None})
        return result

    def search_items(self, query: str, limit: int = 10) -> list[dict]:
        try:
            return self.source.search_items(query, limit=limit)
        except Exception as exc:
            logger.warning("SMIS 搜索失败：%s", exc)
            raise ServiceError(503, "smis_search_failed", "SMIS 搜索暂时不可用") from exc

    @staticmethod
    def _validate_rule(rule_type: str, threshold: float) -> None:
        if rule_type not in RULE_TYPES:
            raise ServiceError(422, "invalid_rule_type", "规则类型必须是 ratio、t7、platform 或 steam")
        if rule_type in {"ratio", "t7"} and not 1 <= threshold <= 100:
            raise ServiceError(422, "invalid_threshold", "比例阈值必须在 1 到 100 之间")
        if rule_type in {"platform", "steam"} and threshold <= 0:
            raise ServiceError(422, "invalid_threshold", "价格阈值必须大于 0")

    def list_rules(self, umo: str, smis_id: int | None = None) -> list[dict]:
        rows = self.storage.list_rules(umo=umo, smis_id=smis_id)
        for row in rows:
            row["state"] = self.storage.get_rule_state(row["id"])
        return rows

    def add_rule(self, umo: str, smis_id: int, rule_type: str, threshold: float) -> dict:
        rule_type = rule_type.strip().lower()
        self._validate_rule(rule_type, threshold)
        if (
            not self.storage.list_rules(smis_id=smis_id)
            and self.storage.count_rule_items() >= self.max_items
        ):
            raise ServiceError(409, "item_limit", f"最多只能监控 {self.max_items} 个饰品")
        item = self.storage.get_item(smis_id)
        if item is None:
            try:
                metadata = self.source.fetch_metadata(smis_id)
            except Exception as exc:
                raise ServiceError(503, "source_unavailable", f"SMIS 饰品信息获取失败：{exc}") from exc
            item = self.storage.upsert_item(metadata)
        rule = self.storage.add_rule(smis_id, umo, rule_type, threshold)
        try:
            self._ensure_history(item_from_row(item))
        except Exception as exc:
            logger.warning("规则历史回填失败 smis_id=%s: %s", smis_id, exc)
        rule["state"] = self.storage.get_rule_state(rule["id"])
        return rule

    def update_rule(self, umo: str, rule_id: int, threshold: float) -> dict:
        rule = self.storage.get_rule(rule_id)
        if not rule or str(rule["umo"]) != umo:
            raise ServiceError(404, "rule_not_found", "当前会话未找到该规则")
        self._validate_rule(str(rule["rule_type"]), threshold)
        return self.storage.update_rule(rule_id, umo, threshold)

    def remove_rule(self, umo: str, rule_id: int) -> None:
        if not self.storage.delete_rule(rule_id, umo):
            raise ServiceError(404, "rule_not_found", "当前会话未找到该规则")

    def _resolve_local_item(self, query: str) -> dict | None:
        matches = self.storage.resolve_items(query)
        if not matches:
            return None
        if query.isdigit():
            return matches[0]
        exact = [
            row for row in matches
            if query.casefold() in {str(row["hash_name"]).casefold(), str(row["cn_name"]).casefold()}
        ]
        if len(exact) == 1:
            return exact[0]
        return None

    def _resolve_market_item(self, query: str) -> dict:
        try:
            if query.isdigit():
                metadata = self.source.fetch_metadata(int(query))
            else:
                matches = self.search_items(query, limit=10)
                exact = [
                    row for row in matches
                    if str(row.get("name_zh") or "").casefold() == query.casefold()
                ]
                candidates = exact if exact else matches
                if not candidates:
                    raise ServiceError(
                        404, "item_not_found", "SMIS 全市场未找到匹配饰品"
                    )
                if len(candidates) > 1:
                    raise ServiceError(
                        409,
                        "ambiguous_item",
                        "名称匹配到多个饰品，请使用 SMIS ID 查询",
                        candidates,
                    )
                metadata = self.source.fetch_metadata(int(candidates[0]["smis_id"]))
        except ServiceError:
            raise
        except Exception as exc:
            logger.warning("SMIS 全市场饰品解析失败：%s", exc)
            raise ServiceError(
                503, "source_unavailable", f"SMIS 饰品信息获取失败：{exc}"
            ) from exc
        return {
            "smis_id": int(metadata["smis_id"]),
            "item_key": str(metadata["item_key"]),
            "appid": int(metadata["appid"]),
            "hash_name": str(metadata["name"]),
            "cn_name": str(metadata["name_zh"]),
        }

    def _resolve_quote_item(self, query: str) -> dict:
        query = query.strip()
        local = self._resolve_local_item(query)
        return local if local is not None else self._resolve_market_item(query)

    def quote(self, query: str) -> dict:
        item_row = self._resolve_quote_item(query)
        item = item_from_row(item_row)
        try:
            self._ensure_history(item)
        except Exception as exc:
            logger.warning("报价历史回填失败 smis_id=%s: %s", item["smis_id"], exc)
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
            uuyp_sell_price=row.get("uuyp_sell_price"), uuyp_sell_num=row.get("uuyp_sell_num"),
            c5_sell_price=row.get("c5_sell_price"), c5_sell_num=row.get("c5_sell_num"),
            igxe_sell_price=row.get("igxe_sell_price"), igxe_sell_num=row.get("igxe_sell_num"),
            eco_sell_price=row.get("eco_sell_price"), eco_sell_num=row.get("eco_sell_num"),
            steam_sell_price=row["steam_sell_price"], steam_sell_num=row["steam_sell_num"],
            steam_transaction_quantity=row["steam_transaction_quantity"],
            buff_to_steam_ratio=row["buff_to_steam_ratio"], kind=row["kind"], source=row["source"],
        )
        lowest = snapshot.lowest_platform
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
            "platforms": [
                {
                    "name": name,
                    "sell_price": price,
                    "sell_num": count,
                    "is_lowest": lowest is not None and price == lowest[1],
                }
                for name, price, count in snapshot.platform_quotes
            ],
            "lowest_platform": (
                {"name": lowest[0], "sell_price": lowest[1], "sell_num": lowest[2]}
                if lowest else None
            ),
        }

    def _quote_payload(self, item: dict, row: dict, *, cached: bool, stale: bool) -> dict:
        snapshot = self._snapshot_row_to_dict(row)
        stats = self._t7_stats(str(item["item_key"]))
        return {
            "smis_id": int(item["smis_id"]), "appid": int(item["appid"]),
            "name": item["hash_name"], "name_zh": item["cn_name"],
            **snapshot, **stats, "cached": cached, "stale": stale,
            "links": {
                "smis": f"https://smis.club/detail/{int(item['smis_id'])}",
                "steam": f"https://steamcommunity.com/market/listings/{int(item['appid'])}/{quote(str(item['hash_name']))}",
            },
        }

    def _ensure_history(self, item: dict) -> None:
        key = f"rule_history_backfill:v1:{item['item_key']}:7"
        if self.storage.get_metadata(key) == "complete":
            return
        snapshots = self.source.fetch_history(item, 7)
        self.storage.save_snapshots(snapshots)
        self.storage.set_metadata(key, "complete")

    @staticmethod
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

    def _t7_stats(self, item_key: str) -> dict:
        rows = self.storage.steam_history(item_key, days=7)
        values = [steam_net_amount(float(row["steam_sell_price"])) for row in rows]
        values = [value for value in values if value > 0]
        span_days = 0.0
        if len(rows) >= 2:
            first = datetime.fromisoformat(rows[0]["source_updated_at"])
            last = datetime.fromisoformat(rows[-1]["source_updated_at"])
            span_days = max(0.0, (last - first).total_seconds() / 86400)
        sufficient = len(values) >= 12 and span_days >= 3
        return {
            "t7_sample_count": len(values),
            "t7_span_days": round(span_days, 2),
            "t7_sufficient": sufficient,
            "t7_steam_net_low": min(values) if values else None,
            "t7_steam_net_p25": self._percentile(values, 0.25),
            "t7_steam_net_median": median(values) if values else None,
        }

    def monitor_item(self, item_row: dict) -> dict:
        item = item_from_row(item_row)
        rules = self.storage.list_rules(smis_id=item["smis_id"])
        if not rules:
            return {"smis_id": item["smis_id"], "skipped": True}
        try:
            try:
                self._ensure_history(item)
            except Exception as exc:
                logger.warning("T+7 历史回填失败 smis_id=%s: %s", item["smis_id"], exc)
            with self._lock_for(item["smis_id"]):
                snapshot = self.source.fetch_current(item)
                self.storage.save_snapshots([snapshot])
        except Exception as exc:
            self._handle_item_failure(item, rules, exc)
            return {"smis_id": item["smis_id"], "success": False, "error": str(exc)}

        self._handle_item_recovery(item, rules, snapshot)
        stats = self._t7_stats(item["item_key"])
        for rule in rules:
            self._evaluate_rule(snapshot, stats, rule)
        return {"smis_id": item["smis_id"], "success": True}

    def _rule_value(self, snapshot: MarketSnapshot, stats: dict, rule_type: str) -> tuple[float | None, float | None, str]:
        lowest = snapshot.lowest_platform
        if rule_type == "steam":
            value = float(snapshot.steam_sell_price or 0)
            return (value if value > 0 else None), None, "ready"
        if lowest is None:
            return None, None, "价格缺失"
        platform_price = float(lowest[1])
        if rule_type == "platform":
            return platform_price, None, "ready"
        if rule_type == "ratio":
            return snapshot.calculated_ratio, snapshot.steam_net, "ready"
        if not stats["t7_sufficient"] or not stats["t7_steam_net_p25"]:
            return None, stats.get("t7_steam_net_p25"), "历史不足"
        return platform_price / float(stats["t7_steam_net_p25"]), float(stats["t7_steam_net_p25"]), "ready"

    def _evaluate_rule(self, snapshot: MarketSnapshot, stats: dict, rule: dict) -> None:
        rule_id = int(rule["id"])
        rule_type = str(rule["rule_type"])
        threshold = float(rule["threshold"])
        state = self.storage.get_rule_state(rule_id)
        value, baseline, status = self._rule_value(snapshot, stats, rule_type)
        observed = snapshot.observed_at.isoformat()
        changes = {
            "last_value": value, "last_baseline": baseline,
            "last_observed_at": observed, "status": status,
        }
        if value is None:
            changes.update({"qualifying_count": 0, "clearing_count": 0})
            self.storage.update_rule_state(rule_id, **changes)
            return

        limit = threshold / 100 if rule_type in {"ratio", "t7"} else threshold
        qualifies = value >= limit if rule_type == "steam" else value <= limit
        if not state["alert_active"]:
            qualifying = int(state["qualifying_count"]) + 1 if qualifies else 0
            changes.update({"qualifying_count": qualifying, "clearing_count": 0})
            if qualifying >= self.confirmations:
                title, content = self._format_rule_alert(snapshot, stats, rule, value)
                signal = f"rule:{rule_id}:{observed}"
                self.storage.enqueue_notification(
                    signal, str(rule["umo"]), f"rule_{rule_type}", title, content
                )
                changes.update({
                    "alert_active": 1, "qualifying_count": qualifying,
                    "last_signal_at": observed,
                })
        else:
            clear_boundary = limit * (0.97 if rule_type == "steam" else 1.03)
            clears = value < clear_boundary if rule_type == "steam" else value > clear_boundary
            clearing = int(state["clearing_count"]) + 1 if clears else 0
            changes.update({"qualifying_count": 0, "clearing_count": clearing})
            if clearing >= self.clear_confirmations:
                changes.update({"alert_active": 0, "clearing_count": 0})
        self.storage.update_rule_state(rule_id, **changes)

    def _handle_item_failure(self, item: dict, rules: list[dict], exc: Exception) -> None:
        for umo in sorted({str(rule["umo"]) for rule in rules}):
            state = self.storage.get_health_state(item["smis_id"], umo)
            failures = int(state["fetch_failures"]) + 1
            alerted = int(state["health_alerted"])
            if failures >= self.health_failure_threshold and not alerted:
                self.storage.enqueue_notification(
                    f"health:{item['item_key']}:{umo}:down:{failures}", umo, "health_down",
                    f"【监控异常】{item['name_zh']}",
                    f"SMIS 行情连续 {failures} 轮请求失败：{exc}",
                )
                alerted = 1
            self.storage.update_health_state(
                item["smis_id"], umo, fetch_failures=failures, health_alerted=alerted
            )

    def _handle_item_recovery(self, item: dict, rules: list[dict], snapshot: MarketSnapshot) -> None:
        for umo in sorted({str(rule["umo"]) for rule in rules}):
            state = self.storage.get_health_state(item["smis_id"], umo)
            if state["health_alerted"]:
                self.storage.enqueue_notification(
                    f"health:{item['item_key']}:{umo}:recovered:{snapshot.observed_at.isoformat()}",
                    umo, "health_recovered", f"【监控恢复】{item['name_zh']}",
                    "SMIS 行情请求已恢复。",
                )
            self.storage.update_health_state(
                item["smis_id"], umo, fetch_failures=0, health_alerted=0
            )

    @staticmethod
    def _format_rule_alert(snapshot: MarketSnapshot, stats: dict, rule: dict, value: float) -> tuple[str, str]:
        labels = {
            "ratio": ("【即时挂刀】", "即时比例"),
            "t7": ("【T+7挂刀】", "T+7 保守比例"),
            "platform": ("【平台到价】", "最低平台价"),
            "steam": ("【Steam清仓】", "Steam 售价"),
        }
        rule_type = str(rule["rule_type"])
        prefix, metric_label = labels[rule_type]
        lowest = snapshot.lowest_platform
        threshold = float(rule["threshold"])
        value_text = f"{value:.2%}" if rule_type in {"ratio", "t7"} else f"¥{value:.2f}"
        threshold_text = f"{threshold:.2f}%" if rule_type in {"ratio", "t7"} else f"¥{threshold:.2f}"
        lines = [
            f"规则 #{int(rule['id'])} · {snapshot.name_zh} / {snapshot.name}",
            f"{metric_label}：{value_text}（阈值 {threshold_text}）",
        ]
        if lowest:
            lines.append(f"最低平台：{lowest[0]} ¥{lowest[1]:.2f}（在售 {lowest[2]}）")
        lines.extend([
            f"Steam 售价：¥{float(snapshot.steam_sell_price or 0):.2f}",
            f"Steam 预计到手：¥{snapshot.steam_net:.2f}",
            f"Steam 在售/日成交：{snapshot.steam_sell_num or 0}/{snapshot.steam_transaction_quantity or 0}",
        ])
        if stats.get("t7_steam_net_p25") is not None:
            lines.extend([
                f"7 日 Steam 到手最低：¥{stats['t7_steam_net_low']:.2f}",
                f"7 日 Steam 到手 P25：¥{stats['t7_steam_net_p25']:.2f}",
                f"7 日 Steam 到手中位数：¥{stats['t7_steam_net_median']:.2f}",
            ])
        lines.extend([
            f"数据更新时间：{snapshot.source_updated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"SMIS：https://smis.club/detail/{snapshot.smis_id}",
            f"Steam：https://steamcommunity.com/market/listings/{snapshot.appid}/{quote(snapshot.name)}",
        ])
        return f"{prefix}{snapshot.name_zh} {value_text}", "\n".join(lines)

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
        active_ids = {int(rule["smis_id"]) for rule in self.storage.list_rules()}
        items = [
            item for item in self.storage.list_items(enabled_only=True)
            if int(item["smis_id"]) in active_ids
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
