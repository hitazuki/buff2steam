import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from unittest.mock import patch

from src.monitoring.models import MarketSnapshot, StrategyContext, steam_net_amount
from src.monitoring.runner import MonitorRunner
from src.monitoring.service import MonitorService
from src.monitoring.smis_client import SmisClient, SmisClientError
from src.monitoring.storage import MonitorStorage
from src.monitoring.strategy import ThresholdStrategy
from src.notifications.base import Notifier, NotifyResult
from src.notifications.pushplus import PushPlusNotifier


ITEM = {
    "item_key": "csgo:fracture_case",
    "smis_id": 1579,
    "appid": 730,
    "name": "Fracture Case",
    "name_zh": "裂空武器箱",
}


def make_snapshot(ratio_target=0.70, *, eligible=True, kind="current", offset=0):
    now = datetime.now(timezone.utc) + timedelta(seconds=offset)
    steam_price = 5.34
    steam_net = steam_net_amount(steam_price)
    return MarketSnapshot(
        item_key=ITEM["item_key"],
        smis_id=1579,
        appid=730,
        name="Fracture Case",
        name_zh="裂空武器箱",
        observed_at=now,
        source_updated_at=now,
        buff_sell_price=round(steam_net * ratio_target, 2),
        buff_sell_num=1000 if eligible else 1,
        steam_sell_price=steam_price,
        steam_sell_num=100000,
        steam_transaction_quantity=30000,
        buff_to_steam_ratio=ratio_target,
        kind=kind,
    )


class FakeSource:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.history_calls = 0

    def fetch_history(self, item, days):
        self.history_calls += 1
        return [make_snapshot(0.74, kind="history", offset=-3600)]

    def fetch_current(self, item):
        value = self.snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class RecordingNotifier(Notifier):
    def __init__(self, success=True):
        self.success = success
        self.messages = []

    def send(self, title, content):
        self.messages.append((title, content))
        return NotifyResult(self.success, "ok" if self.success else "failed")


class TestSmisClient(unittest.TestCase):
    def test_auth_header_is_deterministic(self):
        headers = SmisClient().build_auth_headers(1784390400000)
        self.assertEqual(headers["Auth"], "Jv4JZFyQ2TBoieIExzhf9Q==")
        self.assertEqual(headers["Auth2"], SmisClient.DEFAULT_AUTH2)

    def test_history_rejects_misaligned_series(self):
        client = SmisClient(max_retries=1)
        client._request = Mock(return_value=[[1, 2], [3]])
        with self.assertRaises(SmisClientError):
            client.fetch_history(ITEM)

    def test_current_rejects_missing_required_fields(self):
        client = SmisClient(max_retries=1)
        client._request = Mock(return_value={"hashName": "Fracture Case"})
        with self.assertRaises(SmisClientError):
            client.fetch_current(ITEM)


class TestThresholdStrategy(unittest.TestCase):
    def test_steam_net_formula(self):
        self.assertEqual(steam_net_amount(5.34), 4.64)
        self.assertEqual(steam_net_amount(0), 0)

    def test_ratio_boundary_is_eligible(self):
        strategy = ThresholdStrategy(max_ratio=0.72)
        snapshot = make_snapshot(0.72)
        result = strategy.evaluate(StrategyContext(snapshot, now=snapshot.source_updated_at))
        self.assertTrue(result.eligible, result.reasons)

    def test_stale_or_illiquid_snapshot_is_rejected(self):
        strategy = ThresholdStrategy()
        snapshot = make_snapshot(0.70, eligible=False)
        stale = MarketSnapshot(**{
            **snapshot.__dict__,
            "source_updated_at": datetime.now(timezone.utc) - timedelta(minutes=20),
        })
        result = strategy.evaluate(StrategyContext(stale))
        self.assertFalse(result.eligible)
        self.assertTrue(any("时间" in reason for reason in result.reasons))
        self.assertTrue(any("在售数" in reason for reason in result.reasons))


