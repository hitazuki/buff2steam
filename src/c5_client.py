"""C5GAME Cookie 客户端。

仅通过已登录网页使用的只读接口拉取成功买单，并标准化为项目通用买入记录。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

GAME_APP_IDS = {"csgo": 730, "dota2": 570}
APP_ID_GAMES = {str(v): k for k, v in GAME_APP_IDS.items()}
STEAM_ID_KEYS = {
    "steamid",
    "receivesteamid",
    "buyersteamid",
    "targetsteamid",
    "tradesteamid",
}
STEAM_ID_RE = re.compile(r"^\d{17}$")


class C5ClientError(RuntimeError):
    """C5 请求或响应无法安全用于统计。"""


class C5AuthenticationError(C5ClientError):
    """C5 Cookie 无效或登录已过期。"""


class C5Client:
    """使用 C5 网页 Cookie 拉取当前账号的成功买单。"""

    SITE_URL = "https://www.c5game.com"
    BASE_URL = f"{SITE_URL}/api/v1"
    USER_INFO_PATH = "/user/v2/userInfo"
    BUY_LIST_PATH = "/search/v2/purchase/orders/list"
    BUY_DETAIL_PATH = "/support/order/v1/buyer-order/{order_id}"

    def __init__(self, cookie: str, page_size: int = 60, max_pages: int = 100):
        self.cookie = cookie.strip()
        self.page_size = max(1, min(int(page_size), 100))
        self.max_pages = max(1, int(max_pages))
        self.bound_steam_ids: set[str] = set()
        self.account_checked = False
        cookie_values = self._parse_cookie_header(self.cookie)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, br, zstd, deflate",
            "Referer": f"{self.SITE_URL}/user/order/buy",
            "Cookie": self.cookie,
            "x-app-channel": "WEB",
            "x-access-token": cookie_values.get("NC5_accessToken", ""),
            "x-area": "1",
            "x-source": "1",
            "x-traffic-tag": cookie_values.get("x-traffic-tag", ""),
            "accept-language": "zh-CN",
        })

    def check_login(self) -> bool:
        """验证 Cookie，并读取 C5 账号绑定的 SteamID64。"""
        try:
            payload = self._request_json(self.USER_INFO_PATH)
            user_data = self._unwrap_data(payload)
            if not isinstance(user_data, dict) or not user_data:
                raise C5AuthenticationError("账号信息响应为空，Cookie 可能已过期")
            self.account_checked = True
            self.bound_steam_ids = self.extract_steam_ids(payload)
            if self.bound_steam_ids:
                logger.info(
                    "[C5] Cookie 验证通过，账号信息中识别到 %d 个 Steam 账号",
                    len(self.bound_steam_ids),
                )
            else:
                logger.info(
                    "[C5] Cookie 验证通过；账号接口不返回 Steam 绑定列表，"
                    "将在买单中识别接收账号"
                )
            return True
        except C5ClientError as exc:
            logger.error("[C5] 登录检查失败: %s", exc)
            return False

    def fetch_buy_orders(
        self,
        games: Iterable[str] = ("csgo", "dota2"),
        cache_path: Path | None = None,
        force_refresh: bool = False,
    ) -> list[dict]:
        """拉取所有指定游戏的成功买单；失败时不写入不完整缓存。"""
        if cache_path and cache_path.exists() and not force_refresh:
            logger.info("[C5] 读取缓存: %s", cache_path)
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cached = json.load(f)
            except (OSError, ValueError) as exc:
                raise C5ClientError(f"C5 缓存无法读取: {exc}") from exc
            if not isinstance(cached, list) or any(
                not isinstance(item, dict) or item.get("source") != "c5"
                for item in cached
            ):
                raise C5ClientError("C5 缓存格式无效，请使用 --no-cache 重新拉取")
            for item in cached:
                self.bound_steam_ids.update(self.extract_steam_ids(item))
            logger.info(
                "[C5] 缓存中识别到 %d 个接收 Steam 账号",
                len(self.bound_steam_ids),
            )
            return cached

        if not self.cookie:
            raise C5AuthenticationError("未配置 c5.cookie")

        if not self.account_checked:
            user_payload = self._request_json(self.USER_INFO_PATH)
            user_data = self._unwrap_data(user_payload)
            if not isinstance(user_data, dict) or not user_data:
                raise C5AuthenticationError("账号信息响应为空，Cookie 可能已过期")
            self.account_checked = True
            self.bound_steam_ids = self.extract_steam_ids(user_payload)

        all_orders: list[dict] = []
        seen_orders: set[tuple[str, str]] = set()
        for game in games:
            app_id = GAME_APP_IDS.get(game)
            if not app_id:
                logger.warning("[C5] 暂不支持游戏标识: %s", game)
                continue
            game_orders = self._fetch_game_orders(game, app_id, seen_orders)
            all_orders.extend(game_orders)

        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(all_orders, f, ensure_ascii=False, indent=2)
            logger.info("[C5] 已缓存到 %s", cache_path)

        logger.info("[C5] 成功买单拉取完成，共 %d 件", len(all_orders))
        logger.info(
            "[C5] 从买单中累计识别到 %d 个接收 Steam 账号",
            len(self.bound_steam_ids),
        )
        return all_orders

    def _fetch_game_orders(
        self,
        game: str,
        app_id: int,
        seen_orders: set[tuple[str, str]],
    ) -> list[dict]:
        result: list[dict] = []
        pagination_complete = False
        for page in range(1, self.max_pages + 1):
            payload = self._request_json(
                self.BUY_LIST_PATH,
                params={
                    "appId": app_id,
                    "page": page,
                    "limit": self.page_size,
                    "status": 3,  # C5 网页筛选中的“交易成功”
                },
            )
            data = self._unwrap_data(payload)
            raw_orders = data.get("list", []) if isinstance(data, dict) else []
            if not isinstance(raw_orders, list):
                raise C5ClientError("买单列表响应缺少 data.list")

            # 当前网页登录接口在 buyerSteamInfo.steamId 中返回接收账号。
            # 先扫描整页，确保同页缺失 SteamID 的订单也可使用唯一账号回退。
            for raw_order in raw_orders:
                self.bound_steam_ids.update(self.extract_steam_ids(raw_order))

            for raw_order in raw_orders:
                if not isinstance(raw_order, dict) or not self._is_completed(raw_order):
                    continue
                order_id = self._order_id(raw_order)
                dedupe_key = (game, order_id)
                if order_id and dedupe_key in seen_orders:
                    continue

                detail: dict[str, Any] | None = None
                if self._needs_detail(raw_order):
                    if not order_id:
                        raise C5ClientError("C5 买单缺少订单ID，无法补抓详情")
                    detail_payload = self._request_json(
                        self.BUY_DETAIL_PATH.format(order_id=order_id)
                    )
                    detail_data = self._unwrap_data(detail_payload)
                    if not isinstance(detail_data, dict):
                        raise C5ClientError(f"订单 {order_id} 详情格式无效")
                    detail = detail_data

                parsed = self._parse_order(raw_order, detail, game, app_id)
                if parsed:
                    result.extend(parsed)
                    if order_id:
                        seen_orders.add(dedupe_key)

            total_pages = self._int_value(data.get("pages")) if isinstance(data, dict) else 0
            total = self._int_value(data.get("total")) if isinstance(data, dict) else 0
            logger.info(
                "[C5] %s 第 %d 页，获取 %d 笔订单，累计 %d 件",
                game,
                page,
                len(raw_orders),
                len(result),
            )
            if not raw_orders:
                pagination_complete = True
                break
            if total_pages and page >= total_pages:
                pagination_complete = True
                break
            if not total_pages and len(raw_orders) < self.page_size:
                pagination_complete = True
                break
            if total and page * self.page_size >= total:
                pagination_complete = True
                break
            time.sleep(0.5)

        if not pagination_complete:
            raise C5ClientError(
                f"{game} 买单达到 max_pages={self.max_pages} 仍未结束，"
                "拒绝使用可能被截断的数据；请增大 c5.max_pages"
            )
        return result

    def _parse_order(
        self,
        raw_order: dict,
        detail: dict | None,
        game: str,
        app_id: int,
    ) -> list[dict]:
        combined = detail or raw_order
        order_info = combined.get("orderInfo", combined)
        if not isinstance(order_info, dict):
            order_info = raw_order

        order_id = self._order_id(order_info) or self._order_id(raw_order)
        steam_ids = self.extract_steam_ids(raw_order)
        if detail:
            steam_ids.update(self.extract_steam_ids(detail))
        buyer_steamid = self._preferred_steam_id(raw_order, detail)
        if not buyer_steamid and len(steam_ids) == 1:
            buyer_steamid = next(iter(steam_ids))
        if not buyer_steamid and len(self.bound_steam_ids) == 1:
            buyer_steamid = next(iter(self.bound_steam_ids))

        assets = self._find_assets(order_info) or self._find_assets(raw_order)
        if not assets:
            raise C5ClientError(f"订单 {order_id or '?'} 缺少 orderAssetList")

        total_paid = self._first_decimal(
            order_info,
            ("actualPay", "orderAssetTotalPrice", "totalPrice", "price"),
        )
        if total_paid is None:
            total_paid = self._first_decimal(
                raw_order,
                ("actualPay", "orderAssetTotalPrice", "totalPrice", "price"),
            )

        units: list[dict[str, Any]] = []
        for asset_index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            quantity = max(1, self._int_value(
                asset.get("quantity", asset.get("num", asset.get("count", 1)))
            ))
            line_total = self._first_decimal(
                asset,
                ("totalPrice", "orderAssetTotalPrice", "actualPay"),
            )
            unit_gross = self._first_decimal(
                asset,
                ("price", "unitPrice", "actualPrice", "orderAssetPrice"),
            )
            if line_total is None and unit_gross is not None:
                line_total = unit_gross * quantity
            weight_per_unit = (
                line_total / quantity if line_total is not None else Decimal("1")
            )
            for unit_index in range(quantity):
                units.append({
                    "asset": asset,
                    "asset_index": asset_index,
                    "unit_index": unit_index,
                    "weight": max(weight_per_unit, Decimal("0")),
                })

        if not units:
            return []
        if total_paid is None:
            total_paid = sum((u["weight"] for u in units), Decimal("0"))
        allocations = self._allocate_cents(total_paid, [u["weight"] for u in units])

        created_at = self._timestamp_iso(
            order_info.get("orderCreateTime")
            or order_info.get("createTime")
            or raw_order.get("orderCreateTime")
            or raw_order.get("createTime")
        )
        parsed: list[dict] = []
        for index, (unit, allocated) in enumerate(zip(units, allocations)):
            asset = unit["asset"]
            market_name = str(
                asset.get("marketHashName")
                or asset.get("market_hash_name")
                or asset.get("nameEn")
                or asset.get("shortName")
                or asset.get("name")
                or ""
            ).strip()
            if not market_name:
                raise C5ClientError(f"订单 {order_id or '?'} 的饰品缺少名称")
            name_zh = str(asset.get("name") or asset.get("shortName") or market_name)
            item_app_id = str(asset.get("appId") or order_info.get("appId") or app_id)
            item_game = APP_ID_GAMES.get(item_app_id, game)
            asset_id = str(
                asset.get("orderAssetId")
                or asset.get("assetId")
                or asset.get("productId")
                or unit["asset_index"]
            )
            parsed.append({
                "id": (
                    f"c5_{order_id}_{asset_id}_"
                    f"{unit['asset_index']}_{unit['unit_index']}"
                ),
                "game": item_game,
                "name": market_name,
                "name_zh": name_zh,
                "price_cny": float(allocated),
                "quantity": 1,
                "created_at": created_at,
                "order_no": order_id,
                "source": "c5",
                "buyer_steamid": buyer_steamid,
            })
        return parsed

    def _request_json(self, path: str, params: dict | None = None) -> dict:
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=20,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise C5ClientError(f"请求失败: {exc}") from exc

        location = response.headers.get("Location", "")
        if response.status_code in {301, 302, 303, 307, 308}:
            if "/login" in location:
                raise C5AuthenticationError("Cookie 无效或已过期")
            raise C5ClientError(f"接口发生意外重定向: {location}")
        if response.status_code in {401, 403}:
            raise C5AuthenticationError(f"登录被拒绝（HTTP {response.status_code}）")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise C5ClientError(f"接口返回 HTTP {response.status_code}") from exc

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" in content_type or response.text.lstrip().lower().startswith("<!doctype html"):
            raise C5AuthenticationError("接口返回登录页面，Cookie 可能已过期")
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise C5ClientError("接口未返回有效 JSON") from exc
        if not isinstance(payload, dict):
            raise C5ClientError("接口 JSON 顶层不是对象")
        if payload.get("success") is False or payload.get("errorCode") not in (None, 0):
            message = payload.get("errorMsg") or payload.get("message") or "未知错误"
            if str(payload.get("errorCode")) == "101":
                raise C5AuthenticationError(f"Cookie 无效或已过期: {message}")
            raise C5ClientError(f"C5 API 返回错误: {message}")
        code = payload.get("code")
        if code not in (None, 0, 200, "0", "200"):
            message = payload.get("msg") or payload.get("message") or "未知错误"
            if str(code) in {"401", "403"}:
                raise C5AuthenticationError(f"Cookie 无效或已过期: {message}")
            raise C5ClientError(f"C5 API 返回错误 {code}: {message}")
        return payload

    @staticmethod
    def _unwrap_data(payload: dict) -> Any:
        return payload.get("data", payload)

    @classmethod
    def extract_steam_ids(cls, value: Any) -> set[str]:
        found: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    if normalized_key in STEAM_ID_KEYS:
                        candidate = str(child).strip()
                        if STEAM_ID_RE.fullmatch(candidate):
                            found.add(candidate)
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return found

    @classmethod
    def _preferred_steam_id(cls, raw: dict, detail: dict | None) -> str:
        preferred_keys = ("receiveSteamId", "buyerSteamId", "steamId", "steam_id")

        def find(node: Any, wanted: str) -> str:
            if isinstance(node, dict):
                for key, child in node.items():
                    if str(key).lower() == wanted.lower():
                        candidate = str(child).strip()
                        if STEAM_ID_RE.fullmatch(candidate):
                            return candidate
                for child in node.values():
                    result = find(child, wanted)
                    if result:
                        return result
            elif isinstance(node, list):
                for child in node:
                    result = find(child, wanted)
                    if result:
                        return result
            return ""

        for key in preferred_keys:
            for source in (raw, detail):
                if source:
                    result = find(source, key)
                    if result:
                        return result
        return ""

    @classmethod
    def _needs_detail(cls, order: dict) -> bool:
        return not cls.extract_steam_ids(order) or not cls._find_assets(order)

    @staticmethod
    def _find_assets(value: dict) -> list[dict]:
        direct = value.get("orderAssetList")
        if isinstance(direct, list):
            return direct
        order_info = value.get("orderInfo")
        if isinstance(order_info, dict) and isinstance(order_info.get("orderAssetList"), list):
            return order_info["orderAssetList"]
        return []

    @staticmethod
    def _order_id(order: dict) -> str:
        return str(order.get("orderId") or order.get("id") or order.get("orderNo") or "")

    @staticmethod
    def _is_completed(order: dict) -> bool:
        status_name = str(
            order.get("statusName")
            or (order.get("statusInfo") or {}).get("statusName", "")
        ).strip().lower()
        if not status_name:
            return True  # 列表请求已固定 status=3（交易成功）
        rejected = (
            "cancel", "refund", "fail", "pending", "processing",
            "取消", "退款", "失败", "待发", "待收", "待付", "交易中",
        )
        return not any(token in status_name for token in rejected)

    @staticmethod
    def _first_decimal(mapping: dict, keys: Iterable[str]) -> Decimal | None:
        for key in keys:
            value = mapping.get(key)
            if value in (None, ""):
                continue
            try:
                number = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            if number >= 0:
                return number
        return None

    @staticmethod
    def _allocate_cents(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
        total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not weights:
            return []
        weight_sum = sum(weights, Decimal("0"))
        if weight_sum <= 0:
            weights = [Decimal("1")] * len(weights)
            weight_sum = Decimal(len(weights))
        allocations: list[Decimal] = []
        allocated = Decimal("0")
        for index, weight in enumerate(weights):
            if index == len(weights) - 1:
                amount = total - allocated
            else:
                amount = (total * weight / weight_sum).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                allocated += amount
            allocations.append(amount)
        return allocations

    @staticmethod
    def _timestamp_iso(value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, str) and not value.isdigit():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
            except ValueError:
                return value
        try:
            timestamp = int(value)
            if timestamp > 10_000_000_000:
                timestamp //= 1000
            return datetime.fromtimestamp(timestamp).isoformat()
        except (ValueError, TypeError, OSError):
            return ""

    @staticmethod
    def _int_value(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_cookie_header(cookie: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for part in cookie.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name:
                values[name] = value
        return values
