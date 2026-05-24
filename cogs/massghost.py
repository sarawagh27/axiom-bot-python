"""Multi-target disappearing ping command."""

from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from util.discord_ui import error_text, success_text, watch_text
from util.permissions import bot_has_permissions

log = logging.getLogger("axiom.cogs.massghost")


class MassGhostCog(commands.Cog, name="MassGhost"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="massghost",
        description="Send disappearing pings to multiple users.",
    )
    @app_commands.describe(
        targets="Mention users to ping. Maximum 20.",
        count="How many times to ping each user (1-20)",
    )
    @app_commands.guild_only()
    @bot_has_permissions(send_messages=True, manage_messages=True)
    async def massghost(
        self,
        interaction: discord.Interaction,
        targets: str,
        count: app_commands.Range[int, 1, 20] = 1,
    ) -> None:
        guild_id = interaction.guild_id
        guild_cfg = guild_config_manager.get(guild_id)
        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(error_text("Axiom commands are disabled on this server."), ephemeral=True)
            return

        if not guild_config_manager.is_channel_allowed(guild_id, interaction.channel_id):
            allowed = ", ".join(f"<#{channel_id}>" for channel_id in guild_cfg.allowed_channel_ids)
            await interaction.response.send_message(error_text(f"This command can only be used in: {allowed}"), ephemeral=True)
            return

        raw_ids = re.findall(r"<@!?(\d+)>", targets)
        if not raw_ids:
            await interaction.response.send_message(
                error_text("No valid mentions found. Mention users directly."),
                ephemeral=True,
            )
            return

        seen = []
        for user_id in raw_ids:
            if user_id not in seen:
                seen.append(user_id)
        raw_ids = seen[:20]

        members: list[discord.Member] = []
        skipped: list[str] = []
        for user_id in raw_ids:
            member = interaction.guild.get_member(int(user_id))
            if member is None:
                skipped.append(f"<@{user_id}> (not found)")
                continue
            if member.id == interaction.user.id:
                skipped.append(f"{member.mention} (self)")
                continue
            if member.bot:
                skipped.append(f"{member.mention} (bot)")
                continue
            members.append(member)

        if not members:
            await interaction.response.send_message(
                error_text("No valid targets after filtering."),
                ephemeral=True,
            )
            return

        names = ", ".join(member.mention for member in members)
        await interaction.response.send_message(
            watch_text(f"Sending **{count}x** disappearing pings to {names}."),
            ephemeral=True,
        )

        channel = interaction.channel
        total_sent = 0
        for _ in range(count):
            results = await asyncio.gather(
                *(_ghost_ping_one(channel, member) for member in members),
                return_exceptions=True,
            )
            total_sent += sum(1 for result in results if result is True)
            if count > 1:
                await asyncio.sleep(0.8)

        summary = success_text(f"Sent **{total_sent}** disappearing ping(s) to **{len(members)}** user(s).")
        if skipped:
            summary += f"\nSkipped: {', '.join(skipped)}"

        await interaction.followup.send(summary, ephemeral=True)
        log.info(
            "/massghost: guild=%s invoker=%s targets=%s count=%s",
            guild_id, interaction.user.id, [member.id for member in members], count,
        )


async def _ghost_ping_one(channel: discord.TextChannel, member: discord.Member) -> bool:
    try:
        msg = await channel.send(
            member.mention,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await msg.delete()
        return True
    except discord.HTTPException:
        return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MassGhostCog(bot))