class TestMonitorStorageAndService(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.storage = MonitorStorage(Path(self.tmp.name) / "monitor.db")

    def tearDown(self):
        self.tmp.cleanup()

    def build_service(self, snapshots, notifier=None):
        source = FakeSource(snapshots)
        notifier = notifier or RecordingNotifier()
        service = MonitorService(
            ITEM,
            source,
            self.storage,
            ThresholdStrategy(),
            notifier,
            confirmations=2,
            clear_confirmations=2,
        )
        return service, source, notifier

    def test_snapshot_upsert_and_history_backfill_are_idempotent(self):
        snapshot = make_snapshot(kind="history")
        self.assertEqual(self.storage.save_snapshots([snapshot]), 1)
        self.assertEqual(self.storage.save_snapshots([snapshot]), 0)
        service, source, _ = self.build_service([make_snapshot()])
        service.ensure_history()
        service.ensure_history()
        self.assertEqual(source.history_calls, 1)

    def test_two_hits_alert_once_and_two_clears_rearm(self):
        snapshots = [
            make_snapshot(0.70, offset=1),
            make_snapshot(0.70, offset=2),
            make_snapshot(0.74, offset=3),
            make_snapshot(0.74, offset=4),
            make_snapshot(0.70, offset=5),
            make_snapshot(0.70, offset=6),
        ]
        service, _, notifier = self.build_service(snapshots)
        results = [service.run_once() for _ in snapshots]
        self.assertFalse(results[0].notification_sent)
        self.assertTrue(results[1].notification_sent)
        self.assertFalse(results[2].notification_sent)
        self.assertFalse(results[3].notification_sent)
        self.assertFalse(results[4].notification_sent)
        self.assertTrue(results[5].notification_sent)
        self.assertEqual(len(notifier.messages), 2)

    def test_notification_failure_does_not_activate_alert(self):
        notifier = RecordingNotifier(success=False)
        service, _, _ = self.build_service(
            [make_snapshot(offset=1), make_snapshot(offset=2)], notifier
        )
        service.run_once()
        result = service.run_once()
        self.assertFalse(result.notification_sent)
        self.assertEqual(self.storage.get_state(ITEM["item_key"])["alert_active"], 0)

    def test_dry_run_saves_snapshot_without_changing_state(self):
        service, _, notifier = self.build_service([make_snapshot()])
        result = service.run_once(dry_run=True)
        self.assertTrue(result.success)
        self.assertEqual(self.storage.get_state(ITEM["item_key"])["qualifying_count"], 0)
        self.assertIsNotNone(self.storage.latest_snapshot(ITEM["item_key"]))
        self.assertEqual(notifier.messages, [])

    def test_three_source_failures_alert_once_and_recovery_notifies(self):
        failures = [RuntimeError("down") for _ in range(4)]
        service, _, notifier = self.build_service(failures + [make_snapshot(offset=5)])
        results = [service.run_once() for _ in range(5)]
        self.assertFalse(results[0].success)
        self.assertEqual(len(notifier.messages), 2)
        self.assertIn("监控异常", notifier.messages[0][0])
        self.assertIn("监控恢复", notifier.messages[1][0])
        state = self.storage.get_state(ITEM["item_key"])
        self.assertEqual(state["fetch_failures"], 0)
        self.assertEqual(state["health_alerted"], 0)


class TestPushPlusNotifier(unittest.TestCase):
    def test_successful_response(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 200, "msg": "请求成功"}
        session = Mock()
        session.post.return_value = response
        result = PushPlusNotifier("token", session=session).send("title", "content")
        self.assertTrue(result.success)
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["token"], "token")
        self.assertEqual(payload["template"], "html")

    def test_business_error_is_failure(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 500, "msg": "bad token"}
        session = Mock()
        session.post.return_value = response
        result = PushPlusNotifier("token", max_retries=1, session=session).send("t", "c")
        self.assertFalse(result.success)


class TestMonitorRunner(unittest.TestCase):
    def test_keyboard_interrupt_during_wait_stops_runner(self):
        service = Mock()
        runner = MonitorRunner(service, interval_seconds=300)
        with patch("src.monitoring.runner.time.sleep", side_effect=KeyboardInterrupt):
            runner.run()
        service.run_once.assert_called_once_with()
        self.assertTrue(runner.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
