import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.anomaly_detection import AnomalyDetector, AnomalyRuleConfig  # noqa: E402
from core.database import db  # noqa: E402
from services.operational_events import OperationalEventType  # noqa: E402


class AnomalyDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        db.connect()
        self.detector = AnomalyDetector(
            AnomalyRuleConfig(
                session_starts_per_user=2,
                session_starts_guild=3,
                session_pings_guild=5,
                cooldown_rejections_per_user=2,
                rate_limits_per_user=2,
                command_uses_per_user=3,
                command_uses_per_command=4,
                command_uses_guild=5,
                errors_total=2,
                rejected_commands_total=4,
            )
        )

    def tearDown(self) -> None:
        db.close()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _event(
        self,
        event_type: str,
        *,
        user_id: int = 456,
        command: str | None = None,
        severity: str = "info",
        metadata: dict | None = None,
    ) -> None:
        db.record_operational_event(
            event_type=event_type,
            severity=severity,
            source="test",
            guild_id=123,
            user_id=user_id,
            command=command,
            metadata=metadata,
        )

    def test_detects_session_volume_and_command_spikes(self) -> None:
        for _ in range(3):
            self._event(OperationalEventType.SESSION_STARTED, user_id=456)
        for _ in range(5):
            self._event(OperationalEventType.SESSION_PING, user_id=456)
        for _ in range(5):
            self._event(OperationalEventType.COMMAND_USED, user_id=456, command="pingbomb")

        report = self.detector.detect(guild_id=123, window_seconds=60)
        anomaly_types = {signal.anomaly_type for signal in report.signals}

        self.assertIn("abnormal_ping_session_activity", anomaly_types)
        self.assertIn("suspicious_command_spike", anomaly_types)
        self.assertEqual(report.highest_severity, "high")
        self.assertEqual(report.to_dict()["highest_severity"], "high")

    def test_detects_cooldown_abuse_and_repeated_failures(self) -> None:
        for _ in range(2):
            self._event(
                OperationalEventType.COMMAND_REJECTED,
                user_id=456,
                command="pingbomb",
                severity="warning",
                metadata={"reason": "cooldown"},
            )
            self._event(
                OperationalEventType.COMMAND_RATE_LIMITED,
                user_id=456,
                command="pingbomb",
                severity="warning",
            )
            self._event(
                OperationalEventType.COMMAND_ERROR,
                user_id=789,
                command="ghostping",
                severity="error",
            )

        report = self.detector.detect(guild_id=123, window_seconds=60)
        anomaly_types = {signal.anomaly_type for signal in report.signals}

        self.assertIn("cooldown_abuse", anomaly_types)
        self.assertIn("repeated_failures", anomaly_types)
        self.assertEqual(report.highest_severity, "high")

    def test_ignores_old_events_outside_window(self) -> None:
        db.record_operational_event(
            event_type=OperationalEventType.COMMAND_ERROR,
            severity="error",
            source="test",
            guild_id=123,
            user_id=456,
            command="pingbomb",
            timestamp=1.0,
        )

        report = self.detector.detect(guild_id=123, window_seconds=60)

        self.assertEqual(report.total_events, 0)
        self.assertEqual(report.signals, [])
        self.assertEqual(report.highest_severity, "none")


if __name__ == "__main__":
    unittest.main()
