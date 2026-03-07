"""
cogs/ghostping.py — /ghostping command.
Sends N pings to a target then immediately deletes each one.
The target gets a notification but sees nothing when they open it.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from util.permissions import bot_has_permissions

log = logging.getLogger("axiom.cogs.ghostping")

# Small delay between each ghost ping to avoid rate limits
_PING_DELAY = 0.8


class GhostPingCog(commands.Cog, name="GhostPing"):
    """Ghost ping — sends pings that vanish instantly."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ghostping",
        description="Ghost ping a user — they get notified but see nothing.",
    )
    @app_commands.describe(
        target="The member to ghost ping",
        count="How many ghost pings to send (1–10)",
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

        # ── Guild feature check ──────────────────────────────────────
        guild_cfg = guild_config_manager.get(guild_id)
        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(
                "❌ Axiom commands are disabled on this server.", ephemeral=True
            )
            return

        # ── Channel restriction check ────────────────────────────────
        if not guild_config_manager.is_channel_allowed(guild_id, interaction.channel_id):
            allowed = ", ".join(f"<#{c}>" for c in guild_cfg.allowed_channel_ids)
            await interaction.response.send_message(
                f"❌ This command can only be used in: {allowed}", ephemeral=True
            )
            return

        # ── Self-ping guard ──────────────────────────────────────────
        if target.id == user_id:
            await interaction.response.send_message(
                "You can't ghost ping yourself.", ephemeral=True
            )
            return

        # ── Bot-ping guard ───────────────────────────────────────────
        if target.bot:
            await interaction.response.send_message(
                "You can't ghost ping a bot.", ephemeral=True
            )
            return

        # ── Acknowledge immediately (ephemeral — only invoker sees) ──
        await interaction.response.send_message(
            f"👻 Ghost pinging {target.mention} **{count}** time(s)...",
            ephemeral=True,
        )

        # ── Fire ghost pings ─────────────────────────────────────────
        channel = interaction.channel
        success = 0

        for i in range(count):
            try:
                msg = await channel.send(
                    target.mention,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                # Delete instantly — notification already fired
                await msg.delete()
                success += 1
                log.info(
                    "Ghost ping %d/%d: guild=%s invoker=%s target=%s",
                    i + 1, count, guild_id, user_id, target.id,
                )
            except discord.Forbidden:
                log.warning(
                    "Ghost ping failed (Forbidden): guild=%s channel=%s",
                    guild_id, interaction.channel_id,
                )
                await interaction.followup.send(
                    "❌ I don't have permission to send or delete messages in this channel.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as exc:
                log.error("Ghost ping HTTP error: %s", exc)

            # Small gap between pings to avoid rate limits
            if i < count - 1:
                await asyncio.sleep(_PING_DELAY)

        # ── Final confirmation to invoker ────────────────────────────
        await interaction.followup.send(
            f"👻 Done! Sent **{success}/{count}** ghost ping(s) to {target.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GhostPingCog(bot))
