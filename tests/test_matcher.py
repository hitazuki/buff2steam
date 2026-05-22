import unittest
from src.transaction_matcher import TransactionMatcher, MatchedTrade, UnmatchedBuy, UnmatchedSell

class MockConverter:
    def convert_to_cny(self, amount, currency):
        if currency == "HKD":
            return round(amount * 0.9, 2)
        return amount

class TestTransactionMatcher(unittest.TestCase):
    def test_fifo_matching(self):
        # We have 2 buys of AK-47, and 1 sell
        buff_orders = [
            {
                "id": "buy1",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "name_zh": "AK-47 | 红线 (战痕累累)",
                "price_cny": 100.0,
                "quantity": 1,
                "created_at": "2026-05-01T10:00:00",
                "order_no": "no1",
            },
            {
                "id": "buy2",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "name_zh": "AK-47 | 红线 (战痕累累)",
                "price_cny": 110.0,
                "quantity": 1,
                "created_at": "2026-05-02T10:00:00",
                "order_no": "no2",
            }
        ]
        
        steam_sales = [
            {
                "id": "sell1",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "price_received": 130.0,
                "currency": "CNY",
                "sold_at": "2026-05-03T10:00:00",
            }
        ]
        
        matcher = TransactionMatcher(converter=MockConverter())
        result = matcher.match(buff_orders, steam_sales)
        
        # We expect 1 match, 1 unmatched buy, 0 unmatched sells
        self.assertEqual(len(result.matched), 1)
        self.assertEqual(len(result.unmatched_buys), 1)
        self.assertEqual(len(result.unmatched_sells), 0)
        
        # Match should be with buy1 (FIFO)
        matched_trade = result.matched[0]
        self.assertEqual(matched_trade.buff_order_id, "buy1")
        self.assertEqual(matched_trade.buy_price_cny, 100.0)
        self.assertEqual(matched_trade.sell_price_cny, 130.0)
        
        # Unmatched buy should be buy2
        unmatched_buy = result.unmatched_buys[0]
        self.assertEqual(unmatched_buy.buff_order_id, "buy2")
        self.assertEqual(unmatched_buy.buy_price_cny, 110.0)

    def test_quantity_split(self):
        # A buy order with quantity 2
        buff_orders = [
            {
                "id": "buy_bulk",
                "game": "dota2",
                "name": "Dragonclaw Hook",
                "price_cny": 800.0,
                "quantity": 2,
                "created_at": "2026-05-01T10:00:00",
            }
        ]
        
        # We sold them one by one
        steam_sales = [
            {
                "id": "sell1",
                "game": "dota2",
                "name": "Dragonclaw Hook",
                "price_received": 1000.0,
                "currency": "CNY",
                "sold_at": "2026-05-02T10:00:00",
            },
            {
                "id": "sell2",
                "game": "dota2",
                "name": "Dragonclaw Hook",
                "price_received": 1050.0,
                "currency": "CNY",
                "sold_at": "2026-05-03T10:00:00",
            }
        ]
        
        matcher = TransactionMatcher()
        result = matcher.match(buff_orders, steam_sales)
        
        # We expect 2 matches because quantity was 2
        self.assertEqual(len(result.matched), 2)
        self.assertEqual(result.matched[0].buy_price_cny, 800.0)
        self.assertEqual(result.matched[0].sell_price_cny, 1000.0)
        self.assertEqual(result.matched[1].buy_price_cny, 800.0)
        self.assertEqual(result.matched[1].sell_price_cny, 1050.0)
        
        self.assertEqual(len(result.unmatched_buys), 0)
        self.assertEqual(len(result.unmatched_sells), 0)

    def test_unmatched_sells(self):
        buff_orders = []
        steam_sales = [
            {
                "id": "sell_unknown",
                "game": "csgo",
                "name": "Operation Bravo Case",
                "price_received": 300.0,
                "currency": "HKD",
                "sold_at": "2026-05-01T10:00:00",
            }
        ]
        
        matcher = TransactionMatcher(converter=MockConverter())
        result = matcher.match(buff_orders, steam_sales)
        
        self.assertEqual(len(result.matched), 0)
        self.assertEqual(len(result.unmatched_buys), 0)
        self.assertEqual(len(result.unmatched_sells), 1)
        
        self.assertEqual(result.unmatched_sells[0].sell_price_cny, 270.0) # 300 * 0.9

    def test_partitioning_by_steam_id(self):
        # We have 3 buys of AK-47: 1 with buyer_steamid="12345" (matching current), 
        # 1 with buyer_steamid="67890" (non-matching), and 1 with empty buyer_steamid.
        buff_orders = [
            {
                "id": "buy1",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "price_cny": 100.0,
                "quantity": 1,
                "created_at": "2026-05-01T10:00:00",
                "order_no": "no1",
                "buyer_steamid": "12345",
            },
            {
                "id": "buy2",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "price_cny": 110.0,
                "quantity": 1,
                "created_at": "2026-05-02T10:00:00",
                "order_no": "no2",
                "buyer_steamid": "67890",
            },
            {
                "id": "buy3",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "price_cny": 120.0,
                "quantity": 1,
                "created_at": "2026-05-03T10:00:00",
                "order_no": "no3",
                "buyer_steamid": "",
            }
        ]

        steam_sales = [
            {
                "id": "sell1",
                "game": "csgo",
                "name": "AK-47 | Redline (Field-Tested)",
                "price_received": 150.0,
                "currency": "CNY",
                "sold_at": "2026-05-04T10:00:00",
            }
        ]

        # Case 1: Active Steam ID is "12345" (Multi-account isolation mode)
        matcher = TransactionMatcher()
        result = matcher.match(buff_orders, steam_sales, current_steam_id="12345")

        # We expect:
        # - buy1 matches sell1 (FIFO among active purchases)
        # - buy2 (different steam ID) is categorized into unmatched_other_buys
        # - buy3 (empty steam ID) is categorized into unmatched_no_steamid_buys
        # - unmatched_buys is empty because there are no active unmatched buys
        self.assertEqual(len(result.matched), 1)
        self.assertEqual(result.matched[0].buff_order_id, "buy1")

        self.assertEqual(len(result.unmatched_buys), 0)

        self.assertEqual(len(result.unmatched_other_buys), 1)
        self.assertEqual(result.unmatched_other_buys[0].buff_order_id, "buy2")
        self.assertEqual(result.unmatched_other_buys[0].buyer_steamid, "67890")

        self.assertEqual(len(result.unmatched_no_steamid_buys), 1)
        self.assertEqual(result.unmatched_no_steamid_buys[0].buff_order_id, "buy3")

        # Case 2: No active Steam ID (Legacy single-account mode)
        result_legacy = matcher.match(buff_orders, steam_sales, current_steam_id="")

        # We expect:
        # - buy1 matches sell1 (FIFO among all purchases)
        # - buy2 and buy3 remain unmatched in unmatched_buys
        # - unmatched_other_buys and unmatched_no_steamid_buys are empty
        self.assertEqual(len(result_legacy.matched), 1)
        self.assertEqual(result_legacy.matched[0].buff_order_id, "buy1")
        
        self.assertEqual(len(result_legacy.unmatched_buys), 2)
        self.assertEqual(result_legacy.unmatched_buys[0].buff_order_id, "buy2")
        self.assertEqual(result_legacy.unmatched_buys[1].buff_order_id, "buy3")
        
        self.assertEqual(len(result_legacy.unmatched_other_buys), 0)
        self.assertEqual(len(result_legacy.unmatched_no_steamid_buys), 0)
