"""
cogs/pingbomb.py — /pingbomb slash command group.
Validates input, enforces guild config, cooldown + rate-limit, creates session, launches engine.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import CONFIG
from core.session_manager import session_manager
from core.cooldown_manager import cooldown_manager
from core.rate_limiter import rate_limiter
from core.pingbomb_engine import PingbombEngine
from core.guild_config import guild_config_manager
from ui.pingbomb_view import PingbombView
from util.permissions import bot_has_permissions
from util.time_utils import format_duration

log = logging.getLogger("axiom.cogs.pingbomb")


class PingbombCog(commands.Cog, name="Pingbomb"):
    """Commands for the pingbomb session engine."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._engine = PingbombEngine(bot)

    @app_commands.command(
        name="pingbomb",
        description="Repeatedly ping a user a set number of times.",
    )
    @app_commands.describe(
        target="The member to ping",
        count=f"Number of pings (1–{CONFIG.pingbomb_max_count})",
        interval=f"Seconds between pings ({CONFIG.pingbomb_min_interval}–{CONFIG.pingbomb_max_interval})",
        anonymous="Hide your identity — no one sees who started it (default: False)",
    )
    @app_commands.guild_only()
    @bot_has_permissions(send_messages=True, mention_everyone=False)
    async def pingbomb(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        count: app_commands.Range[int, 1, 50],
        interval: app_commands.Range[float, 1.0, 60.0] = 2.0,
        anonymous: bool = False,
    ) -> None:
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        guild_cfg = guild_config_manager.get(guild_id)

        # 0. Guild feature toggle
        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(
                "❌ Pingbomb is **disabled** on this server. An admin can re-enable it with `/settings_toggle_pingbomb`.",
                ephemeral=True,
            )
            return

        # 0b. Channel restriction
        if not guild_config_manager.is_channel_allowed(guild_id, interaction.channel_id):
            allowed = ", ".join(f"<#{c}>" for c in guild_cfg.allowed_channel_ids)
            await interaction.response.send_message(
                f"❌ Pingbomb can only be used in: {allowed}", ephemeral=True,
            )
            return

        # 1. Self-ping guard
        if target.id == user_id:
            await interaction.response.send_message("You can't pingbomb yourself.", ephemeral=True)
            return

        # 2. Bot-ping guard
        if target.bot:
            await interaction.response.send_message("You can't pingbomb a bot.", ephemeral=True)
            return

        # 3. Cooldown check
        remaining = cooldown_manager.check(guild_id, user_id)
        if remaining is not None:
            await interaction.response.send_message(
                f"⏳ You're on cooldown. Try again in **{format_duration(remaining)}**.",
                ephemeral=True,
            )
            return

        # 4. Existing session guard
        if session_manager.has_active(guild_id, user_id):
            await interaction.response.send_message(
                "You already have an active pingbomb session. Stop it first.", ephemeral=True,
            )
            return

        # 5. Rate limiter
        if not rate_limiter.try_acquire(guild_id, user_id):
            await interaction.response.send_message(
                "🚦 Rate limit hit. Please wait a moment before trying again.", ephemeral=True,
            )
            return

        # 6. Guild max count
        if count > guild_cfg.max_count:
            await interaction.response.send_message(
                f"❌ This server's max ping count is **{guild_cfg.max_count}**.", ephemeral=True,
            )
            return

        # 7. Guild min interval
        if interval < guild_cfg.min_interval:
            await interaction.response.send_message(
                f"❌ This server's minimum interval is **{guild_cfg.min_interval}s**.", ephemeral=True,
            )
            return

        # 8. Create session
        session = session_manager.create(
            guild_id=guild_id,
            user_id=user_id,
            target_id=target.id,
            channel_id=interaction.channel_id,
            count=count,
            interval=interval,
        )

        # 9. Send control panel
        view = PingbombView(session=session, invoker_id=user_id)
        embed = discord.Embed(
            title="💣 Pingbomb Launched",
            description=(
                f"Pinging {target.mention} **{count}** time(s) every **{interval}s**.\n\n"
                f"Use the buttons below to pause or stop."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text="Started anonymously 👤" if anonymous else f"Started by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, view=view)

        # 10. Launch engine with guild cooldown override
        await self._engine.launch(session, cooldown_override=guild_cfg.cooldown_seconds, anonymous=anonymous)
        log.info(
            "/pingbomb invoked: guild=%s invoker=%s target=%s count=%s interval=%s",
            guild_id, user_id, target.id, count, interval,
        )

    @app_commands.command(
        name="pingbomb_status",
        description="Check your current pingbomb session status.",
    )
    @app_commands.guild_only()
    async def pingbomb_status(self, interaction: discord.Interaction) -> None:
        session = session_manager.get(interaction.guild_id, interaction.user.id)

        if session is None:
            remaining = cooldown_manager.check(interaction.guild_id, interaction.user.id)
            if remaining:
                msg = f"No active session. Cooldown expires in **{format_duration(remaining)}**."
            else:
                msg = "You have no active pingbomb session."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        embed = discord.Embed(title="📊 Session Status", colour=discord.Colour.blurple())
        embed.add_field(name="State", value=session.state.name, inline=True)
        embed.add_field(name="Target", value=f"<@{session.target_id}>", inline=True)
        embed.add_field(name="Progress", value=f"{session.pings_sent} / {session.count}", inline=True)
        embed.add_field(name="Interval", value=f"{session.interval}s", inline=True)
        embed.add_field(name="Elapsed", value=format_duration(session.elapsed), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingbombCog(bot))
