import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.database import db  # noqa: E402
from core.telemetry import EventName  # noqa: E402
from services.operational_intelligence import operational_intelligence_service  # noqa: E402
from services.operational_events import OperationalEventType  # noqa: E402


class OperationalIntelligenceServiceTest(unittest.TestCase):
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

        overview = operational_intelligence_service.overview(guild_id=123, window_seconds=3600)

        self.assertEqual(overview["guild_id"], 123)
        self.assertIn("live_metrics", overview)
        self.assertIn("timeline", overview)
        self.assertIn("incidents", overview)
        self.assertEqual(overview["analytics"]["top_commands"][0]["command"], "pingbomb")
        self.assertEqual(overview["analytics"]["cooldown_trigger_count"], 1)
        self.assertEqual(overview["analytics"]["command_error_count"], 1)
        self.assertEqual(overview["health"]["factors"]["command_failures"], 1)
        self.assertTrue(overview["events"])
        self.assertTrue(overview["timeline"])

    def test_recent_event_cursor_remains_available_to_internal_workers(self) -> None:
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

        snapshot = operational_intelligence_service.overview(guild_id=123, window_seconds=3600)
        new_events = db.get_operational_events_after(123, after_id=first_id, limit=10)

        self.assertEqual(db.get_latest_operational_event_id(123), first_id + 1)
        self.assertEqual(len(new_events), 1)
        self.assertEqual(new_events[0]["event_type"], OperationalEventType.COMMAND_ERROR)
        self.assertEqual(new_events[0]["event_name"], OperationalEventType.COMMAND_ERROR)
        self.assertEqual(new_events[0]["schema_version"], 1)
        self.assertGreater(snapshot["live_metrics"]["error_spikes"], 0)

    def test_incidents_are_derived_from_anomalies(self) -> None:
        for _ in range(3):
            db.record_operational_event(
                event_type=EventName.COMMAND_ERROR,
                severity="error",
                source="test",
                guild_id=123,
                user_id=456,
                command="pingbomb",
            )

        overview = operational_intelligence_service.overview(guild_id=123, window_seconds=3600)
        incident = overview["incidents"]["active"][0]

        self.assertEqual(overview["incidents"]["active_count"], 1)
        self.assertEqual(incident["status"], "open")
        self.assertEqual(incident["severity"], "high")
        self.assertEqual(incident["anomaly_type"], "repeated_failures")
        self.assertEqual(len(incident["linked_event_ids"]), 3)
        self.assertTrue(any(item["kind"] == "incident" for item in overview["timeline"]))

    def test_empty_overview_has_no_mock_data(self) -> None:
        overview = operational_intelligence_service.overview(window_seconds=3600)

        self.assertIsNone(overview["guild_id"])
        self.assertEqual(overview["events"], [])
        self.assertEqual(overview["analytics"]["top_commands"], [])
        self.assertEqual(overview["health"]["score"], 100)
        self.assertEqual(overview["incidents"]["active"], [])
        self.assertEqual(overview["timeline"], [])


if __name__ == "__main__":
    unittest.main()
