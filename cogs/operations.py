"""
cogs/operations.py - operational intelligence commands for server admins.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.anomaly_detection import AnomalySignal, anomaly_detector
from core.server_health import ServerHealthSnapshot, server_health_analyzer
from util.permissions import is_admin


def _format_counts(counts: dict[str, int], *, limit: int = 5) -> str:
    if not counts:
        return "None"
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "\n".join(f"`{name}`: **{count}**" for name, count in ordered[:limit])


def _status_colour(snapshot: ServerHealthSnapshot) -> discord.Colour:
    if snapshot.status == "healthy":
        return discord.Colour.green()
    if snapshot.status == "watch":
        return discord.Colour.gold()
    if snapshot.status == "degraded":
        return discord.Colour.orange()
    return discord.Colour.red()


def _anomaly_colour(severity: str) -> discord.Colour:
    if severity in {"critical", "high"}:
        return discord.Colour.red()
    if severity == "medium":
        return discord.Colour.orange()
    return discord.Colour.gold()


def _format_anomaly(signal: AnomalySignal) -> str:
    parts = [signal.description, f"Count: **{signal.count}** / threshold **{signal.threshold}**"]
    if signal.actor_id:
        parts.append(f"Actor: <@{signal.actor_id}>")
    if signal.target_id:
        parts.append(f"Target: <@{signal.target_id}>")
    if signal.command:
        parts.append(f"Command: `/{signal.command}`")
    return "\n".join(parts)


class OperationsCog(commands.Cog, name="Operations"):
    """Admin-only operational intelligence surfaces."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ops_health",
        description="[Admin] View Axiom's recent operational health for this server.",
    )
    @app_commands.describe(
        window_minutes="Lookback window in minutes (default: 60)."
    )
    @app_commands.guild_only()
    @is_admin()
    async def ops_health(
        self,
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 15, 1440] = 60,
    ) -> None:
        snapshot = server_health_analyzer.snapshot(
            guild_id=interaction.guild_id,
            window_seconds=window_minutes * 60,
        )

        embed = discord.Embed(
            title=f"Operational Health - {interaction.guild.name}",
            description=f"**{snapshot.score}/100** - `{snapshot.status}`",
            colour=_status_colour(snapshot),
        )
        embed.add_field(name="Window", value=f"{window_minutes} minutes", inline=True)
        embed.add_field(name="Events", value=str(snapshot.total_events), inline=True)
        embed.add_field(name="Active Sessions", value=str(snapshot.active_sessions), inline=True)
        embed.add_field(name="Unique Users", value=str(snapshot.unique_users), inline=True)
        if snapshot.last_event_ts:
            embed.add_field(
                name="Last Event",
                value=f"<t:{int(snapshot.last_event_ts)}:R>",
                inline=True,
            )
        embed.add_field(
            name="Severity Mix",
            value=_format_counts(snapshot.severity_counts),
            inline=False,
        )
        embed.add_field(
            name="Top Event Types",
            value=_format_counts(snapshot.event_counts),
            inline=False,
        )
        embed.add_field(
            name="Signals",
            value="\n".join(f"- {signal}" for signal in snapshot.signals),
            inline=False,
        )
        embed.set_footer(text="Backed by SQLite operational_events telemetry")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ops_anomalies",
        description="[Admin] Detect suspicious Axiom activity in recent telemetry.",
    )
    @app_commands.describe(
        window_minutes="Lookback window in minutes (default: 60)."
    )
    @app_commands.guild_only()
    @is_admin()
    async def ops_anomalies(
        self,
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 15, 1440] = 60,
    ) -> None:
        report = anomaly_detector.detect(
            guild_id=interaction.guild_id,
            window_seconds=window_minutes * 60,
        )

        embed = discord.Embed(
            title=f"Operational Anomalies - {interaction.guild.name}",
            description=(
                f"**{len(report.signals)}** signal(s) detected "
                f"in the last **{window_minutes}** minutes."
            ),
            colour=_anomaly_colour(report.highest_severity),
        )
        embed.add_field(name="Events Analyzed", value=str(report.total_events), inline=True)
        embed.add_field(name="Highest Severity", value=f"`{report.highest_severity}`", inline=True)

        if report.signals:
            for signal in report.signals[:5]:
                embed.add_field(
                    name=f"{signal.title} ({signal.severity})",
                    value=_format_anomaly(signal),
                    inline=False,
                )
        else:
            embed.add_field(
                name="Signals",
                value="No anomaly thresholds were crossed in this window.",
                inline=False,
            )

        embed.set_footer(text="Dashboard-ready report from operational_events")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OperationsCog(bot))
