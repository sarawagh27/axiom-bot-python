"""Anonymous channel message relay."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from util.discord_ui import error_text, success_text

log = logging.getLogger("axiom.cogs.echo")


class EchoCog(commands.Cog, name="Echo"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="echo",
        description="Send a message through Axiom.",
    )
    @app_commands.describe(
        message="The message to send",
        channel="The channel to send it in. Defaults to current channel.",
    )
    @app_commands.guild_only()
    async def echo(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel = None,
    ) -> None:
        guild_id = interaction.guild_id

        if not guild_config_manager.get(guild_id).pingbomb_enabled:
            await interaction.response.send_message(
                error_text("Axiom commands are disabled on this server."),
                ephemeral=True,
            )
            return

        target_channel = channel or interaction.channel
        bot_perms = target_channel.permissions_for(interaction.guild.me)
        if not bot_perms.send_messages:
            await interaction.response.send_message(
                error_text(f"Axiom cannot send messages in {target_channel.mention}."),
                ephemeral=True,
            )
            return

        if not message.strip():
            await interaction.response.send_message(error_text("Message cannot be empty."), ephemeral=True)
            return

        if len(message) > 2000:
            await interaction.response.send_message(
                error_text("Message too long. Maximum is 2000 characters."),
                ephemeral=True,
            )
            return

        try:
            await target_channel.send(message)
            await interaction.response.send_message(
                success_text(f"Message sent in {target_channel.mention}."),
                ephemeral=True,
            )
            log.info(
                "/echo: guild=%s user=%s channel=%s msg_len=%d",
                guild_id, interaction.user.id, target_channel.id, len(message),
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                error_text(f"Missing permissions to send in {target_channel.mention}."),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                error_text(f"Failed to send message: {exc}"),
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EchoCog(bot))
