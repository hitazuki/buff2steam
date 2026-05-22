"""
货币转换模块
优先从在线汇率 API 获取实时汇率，失败时使用配置中的备用汇率
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# 免费汇率 API（无需 API Key，基于 EUR 基准）
RATE_API_URL = "https://api.exchangerate-api.com/v4/latest/CNY"
# 备用 API
RATE_API_FALLBACK = "https://open.er-api.com/v6/latest/CNY"


class CurrencyConverter:
    """
    货币转换器：将任意货币金额转换为 CNY

    汇率获取优先级：
    1. 本地缓存（若未过期）
    2. 在线 API（exchangerate-api.com）
    3. 备用在线 API（open.er-api.com）
    4. 配置文件中的硬编码备用汇率
    """

    def __init__(self, fallback_rates: dict[str, float],
                 cache_path: Path | None = None,
                 cache_ttl_hours: float = 6.0):
        self.fallback_rates = fallback_rates
        self.cache_path = cache_path
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        self._rates: dict[str, float] = {}  # 货币代码 → 相对于 CNY 的汇率（1 外币 = ? CNY）
        self._loaded = False

    def ensure_loaded(self) -> None:
        """确保汇率已加载（惰性初始化）"""
        if not self._loaded:
            self._load_rates()
            self._loaded = True

    def convert_to_cny(self, amount: float, from_currency: str) -> float:
        """
        将金额从 from_currency 转换为 CNY

        Args:
            amount: 原始金额
            from_currency: ISO 4217 货币代码，如 "USD", "EUR"

        Returns:
            CNY 金额（保留2位小数）
        """
        self.ensure_loaded()

        if from_currency == "CNY":
            return round(amount, 2)

        rate = self._rates.get(from_currency.upper())
        if rate is None:
            logger.warning("[Currency] 未找到 %s 的汇率，尝试备用汇率", from_currency)
            rate = self.fallback_rates.get(from_currency.upper(), 1.0)

        return round(amount * rate, 2)

    def get_rate(self, currency: str) -> float:
        """获取指定货币对 CNY 的汇率"""
        self.ensure_loaded()
        return self._rates.get(currency.upper(),
                               self.fallback_rates.get(currency.upper(), 1.0))

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_rates(self) -> None:
        """加载汇率，优先使用缓存"""
        # 1. 尝试读取有效缓存
        if self.cache_path and self._is_cache_valid():
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    cached = json.load(f)
                self._rates = cached.get("rates", {})
                logger.info("[Currency] 从缓存加载汇率，共 %d 种货币", len(self._rates))
                return
            except Exception as e:
                logger.warning("[Currency] 读取汇率缓存失败: %s", e)

        # 2. 从在线 API 获取
        rates = self._fetch_online_rates()
        if rates:
            self._rates = rates
            self._save_cache(rates)
            return

        # 3. 使用配置备用汇率
        logger.warning("[Currency] 在线汇率获取失败，使用配置备用汇率")
        self._rates = {k: v for k, v in self.fallback_rates.items()}

    def _fetch_online_rates(self) -> dict[str, float] | None:
        """
        从在线 API 获取以 CNY 为基准的汇率
        返回：{货币代码: 1外币=?CNY} 的字典
        """
        for api_url in [RATE_API_URL, RATE_API_FALLBACK]:
            try:
                logger.info("[Currency] 从 %s 获取汇率...", api_url)
                resp = requests.get(api_url, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                # API 返回的是 1 CNY = ? 外币，需要取倒数得到 1 外币 = ? CNY
                raw_rates: dict[str, float] = data.get("rates", {})
                if not raw_rates:
                    continue

                # 转换：1 外币 = (1 / raw_rates[外币]) CNY
                converted = {}
                for code, rate in raw_rates.items():
                    if rate and rate > 0:
                        converted[code.upper()] = round(1.0 / rate, 6)
                converted["CNY"] = 1.0

                logger.info("[Currency] 汇率获取成功，共 %d 种货币", len(converted))
                return converted

            except Exception as e:
                logger.warning("[Currency] API %s 失败: %s", api_url, e)
                continue

        return None

    def _is_cache_valid(self) -> bool:
        """检查缓存文件是否存在且未过期"""
        if not self.cache_path or not self.cache_path.exists():
            return False
        age = time.time() - self.cache_path.stat().st_mtime
        return age < self.cache_ttl_seconds

    def _save_cache(self, rates: dict[str, float]) -> None:
        """保存汇率到本地缓存"""
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "fetched_at": time.time(),
                    "base": "CNY",
                    "rates": rates,
                }, f, ensure_ascii=False, indent=2)
            logger.info("[Currency] 汇率已缓存到 %s", self.cache_path)
        except Exception as e:
            logger.warning("[Currency] 保存汇率缓存失败: %s", e)
