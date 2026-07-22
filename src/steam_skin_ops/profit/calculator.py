"""
收益计算模块
对已匹配的交易计算净利润、倒余额比例、持仓天数等指标
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .matching import MatchResult, MatchedTrade, UnmatchedBuy

logger = logging.getLogger(__name__)


@dataclass
class TradeSummary:
    """全部交易的汇总统计"""
    total_trades: int = 0          # 完成配对的交易笔数
    total_invested_cny: float = 0  # 总买入金额（CNY）
    total_received_cny: float = 0  # 总到手金额（CNY）
    total_profit_cny: float = 0    # 总净利润（CNY）
    balance_ratio_pct: float = 0   # 综合倒余额比例（%）
    best_trade: MatchedTrade | None = None    # 利润最高的单笔
    worst_trade: MatchedTrade | None = None   # 亏损最大的单笔
    avg_hold_days: float = 0       # 平均持仓天数

    # 持仓统计
    holding_count: int = 0         # 未售出物品数量
    holding_invested_cny: float = 0  # 未售出物品总成本

    # 按游戏分类
    by_game: dict[str, dict] = field(default_factory=dict)


class ProfitCalculator:
    """
    收益计算器

    计算公式：
        净利润 = Steam到手价(CNY) - 买入价(CNY)
        倒余额比例 = 买入价 / Steam到手价 × 100%
        持仓天数 = (卖出时间 - 买入时间).days

    说明：
        - Steam到手价已经是扣除平台手续费（约15%）后的金额
        - BUFF 买家无需支付手续费
        - 不考虑 Steam 钱包充值/提现损耗（此部分难以精确量化）
    """

    def calculate(self, match_result: MatchResult) -> tuple[list[MatchedTrade], TradeSummary]:
        """
        计算所有已匹配交易的收益指标

        Args:
            match_result: TransactionMatcher 的配对结果

        Returns:
            (更新后的已匹配交易列表, 汇总统计)
        """
        trades = match_result.matched
        unmatched_buys = match_result.unmatched_buys

        # 计算每笔交易
        for trade in trades:
            self._calc_trade(trade)

        # 生成汇总
        summary = self._summarize(trades, unmatched_buys)

        logger.info(
            "[Calculator] 统计完成：%d 笔交易，总投入 ¥%.2f，"
            "总收益 ¥%.2f，倒余额比例 %.1f%%",
            summary.total_trades,
            summary.total_invested_cny,
            summary.total_profit_cny,
            summary.balance_ratio_pct,
        )
        return trades, summary

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_trade(trade: MatchedTrade) -> None:
        """计算单笔交易的收益指标（原地修改）"""
        trade.profit_cny = round(trade.sell_price_cny - trade.buy_price_cny, 2)

        if trade.sell_price_cny > 0:
            trade.balance_ratio_pct = round(
                trade.buy_price_cny / trade.sell_price_cny * 100, 2
            )
        else:
            trade.balance_ratio_pct = 0.0

        # 持仓天数
        try:
            buy_dt = datetime.fromisoformat(trade.bought_at)
            sell_dt = datetime.fromisoformat(trade.sold_at)
            trade.hold_days = max(0, (sell_dt - buy_dt).days)
        except (ValueError, TypeError):
            trade.hold_days = 0

    @staticmethod
    def _summarize(trades: list[MatchedTrade],
                   unmatched_buys: list[UnmatchedBuy]) -> TradeSummary:
        """生成汇总统计"""
        s = TradeSummary()

        if not trades:
            # 仍需统计持仓
            s.holding_count = len(unmatched_buys)
            s.holding_invested_cny = sum(b.buy_price_cny for b in unmatched_buys)
            return s

        s.total_trades = len(trades)
        s.total_invested_cny = round(sum(t.buy_price_cny for t in trades), 2)
        s.total_received_cny = round(sum(t.sell_price_cny for t in trades), 2)
        s.total_profit_cny = round(sum(t.profit_cny for t in trades), 2)

        if s.total_received_cny > 0:
            s.balance_ratio_pct = round(
                s.total_invested_cny / s.total_received_cny * 100, 2
            )

        if trades:
            s.avg_hold_days = round(sum(t.hold_days for t in trades) / len(trades), 1)
            s.best_trade = max(trades, key=lambda t: t.profit_cny)
            s.worst_trade = min(trades, key=lambda t: t.profit_cny)

        # 持仓统计
        s.holding_count = len(unmatched_buys)
        s.holding_invested_cny = round(
            sum(b.buy_price_cny for b in unmatched_buys), 2)

        # 按游戏分类
        game_groups: dict[str, list[MatchedTrade]] = {}
        for t in trades:
            game_groups.setdefault(t.game, []).append(t)

        for game, g_trades in game_groups.items():
            invested = sum(t.buy_price_cny for t in g_trades)
            received = sum(t.sell_price_cny for t in g_trades)
            profit = sum(t.profit_cny for t in g_trades)
            s.by_game[game] = {
                "count": len(g_trades),
                "invested_cny": round(invested, 2),
                "profit_cny": round(profit, 2),
                "balance_ratio_pct": (
                    round(invested / received * 100, 2) if received > 0 else 0.0
                ),
            }

        return s
