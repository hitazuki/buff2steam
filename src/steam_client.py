"""
Steam 社区市场交易历史客户端
拉取个人卖单历史（支持多货币）
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Steam 货币代码 → ISO 4217 货币代码 映射
STEAM_CURRENCY_MAP: dict[int, str] = {
    1:  "USD",
    2:  "GBP",
    3:  "EUR",
    4:  "CHF",
    5:  "RUB",
    6:  "PLN",
    7:  "BRL",
    8:  "JPY",
    9:  "NOK",
    10: "IDR",
    11: "MYR",
    12: "PHP",
    13: "SGD",
    14: "THB",
    15: "VND",
    16: "KRW",
    17: "TRY",
    18: "UAH",
    19: "MXN",
    20: "CAD",
    21: "AUD",
    22: "NZD",
    23: "CNY",
    24: "INR",
    25: "CLP",
    26: "PEN",
    27: "COP",
    28: "ZAR",
    29: "HKD",
    30: "TWD",
    31: "SAR",
    32: "AED",
    37: "ARS",
    38: "ILS",
    39: "KZT",
    40: "KWD",
    41: "QAR",
    42: "CRC",
    43: "UYU",
}


class SteamClient:
    """
    Steam 社区市场交易历史客户端
    通过 Cookie 访问 /market/myhistory 接口获取卖单记录
    """

    BASE_URL = "https://steamcommunity.com"

    def __init__(self, session_id: str, steam_login_secure: str,
                 default_currency: int = 23):
        self.session_id = session_id
        self.steam_login_secure = steam_login_secure
        self.default_currency = default_currency
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://steamcommunity.com/market/",
            "Cookie": (
                f"sessionid={session_id}; "
                f"steamLoginSecure={steam_login_secure}"
            ),
        })

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def fetch_sell_history(self, cache_path: Path | None = None,
                           fetch_count: int = 500) -> list[dict]:
        """
        拉取全部卖单历史

        Returns:
            卖单列表，每条记录格式见 `_parse_listing`
        """
        if cache_path and cache_path.exists():
            logger.info("[Steam] 读取缓存: %s", cache_path)
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)

        logger.info("[Steam] 开始拉取市场卖单历史...")
        all_sales: list[dict] = []
        start = 0

        while True:
            batch, total = self._fetch_page(start, fetch_count)
            all_sales.extend(batch)
            logger.info("[Steam] 已获取 %d / %d 条卖单记录",
                        len(all_sales), total)

            if len(all_sales) >= total or len(batch) == 0:
                break

            start += fetch_count
            time.sleep(2.0)  # Steam 对频繁请求较敏感

        logger.info("[Steam] 卖单历史拉取完成，共 %d 条", len(all_sales))

        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(all_sales, f, ensure_ascii=False, indent=2)
            logger.info("[Steam] 已缓存到 %s", cache_path)

        return all_sales

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _fetch_page(self, start: int, count: int) -> tuple[list[dict], int]:
        """
        拉取单批次市场历史记录（纯 JSON 解析）

        Returns:
            (当前批次记录列表, 总记录数)
        """
        url = f"{self.BASE_URL}/market/myhistory/render/"
        params = {
            "query": "",
            "start": start,
            "count": count,
            "norender": 1,
        }

        try:
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("[Steam] 请求失败 (start=%d): %s", start, e)
            return [], 0
        except json.JSONDecodeError as e:
            logger.error("[Steam] JSON 解析失败 (start=%d): %s", start, e)
            return [], 0

        total_count: int = data.get("total_count", 0)
        events: list[dict] = data.get("events", [])
        listings: dict = data.get("listings", {})
        purchases: dict = data.get("purchases", {})
        assets: dict = data.get("assets", {})

        records: list[dict] = []

        # 遍历所有事件，只处理售出成功（event_type == 3）
        for event in events:
            if event.get("event_type") != 3:
                continue

            listingid = event.get("listingid")
            purchaseid = event.get("purchaseid")
            if not listingid or not purchaseid:
                continue

            # 获取购买详细信息
            pkey = f"{listingid}_{purchaseid}"
            purchase_info = purchases.get(pkey) or {}
            listing_info = listings.get(listingid) or {}

            # 卖家到手金额和到手货币
            received_amount = purchase_info.get("received_amount")
            if received_amount is None:
                # 兼容：如果 purchase_info 里没有，从 listing_info 的 original_price 兜底
                received_amount = listing_info.get("original_price")
            
            if received_amount is None:
                continue

            price_val = float(received_amount) / 100.0

            # 货币 ID：从 received_currencyid 获取（通常形如 2023 或 2029 等，取模 1000 得到实际的币种 ID）
            currency_id_raw = purchase_info.get("received_currencyid") or listing_info.get("currencyid")
            try:
                currency_id = int(currency_id_raw) % 1000 if currency_id_raw is not None else self.default_currency
            except (ValueError, TypeError):
                currency_id = self.default_currency

            currency_code = STEAM_CURRENCY_MAP.get(currency_id, "CNY")

            # 时间：已售时间戳
            time_sold = purchase_info.get("time_sold") or event.get("time_event")
            if time_sold:
                try:
                    sold_at = datetime.fromtimestamp(int(time_sold))
                except (ValueError, TypeError):
                    sold_at = datetime.min
            else:
                sold_at = datetime.min

            # 物品与游戏信息
            asset_ref = listing_info.get("asset") or purchase_info.get("asset") or {}
            appid = str(asset_ref.get("appid", ""))
            contextid = str(asset_ref.get("contextid", "2"))
            assetid = str(asset_ref.get("id", ""))

            # 从 assets 详细表中查物品名
            asset_detail = assets.get(appid, {}).get(contextid, {}).get(assetid, {})
            item_name = asset_detail.get("market_hash_name") or asset_detail.get("name") or "Unknown Item"
            item_name_zh = asset_detail.get("name") or item_name

            # 判定游戏
            game = "unknown"
            if appid == "730":
                game = "csgo"
            elif appid == "570":
                game = "dota2"

            records.append({
                "id": f"steam_{listingid}_{purchaseid}",
                "game": game,
                "name": item_name,
                "name_zh": item_name_zh,
                "price_received": price_val,
                "currency": currency_code,
                "sold_at": sold_at.isoformat() if sold_at != datetime.min else "",
                "source": "steam",
            })

        return records, total_count

    def check_login(self) -> bool:
        """检查 Steam Cookie 是否有效"""
        try:
            # 使用获取单条历史记录的 API 精准检测登录状态，规避主页面重定向或资格检查 (eligibilitycheck) 带来的误判
            url = f"{self.BASE_URL}/market/myhistory/render/"
            resp = self.session.get(
                url,
                params={"query": "", "start": 0, "count": 1},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                results_html = data.get("results_html", "")
                if "login" not in results_html.lower():
                    logger.info("[Steam] Cookie 验证通过")
                    return True
            logger.error("[Steam] Cookie 无效或已过期")
            return False
        except Exception as e:
            logger.error("[Steam] 登录检查失败: %s", e)
            return False
