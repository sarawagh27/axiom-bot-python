import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.database import db  # noqa: E402
from core.server_health import server_health_analyzer  # noqa: E402
from services.operational_events import (  # noqa: E402
    OperationalEventType,
    operational_event_recorder,
)


class OperationalHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_usage_stats_also_create_operational_events(self) -> None:
        db.record_usage(
            guild_id=123,
            user_id=456,
            command="pingbomb",
            target_id=789,
            count=3,
        )

        summary = db.get_operational_event_summary(guild_id=123, window_seconds=60)

        self.assertEqual(summary["total_events"], 1)
        self.assertEqual(summary["event_counts"]["command_used"], 1)
        self.assertEqual(summary["severity_counts"]["info"], 1)

    def test_health_score_degrades_on_errors_and_warnings(self) -> None:
        operational_event_recorder.record(
            event_type=OperationalEventType.COMMAND_ERROR,
            source="test",
            severity="error",
            guild_id=123,
            user_id=456,
            command="pingbomb",
        )
        operational_event_recorder.record(
            event_type=OperationalEventType.COMMAND_RATE_LIMITED,
            source="test",
            severity="warning",
            guild_id=123,
            user_id=456,
            command="pingbomb",
        )

        snapshot = server_health_analyzer.snapshot(guild_id=123, window_seconds=60)

        self.assertLess(snapshot.score, 100)
        self.assertIn(snapshot.status, {"watch", "degraded", "critical"})
        self.assertEqual(snapshot.event_counts[OperationalEventType.COMMAND_ERROR], 1)
        self.assertEqual(snapshot.event_counts[OperationalEventType.COMMAND_RATE_LIMITED], 1)
        self.assertTrue(snapshot.signals)


if __name__ == "__main__":
    unittest.main()
