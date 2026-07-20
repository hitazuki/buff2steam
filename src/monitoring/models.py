from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import floor


def steam_net_amount(gross_price: float) -> float:
    """按 Steam 市场展示价估算卖家到手余额。"""
    if gross_price <= 0:
        return 0.0
    proportional = floor(gross_price * 100 / 1.15) / 100
    minimum_fee = gross_price - 0.14
    return round(max(min(proportional, minimum_fee), 0.0), 2)


@dataclass(frozen=True)
class MarketSnapshot:
    item_key: str
    smis_id: int
    appid: int
    name: str
    name_zh: str
    observed_at: datetime
    source_updated_at: datetime
    buff_sell_price: float | None = None
    buff_sell_num: int | None = None
    steam_sell_price: float | None = None
    steam_sell_num: int | None = None
    steam_transaction_quantity: int | None = None
    buff_to_steam_ratio: float | None = None
    kind: str = "current"
    source: str = "smis"

    @property
    def steam_net(self) -> float:
        return steam_net_amount(float(self.steam_sell_price or 0))

    @property
    def calculated_ratio(self) -> float | None:
        if not self.buff_sell_price or self.steam_net <= 0:
            return None
        return round(self.buff_sell_price / self.steam_net, 4)

    def ratio(self) -> float | None:
        return self.calculated_ratio if self.kind == "current" else self.buff_to_steam_ratio


@dataclass(frozen=True)
class HistoryStats:
    count: int = 0
    median: float | None = None
    percentile_10: float | None = None
    percentile_25: float | None = None
    current_percentile: float | None = None


@dataclass(frozen=True)
class StrategyContext:
    snapshot: MarketSnapshot
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    history: HistoryStats = field(default_factory=HistoryStats)


@dataclass(frozen=True)
class StrategyResult:
    eligible: bool
    ratio: float | None
    reasons: tuple[str, ...]
    strategy_name: str
