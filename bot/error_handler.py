"""Global slash command error handling for Axiom."""

from __future__ import annotations

import logging
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from services.operational_events import operational_event_recorder
from util.discord_ui import error_text, watch_text
from util.time_utils import format_duration

log = logging.getLogger("axiom.error_handler")


class ErrorHandler(commands.Cog):
    """Converts command failures into calm, Discord-native responses."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.tree.on_error = self.on_app_command_error

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)

        log.error(
            "Command error in /%s (guild=%s user=%s): %s\n%s",
            interaction.command.name if interaction.command else "unknown",
            interaction.guild_id,
            interaction.user.id,
            original,
            "".join(traceback.format_exception(type(original), original, original.__traceback__)),
        )
        operational_event_recorder.record_command_error(
            command=interaction.command.name if interaction.command else "unknown",
            guild_id=interaction.guild_id,
            user_id=interaction.user.id if interaction.user else None,
            error=original,
        )

        if isinstance(error, app_commands.CommandOnCooldown):
            msg = watch_text(f"Cooldown active. Try again in **{format_duration(error.retry_after)}**.")
        elif isinstance(error, app_commands.MissingPermissions):
            msg = error_text("You do not have permission to use this command.")
        elif isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            msg = error_text(f"Axiom is missing permissions: `{missing}`")
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = error_text("This command can only be used in a server.")
        elif isinstance(error, app_commands.CheckFailure):
            msg = error_text("You do not meet the requirements for this command.")
        else:
            msg = error_text("Something went wrong. The event was recorded for review.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorHandler(bot))
