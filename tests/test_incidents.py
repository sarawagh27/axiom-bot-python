import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.anomaly_detection import AnomalySignal  # noqa: E402
from core.database import db  # noqa: E402
from core.incidents import IncidentService  # noqa: E402
from core.telemetry import EventName  # noqa: E402


class IncidentLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()
        self.service = IncidentService()

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _signal(self) -> AnomalySignal:
        return AnomalySignal(
            anomaly_type="repeated_failures",
            severity="high",
            title="Repeated command or runtime failures",
            description="Errors exceeded the expected operating band.",
            count=2,
            threshold=2,
            guild_id=123,
            window_seconds=3600,
            command="pingbomb",
            event_type=EventName.COMMAND_ERROR,
        )

    def test_creates_persistent_incident_and_links_matching_telemetry(self) -> None:
        for _ in range(2):
            db.record_operational_event(
                event_type=EventName.COMMAND_ERROR,
                severity="error",
                source="test",
                guild_id=123,
                user_id=456,
                command="pingbomb",
            )

        incident = self.service.create_or_update_from_signal(self._signal())

        self.assertTrue(incident["incident_id"].startswith("inc_"))
        self.assertEqual(incident["status"], "open")
        self.assertEqual(incident["severity"], "high")
        self.assertEqual(incident["event_type"], EventName.COMMAND_ERROR)

        persisted = db.get_incident(incident["incident_id"])
        self.assertEqual(persisted["incident_id"], incident["incident_id"])
        self.assertEqual(len(persisted["linked_event_ids"]), 2)
        self.assertTrue(persisted["timeline"])

    def test_incident_lifecycle_transitions_are_persisted(self) -> None:
        incident = self.service.create_or_update_from_signal(self._signal())

        acknowledged = self.service.acknowledge(
            incident["incident_id"],
            actor_id=999,
            note="Investigating",
        )
        resolved = self.service.resolve(
            incident["incident_id"],
            actor_id=999,
            note="Recovered",
        )

        self.assertEqual(acknowledged["status"], "acknowledged")
        self.assertIsNotNone(acknowledged["acknowledged_at"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertIsNotNone(resolved["resolved_at"])

        active = self.service.active_incidents(123)
        self.assertEqual(active, [])

        timeline_types = {
            item["event_type"]
            for item in self.service.incident_timeline(incident["incident_id"])
        }
        self.assertIn("incident.created", timeline_types)
        self.assertIn("incident.acknowledged", timeline_types)
        self.assertIn("incident.resolved", timeline_types)

    def test_repeated_signal_updates_existing_active_incident(self) -> None:
        first = self.service.create_or_update_from_signal(self._signal())
        second_signal = AnomalySignal(
            **{
                **self._signal().to_dict(),
                "count": 4,
                "severity": "critical",
            }
        )

        second = self.service.create_or_update_from_signal(second_signal)

        self.assertEqual(first["incident_id"], second["incident_id"])
        self.assertEqual(second["count"], 4)
        self.assertEqual(second["severity"], "critical")
        self.assertEqual(len(db.list_incidents(123, statuses=["open", "acknowledged"])), 1)

    def test_resolved_fingerprint_can_open_and_resolve_again(self) -> None:
        first = self.service.create_or_update_from_signal(self._signal())
        self.service.resolve(first["incident_id"], actor_id=999, note="Recovered")

        second = self.service.create_or_update_from_signal(self._signal())
        resolved_second = self.service.resolve(second["incident_id"], actor_id=999, note="Recovered again")

        self.assertNotEqual(first["incident_id"], second["incident_id"])
        self.assertEqual(resolved_second["status"], "resolved")
        self.assertEqual(len(db.list_incidents(123, statuses=["resolved"])), 2)


if __name__ == "__main__":
    unittest.main()
