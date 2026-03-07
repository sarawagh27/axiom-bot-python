"""
bot/error_handler.py — Global app_command and interaction error handler.
Produces user-facing ephemeral error messages and logs server-side details.
"""

import logging
import traceback

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("axiom.error_handler")

# Map known error types to user-friendly messages
_ERROR_MESSAGES: dict[type[Exception], str] = {
    app_commands.MissingPermissions: "You don't have permission to use that command.",
    app_commands.BotMissingPermissions: "I'm missing required permissions to do that.",
    app_commands.CommandOnCooldown: "That command is on cooldown. Try again later.",
    app_commands.NoPrivateMessage: "This command can't be used in DMs.",
}


def _build_embed(title: str, description: str, colour: discord.Colour) -> discord.Embed:
    return discord.Embed(title=title, description=description, colour=colour)


async def _respond(interaction: discord.Interaction, embed: discord.Embed) -> None:
    """Send ephemeral error embed, handling already-responded interactions."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass  # Interaction expired — nothing we can do


def setup_error_handlers(bot: commands.Bot) -> None:
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)

        for err_type, message in _ERROR_MESSAGES.items():
            if isinstance(original, err_type):
                embed = _build_embed("⚠️ Command Error", message, discord.Colour.orange())
                await _respond(interaction, embed)
                return

        # Cooldown with dynamic time remaining
        if isinstance(original, app_commands.CommandOnCooldown):
            msg = f"This command is on cooldown. Retry in **{original.retry_after:.1f}s**."
            embed = _build_embed("⏳ Cooldown", msg, discord.Colour.orange())
            await _respond(interaction, embed)
            return

        # Unknown / unhandled — log full traceback, show generic message
        log.error(
            "Unhandled app command error in '%s' (guild=%s user=%s):\n%s",
            interaction.command.name if interaction.command else "unknown",
            interaction.guild_id,
            interaction.user.id,
            "".join(traceback.format_exception(type(original), original, original.__traceback__)),
        )

        embed = _build_embed(
            "❌ Unexpected Error",
            "Something went wrong. The error has been logged. Please try again.",
            discord.Colour.red(),
        )
        await _respond(interaction, embed)
