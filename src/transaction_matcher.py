"""
交易记录匹配模块
将 BUFF 买单与 Steam 卖单按物品名称 + FIFO 策略配对
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MatchedTrade:
    """一笔完整的挂刀交易（买入+卖出配对完成）"""
    game: str
    name: str                   # 物品名称（market_hash_name）
    name_zh: str                # 中文名（若有）

    # 买入信息（BUFF）
    buff_order_id: str
    buff_order_no: str
    buy_price_cny: float        # BUFF 买入价（CNY）
    buy_quantity: int
    bought_at: str              # ISO 格式时间

    # 卖出信息（Steam）
    steam_row_id: str
    sell_price_received: float  # Steam 到手价（原始货币）
    sell_currency: str          # 原始货币代码
    sell_price_cny: float       # Steam 到手价换算为 CNY
    sold_at: str                # ISO 格式时间

    # 收益计算（由 profit_calculator 填充）
    profit_cny: float = 0.0
    roi_pct: float = 0.0
    hold_days: int = 0


@dataclass
class UnmatchedBuy:
    """已买入但尚未卖出（仍在库存或 Steam 上挂单）"""
    game: str
    name: str
    name_zh: str
    buff_order_id: str
    buff_order_no: str
    buy_price_cny: float
    buy_quantity: int
    bought_at: str
    buyer_steamid: str = ""


@dataclass
class UnmatchedSell:
    """已卖出但找不到对应 BUFF 买单（可能为礼物/其他来源）"""
    game: str
    name: str
    steam_row_id: str
    sell_price_received: float
    sell_currency: str
    sell_price_cny: float
    sold_at: str


@dataclass
class MatchResult:
    """FIFO 匹配结果"""
    matched: list[MatchedTrade] = field(default_factory=list)
    unmatched_buys: list[UnmatchedBuy] = field(default_factory=list)
    unmatched_sells: list[UnmatchedSell] = field(default_factory=list)
    unmatched_other_buys: list[UnmatchedBuy] = field(default_factory=list)
    unmatched_no_steamid_buys: list[UnmatchedBuy] = field(default_factory=list)


class TransactionMatcher:
    """
    BUFF 买单 × Steam 卖单 FIFO 匹配器

    匹配规则：
    - 按物品名称（market_hash_name）分组
    - 同一物品内，买单 and 卖单各自按时间升序排列
    - 依次将最早的买单与最早的卖单配对
    - 剩余未配对的记录归入 unmatched 列表

    注意：
    - BUFF 买单中的 quantity 字段可能 > 1（批量购买），目前简化处理：
      quantity > 1 时将该买单拆分为多个单独记录参与 FIFO
    """

    def __init__(self, converter=None):
        """
        Args:
            converter: CurrencyConverter 实例，用于将卖出价换算为 CNY
        """
        self.converter = converter

    def match(
        self,
        buff_orders: list[dict],
        steam_sales: list[dict],
        current_steam_id: str = "",
    ) -> MatchResult:
        """
        执行 FIFO 匹配

        Args:
            buff_orders: buff_client 返回的买单列表
            steam_sales: steam_client 返回的卖单列表
            current_steam_id: 当前登录的 SteamID64 字符串。若不为空，则将不同 SteamID 的买单划分至 unmatched_other_buys。

        Returns:
            MatchResult
        """
        result = MatchResult()

        # 根据 Steam ID 进行分区过滤
        matching_buff_orders = []
        for o in buff_orders:
            buyer_id = o.get("buyer_steamid", "")
            if current_steam_id:
                if not buyer_id:
                    qty = int(o.get("quantity", 1))
                    for _ in range(qty):
                        result.unmatched_no_steamid_buys.append(UnmatchedBuy(
                            game=o.get("game", "unknown"),
                            name=o.get("name", ""),
                            name_zh=o.get("name_zh", ""),
                            buff_order_id=o.get("id", ""),
                            buff_order_no=o.get("order_no", ""),
                            buy_price_cny=float(o.get("price_cny", 0)),
                            buy_quantity=1,
                            bought_at=o.get("created_at", ""),
                            buyer_steamid="",
                        ))
                elif buyer_id != current_steam_id:
                    qty = int(o.get("quantity", 1))
                    for _ in range(qty):
                        result.unmatched_other_buys.append(UnmatchedBuy(
                            game=o.get("game", "unknown"),
                            name=o.get("name", ""),
                            name_zh=o.get("name_zh", ""),
                            buff_order_id=o.get("id", ""),
                            buff_order_no=o.get("order_no", ""),
                            buy_price_cny=float(o.get("price_cny", 0)),
                            buy_quantity=1,
                            bought_at=o.get("created_at", ""),
                            buyer_steamid=buyer_id,
                        ))
                else:
                    matching_buff_orders.append(o)
            else:
                matching_buff_orders.append(o)

        # 仅保留有效记录
        valid_buys = [o for o in matching_buff_orders if o.get("name")]
        valid_sells = [s for s in steam_sales if s.get("name")]

        # 按物品名称分组（忽略大小写，trim空格）
        buy_groups: dict[str, list[dict]] = defaultdict(list)
        for order in valid_buys:
            key = self._normalize_name(order["name"])
            # 拆分 quantity > 1 的批量订单
            qty = int(order.get("quantity", 1))
            for _ in range(qty):
                buy_groups[key].append(order)

        sell_groups: dict[str, list[dict]] = defaultdict(list)
        for sale in valid_sells:
            key = self._normalize_name(sale["name"])
            sell_groups[key].append(sale)

        # 对每组按时间升序排序
        all_names = set(buy_groups.keys()) | set(sell_groups.keys())

        for name_key in all_names:
            buys = sorted(buy_groups.get(name_key, []),
                          key=lambda x: x.get("created_at", ""))
            sells = sorted(sell_groups.get(name_key, []),
                           key=lambda x: x.get("sold_at", ""))

            # FIFO 配对
            bi, si = 0, 0
            while bi < len(buys) and si < len(sells):
                buy = buys[bi]
                sell = sells[si]

                sell_price_cny = self._get_sell_price_cny(sell)

                matched = MatchedTrade(
                    game=buy.get("game", sell.get("game", "unknown")),
                    name=buy.get("name", ""),
                    name_zh=buy.get("name_zh", ""),
                    buff_order_id=buy.get("id", ""),
                    buff_order_no=buy.get("order_no", ""),
                    buy_price_cny=float(buy.get("price_cny", 0)),
                    buy_quantity=1,
                    bought_at=buy.get("created_at", ""),
                    steam_row_id=sell.get("id", ""),
                    sell_price_received=float(sell.get("price_received", 0)),
                    sell_currency=sell.get("currency", "CNY"),
                    sell_price_cny=sell_price_cny,
                    sold_at=sell.get("sold_at", ""),
                )
                result.matched.append(matched)
                bi += 1
                si += 1

            # 未配对买单
            for buy in buys[bi:]:
                result.unmatched_buys.append(UnmatchedBuy(
                    game=buy.get("game", "unknown"),
                    name=buy.get("name", ""),
                    name_zh=buy.get("name_zh", ""),
                    buff_order_id=buy.get("id", ""),
                    buff_order_no=buy.get("order_no", ""),
                    buy_price_cny=float(buy.get("price_cny", 0)),
                    buy_quantity=1,
                    bought_at=buy.get("created_at", ""),
                    buyer_steamid=buy.get("buyer_steamid", ""),
                ))

            # 未配对卖单
            for sell in sells[si:]:
                sell_price_cny = self._get_sell_price_cny(sell)
                result.unmatched_sells.append(UnmatchedSell(
                    game=sell.get("game", "unknown"),
                    name=sell.get("name", ""),
                    steam_row_id=sell.get("id", ""),
                    sell_price_received=float(sell.get("price_received", 0)),
                    sell_currency=sell.get("currency", "CNY"),
                    sell_price_cny=sell_price_cny,
                    sold_at=sell.get("sold_at", ""),
                ))

        logger.info(
            "[Matcher] 配对完成：%d 条已匹配，%d 条未卖出买单，%d 条未匹配卖单，%d 条其他账号买单，%d 条缺失SteamID买单",
            len(result.matched),
            len(result.unmatched_buys),
            len(result.unmatched_sells),
            len(result.unmatched_other_buys),
            len(result.unmatched_no_steamid_buys),
        )
        return result

    def _get_sell_price_cny(self, sell: dict) -> float:
        """将卖出价换算为 CNY"""
        price = float(sell.get("price_received", 0))
        currency = sell.get("currency", "CNY")

        if currency == "CNY" or self.converter is None:
            return price

        return self.converter.convert_to_cny(price, currency)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """标准化物品名称用于分组（小写 + 去首尾空格）"""
        return name.strip().lower()
