from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from .models import MarketSnapshot

logger = logging.getLogger(__name__)


class SmisClientError(RuntimeError):
    pass


class SmisClient:
    BASE_URL = "https://smis.club/api"
    DEFAULT_AUTH_KEY = "CMDDTYDF&WY196KJ"
    DEFAULT_AUTH2 = "3d4b7647-283e-5f5b-8c1c-65ff8b166e97"
    HISTORY_KEYS = (
        "buffSellPrice",
        "buffSellNum",
        "steamSellPrice",
        "steamSellNum",
        "steamTransactionQuantity",
        "buffExchangeSteamBySell",
    )

    def __init__(
        self,
        timeout: float = 15,
        max_retries: int = 3,
        auth_key: str = DEFAULT_AUTH_KEY,
        auth2: str = DEFAULT_AUTH2,
        session: requests.Session | None = None,
    ) -> None:
        if len(auth_key.encode("utf-8")) not in (16, 24, 32):
            raise ValueError("SMIS auth_key 必须是有效 AES key 长度")
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.auth_key = auth_key
        self.auth2 = auth2
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "buff2steam-monitor/1.0",
            "Origin": "https://smis.club",
            "Referer": "https://smis.club/exchange",
        })

    def build_auth_headers(self, timestamp_ms: int | None = None) -> dict[str, str]:
        timestamp_ms = timestamp_ms or int(time.time() * 1000)
        key = self.auth_key.encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv=key)
        encrypted = cipher.encrypt(pad(str(timestamp_ms).encode("utf-8"), AES.block_size))
        return {"Auth": base64.b64encode(encrypted).decode("ascii"), "Auth2": self.auth2}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                headers = dict(kwargs.pop("headers", {}) or {})
                headers.update(self.build_auth_headers())
                response = self.session.request(
                    method,
                    f"{self.BASE_URL}{path}",
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != 200:
                    raise SmisClientError(
                        f"SMIS 返回错误 code={payload.get('code')}: {payload.get('message')}"
                    )
                return payload.get("data")
            except (requests.RequestException, ValueError, SmisClientError) as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
        raise SmisClientError(f"SMIS 请求失败: {last_error}") from last_error

    @staticmethod
    def _smis_time(value: str) -> datetime:
        try:
            local = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=ZoneInfo("Asia/Shanghai")
            )
            return local.astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise SmisClientError(f"SMIS 更新时间无效: {value!r}") from exc

    def fetch_current(self, item: dict[str, Any]) -> MarketSnapshot:
        data = self._request("GET", f"/commodity/{int(item['smis_id'])}")
        if not isinstance(data, dict):
            raise SmisClientError("SMIS 商品详情结构无效")
        required = {
            "hashName", "updateTime", "buffSellPrice", "buffSellNum",
            "steamSellPrice", "steamSellNum", "steamTransactionQuantity",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise SmisClientError(f"SMIS 商品详情缺少字段: {', '.join(missing)}")
        if str(data.get("hashName")) != str(item["name"]):
            raise SmisClientError(
                f"SMIS 商品不匹配: 期望 {item['name']}, 实际 {data.get('hashName')}"
            )
        snapshot = MarketSnapshot(
            item_key=str(item["item_key"]),
            smis_id=int(item["smis_id"]),
            appid=int(item["appid"]),
            name=str(item["name"]),
            name_zh=str(item["name_zh"]),
            observed_at=datetime.now(timezone.utc),
            source_updated_at=self._smis_time(data.get("updateTime")),
            buff_sell_price=float(data.get("buffSellPrice") or 0),
            buff_sell_num=int(data.get("buffSellNum") or 0),
            steam_sell_price=float(data.get("steamSellPrice") or 0),
            steam_sell_num=int(data.get("steamSellNum") or 0),
            steam_transaction_quantity=int(data.get("steamTransactionQuantity") or 0),
            kind="current",
        )
        return snapshot

    def fetch_metadata(self, smis_id: int) -> dict[str, Any]:
        """Fetch and validate the stable fields needed to register an item."""
        data = self._request("GET", f"/commodity/{int(smis_id)}")
        if not isinstance(data, dict):
            raise SmisClientError("SMIS 商品详情结构无效")
        required = {"id", "appid", "hashName", "cnName"}
        missing = sorted(required - data.keys())
        if missing:
            raise SmisClientError(f"SMIS 商品详情缺少字段: {', '.join(missing)}")
        if int(data["id"]) != int(smis_id):
            raise SmisClientError(
                f"SMIS 商品 ID 不匹配: 期望 {smis_id}, 实际 {data.get('id')}"
            )
        return {
            "smis_id": int(data["id"]),
            "item_key": f"smis:{int(data['id'])}",
            "appid": int(data["appid"]),
            "name": str(data["hashName"]),
            "name_zh": str(data["cnName"] or data["hashName"]),
        }

    def search_items(self, query: str, limit: int = 10, game: str = "csgo") -> list[dict[str, Any]]:
        """Search the SMIS catalog and return lightweight, display-safe candidates."""
        query = str(query).strip()
        if not query:
            return []
        data = self._request(
            "POST", "/commodity/suggest", json={"game": game, "text": query}
        )
        if not isinstance(data, list):
            raise SmisClientError("SMIS 搜索结果结构无效")
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in data:
            if not isinstance(row, dict):
                continue
            try:
                smis_id = int(row["id"])
            except (KeyError, TypeError, ValueError):
                continue
            name_zh = str(row.get("value") or "").strip()
            if smis_id <= 0 or not name_zh or smis_id in seen:
                continue
            seen.add(smis_id)
            results.append({
                "smis_id": smis_id,
                "name_zh": name_zh,
                "rarity": str(row.get("rarity") or "").strip() or None,
            })
            if len(results) >= max(1, min(int(limit), 20)):
                break
        return results

    def fetch_history(self, item: dict[str, Any], days: int = 30) -> list[MarketSnapshot]:
        data = self._request(
            "POST",
            "/commodity/history/line",
            json={
                "commodityId": int(item["smis_id"]),
                "days": int(days),
                "keys": list(self.HISTORY_KEYS),
            },
        )
        expected = len(self.HISTORY_KEYS) + 1
        if not isinstance(data, list) or len(data) != expected or not data[0]:
            raise SmisClientError("SMIS 历史数据结构无效")
        row_count = len(data[0])
        if any(not isinstance(series, list) or len(series) != row_count for series in data):
            raise SmisClientError("SMIS 历史数据序列长度不一致")
        snapshots: list[MarketSnapshot] = []
        for row in zip(*data):
            observed = datetime.fromtimestamp(float(row[0]) / 1000, timezone.utc)
            snapshots.append(MarketSnapshot(
                item_key=str(item["item_key"]),
                smis_id=int(item["smis_id"]),
                appid=int(item["appid"]),
                name=str(item["name"]),
                name_zh=str(item["name_zh"]),
                observed_at=observed,
                source_updated_at=observed,
                buff_sell_price=float(row[1] or 0),
                buff_sell_num=int(row[2] or 0),
                steam_sell_price=float(row[3] or 0),
                steam_sell_num=int(row[4] or 0),
                steam_transaction_quantity=int(row[5] or 0),
                buff_to_steam_ratio=float(row[6]) if row[6] is not None else None,
                kind="history",
            ))
        return snapshots
