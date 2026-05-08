import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.database import db  # noqa: E402
from services.dashboard_data import dashboard_data_service  # noqa: E402
from services.operational_events import OperationalEventType  # noqa: E402


class DashboardDataServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_overview_uses_operational_telemetry(self) -> None:
        db.record_usage(123, 456, "pingbomb", target_id=789, count=4)
        db.record_operational_event(
            event_type=OperationalEventType.COMMAND_REJECTED,
            severity="warning",
            source="test",
            guild_id=123,
            user_id=456,
            command="pingbomb",
            metadata={"reason": "cooldown"},
        )
        db.record_operational_event(
            event_type=OperationalEventType.COMMAND_ERROR,
            severity="error",
            source="test",
            guild_id=123,
            user_id=456,
            command="pingbomb",
        )

        overview = dashboard_data_service.overview(guild_id=123, window_seconds=3600)

        self.assertEqual(overview["guild_id"], 123)
        self.assertIn("live_metrics", overview)
        self.assertIn("timeline", overview)
        self.assertEqual(overview["analytics"]["top_commands"][0]["command"], "pingbomb")
        self.assertEqual(overview["analytics"]["cooldown_trigger_count"], 1)
        self.assertEqual(overview["analytics"]["command_error_count"], 1)
        self.assertEqual(overview["health"]["factors"]["command_failures"], 1)
        self.assertTrue(overview["events"])
        self.assertTrue(overview["timeline"])

    def test_live_snapshot_uses_event_cursor(self) -> None:
        db.record_usage(123, 456, "pingbomb", target_id=789, count=1)
        first_id = db.get_latest_operational_event_id(123)
        db.record_operational_event(
            event_type=OperationalEventType.COMMAND_ERROR,
            severity="error",
            source="test",
            guild_id=123,
            user_id=456,
            command="pingbomb",
        )

        snapshot = dashboard_data_service.live_snapshot(
            guild_id=123,
            window_seconds=3600,
            after_id=first_id,
        )

        self.assertEqual(snapshot["latest_event_id"], first_id + 1)
        self.assertEqual(len(snapshot["new_events"]), 1)
        self.assertEqual(snapshot["new_events"][0]["event_type"], OperationalEventType.COMMAND_ERROR)
        self.assertGreater(snapshot["live_metrics"]["error_spikes"], 0)

    def test_empty_overview_has_no_mock_data(self) -> None:
        overview = dashboard_data_service.overview(window_seconds=3600)

        self.assertIsNone(overview["guild_id"])
        self.assertEqual(overview["events"], [])
        self.assertEqual(overview["analytics"]["top_commands"], [])
        self.assertEqual(overview["health"]["score"], 100)
        self.assertEqual(overview["timeline"], [])


if __name__ == "__main__":
    unittest.main()
