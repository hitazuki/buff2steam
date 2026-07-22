import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from steam_skin_ops.profit.clients.c5 import C5AuthenticationError, C5Client, C5ClientError


STEAM_A = "76561198000000001"
STEAM_B = "76561198000000002"


def asset(name, price, quantity=1, asset_id="asset-1"):
    return {
        "orderAssetId": asset_id,
        "marketHashName": name,
        "name": name,
        "price": price,
        "quantity": quantity,
        "appId": 730,
    }


class TestC5Client(unittest.TestCase):
    def test_extracts_bound_steam_ids_and_single_account_fallback(self):
        client = C5Client("NC5_accessToken=fake-token; x-traffic-tag=tag")
        self.assertIn("zstd", client.session.headers["Accept-Encoding"])
        self.assertEqual(client.BASE_URL, "https://www.c5game.com/api/v1")
        self.assertEqual(client.session.headers["x-access-token"], "fake-token")
        self.assertEqual(client.session.headers["x-traffic-tag"], "tag")
        client.bound_steam_ids = {STEAM_A}
        parsed = client._parse_order(
            {
                "orderId": "1001",
                "statusName": "交易成功",
                "actualPay": "12.34",
                "orderCreateTime": "2026-07-01T12:00:00",
                "orderAssetList": [asset("AK-47 | Redline", "12.34")],
            },
            None,
            "csgo",
            730,
        )
        self.assertEqual(parsed[0]["buyer_steamid"], STEAM_A)
        self.assertEqual(parsed[0]["source"], "c5")
        self.assertEqual(parsed[0]["price_cny"], 12.34)
        self.assertEqual(
            C5Client.extract_steam_ids({"steamList": [{"steamId": STEAM_A}]}),
            {STEAM_A},
        )

    def test_multiple_accounts_without_order_steam_id_stays_unassigned(self):
        client = C5Client("sid=fake")
        client.bound_steam_ids = {STEAM_A, STEAM_B}
        parsed = client._parse_order(
            {
                "orderId": "1002",
                "actualPay": "5.00",
                "orderAssetList": [asset("Operation Case", "5.00")],
            },
            None,
            "csgo",
            730,
        )
        self.assertEqual(parsed[0]["buyer_steamid"], "")

    def test_list_without_steam_id_fetches_detail(self):
        client = C5Client("sid=fake")
        list_payload = {
            "data": {
                "list": [{"orderId": "1003", "statusName": "交易成功"}],
                "pages": 1,
            }
        }
        detail_payload = {
            "data": {
                "orderId": "1003",
                "receiveSteamId": STEAM_B,
                "actualPay": "9.99",
                "orderCreateTime": 1782907200000,
                "orderAssetList": [asset("M4A1-S | Printstream", "9.99")],
            }
        }
        client._request_json = Mock(side_effect=[list_payload, detail_payload])

        parsed = client._fetch_game_orders("csgo", 730, set())

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["buyer_steamid"], STEAM_B)
        self.assertEqual(client._request_json.call_count, 2)
        list_call = client._request_json.call_args_list[0]
        self.assertEqual(list_call.kwargs["params"]["status"], 3)

    def test_only_completed_orders_are_parsed(self):
        client = C5Client("sid=fake")
        client._request_json = Mock(return_value={
            "data": {
                "list": [
                    {
                        "orderId": "cancelled",
                        "statusName": "已取消",
                        "receiveSteamId": STEAM_A,
                        "orderAssetList": [asset("Cancelled Item", "1.00")],
                    },
                    {
                        "orderId": "success",
                        "statusName": "交易成功",
                        "receiveSteamId": STEAM_A,
                        "actualPay": "2.00",
                        "orderAssetList": [asset("Successful Item", "2.00")],
                    },
                ],
                "pages": 1,
            }
        })
        parsed = client._fetch_game_orders("csgo", 730, set())
        self.assertEqual([item["order_no"] for item in parsed], ["success"])

    def test_multi_asset_actual_payment_allocation_is_cent_exact(self):
        client = C5Client("sid=fake")
        parsed = client._parse_order(
            {
                "orderId": "1004",
                "receiveSteamId": STEAM_A,
                "actualPay": "10.01",
                "orderAssetList": [
                    asset("Item A", "3.00", asset_id="a"),
                    asset("Item B", "7.00", quantity=2, asset_id="b"),
                ],
            },
            None,
            "csgo",
            730,
        )
        self.assertEqual(len(parsed), 3)
        self.assertEqual(round(sum(item["price_cny"] for item in parsed), 2), 10.01)
        self.assertEqual([item["price_cny"] for item in parsed], [1.77, 4.12, 4.12])

    def test_pagination_limit_rejects_incomplete_data(self):
        client = C5Client("sid=fake", page_size=1, max_pages=1)
        client._request_json = Mock(return_value={
            "data": {
                "list": [{
                    "orderId": "1005",
                    "statusName": "交易成功",
                    "receiveSteamId": STEAM_A,
                    "actualPay": "1.00",
                    "orderAssetList": [asset("Item", "1.00")],
                }],
                "pages": 2,
            }
        })
        with self.assertRaisesRegex(C5ClientError, "max_pages"):
            client._fetch_game_orders("csgo", 730, set())

    def test_html_response_is_treated_as_expired_cookie(self):
        client = C5Client("sid=fake")
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.text = "<!doctype html><title>login</title>"
        response.raise_for_status.return_value = None
        client.session.get = Mock(return_value=response)
        with self.assertRaises(C5AuthenticationError):
            client._request_json(client.USER_INFO_PATH)

    def test_invalid_cache_is_rejected(self):
        client = C5Client("sid=fake")
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "c5.json"
            cache.write_text('{"partial": true}', encoding="utf-8")
            with self.assertRaisesRegex(C5ClientError, "缓存格式无效"):
                client.fetch_buy_orders(cache_path=cache)


if __name__ == "__main__":
    unittest.main()
