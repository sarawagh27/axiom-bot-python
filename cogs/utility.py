"""General utility slash commands for Axiom."""

from __future__ import annotations

import logging
import platform
import time

import discord
from discord import app_commands
from discord.ext import commands

from util.discord_ui import AxiomColor, make_embed, metric

log = logging.getLogger("axiom.cogs.utility")

_START_TIME = time.monotonic()


def _latency_status(milliseconds: int) -> str:
    if milliseconds < 125:
        return "healthy"
    if milliseconds < 250:
        return "watch"
    return "degraded"


def _duration_parts(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


class UtilityCog(commands.Cog, name="Utility"):
    """General utility commands available to all users."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check Axiom's gateway latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        ws_latency = round(self.bot.latency * 1000)
        status = _latency_status(ws_latency)
        embed = make_embed(
            "Gateway Ping",
            "Axiom is online and responding.",
            status=status,
        )
        embed.add_field(name="Latency", value=f"**{ws_latency}ms**", inline=True)
        embed.add_field(name="Status", value=status.upper(), inline=True)
        embed.add_field(
            name="Next Step",
            value="Use `/ops status` for live server health and incident context.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="View Axiom's runtime status.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        from core.cooldown_manager import cooldown_manager
        from core.session_manager import session_manager

        uptime_s = int(time.monotonic() - _START_TIME)
        active_sessions = len([
            sess for sess in session_manager.active_sessions()
            if sess.guild_id == interaction.guild_id
        ])
        active_cooldowns = len([
            (key, _) for (key, _) in cooldown_manager.all_active()
            if key[0] == interaction.guild_id
        ])

        embed = make_embed(
            "Runtime Status",
            "Local bot runtime and current guild workload.",
            colour=AxiomColor.PRIMARY,
        )
        embed.add_field(name="Uptime", value=_duration_parts(uptime_s), inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Active Sessions", value=str(active_sessions), inline=True)
        embed.add_field(name="Active Cooldowns", value=str(active_cooldowns), inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="About Axiom.")
    async def info(self, interaction: discord.Interaction) -> None:
        from config import CONFIG

        embed = make_embed(
            "About Axiom",
            (
                "Axiom is a Discord-native operational intelligence bot with "
                "managed sessions, moderation utilities, telemetry, anomaly "
                "detection, health scoring, and incident memory."
            ),
            colour=AxiomColor.PRIMARY,
        )
        embed.add_field(
            name="Identity",
            value="Modern server operations, daily-use utilities, and telemetry-backed intelligence.",
            inline=False,
        )
        embed.add_field(
            name="Core Systems",
            value=(
                "`/ops status` health scoring\n"
                "`/ops report` operational summaries\n"
                "`/ops anomalies` suspicious activity detection\n"
                "`/ops incidents` incident memory"
            ),
            inline=False,
        )
        embed.add_field(
            name="Default Limits",
            value=(
                f"{metric('Max pings', CONFIG.pingbomb_max_count)}\n"
                f"{metric('Min interval', str(CONFIG.pingbomb_min_interval) + 's')}\n"
                f"{metric('Cooldown', str(CONFIG.pingbomb_cooldown_seconds) + 's')}"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Open Axiom's command guide.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = make_embed(
            "Command Center",
            "Phase 1 focuses on fast daily-use commands and Discord-native operational intelligence.",
            colour=AxiomColor.PRIMARY,
        )

        sections = {
            "Start Here": [
                ("`/help`", "Command guide"),
                ("`/ping`", "Gateway latency"),
                ("`/status`", "Runtime snapshot"),
                ("`/info`", "About Axiom"),
            ],
            "Server Intelligence": [
                ("`/server`", "Server profile"),
                ("`/userinfo`", "Member profile"),
                ("`/avatar`", "Avatar viewer"),
                ("`/stats`", "Usage analytics"),
            ],
            "Operations": [
                ("`/ops status`", "Health, incidents, and risk signals"),
                ("`/ops report`", "Operational summary and memory"),
                ("`/ops anomalies`", "Suspicious activity detection"),
                ("`/ops incidents`", "Active incident queue"),
            ],
            "Moderation": [
                ("`/warn`", "Record a warning"),
                ("`/mute`", "Timeout a member"),
                ("`/ban`", "Ban a member"),
                ("`/purge`", "Clean recent messages"),
            ],
            "Community": [
                ("`/poll`", "Create a reaction poll"),
                ("`/remind`", "Set a reminder"),
                ("`/afk`", "Set AFK status"),
                ("`/echo`", "Send a message through Axiom"),
            ],
            "Session Tools": [
                ("`/pingbomb`", "Controlled ping session"),
                ("`/pingbomb_status`", "Your active session"),
                ("`/ghostping`", "Single ghost ping"),
                ("`/massghost`", "Multi-target ghost ping"),
            ],
            "Settings and Admin": [
                ("`/settings`", "Server configuration"),
                ("`/admin_sessions`", "Active sessions"),
                ("`/admin_stop_all`", "Force-stop all sessions"),
                ("`/admin_clear_all_cooldowns`", "Clear cooldowns"),
            ],
        }

        for section, commands_list in sections.items():
            embed.add_field(
                name=section,
                value="\n".join(f"{name} - {description}" for name, description in commands_list),
                inline=False,
            )

        embed.set_footer(text="Axiom Operations | Use /ops status for live intelligence")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
