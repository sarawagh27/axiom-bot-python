import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.database import db  # noqa: E402
from core.telemetry import EventName  # noqa: E402
from scripts.generate_demo_telemetry import DemoTelemetryGenerator  # noqa: E402


class DemoTelemetryGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_generator_creates_operational_events_and_incidents(self) -> None:
        generator = DemoTelemetryGenerator(guild_id=123, seed=7)

        for _ in range(7):
            generator.emit_step()

        events = db.get_operational_events(123, window_seconds=3600)
        active_incidents = db.list_incidents(123, statuses=["open", "acknowledged"])
        event_types = {event["event_type"] for event in events}

        self.assertIn(EventName.COMMAND_USED, event_types)
        self.assertIn(EventName.COMMAND_ERROR, event_types)
        self.assertIn(EventName.INCIDENT_OPENED, event_types)
        self.assertGreaterEqual(len(active_incidents), 1)
        self.assertTrue(active_incidents[0]["linked_event_ids"])


if __name__ == "__main__":
    unittest.main()
