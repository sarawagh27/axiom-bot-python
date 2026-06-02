import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from cogs.community import (  # noqa: E402
    AFK_REPLY_COOLDOWN_SECONDS,
    AfkStatus,
    CommunityCog,
    _clean_afk_reason,
    _format_afk_duration,
    _format_afk_mention,
    _format_afk_removed,
    _format_afk_set_confirmation,
)
from cogs.operations import OperationsCog  # noqa: E402
from cogs.utility import UtilityCog  # noqa: E402
from util.time_utils import format_duration, parse_duration  # noqa: E402


class Phase1CommandRegistrationTest(unittest.TestCase):
    def test_daily_commands_are_registered(self) -> None:
        command_names = {
            command.name
            for command in CommunityCog.__cog_app_commands__
        }

        self.assertEqual(
            {
                "server",
                "userinfo",
                "avatar",
                "warn",
                "mute",
                "ban",
                "purge",
                "poll",
                "reminder",
                "timezone",
                "remind",
                "afk",
            },
            command_names,
        )

    def test_reminder_groups_have_expected_subcommands(self) -> None:
        groups = {
            command.name: command
            for command in CommunityCog.__cog_app_commands__
            if command.name in {"reminder", "timezone"}
        }

        self.assertEqual({"add", "list", "remove", "clear"}, {command.name for command in groups["reminder"].commands})
        self.assertEqual({"set", "view", "reset"}, {command.name for command in groups["timezone"].commands})

    def test_reminder_remove_uses_human_option_name(self) -> None:
        reminder_group = next(
            command
            for command in CommunityCog.__cog_app_commands__
            if command.name == "reminder"
        )
        remove_command = next(
            command
            for command in reminder_group.commands
            if command.name == "remove"
        )

        self.assertEqual(remove_command.parameters[0].display_name, "reminder")

    def test_utility_commands_are_registered(self) -> None:
        command_names = {
            command.name
            for command in UtilityCog.__cog_app_commands__
        }

        self.assertEqual({"ping", "status", "info", "help"}, command_names)

    def test_ops_group_has_phase1_subcommands(self) -> None:
        ops_group = next(
            command
            for command in OperationsCog.__cog_app_commands__
            if command.name == "ops"
        )
        command_names = {command.name for command in ops_group.commands}

        self.assertEqual({"status", "report", "anomalies", "incidents"}, command_names)

    def test_duration_parser_supports_day_scale_phase1_commands(self) -> None:
        self.assertEqual(parse_duration("1d"), 86400)
        self.assertEqual(parse_duration("1d2h30m"), 95400)
        self.assertEqual(format_duration(90061), "1d 1h 1m 1s")

    def test_afk_copy_is_short_and_human(self) -> None:
        status = AfkStatus(reason="lunch", since=1000)

        self.assertEqual(_format_afk_set_confirmation(status), "You're now AFK.\nReason: lunch")
        self.assertEqual(_format_afk_duration(1000, now=8740), "2h 9m")
        self.assertEqual(_format_afk_removed(status, now=9140), "Welcome back.\nAFK removed after 2h 15m.")
        self.assertEqual(
            _format_afk_mention("Sara", status, now=1720),
            "Sara is currently away - back in 12m.\nReason: lunch",
        )

    def test_afk_reason_is_optional_and_compact(self) -> None:
        self.assertIsNone(_clean_afk_reason("   "))
        self.assertEqual(_clean_afk_reason("  deep   work  "), "deep work")
        self.assertTrue(_clean_afk_reason("x" * 200).endswith("..."))

    def test_afk_mention_replies_are_cooldown_limited(self) -> None:
        cog = CommunityCog(bot=None)
        guild = SimpleNamespace(id=123)
        author = SimpleNamespace(id=456)
        member = SimpleNamespace(id=789)
        message = SimpleNamespace(guild=guild, author=author, mentions=[member])
        cog._afk[(123, 789)] = AfkStatus(reason=None, since=1000)

        first = cog._mentionable_afk_members(message)
        second = cog._mentionable_afk_members(message)

        self.assertEqual(first, [member])
        self.assertEqual(second, [])
        cog._afk_reply_cooldowns[(123, 456, 789)] = 0
        self.assertEqual(cog._mentionable_afk_members(message), [member])
        self.assertGreaterEqual(
            cog._afk_reply_cooldowns[(123, 456, 789)],
            AFK_REPLY_COOLDOWN_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
