"""Single-target disappearing ping command."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from util.discord_ui import error_text, success_text, watch_text
from util.permissions import bot_has_permissions

log = logging.getLogger("axiom.cogs.ghostping")

_PING_DELAY = 0.8


class GhostPingCog(commands.Cog, name="GhostPing"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ghostping",
        description="Send a disappearing ping to a user.",
    )
    @app_commands.describe(
        target="The member to ping",
        count="How many pings to send (1-10)",
    )
    @app_commands.guild_only()
    @bot_has_permissions(send_messages=True, manage_messages=True)
    async def ghostping(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        count: app_commands.Range[int, 1, 10] = 1,
    ) -> None:
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        guild_cfg = guild_config_manager.get(guild_id)

        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(error_text("Axiom commands are disabled on this server."), ephemeral=True)
            return

        if not guild_config_manager.is_channel_allowed(guild_id, interaction.channel_id):
            allowed = ", ".join(f"<#{channel_id}>" for channel_id in guild_cfg.allowed_channel_ids)
            await interaction.response.send_message(error_text(f"This command can only be used in: {allowed}"), ephemeral=True)
            return

        if target.id == user_id:
            await interaction.response.send_message(error_text("You cannot ping yourself."), ephemeral=True)
            return

        if target.bot:
            await interaction.response.send_message(error_text("Bot accounts are protected."), ephemeral=True)
            return

        await interaction.response.send_message(
            watch_text(f"Sending **{count}** disappearing ping(s) to {target.mention}."),
            ephemeral=True,
        )

        channel = interaction.channel
        success = 0
        for index in range(count):
            try:
                msg = await channel.send(
                    target.mention,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                await msg.delete()
                success += 1
                log.info(
                    "Ghost ping %d/%d: guild=%s invoker=%s target=%s",
                    index + 1, count, guild_id, user_id, target.id,
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    error_text("Axiom cannot send or delete messages in this channel."),
                    ephemeral=True,
                )
                return
            except discord.HTTPException as exc:
                log.error("Ghost ping HTTP error: %s", exc)

            if index < count - 1:
                await asyncio.sleep(_PING_DELAY)

        from core.database import db

        db.record_usage(interaction.guild_id, interaction.user.id, "ghostping", target.id, success)
        await interaction.followup.send(
            success_text(f"Sent **{success}/{count}** disappearing ping(s) to {target.mention}."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GhostPingCog(bot))
