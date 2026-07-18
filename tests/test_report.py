import unittest
from pathlib import Path
import tempfile
from src.report import ReportGenerator
from src.transaction_matcher import MatchedTrade, UnmatchedBuy
from src.profit_calculator import TradeSummary

class TestReportGenerator(unittest.TestCase):
    def test_csv_and_html_export(self):
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
                sold_at="2026-05-06T10:00:00",
                buy_source="c5",
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
        
        unmatched_other_buys = [
            UnmatchedBuy(
                game="csgo",
                name="M4A4 | Tooth Fairy (Field-Tested)",
                name_zh="M4A4 | 牙仙",
                buy_order_id="b4",
                buy_order_no="bn4",
                buy_price_cny=15.0,
                buy_quantity=1,
                bought_at="2026-05-05T11:00:00",
                buyer_steamid="999999"
            )
        ]
        
        summary = TradeSummary(
            total_trades=1,
            total_invested_cny=100.0,
            total_received_cny=125.0,
            total_profit_cny=25.0,
            balance_ratio_pct=80.0,
            avg_hold_days=5.0,
            holding_count=1,
            holding_invested_cny=5.0,
            best_trade=matched_trades[0],
            worst_trade=matched_trades[0],
            by_game={"csgo": {"count": 1, "invested_cny": 100.0, "profit_cny": 25.0, "balance_ratio_pct": 80.0}}
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = ReportGenerator(output_dir=tmpdir)
            
            # Export CSV
            csv_file = reporter.export_csv(matched_trades, unmatched_buys, summary, unmatched_other_buys)
            self.assertTrue(csv_file.exists())
            self.assertTrue(csv_file.stat().st_size > 0)
            
            # Read CSV content to check headers and values
            with open(csv_file, encoding="utf-8-sig") as f:
                content = f.read()
                self.assertIn("AK-47 | 红线", content)
                self.assertIn("100.00", content)
                self.assertIn("125.00", content)
                self.assertIn("倒余额比例(%)", content)
                self.assertIn("80.00", content)
                self.assertIn("M4A4 | 牙仙", content)
                self.assertIn("其他账号交易", content)
                self.assertIn("999999", content)
                self.assertIn("C5", content)
                
            # Export HTML
            html_file = reporter.export_html(matched_trades, unmatched_buys, summary, unmatched_other_buys)
            self.assertTrue(html_file.exists())
            self.assertTrue(html_file.stat().st_size > 0)
            
            # Read HTML content to check placeholders replaced and JSON data injected
            with open(html_file, encoding="utf-8") as f:
                content = f.read()
                self.assertIn("AK-47 | 红线", content)
                self.assertIn("M4A4 | 牙仙", content)
                self.assertIn("Steam 挂刀收益分析看板", content)
                self.assertIn("total_profit", content)
                self.assertIn("balance_ratio", content)
                self.assertIn("综合倒余额比例", content)
                self.assertIn("other_holdings", content)
                self.assertIn("999999", content)
                self.assertIn('"buy_source": "c5"', content)
                self.assertIn("data-coverage-note", content)
                self.assertIn("tab-count-holdings", content)
                self.assertIn("empty-trades-notice", content)
                self.assertIn('id="date-start"', content)
                self.assertIn('id="date-end"', content)
                self.assertIn("applyDatePreset('30')", content)
                self.assertIn("function calculateSummary(trades, holdings)", content)
                self.assertIn("dateInRange(item.sold_at, start, end)", content)
                self.assertIn("renderCharts(rangeData.trades, summary.by_game)", content)

    def test_view_csv(self):
        from io import StringIO
        import sys
        from src.report import console
        
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
                sold_at="2026-05-06T10:00:00",
                profit_cny=25.0,
                balance_ratio_pct=80.0,
                hold_days=5
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
        summary = TradeSummary(
            total_trades=1,
            total_invested_cny=100.0,
            total_received_cny=125.0,
            total_profit_cny=25.0,
            balance_ratio_pct=80.0,
            avg_hold_days=5.0,
            holding_count=1,
            holding_invested_cny=5.0,
            best_trade=matched_trades[0],
            worst_trade=matched_trades[0],
            by_game={"csgo": {"count": 1, "invested_cny": 100.0, "profit_cny": 25.0, "balance_ratio_pct": 80.0}}
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = ReportGenerator(output_dir=tmpdir)
            csv_file = reporter.export_csv(matched_trades, unmatched_buys, summary)
            
            # Set console width to prevent squashing columns in tests
            old_width = console.width
            console.width = 120
            
            # Redirect stdout to capture report output
            old_stdout = sys.stdout
            sys.stdout = mystdout = StringIO()
            try:
                reporter.view_csv(csv_file)
            finally:
                sys.stdout = old_stdout
                console.width = old_width
                
            output = mystdout.getvalue()
            self.assertIn("AK-47 | 红线", output)
            self.assertIn("裂空武器箱", output)
            self.assertIn("已完成交易明细", output)
            self.assertIn("当前持仓", output)


