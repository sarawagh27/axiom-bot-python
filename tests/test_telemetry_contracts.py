import os
import tempfile
import time
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.database import db  # noqa: E402
from core.telemetry import (  # noqa: E402
    EventName,
    EventSeverity,
    TelemetryEvent,
    TelemetryValidationError,
    normalize_event_name,
)


class TelemetryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_event_contract_validates_names_severity_and_metadata(self) -> None:
        event = TelemetryEvent(
            event_name=EventName.COMMAND_USED,
            severity=EventSeverity.INFO,
            source="test",
            guild_id=123,
            user_id=456,
            command="pingbomb",
            metadata={"count": 1},
        )

        self.assertEqual(event.event_name, "command.used")
        self.assertEqual(event.to_dict()["event_type"], "command.used")
        self.assertEqual(event.to_dict()["schema_version"], 1)

        with self.assertRaises(TelemetryValidationError):
            TelemetryEvent(event_name="random_event", source="test")

        with self.assertRaises(TelemetryValidationError):
            TelemetryEvent(
                event_name=EventName.COMMAND_USED,
                severity="minor",
                source="test",
            )

    def test_legacy_event_names_are_normalized_on_read(self) -> None:
        self.assertEqual(normalize_event_name("command_used"), EventName.COMMAND_USED)

        db._conn.execute(  # noqa: SLF001 - intentionally verifies migration compatibility.
            """
            INSERT INTO operational_events (
                guild_id, event_type, severity, source, user_id, command, metadata, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (123, "command_used", "info", "legacy-test", 456, "pingbomb", "{}", time.time()),
        )
        db._conn.commit()  # noqa: SLF001

        events = db.get_operational_events(123, window_seconds=999999999)

        self.assertEqual(events[0]["event_type"], EventName.COMMAND_USED)
        self.assertEqual(events[0]["event_name"], EventName.COMMAND_USED)
        self.assertEqual(events[0]["schema_version"], 1)

    def test_database_rejects_unknown_events_before_persisting(self) -> None:
        with self.assertRaises(TelemetryValidationError):
            db.record_operational_event(
                event_type="made_up.event",
                severity=EventSeverity.INFO,
                source="test",
                guild_id=123,
            )

        self.assertEqual(db.get_operational_event_summary(123, 60)["total_events"], 0)


if __name__ == "__main__":
    unittest.main()
