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
        self.assertEqual(overview["analytics"]["top_commands"][0]["command"], "pingbomb")
        self.assertEqual(overview["analytics"]["cooldown_trigger_count"], 1)
        self.assertEqual(overview["analytics"]["command_error_count"], 1)
        self.assertEqual(overview["health"]["factors"]["command_failures"], 1)
        self.assertTrue(overview["events"])

    def test_empty_overview_has_no_mock_data(self) -> None:
        overview = dashboard_data_service.overview(window_seconds=3600)

        self.assertIsNone(overview["guild_id"])
        self.assertEqual(overview["events"], [])
        self.assertEqual(overview["analytics"]["top_commands"], [])
        self.assertEqual(overview["health"]["score"], 100)


if __name__ == "__main__":
    unittest.main()
