from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


HELP_TEXT = """buff2steam 命令：
/skin search <名称> - 搜索 SMIS 饰品 ID
/skin quote <SMIS_ID|名称> - 查询已配置饰品
/skin items - 列出已配置饰品
/skin watch list - 当前会话订阅
/skin watch add <SMIS_ID|名称> [阈值百分比]
/skin watch remove <SMIS_ID>
/skin watch threshold <SMIS_ID> <阈值百分比>
/skin watch test - 测试主动推送
/skin watch status - 查看服务状态
/skin help - 显示帮助

管理操作仅限 AstrBot 管理员。"""


class ServiceClientError(RuntimeError):
    pass


@register(
    "astrbot_plugin_buff2steam",
    "buff2steam",
    "饰品行情查询与按会话监控",
    "1.1.0",
)
class Buff2SteamPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = str(config.get("service_base_url", "http://buff2steam:8080")).rstrip("/")
        self.token = str(config.get("service_token", "")).strip()
        self.timeout = float(config.get("timeout_seconds", 10))

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.token:
            raise ServiceClientError("插件尚未配置 service_token")
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=headers, **kwargs
                )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ServiceClientError(f"无法连接 buff2steam 服务：{exc}") from exc
        if response.status_code >= 400 or not payload.get("ok"):
            error = payload.get("error") or {}
            message = error.get("message") or f"HTTP {response.status_code}"
            candidates = error.get("data")
            if candidates:
                lines = [f"{row['smis_id']} - {row['name_zh']} / {row['name']}" for row in candidates]
                message = f"{message}\n" + "\n".join(lines)
            raise ServiceClientError(message)
        return payload.get("data")

    @staticmethod
    def _format_quote(data: dict) -> str:
        marker = "（缓存）" if data.get("cached") else "（实时）"
        if data.get("stale"):
            marker = "（过期快照）"
        ratio = data.get("ratio")
        ratio_text = f"{float(ratio):.2%}" if ratio is not None else "未知"
        source_time = data.get("source_updated_at", "")
        try:
            source_time = datetime.fromisoformat(source_time).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        except (TypeError, ValueError):
            pass
        lines = [
            f"{data['name_zh']} / {data['name']}  [SMIS {data['smis_id']}]",
            f"挂刀比例：{ratio_text} {marker}",
            f"BUFF 最低售价：¥{float(data['buff_sell_price'] or 0):.2f}（在售 {data.get('buff_sell_num') or 0}）",
            f"Steam 售价：¥{float(data['steam_sell_price'] or 0):.2f}",
            f"Steam 预计到手：¥{float(data['steam_net'] or 0):.2f}",
            f"Steam 日成交量：{data.get('steam_transaction_quantity') or 0}",
            f"数据更新时间：{source_time}",
            f"SMIS：{data['links']['smis']}",
            f"Steam：{data['links']['steam']}",
        ]
        if data.get("warning"):
            lines.append(f"警告：{data['warning']}")
        return "\n".join(lines)

    @filter.command_group("skin")
    def skin():
        """饰品行情与监控。"""
        pass

    @skin.command("quote")
    async def quote_item(self, event: AstrMessageEvent, query: str):
        """查询已配置饰品。"""
        try:
            data = await self._request("GET", "/v1/quote", params={"q": query})
            yield event.plain_result(self._format_quote(data))
        except ServiceClientError as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @skin.command("search")
    async def search_item(self, event: AstrMessageEvent, query: str):
        """搜索 SMIS 全市场饰品。"""
        try:
            rows = await self._request(
                "GET", "/v1/search", params={"q": query, "limit": 10}
            )
            if not rows:
                yield event.plain_result("SMIS 未找到匹配饰品，请尝试更完整的中文名称。")
                return
            lines = ["SMIS 搜索结果："]
            for row in rows:
                rarity = f"（{row['rarity']}）" if row.get("rarity") else ""
                lines.append(f"{row['smis_id']} - {row['name_zh']}{rarity}")
            if len(rows) > 1:
                lines.append("结果不唯一，请使用 SMIS ID 添加监控。")
            yield event.plain_result("\n".join(lines))
        except ServiceClientError as exc:
            yield event.plain_result(f"搜索失败：{exc}")

    @skin.command("items")
    async def list_items(self, event: AstrMessageEvent):
        """列出已配置饰品。"""
        try:
            rows = await self._request("GET", "/v1/items")
            if not rows:
                yield event.plain_result("尚未配置饰品。管理员可使用 /skin watch add 添加。")
                return
            lines = ["已配置饰品："]
            lines.extend(f"{row['smis_id']} - {row['cn_name']} / {row['hash_name']}" for row in rows)
            yield event.plain_result("\n".join(lines))
        except ServiceClientError as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @skin.group("watch")
    def watch():
        """监控订阅管理。"""
        pass

    @watch.command("list")
    async def watch_list(self, event: AstrMessageEvent):
        """列出当前会话订阅。"""
        try:
            rows = await self._request(
                "GET", "/v1/subscriptions", params={"umo": event.unified_msg_origin}
            )
            if not rows:
                yield event.plain_result("当前会话尚未订阅饰品。")
                return
            lines = ["当前会话订阅："]
            for row in rows:
                active = "告警中" if row["state"].get("alert_active") else "监控中"
                lines.append(
                    f"{row['smis_id']} - {row['cn_name']}："
                    f"{float(row['max_ratio_percent']):g}%（{active}）"
                )
            yield event.plain_result("\n".join(lines))
        except ServiceClientError as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @watch.command("add")
    async def watch_add(
        self, event: AstrMessageEvent, query: str, max_ratio_percent: float = 72
    ):
        """订阅当前会话。"""
        try:
            target = query.strip()
            if target.isdigit():
                smis_id = int(target)
            else:
                configured = await self._request("GET", "/v1/items")
                exact = [
                    row for row in configured
                    if target.casefold() in {
                        str(row.get("cn_name") or "").casefold(),
                        str(row.get("hash_name") or "").casefold(),
                    }
                ]
                if len(exact) == 1:
                    smis_id = int(exact[0]["smis_id"])
                else:
                    rows = await self._request(
                        "GET", "/v1/search", params={"q": target, "limit": 10}
                    )
                    exact = [
                        row for row in rows
                        if str(row.get("name_zh") or "").casefold() == target.casefold()
                    ]
                    candidates = exact if exact else rows
                    if len(candidates) != 1:
                        if not candidates:
                            yield event.plain_result(
                                "订阅失败：SMIS 未找到匹配饰品，请先使用 /skin search。"
                            )
                        else:
                            lines = ["订阅失败：名称匹配到多个饰品，请改用 SMIS ID："]
                            lines.extend(
                                f"{row['smis_id']} - {row['name_zh']}" for row in candidates
                            )
                            yield event.plain_result("\n".join(lines))
                        return
                    smis_id = int(candidates[0]["smis_id"])
            data = await self._request("POST", "/v1/subscriptions", json={
                "umo": event.unified_msg_origin,
                "smis_id": smis_id,
                "max_ratio_percent": max_ratio_percent,
            })
            sub = data["subscription"]
            yield event.plain_result(
                f"订阅成功：{sub['cn_name']} / {sub['hash_name']}\n"
                f"SMIS ID：{sub['smis_id']}\n阈值：{max_ratio_percent:g}%"
            )
        except ServiceClientError as exc:
            yield event.plain_result(f"订阅失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @watch.command("remove")
    async def watch_remove(self, event: AstrMessageEvent, smis_id: int):
        """取消当前会话订阅。"""
        try:
            await self._request(
                "DELETE", f"/v1/subscriptions/{smis_id}",
                params={"umo": event.unified_msg_origin},
            )
            yield event.plain_result(f"已取消订阅：SMIS {smis_id}")
        except ServiceClientError as exc:
            yield event.plain_result(f"取消失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @watch.command("threshold")
    async def watch_threshold(
        self, event: AstrMessageEvent, smis_id: int, max_ratio_percent: float
    ):
        """修改当前会话阈值。"""
        try:
            await self._request("PATCH", f"/v1/subscriptions/{smis_id}", json={
                "umo": event.unified_msg_origin,
                "max_ratio_percent": max_ratio_percent,
            })
            yield event.plain_result(
                f"阈值已更新：SMIS {smis_id} → {max_ratio_percent:g}%"
            )
        except ServiceClientError as exc:
            yield event.plain_result(f"修改失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @watch.command("test")
    async def watch_test(self, event: AstrMessageEvent):
        """测试主动推送链路。"""
        try:
            await self._request(
                "POST", "/v1/push/test", json={"umo": event.unified_msg_origin}
            )
            yield event.plain_result("主动推送请求已成功执行，请检查当前会话。")
        except ServiceClientError as exc:
            yield event.plain_result(f"推送测试失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @watch.command("status")
    async def watch_status(self, event: AstrMessageEvent):
        """查看服务状态。"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/healthz")
                payload = response.json()
            data = payload.get("data") or {}
            lines = [
                f"服务运行：{'是' if data.get('running') else '否'}",
                f"饰品数：{data.get('items', 0)}",
                f"订阅数：{data.get('subscriptions', 0)}",
                f"最近周期：{data.get('last_cycle_at') or '尚未执行'}",
                f"周期正常：{data.get('last_cycle_ok')}",
                f"待发送：{(data.get('outbox') or {}).get('pending', 0)}",
            ]
            if data.get("last_error"):
                lines.append(f"最近错误：{data['last_error']}")
            yield event.plain_result("\n".join(lines))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("buff2steam healthz 请求失败: %s", exc)
            yield event.plain_result(f"状态查询失败：{exc}")

    @skin.command("help")
    async def skin_help(self, event: AstrMessageEvent):
        """显示帮助。"""
        yield event.plain_result(HELP_TEXT)
