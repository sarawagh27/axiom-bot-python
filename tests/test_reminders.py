import os
import tempfile
import unittest
from datetime import UTC, datetime

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import core.database as database_module  # noqa: E402
from core.database import Database  # noqa: E402
from cogs.community import _format_reminder_list, _reminder_from_row  # noqa: E402
from services.reminders import (  # noqa: E402
    ReminderParseError,
    format_absolute_due,
    format_compact_schedule,
    normalize_timezone,
    parse_reminder_time,
    timezone_view,
)


NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


class ReminderParserTest(unittest.TestCase):
    def test_relative_durations_accept_human_units(self) -> None:
        self.assertEqual(parse_reminder_time("10m", now=NOW).due_at, datetime(2026, 6, 2, 12, 10, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("10 mins", now=NOW).due_at, datetime(2026, 6, 2, 12, 10, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("in 2 hours", now=NOW).due_at, datetime(2026, 6, 2, 14, 0, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("1h 30m", now=NOW).due_at, datetime(2026, 6, 2, 13, 30, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("2d", now=NOW).due_at, datetime(2026, 6, 4, 12, 0, tzinfo=UTC))

    def test_natural_language_dates(self) -> None:
        self.assertEqual(parse_reminder_time("tomorrow", now=NOW).due_at, datetime(2026, 6, 3, 9, 0, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("tomorrow evening", now=NOW).due_at, datetime(2026, 6, 3, 18, 0, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("tomorrow at 5pm", now=NOW).due_at, datetime(2026, 6, 3, 17, 0, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("friday at noon", now=NOW).due_at, datetime(2026, 6, 5, 12, 0, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("next week", now=NOW).due_at, datetime(2026, 6, 9, 9, 0, tzinfo=UTC))

    def test_absolute_style_times_roll_forward(self) -> None:
        self.assertEqual(parse_reminder_time("at 22:46", now=NOW).due_at, datetime(2026, 6, 2, 22, 46, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("at 10pm", now=NOW).due_at, datetime(2026, 6, 2, 22, 0, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("at 10:46 pm", now=NOW).due_at, datetime(2026, 6, 2, 22, 46, tzinfo=UTC))
        self.assertEqual(parse_reminder_time("tonight 8pm", now=NOW).due_at, datetime(2026, 6, 2, 20, 0, tzinfo=UTC))

    def test_timezone_aware_dates(self) -> None:
        parsed = parse_reminder_time("at 10:46 pm IST", now=NOW, user_timezone="Asia/Kolkata")
        self.assertEqual(parsed.due_at, datetime(2026, 6, 2, 17, 16, tzinfo=UTC))
        self.assertTrue(parsed.used_explicit_timezone)

        converted = parse_reminder_time("at 10pm PST", now=NOW, user_timezone="Asia/Kolkata")
        self.assertEqual(converted.due_at, datetime(2026, 6, 3, 5, 0, tzinfo=UTC))
        self.assertEqual(converted.input_timezone_label, "PST")
        self.assertEqual(converted.user_timezone_label, "IST")

    def test_absolute_and_relative_display_are_combined(self) -> None:
        due_at = datetime(2026, 6, 3, 17, 0, tzinfo=UTC)

        self.assertEqual(format_absolute_due(due_at, "UTC", now=NOW), "Tomorrow \u2022 5:00 PM UTC")
        self.assertEqual(
            format_compact_schedule(due_at, "UTC", now=NOW),
            "Tomorrow \u2022 5:00 PM UTC\nIn 1 day",
        )

    def test_timezone_preferences_drive_default_resolution(self) -> None:
        parsed = parse_reminder_time("tomorrow 8am", now=NOW, user_timezone="Asia/Kolkata")
        self.assertEqual(parsed.due_at, datetime(2026, 6, 3, 2, 30, tzinfo=UTC))
        self.assertEqual(normalize_timezone("IST"), "Asia/Kolkata")
        self.assertEqual(timezone_view("Asia/Kolkata", NOW), "Asia/Kolkata (IST)")

    def test_invalid_and_ambiguous_inputs_are_rejected(self) -> None:
        for value in ("", "soon", "10", "at 25pm", "tomorrow someday"):
            with self.subTest(value=value):
                with self.assertRaises(ReminderParseError):
                    parse_reminder_time(value, now=NOW)


class ReminderStorageAndListTest(unittest.TestCase):
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

    def test_reminder_listing_and_deletion(self) -> None:
        later = self.db.create_reminder(
            user_id=1,
            guild_id=10,
            channel_id=20,
            note="Check deployment",
            due_at=1_780_000_000,
            timezone="UTC",
            source="in 2 hours",
        )
        earlier = self.db.create_reminder(
            user_id=1,
            guild_id=10,
            channel_id=20,
            note="Submit assignment",
            due_at=1_770_000_000,
            timezone="UTC",
            source="tomorrow 5pm",
        )

        reminders = [_reminder_from_row(row) for row in self.db.list_reminders(1)]
        self.assertEqual([reminder.id for reminder in reminders], [earlier["id"], later["id"]])
        rendered = _format_reminder_list(reminders, timezone_name="UTC", now=NOW)
        self.assertNotIn(f"ID {earlier['id']}", rendered)
        self.assertIn("Submit assignment", rendered)
        self.assertIn("UTC\n", rendered)

        removed = self.db.delete_reminder(later["id"], 1)
        self.assertEqual(removed["note"], "Check deployment")
        self.assertEqual([row["id"] for row in self.db.list_reminders(1)], [earlier["id"]])

    def test_clear_and_timezone_preferences(self) -> None:
        self.db.create_reminder(
            user_id=1,
            guild_id=None,
            channel_id=None,
            note="One",
            due_at=1_770_000_000,
            timezone="UTC",
            source="tomorrow",
        )
        self.db.create_reminder(
            user_id=1,
            guild_id=None,
            channel_id=None,
            note="Two",
            due_at=1_780_000_000,
            timezone="UTC",
            source="next week",
        )
        self.db.set_user_timezone(1, "Asia/Kolkata")

        self.assertEqual(self.db.get_user_timezone(1), "Asia/Kolkata")
        self.assertEqual(self.db.clear_reminders(1), 2)
        self.assertEqual(self.db.list_reminders(1), [])
        self.assertTrue(self.db.reset_user_timezone(1))
        self.assertIsNone(self.db.get_user_timezone(1))


if __name__ == "__main__":
    unittest.main()
