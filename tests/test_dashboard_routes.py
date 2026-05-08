import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.database import db  # noqa: E402
from keep_alive import app  # noqa: E402
from services.operational_events import OperationalEventType  # noqa: E402


class DashboardRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()
        self.client = app.test_client()

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_dashboard_page_renders(self) -> None:
        db.record_usage(123, 456, "ghostping", target_id=789, count=1)

        response = self.client.get("/dashboard?guild_id=123")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Server Intelligence Dashboard", response.data)
        self.assertIn(b"Live Event Feed", response.data)

    def test_dashboard_json_routes_return_telemetry(self) -> None:
        db.record_operational_event(
            event_type=OperationalEventType.COMMAND_RATE_LIMITED,
            severity="warning",
            source="test",
            guild_id=123,
            user_id=456,
            command="pingbomb",
        )

        health = self.client.get("/dashboard/health?guild_id=123").get_json()
        anomalies = self.client.get("/dashboard/anomalies?guild_id=123").get_json()
        events = self.client.get("/dashboard/events?guild_id=123").get_json()
        data = self.client.get("/dashboard/data?guild_id=123").get_json()

        self.assertEqual(health["guild_id"], 123)
        self.assertEqual(health["factors"]["rate_limit_pressure"], 1)
        self.assertEqual(anomalies["guild_id"], 123)
        self.assertEqual(events[0]["event_type"], OperationalEventType.COMMAND_RATE_LIMITED)
        self.assertEqual(data["guild_id"], 123)


if __name__ == "__main__":
    unittest.main()
