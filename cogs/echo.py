"""
cogs/echo.py — /echo command.
Bot sends a custom message in a specified channel. Fully anonymous —
the slash command interaction is ephemeral so no one sees who typed it.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager

log = logging.getLogger("axiom.cogs.echo")


class EchoCog(commands.Cog, name="Echo"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="echo",
        description="Make the bot say something in a channel. Completely anonymous.",
    )
    @app_commands.describe(
        message="The message to send",
        channel="The channel to send it in (defaults to current channel)",
    )
    @app_commands.guild_only()
    async def echo(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel = None,
    ) -> None:
        guild_id = interaction.guild_id

        # Guild check
        if not guild_config_manager.get(guild_id).pingbomb_enabled:
            await interaction.response.send_message(
                "❌ Axiom commands are disabled on this server.", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel

        # Check bot has permission to send in that channel
        bot_perms = target_channel.permissions_for(interaction.guild.me)
        if not bot_perms.send_messages:
            await interaction.response.send_message(
                f"❌ I don't have permission to send messages in {target_channel.mention}.",
                ephemeral=True,
            )
            return

        # Guard against empty/whitespace messages
        if not message.strip():
            await interaction.response.send_message(
                "❌ Message cannot be empty.", ephemeral=True
            )
            return

        # Limit message length
        if len(message) > 2000:
            await interaction.response.send_message(
                "❌ Message too long. Maximum is 2000 characters.", ephemeral=True
            )
            return

        try:
            await target_channel.send(message)
            # Ephemeral confirmation — only invoker sees this, no trace in channel
            await interaction.response.send_message(
                f"✅ Message sent in {target_channel.mention}.", ephemeral=True
            )
            log.info(
                "/echo: guild=%s user=%s channel=%s msg_len=%d",
                guild_id, interaction.user.id, target_channel.id, len(message),
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Missing permissions to send in {target_channel.mention}.", ephemeral=True
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                f"❌ Failed to send message: {exc}", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EchoCog(bot))
