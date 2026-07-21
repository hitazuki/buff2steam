import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from src.monitoring.models import MarketSnapshot, steam_net_amount
from src.monitoring.storage import MonitorStorage
from src.notifications.base import NotifyResult
from src.notifications.astrbot import AstrBotNotifier
from src.service.app import create_app
from src.service.manager import MonitoringManager


ITEM = {
    "smis_id": 1579,
    "item_key": "smis:1579",
    "appid": 730,
    "name": "Fracture Case",
    "name_zh": "裂空武器箱",
}


def snapshot(ratio=0.70, offset=0):
    now = datetime.now(timezone.utc) + timedelta(seconds=offset)
    steam_price = 5.34
    return MarketSnapshot(
        item_key=ITEM["item_key"], smis_id=1579, appid=730,
        name=ITEM["name"], name_zh=ITEM["name_zh"],
        observed_at=now, source_updated_at=now,
        buff_sell_price=round(steam_net_amount(steam_price) * ratio, 2),
        buff_sell_num=1000, steam_sell_price=steam_price, steam_sell_num=10000,
        steam_transaction_quantity=30000, buff_to_steam_ratio=ratio,
    )


class FakeSource:
    def __init__(self, ratios=None):
        self.ratios = list(ratios or [0.70])
        self.current_calls = 0

    def fetch_metadata(self, smis_id):
        if int(smis_id) != 1579:
            raise RuntimeError("not found")
        return dict(ITEM)

    def fetch_current(self, item):
        self.current_calls += 1
        ratio = self.ratios.pop(0) if len(self.ratios) > 1 else self.ratios[0]
        if isinstance(ratio, Exception):
            raise ratio
        return snapshot(float(ratio), self.current_calls)

    def fetch_history(self, item, days):
        history = snapshot(0.74, -3600)
        return [MarketSnapshot(**{**history.__dict__, "kind": "history"})]


class StaleSource(FakeSource):
    def fetch_current(self, item):
        value = super().fetch_current(item)
        return MarketSnapshot(**{
            **value.__dict__,
            "source_updated_at": datetime.now(timezone.utc) - timedelta(minutes=30),
        })


class FakeNotifier:
    def __init__(self, failing_umo=None):
        self.failing_umo = failing_umo
        self.messages = []

    def send_to(self, umo, title, content):
        self.messages.append((umo, title, content))
        if umo == self.failing_umo:
            return NotifyResult(False, "failed")
        return NotifyResult(True, "ok")


