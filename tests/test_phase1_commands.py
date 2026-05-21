import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from cogs.community import CommunityCog  # noqa: E402
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
                "remind",
                "afk",
            },
            command_names,
        )

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


if __name__ == "__main__":
    unittest.main()
