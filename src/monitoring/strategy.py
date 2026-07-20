from __future__ import annotations

from abc import ABC, abstractmethod

from .models import StrategyContext, StrategyResult


class Strategy(ABC):
    name: str

    @abstractmethod
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        raise NotImplementedError


class ThresholdStrategy(Strategy):
    name = "threshold"

    def __init__(
        self,
        max_ratio: float = 0.72,
        max_age_minutes: int = 15,
        min_buff_sell_num: int = 100,
        min_steam_volume: int = 1000,
    ) -> None:
        self.max_ratio = max_ratio
        self.max_age_minutes = max_age_minutes
        self.min_buff_sell_num = min_buff_sell_num
        self.min_steam_volume = min_steam_volume

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        s = context.snapshot
        ratio = s.calculated_ratio
        reasons: list[str] = []
        if not s.buff_sell_price or s.buff_sell_price <= 0:
            reasons.append("BUFF 在售价无效")
        if not s.steam_sell_price or s.steam_sell_price <= 0:
            reasons.append("Steam 在售价无效")
        if ratio is None or ratio > self.max_ratio:
            reasons.append(
                "挂刀比例无效" if ratio is None else f"挂刀比例 {ratio:.2%} 高于 {self.max_ratio:.2%}"
            )
        age_seconds = (context.now - s.source_updated_at).total_seconds()
        if age_seconds < -60 or age_seconds > self.max_age_minutes * 60:
            reasons.append(f"数据时间异常或超过 {self.max_age_minutes} 分钟")
        if (s.buff_sell_num or 0) < self.min_buff_sell_num:
            reasons.append(f"BUFF 在售数低于 {self.min_buff_sell_num}")
        if (s.steam_transaction_quantity or 0) < self.min_steam_volume:
            reasons.append(f"Steam 成交量低于 {self.min_steam_volume}")
        return StrategyResult(not reasons, ratio, tuple(reasons), self.name)
