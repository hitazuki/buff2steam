import unittest
from steam_skin_ops.profit.calculator import ProfitCalculator
from steam_skin_ops.profit.matching import MatchResult, MatchedTrade, UnmatchedBuy

class TestProfitCalculator(unittest.TestCase):
    def test_calculate_profit_and_summary(self):
        # 1 matched trade (CS2), 1 matched trade (DOTA2), 1 unmatched buy (CS2)
        matched_trades = [
            MatchedTrade(
                game="csgo",
                name="AK-47 | Redline (Field-Tested)",
                name_zh="AK-47 | 红线",
                buy_order_id="b1",
                buy_order_no="bn1",
                buy_price_cny=100.0,
                buy_quantity=1,
                bought_at="2026-05-01T10:00:00",
                steam_row_id="s1",
                sell_price_received=125.0,
                sell_currency="CNY",
                sell_price_cny=125.0,
                sold_at="2026-05-06T10:00:00"  # 5 days hold
            ),
            MatchedTrade(
                game="dota2",
                name="Dragonclaw Hook",
                name_zh="龙钩",
                buy_order_id="b2",
                buy_order_no="bn2",
                buy_price_cny=800.0,
                buy_quantity=1,
                bought_at="2026-05-02T10:00:00",
                steam_row_id="s2",
                sell_price_received=1000.0,
                sell_currency="CNY",
                sell_price_cny=1000.0,
                sold_at="2026-05-03T10:00:00"  # 1 day hold
            )
        ]
        
        unmatched_buys = [
            UnmatchedBuy(
                game="csgo",
                name="Fracture Case",
                name_zh="裂空武器箱",
                buy_order_id="b3",
                buy_order_no="bn3",
                buy_price_cny=5.0,
                buy_quantity=1,
                bought_at="2026-05-05T10:00:00"
            )
        ]
        
        match_result = MatchResult(
            matched=matched_trades,
            unmatched_buys=unmatched_buys,
            unmatched_sells=[]
        )
        
        calculator = ProfitCalculator()
        trades, summary = calculator.calculate(match_result)
        
        # Verify matched trade properties updated
        self.assertEqual(trades[0].profit_cny, 25.0)
        self.assertEqual(trades[0].balance_ratio_pct, 80.0)
        self.assertEqual(trades[0].hold_days, 5)
        
        self.assertEqual(trades[1].profit_cny, 200.0)
        self.assertEqual(trades[1].balance_ratio_pct, 80.0)
        self.assertEqual(trades[1].hold_days, 1)
        
        # Verify summary
        self.assertEqual(summary.total_trades, 2)
        self.assertEqual(summary.total_invested_cny, 900.0) # 100 + 800
        self.assertEqual(summary.total_received_cny, 1125.0) # 125 + 1000
        self.assertEqual(summary.total_profit_cny, 225.0) # 25 + 200
        self.assertEqual(summary.balance_ratio_pct, 80.0) # (900 / 1125) * 100
        self.assertEqual(summary.avg_hold_days, 3.0) # (5 + 1) / 2
        self.assertEqual(summary.holding_count, 1)
        self.assertEqual(summary.holding_invested_cny, 5.0)
        
        # Verify breakdowns
        self.assertIn("csgo", summary.by_game)
        self.assertIn("dota2", summary.by_game)
        self.assertEqual(summary.by_game["csgo"]["count"], 1)
        self.assertEqual(summary.by_game["csgo"]["profit_cny"], 25.0)
        self.assertEqual(summary.by_game["dota2"]["count"], 1)
        self.assertEqual(summary.by_game["dota2"]["profit_cny"], 200.0)