class FakeRuntime:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def status(self):
        return {"running": self.started, "items": 1, "subscriptions": 1, "outbox": {}}


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.storage = MonitorStorage(Path(self.tmp.name) / "monitor.db")
        self.storage.upsert_item(ITEM)

    def tearDown(self):
        self.tmp.cleanup()

    def manager(self, ratios=None, notifier=None, cache=60):
        return MonitoringManager(
            self.storage, FakeSource(ratios), notifier or FakeNotifier(),
            quote_cache_seconds=cache,
        )

    def test_quote_uses_sixty_second_cache(self):
        manager = self.manager([0.70])
        first = manager.quote("1579")
        second = manager.quote("裂空")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(manager.source.current_calls, 1)

    def test_stale_quote_falls_back_when_source_fails(self):
        self.storage.save_snapshots([snapshot(0.70, -120)])
        manager = self.manager([RuntimeError("down")], cache=1)
        result = manager.quote("1579")
        self.assertTrue(result["stale"])
        self.assertIn("实时刷新失败", result["warning"])

    def test_per_session_thresholds_and_rearm(self):
        notifier = FakeNotifier()
        manager = self.manager([0.70, 0.70, 0.75, 0.75, 0.70, 0.70], notifier)
        self.storage.upsert_subscription(1579, "umo:a", 0.72)
        self.storage.upsert_subscription(1579, "umo:b", 0.68)
        for _ in range(6):
            manager.run_cycle(max_workers=1)
        recipients = [message[0] for message in notifier.messages]
        self.assertEqual(recipients, ["umo:a", "umo:a"])
        self.assertEqual(self.storage.get_subscription_state(1579, "umo:b")["alert_active"], 0)

    def test_outbox_failure_isolated_by_umo(self):
        notifier = FakeNotifier(failing_umo="umo:b")
        manager = self.manager(notifier=notifier)
        self.storage.enqueue_notification("sig", "umo:a", "test", "title", "body")
        self.storage.enqueue_notification("sig", "umo:b", "test", "title", "body")
        result = manager.dispatch_outbox()
        self.assertEqual(result, {"sent": 1, "failed": 1})
        self.assertEqual(self.storage.outbox_counts(), {"pending": 1, "sent": 1})

    def test_stale_source_data_triggers_health_alert(self):
        notifier = FakeNotifier()
        manager = MonitoringManager(self.storage, StaleSource([0.70]), notifier)
        self.storage.upsert_subscription(1579, "umo:a", 0.72)
        for _ in range(3):
            manager.run_cycle(max_workers=1)
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("监控异常", notifier.messages[0][1])
        state = self.storage.get_subscription_state(1579, "umo:a")
        self.assertEqual(state["fetch_failures"], 3)
        self.assertEqual(state["health_alerted"], 1)

    def test_api_auth_crud_and_validation_envelope(self):
        manager = self.manager([0.70])
        app = create_app(manager=manager, runtime=FakeRuntime(), service_token="secret")
        with TestClient(app) as client:
            self.assertEqual(client.get("/v1/items").status_code, 401)
            headers = {"Authorization": "Bearer secret"}
            response = client.post("/v1/subscriptions", headers=headers, json={
                "umo": "astrQQ:FriendMessage:test", "smis_id": 1579,
                "max_ratio_percent": 72,
            })
            self.assertEqual(response.status_code, 200, response.text)
            quote_response = client.get("/v1/quote", headers=headers, params={"q": "1579"})
            self.assertTrue(quote_response.json()["ok"])
            bad = client.patch("/v1/subscriptions/1579", headers=headers, json={
                "umo": "astrQQ:FriendMessage:test", "max_ratio_percent": 0,
            })
            self.assertEqual(bad.status_code, 422)
            self.assertEqual(bad.json()["error"]["code"], "validation_error")

    def test_item_limit_is_enforced_before_source_request(self):
        for smis_id in range(1, 21):
            self.storage.upsert_item({
                "smis_id": smis_id,
                "item_key": f"smis:{smis_id}",
                "appid": 730,
                "name": f"Item {smis_id}",
                "name_zh": f"饰品 {smis_id}",
            })
        manager = self.manager()
        with self.assertRaisesRegex(Exception, "最多只能配置 20 个饰品"):
            manager.add_subscription("umo:test", 9999, 72)

    def test_removing_last_subscription_releases_item_slot(self):
        self.storage.upsert_subscription(1579, "umo:a", 0.72)
        manager = self.manager()
        manager.remove_subscription("umo:a", 1579)
        self.assertIsNone(self.storage.get_item(1579))


class AstrBotNotifierTestCase(unittest.TestCase):
    def test_sends_expected_openapi_payload(self):
        from unittest.mock import Mock

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"status": "ok", "data": {}}
        session = Mock()
        session.post.return_value = response
        notifier = AstrBotNotifier(
            "http://astrbot:6185", "abk_test", session=session
        )
        result = notifier.send_to("astrQQ:FriendMessage:test", "标题", "正文")
        self.assertTrue(result.success)
        call = session.post.call_args
        self.assertEqual(call.kwargs["headers"], {"X-API-Key": "abk_test"})
        self.assertEqual(call.kwargs["json"], {
            "umo": "astrQQ:FriendMessage:test", "message": "标题\n正文",
        })


if __name__ == "__main__":
    unittest.main()
