"""
cogs/massghost.py — /massghost command.
Ghost pings multiple users at the same time.
Usage: /massghost targets:@user1 @user2 @user3 count:2
"""

from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from util.permissions import bot_has_permissions

log = logging.getLogger("axiom.cogs.massghost")


class MassGhostCog(commands.Cog, name="MassGhost"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="massghost",
        description="Ghost ping multiple users at once.",
    )
    @app_commands.describe(
        targets="Mention the users to ghost ping e.g. @user1 @user2 @user3 (max 20)",
        count="How many times to ghost ping each of them (1–5)",
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

        # Guild feature check
        guild_cfg = guild_config_manager.get(guild_id)
        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(
                "❌ Axiom commands are disabled on this server.", ephemeral=True
            )
            return

        # Channel restriction
        if not guild_config_manager.is_channel_allowed(guild_id, interaction.channel_id):
            allowed = ", ".join(f"<#{c}>" for c in guild_cfg.allowed_channel_ids)
            await interaction.response.send_message(
                f"❌ This command can only be used in: {allowed}", ephemeral=True
            )
            return

        # Parse mentioned user IDs from the targets string
        raw_ids = re.findall(r"<@!?(\d+)>", targets)

        if not raw_ids:
            await interaction.response.send_message(
                "❌ No valid mentions found. Use `@username` to mention users.",
                ephemeral=True,
            )
            return

        # Deduplicate and limit to 5
        seen = []
        for uid in raw_ids:
            if uid not in seen:
                seen.append(uid)
        raw_ids = seen[:20]

        # Resolve members, skip bots and self
        members: list[discord.Member] = []
        skipped: list[str] = []

        for uid in raw_ids:
            member = interaction.guild.get_member(int(uid))
            if member is None:
                skipped.append(f"<@{uid}> (not found)")
                continue
            if member.id == interaction.user.id:
                skipped.append(f"{member.mention} (can't ghost ping yourself)")
                continue
            if member.bot:
                skipped.append(f"{member.mention} (bot)")
                continue
            members.append(member)

        if not members:
            await interaction.response.send_message(
                "❌ No valid targets after filtering. Make sure you're not only mentioning bots or yourself.",
                ephemeral=True,
            )
            return

        # Acknowledge to invoker
        names = ", ".join(m.mention for m in members)
        await interaction.response.send_message(
            f"👻 Mass ghost pinging {names} — **{count}x** each...",
            ephemeral=True,
        )

        channel = interaction.channel
        total_sent = 0

        for _ in range(count):
            # Fire all targets simultaneously in this round
            tasks = []
            for member in members:
                tasks.append(_ghost_ping_one(channel, member))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_sent += sum(1 for r in results if r is True)

            # Small gap between rounds if count > 1
            if count > 1:
                await asyncio.sleep(0.8)

        # Final confirmation
        summary = f"👻 Done! Sent **{count}x** ghost ping(s) to **{len(members)}** user(s)."
        if skipped:
            summary += f"\n⚠️ Skipped: {', '.join(skipped)}"

        await interaction.followup.send(summary, ephemeral=True)

        log.info(
            "/massghost: guild=%s invoker=%s targets=%s count=%s",
            guild_id, interaction.user.id,
            [m.id for m in members], count,
        )


async def _ghost_ping_one(channel: discord.TextChannel, member: discord.Member) -> bool:
    """Send and immediately delete a single ping. Returns True on success."""
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
