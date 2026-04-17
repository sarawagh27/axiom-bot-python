"""
bot/error_handler.py — Global slash command error handler.
Catches all command errors and sends user-friendly messages.
Also logs every error with full context for debugging.
"""

from __future__ import annotations

import logging
import traceback

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("axiom.error_handler")


class ErrorHandler(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.tree.on_error = self.on_app_command_error

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:

        # Unwrap the original error if wrapped
        original = getattr(error, "original", error)

        # Log full traceback for debugging
        log.error(
            "Command error in /%s (guild=%s user=%s): %s\n%s",
            interaction.command.name if interaction.command else "unknown",
            interaction.guild_id,
            interaction.user.id,
            original,
            "".join(traceback.format_exception(type(original), original, original.__traceback__)),
        )

        # User-friendly messages based on error type
        if isinstance(error, app_commands.CommandOnCooldown):
            remaining = round(error.retry_after)
            msg = f"⏳ You're on cooldown! Try again in **{remaining}s**."

        elif isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You don't have permission to use this command."

        elif isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            msg = f"❌ I'm missing permissions: `{missing}`"

        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "❌ This command can only be used in a server."

        elif isinstance(error, app_commands.CheckFailure):
            msg = "❌ You don't meet the requirements for this command."

        else:
            msg = "❌ Something went wrong. Please try again."

        # Send response — handle both responded and unresponded interactions
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorHandler(bot))
