"""General utility slash commands for Axiom."""

from __future__ import annotations

import logging
import platform
import time

import discord
from discord import app_commands
from discord.ext import commands

from util.discord_ui import (
    AXIOM_OPS_FOOTER,
    AxiomColor,
    bullet_list,
    command_line,
    make_embed,
    metric,
    status_label,
)

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
            footer=AXIOM_OPS_FOOTER,
        )
        embed.add_field(name="Latency", value=f"**{ws_latency}ms**", inline=True)
        embed.add_field(name="Status", value=status_label(status), inline=True)
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
            footer=AXIOM_OPS_FOOTER,
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
            footer=AXIOM_OPS_FOOTER,
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
    @app_commands.describe(category="Optional command category to focus.")
    @app_commands.choices(category=[
        app_commands.Choice(name="Start here", value="start"),
        app_commands.Choice(name="Operations", value="operations"),
        app_commands.Choice(name="Moderation", value="moderation"),
        app_commands.Choice(name="Community", value="community"),
        app_commands.Choice(name="Sessions", value="sessions"),
        app_commands.Choice(name="Admin", value="admin"),
    ])
    async def help_command(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str] | None = None,
    ) -> None:
        embed = make_embed(
            "Axiom Command Guide",
            "A calm command surface for server operations, incident awareness, and daily moderation.",
            colour=AxiomColor.PRIMARY,
            footer="Axiom | Use /ops status for live intelligence",
        )

        sections = {
            "start": ("Start Here", [
                ("help", "Command guide"),
                ("ping", "Gateway latency"),
                ("status", "Runtime snapshot"),
                ("info", "About Axiom"),
            ],
            ),
            "server": ("Server Intelligence", [
                ("server", "Server profile"),
                ("userinfo", "Member profile"),
                ("avatar", "Avatar viewer"),
                ("stats", "Usage analytics"),
            ],
            ),
            "operations": ("Operations", [
                ("ops status", "Health, incidents, and pressure"),
                ("ops report", "Operational digest and memory"),
                ("ops anomalies", "Suspicious activity detection"),
                ("ops incidents", "Prioritized incident queue"),
            ],
            ),
            "moderation": ("Moderation", [
                ("warn", "Record a warning"),
                ("mute", "Timeout a member"),
                ("ban", "Ban a member"),
                ("purge", "Clean recent messages"),
            ],
            ),
            "community": ("Community", [
                ("poll", "Create a reaction poll"),
                ("remind", "Set a reminder"),
                ("afk", "Set AFK status"),
                ("echo", "Send a message through Axiom"),
            ],
            ),
            "sessions": ("Session Tools", [
                ("pingbomb", "Controlled ping session"),
                ("pingbomb_status", "Your active session"),
                ("ghostping", "Single ghost ping"),
                ("massghost", "Multi-target ghost ping"),
            ],
            ),
            "admin": ("Settings and Admin", [
                ("settings", "Server configuration"),
                ("admin_sessions", "Active sessions"),
                ("admin_stop_all", "Force-stop all sessions"),
                ("admin_clear_all_cooldowns", "Clear cooldowns"),
            ],
            ),
        }

        visible = sections.items()
        if category:
            selected = {category.value}
            if category.value == "start":
                selected.add("server")
            visible = [(key, value) for key, value in sections.items() if key in selected]

        for _, (section, commands_list) in visible:
            embed.add_field(
                name=section,
                value="\n".join(command_line(name, description) for name, description in commands_list),
                inline=False,
            )
        embed.add_field(
            name="Best Next Step",
            value=bullet_list([
                "`/ops status` for live health.",
                "`/ops report` for a concise operational digest.",
                "`/help category:Operations` to focus this guide.",
            ]),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
