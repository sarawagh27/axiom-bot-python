import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import core.database as database_module  # noqa: E402
from core.database import Database  # noqa: E402


class PingbombAcknowledgementStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = database_module._DB_PATH
        database_module._DB_PATH = os.path.join(self.temp_dir.name, "axiom.db")
        self.db = Database()
        self.db.connect()

    def tearDown(self) -> None:
        self.db.close()
        database_module._DB_PATH = self.old_path
        self.temp_dir.cleanup()

    def test_alert_creation_tracks_target_recipient(self) -> None:
        alert = self.db.create_pingbomb_alert(
            guild_id=123,
            channel_id=456,
            created_by_user_id=789,
            target_id=101,
            count=3,
            interval=2.0,
        )

        summary = self.db.get_pingbomb_ack_summary(alert["id"])
        metrics = self.db.get_pingbomb_ack_metrics(123)

        self.assertEqual(summary, {"total_recipients": 1, "acknowledged": 0, "pending": 1})
        self.assertEqual(metrics["total_alerts"], 1)
        self.assertEqual(metrics["total_recipients"], 1)
        self.assertEqual(metrics["acknowledged"], 0)
        self.assertEqual(metrics["pending"], 1)

    def test_recipient_acknowledgement_is_persisted_once(self) -> None:
        alert = self.db.create_pingbomb_alert(
            guild_id=123,
            channel_id=456,
            created_by_user_id=789,
            target_id=101,
            count=3,
            interval=2.0,
        )

        self.assertEqual(self.db.acknowledge_pingbomb_alert(alert["id"], 999), "not_recipient")
        self.assertEqual(self.db.acknowledge_pingbomb_alert(alert["id"], 101), "acknowledged")
        self.assertEqual(self.db.acknowledge_pingbomb_alert(alert["id"], 101), "already_acknowledged")

        summary = self.db.get_pingbomb_ack_summary(alert["id"])
        user_metrics = self.db.get_pingbomb_user_ack_metrics(123, 101)

        self.assertEqual(summary, {"total_recipients": 1, "acknowledged": 1, "pending": 0})
        self.assertEqual(user_metrics["total_alerts"], 1)
        self.assertEqual(user_metrics["acknowledged"], 1)
        self.assertEqual(user_metrics["pending"], 0)
        self.assertEqual(user_metrics["ack_rate"], 1)


if __name__ == "__main__":
    unittest.main()
