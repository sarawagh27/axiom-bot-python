"""Controlled ping session commands."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import CONFIG
from core.cooldown_manager import cooldown_manager
from core.guild_config import guild_config_manager
from core.pingbomb_engine import PingbombEngine
from core.rate_limiter import rate_limiter
from core.session_manager import session_manager
from services.operational_events import (
    OperationalEventType,
    operational_event_recorder,
)
from ui.pingbomb_view import PingbombView
from util.discord_ui import AXIOM_OPS_FOOTER, error_text, make_embed, status_label, watch_text
from util.permissions import bot_has_permissions
from util.time_utils import format_duration

log = logging.getLogger("axiom.cogs.pingbomb")


class PingbombCog(commands.Cog, name="Pingbomb"):
    """Commands for the ping session engine."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._engine = PingbombEngine(bot)

    @app_commands.command(
        name="pingbomb",
        description="Start a controlled ping session.",
    )
    @app_commands.describe(
        target="The member to ping",
        count=f"Number of pings (1-{CONFIG.pingbomb_max_count})",
        interval=f"Seconds between pings ({CONFIG.pingbomb_min_interval}-{CONFIG.pingbomb_max_interval})",
        anonymous="Hide who started the session.",
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

        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(
                error_text("Ping sessions are disabled on this server. An admin can re-enable them with `/settings_toggle_pingbomb`."),
                ephemeral=True,
            )
            return

        if not guild_config_manager.is_channel_allowed(guild_id, interaction.channel_id):
            allowed = ", ".join(f"<#{channel_id}>" for channel_id in guild_cfg.allowed_channel_ids)
            await interaction.response.send_message(
                error_text(f"Ping sessions can only be used in: {allowed}"),
                ephemeral=True,
            )
            return

        if target.id == user_id:
            await interaction.response.send_message(error_text("You cannot start a ping session against yourself."), ephemeral=True)
            return

        if target.bot:
            await interaction.response.send_message(error_text("Bot accounts are protected from ping sessions."), ephemeral=True)
            return

        remaining = cooldown_manager.check(guild_id, user_id)
        if remaining is not None:
            operational_event_recorder.record(
                event_type=OperationalEventType.COMMAND_REJECTED,
                source="pingbomb_command",
                severity="warning",
                guild_id=guild_id,
                user_id=user_id,
                command="pingbomb",
                metadata={
                    "reason": "cooldown",
                    "remaining_seconds": round(remaining, 3),
                },
            )
            await interaction.response.send_message(
                watch_text(f"Cooldown active. Try again in **{format_duration(remaining)}**."),
                ephemeral=True,
            )
            return

        if session_manager.has_active(guild_id, user_id):
            await interaction.response.send_message(
                watch_text("You already have an active ping session. Stop it first."),
                ephemeral=True,
            )
            return

        if not rate_limiter.try_acquire(guild_id, user_id):
            retry_after = max(1, round(rate_limiter.retry_after(guild_id, user_id)))
            operational_event_recorder.record(
                event_type=OperationalEventType.COMMAND_RATE_LIMITED,
                source="pingbomb_command",
                severity="warning",
                guild_id=guild_id,
                user_id=user_id,
                command="pingbomb",
                metadata={"retry_after": retry_after},
            )
            await interaction.response.send_message(
                watch_text(f"Rate limit reached. Try again in about **{retry_after}s**."),
                ephemeral=True,
            )
            return

        if count > guild_cfg.max_count:
            await interaction.response.send_message(
                error_text(f"This server's max ping count is **{guild_cfg.max_count}**."),
                ephemeral=True,
            )
            return

        if interval < guild_cfg.min_interval:
            await interaction.response.send_message(
                error_text(f"This server's minimum interval is **{guild_cfg.min_interval}s**."),
                ephemeral=True,
            )
            return

        session = session_manager.create(
            guild_id=guild_id,
            user_id=user_id,
            target_id=target.id,
            channel_id=interaction.channel_id,
            count=count,
            interval=interval,
        )

        view = PingbombView(session=session, invoker_id=user_id)
        embed = make_embed(
            "Ping Session Started",
            "A controlled session is now running.",
            status="watch",
            footer=AXIOM_OPS_FOOTER,
        )
        embed.add_field(name="Target", value=target.mention, inline=True)
        embed.add_field(name="Cadence", value=f"{count} ping(s), {interval}s apart", inline=True)
        embed.add_field(name="Controls", value="Use the buttons below to pause or stop.", inline=False)
        embed.set_footer(text="Axiom Operations | Anonymous session" if anonymous else f"Axiom Operations | Started by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, view=view)

        await self._engine.launch(session, cooldown_override=guild_cfg.cooldown_seconds, anonymous=anonymous)

        from core.database import db

        db.record_usage(guild_id, user_id, "pingbomb", target.id, count)
        log.info(
            "/pingbomb invoked: guild=%s invoker=%s target=%s count=%s interval=%s",
            guild_id, user_id, target.id, count, interval,
        )

    @app_commands.command(
        name="pingbomb_status",
        description="Check your current ping session status.",
    )
    @app_commands.guild_only()
    async def pingbomb_status(self, interaction: discord.Interaction) -> None:
        session = session_manager.get(interaction.guild_id, interaction.user.id)

        if session is None:
            remaining = cooldown_manager.check(interaction.guild_id, interaction.user.id)
            if remaining:
                msg = watch_text(f"No active session. Cooldown expires in **{format_duration(remaining)}**.")
            else:
                msg = "No active ping session."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        embed = make_embed("Session Status", "Current ping session state.", footer=AXIOM_OPS_FOOTER)
        embed.add_field(name="State", value=status_label(session.state.name.lower()), inline=True)
        embed.add_field(name="Target", value=f"<@{session.target_id}>", inline=True)
        embed.add_field(name="Progress", value=f"{session.pings_sent} / {session.count}", inline=True)
        embed.add_field(name="Interval", value=f"{session.interval}s", inline=True)
        embed.add_field(name="Elapsed", value=format_duration(session.elapsed), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingbombCog(bot))
