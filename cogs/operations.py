"""
cogs/operations.py - operational intelligence commands for server admins.
"""

from __future__ import annotations

import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.anomaly_detection import AnomalySignal, anomaly_detector
from core.incidents import incident_service
from core.server_health import ServerHealthSnapshot
from services.operational_intelligence import operational_intelligence_service
from services.operational_formatting import (
    bullet_lines,
    clip,
    format_actor_pressure,
    format_command_intelligence,
    format_recommendations,
    format_what_changed,
    pressure_label,
    pressure_ratio,
    severity_label,
    trend_line,
    window_label,
)
from util.discord_ui import badge, join_lines, make_embed
from util.permissions import is_admin


SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "watch": 2, "high": 3, "degraded": 3, "critical": 4}
ALERT_DEDUP_SECONDS = 3600


def _require_guild_id(interaction: discord.Interaction) -> int:
    if interaction.guild_id is None:
        raise RuntimeError("Operations commands require a guild context.")
    return interaction.guild_id


def _signal_root_cause(signal: AnomalySignal) -> str:
    explanations = {
        "abnormal_ping_session_activity": (
            "Ping-session volume crossed its expected operating band. This usually means "
            "a coordinated ping run, a single eager operator, or a workflow that needs a lower ceiling."
        ),
        "cooldown_abuse": (
            "Protection controls are absorbing repeated retries. The system is holding, "
            "but user behavior is noisy enough to deserve attention."
        ),
        "suspicious_command_spike": (
            "Command usage is materially above the baseline threshold for this window. "
            "Check whether this is planned admin work or sudden misuse."
        ),
        "repeated_failures": (
            "Failures are clustering instead of appearing as isolated errors. Treat this as "
            "a reliability signal until the linked events explain it."
        ),
    }
    return explanations.get(signal.anomaly_type, "Telemetry crossed a configured anomaly threshold.")


def _format_anomaly(signal: AnomalySignal) -> str:
    parts = [
        signal.description,
        f"Severity: {severity_label(signal.severity)}",
        f"Signal: **{signal.count}** / **{signal.threshold}** ({pressure_ratio(signal.count, signal.threshold)})",
        f"Why it matters: {_signal_root_cause(signal)}",
    ]
    if signal.actor_id:
        parts.append(f"Actor: <@{signal.actor_id}>")
    if signal.target_id:
        parts.append(f"Target: <@{signal.target_id}>")
    if signal.command:
        parts.append(f"Command: `/{signal.command}`")
    if signal.event_type:
        parts.append(f"Telemetry: `{signal.event_type}`")
    return clip("\n".join(parts))


def _format_incident(incident: dict) -> str:
    linked_events = incident.get("linked_event_ids") or []
    parts = [
        f"`{incident['incident_id']}` - {severity_label(incident['severity'])} - **{incident['status']}**",
        incident["description"],
        (
            f"Signal: **{incident['count']}** / **{incident['threshold']}** "
            f"({pressure_ratio(incident['count'], incident['threshold'])})"
        ),
        f"Links: **{len(linked_events)}** telemetry event(s)",
    ]
    if incident.get("actor_id"):
        parts.append(f"Actor: <@{incident['actor_id']}>")
    if incident.get("target_id"):
        parts.append(f"Target: <@{incident['target_id']}>")
    if incident.get("command"):
        parts.append(f"Command: `/{incident['command']}`")
    if incident.get("first_seen_ts") and incident.get("last_seen_ts"):
        parts.append(
            f"Observed: <t:{int(incident['first_seen_ts'])}:R> -> <t:{int(incident['last_seen_ts'])}:R>"
        )
    recurrence = incident.get("recurrence")
    if recurrence and recurrence.get("occurrences", 0) > 1:
        parts.append(f"Recurrence: **{recurrence['occurrences']}** related incident(s) in memory")
    return clip("\n".join(parts))


def _snapshot_from_health(health: dict[str, Any], generated_at: float) -> ServerHealthSnapshot:
    return ServerHealthSnapshot(
        guild_id=health["guild_id"],
        score=health["score"],
        status=health["status"],
        window_seconds=health["window_seconds"],
        total_events=health["total_events"],
        active_sessions=health["active_sessions"],
        unique_users=health["unique_users"],
        severity_counts=health["severity_counts"],
        event_counts=health["event_counts"],
        last_event_ts=health["last_event_ts"],
        generated_at=generated_at,
        signals=health["signals"],
    )


def _recurrence_by_fingerprint(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["fingerprint"]: item
        for item in memory.get("recurring_incidents", [])
    }


def _executive_summary(
    snapshot: ServerHealthSnapshot,
    anomaly_count: int,
    incident_count: int,
    trend: dict[str, Any],
    pressure: dict[str, Any] | None = None,
) -> str:
    if snapshot.status == "critical" or incident_count:
        posture = "Active operational pressure is present."
    elif snapshot.status in {"degraded", "watch"} or anomaly_count:
        posture = "The server is mostly functional, with warning signals worth watching."
    else:
        posture = "The server is quiet and inside expected operating bounds."

    pressure_text = ""
    if pressure:
        pressure_text = f" Ops pressure is **{pressure['score']}/100** ({pressure['band']})."

    return (
        f"{posture} Health is **{snapshot.score}/100** with **{anomaly_count}** anomaly "
        f"signal(s), **{incident_count}** active incident(s), and a **{trend['direction']}** trend."
        f"{pressure_text}"
    )


def _predictive_summary(
    snapshot: ServerHealthSnapshot,
    anomaly_count: int,
    active_incident_count: int,
) -> str:
    if snapshot.status == "critical" or active_incident_count >= 3:
        return "High risk: stabilize active incidents before starting more ping sessions."
    if snapshot.status == "degraded" or anomaly_count:
        return "Watch closely: recent telemetry suggests elevated operational pressure."
    if snapshot.status == "watch":
        return "Mostly stable, with enough warning pressure to keep monitoring."
    return "Stable: recent behavior is within expected operating bounds."


class OperationsCog(commands.Cog, name="Operations"):
    """Admin-only operational intelligence surfaces."""

    ops = app_commands.Group(
        name="ops",
        description="Discord-native operational intelligence for this server.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._recent_alerts: dict[str, float] = {}

    async def cog_load(self) -> None:
        self._proactive_anomaly_alerts.start()

    async def cog_unload(self) -> None:
        self._proactive_anomaly_alerts.cancel()

    @tasks.loop(minutes=5)
    async def _proactive_anomaly_alerts(self) -> None:
        now = time.time()
        self._recent_alerts = {
            key: expires_at
            for key, expires_at in self._recent_alerts.items()
            if expires_at > now
        }

        for guild in self.bot.guilds:
            report = anomaly_detector.detect(guild.id, window_seconds=900)
            urgent_signals = [
                signal
                for signal in report.signals
                if SEVERITY_ORDER.get(signal.severity, 0) >= SEVERITY_ORDER["high"]
            ]
            if not urgent_signals:
                continue

            incident_service.reconcile_anomalies(report)
            fresh_signals = []
            for signal in urgent_signals[:3]:
                key = self._alert_key(signal)
                if key in self._recent_alerts:
                    continue
                self._recent_alerts[key] = now + ALERT_DEDUP_SECONDS
                fresh_signals.append(signal)

            if not fresh_signals:
                continue

            channel = self._alert_channel(guild)
            if channel is None:
                continue
            overview = operational_intelligence_service.overview(
                guild_id=guild.id,
                window_seconds=900,
                event_limit=5,
            )

            embed = make_embed(
                f"Ops Alert - {guild.name}",
                (
                    "Axiom detected high-confidence operational pressure in the last **15m**. "
                    f"Current pressure is **{overview['pressure']['score']}/100** "
                    f"({overview['pressure']['band']})."
                ),
                status=report.highest_severity,
            )
            embed.add_field(
                name="Pressure",
                value=pressure_label(overview["pressure"]["score"]),
                inline=True,
            )
            embed.add_field(
                name="Trend",
                value=f"**{overview['trend']['direction']}**",
                inline=True,
            )
            for signal in fresh_signals:
                embed.add_field(
                    name=f"{badge(signal.severity)} {signal.title}",
                    value=_format_anomaly(signal),
                    inline=False,
                )
            embed.add_field(
                name="What Changed",
                value=format_what_changed(overview["trend"]),
                inline=False,
            )
            embed.add_field(
                name="Recommended Response",
                value=format_recommendations(overview["recommendations"]),
                inline=False,
            )
            embed.set_footer(text="Axiom Operations | Proactive anomaly alert")
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                continue

    @_proactive_anomaly_alerts.before_loop
    async def _before_proactive_anomaly_alerts(self) -> None:
        await self.bot.wait_until_ready()

    def _alert_key(self, signal: AnomalySignal) -> str:
        return "|".join(
            [
                str(signal.guild_id),
                signal.anomaly_type,
                signal.event_type or "any",
                str(signal.actor_id or "guild"),
                signal.command or "any",
                signal.severity,
            ]
        )

    def _alert_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        candidates = []
        if guild.system_channel:
            candidates.append(guild.system_channel)
        candidates.extend(guild.text_channels)

        member = guild.me
        if member is None:
            return None

        for channel in candidates:
            permissions = channel.permissions_for(member)
            if permissions.send_messages and permissions.embed_links:
                return channel
        return None

    async def _send_status(
        self,
        interaction: discord.Interaction,
        window_minutes: int,
    ) -> None:
        guild_id = _require_guild_id(interaction)
        overview = operational_intelligence_service.overview(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
            event_limit=8,
        )
        health = overview["health"]
        anomalies = overview["anomalies"]
        incidents = overview["incidents"]["active"]
        trend = overview["trend"]
        command_intelligence = overview["command_intelligence"]
        pressure = overview["pressure"]
        snapshot = _snapshot_from_health(health, overview["generated_at"])

        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Status - {guild_name}",
            _executive_summary(snapshot, len(anomalies["signals"]), len(incidents), trend, pressure),
            status=snapshot.status,
        )
        embed.add_field(name="Window", value=window_label(window_minutes), inline=True)
        embed.add_field(name="Health", value=f"**{snapshot.score}/100**\n{severity_label(snapshot.status)}", inline=True)
        embed.add_field(name="Ops Pressure", value=pressure_label(pressure["score"]), inline=True)
        embed.add_field(name="Incidents", value=f"**{len(incidents)}** active", inline=True)
        embed.add_field(
            name="Activity",
            value=join_lines([
                f"Events: **{snapshot.total_events}**",
                f"Active sessions: **{snapshot.active_sessions}**",
                f"Unique users: **{snapshot.unique_users}**",
            ]),
            inline=True,
        )
        if snapshot.last_event_ts:
            embed.add_field(
                name="Last Event",
                value=f"<t:{int(snapshot.last_event_ts)}:R>",
                inline=True,
            )
        embed.add_field(
            name="Trend",
            value=join_lines([
                trend_line("Events", trend["current"]["events"], trend["previous"]["events"]),
                trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
                trend_line("Rate limits", trend["current"]["rate_limits"], trend["previous"]["rate_limits"]),
            ]),
            inline=False,
        )
        embed.add_field(
            name="What Changed",
            value=format_what_changed(trend),
            inline=False,
        )
        embed.add_field(
            name="Command Intelligence",
            value=format_command_intelligence(command_intelligence),
            inline=False,
        )
        embed.add_field(
            name="Pressure Drivers",
            value=bullet_lines(
                pressure["drivers"],
                empty="No active pressure drivers.",
            ),
            inline=False,
        )
        embed.add_field(
            name="Signals",
            value=join_lines(f"- {signal}" for signal in snapshot.signals),
            inline=False,
        )
        embed.add_field(
            name="Recommended Actions",
            value=format_recommendations(overview["recommendations"]),
            inline=False,
        )
        embed.set_footer(text="Axiom Operations | Calm status from operational telemetry")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _send_anomalies(
        self,
        interaction: discord.Interaction,
        window_minutes: int,
    ) -> None:
        guild_id = _require_guild_id(interaction)
        overview = operational_intelligence_service.overview(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
            event_limit=8,
        )
        anomalies = overview["anomalies"]
        trend = overview["trend"]
        command_intelligence = overview["command_intelligence"]
        pressure = overview["pressure"]

        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Anomalies - {guild_name}",
            (
                f"**{len(anomalies['signals'])}** signal(s) detected in the last **{window_label(window_minutes)}**. "
                f"Ops pressure is **{pressure['score']}/100** with **{pressure['band']}** severity."
            ),
            status=anomalies["highest_severity"],
        )
        embed.add_field(name="Events Analyzed", value=str(anomalies["total_events"]), inline=True)
        embed.add_field(name="Highest Severity", value=severity_label(anomalies["highest_severity"]), inline=True)
        embed.add_field(name="Ops Pressure", value=pressure_label(pressure["score"]), inline=True)
        embed.add_field(
            name="Trend",
            value=join_lines([
                trend_line("Commands", trend["current"]["commands"], trend["previous"]["commands"]),
                trend_line("Rejections", trend["current"]["rejections"], trend["previous"]["rejections"]),
                trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
            ]),
            inline=False,
        )
        embed.add_field(
            name="Suspicious Activity",
            value=format_actor_pressure(command_intelligence),
            inline=False,
        )
        recurring = overview["anomaly_memory"]["recurring_signals"]
        if recurring:
            embed.add_field(
                name="Recurring Patterns",
                value=bullet_lines(
                    (
                        f"**{item['title']}** recurred **{item['occurrences']}** time(s); "
                        f"last seen <t:{int(item['last_seen_ts'])}:R>"
                    )
                    for item in recurring[:3]
                ),
                inline=False,
            )

        if anomalies["signals"]:
            for signal in [AnomalySignal(**item) for item in anomalies["signals"][:5]]:
                embed.add_field(
                    name=f"{badge(signal.severity)} {signal.title}",
                    value=_format_anomaly(signal),
                    inline=False,
                )
        else:
            embed.add_field(
                name="Signals",
                value="No anomaly thresholds were crossed in this window.",
                inline=False,
            )
        embed.add_field(
            name="Recommended Response",
            value=format_recommendations(overview["recommendations"]),
            inline=False,
        )

        embed.set_footer(text="Axiom Operations | Explainable anomaly detection")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ops.command(
        name="status",
        description="[Admin] Get a live operational readout for this server.",
    )
    @app_commands.describe(
        window_minutes="Lookback window in minutes (default: 60)."
    )
    @app_commands.guild_only()
    @is_admin()
    async def ops_status(
        self,
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 15, 1440] = 60,
    ) -> None:
        await self._send_status(interaction, window_minutes)

    @ops.command(
        name="anomalies",
        description="[Admin] Detect suspicious activity from recent telemetry.",
    )
    @app_commands.describe(
        window_minutes="Lookback window in minutes (default: 60)."
    )
    @app_commands.guild_only()
    @is_admin()
    async def ops_anomalies_grouped(
        self,
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 15, 1440] = 60,
    ) -> None:
        await self._send_anomalies(interaction, window_minutes)

    @ops.command(
        name="incidents",
        description="[Admin] Review active operational incidents.",
    )
    @app_commands.describe(
        window_minutes="Lookback window in minutes (default: 60)."
    )
    @app_commands.guild_only()
    @is_admin()
    async def ops_incidents(
        self,
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 15, 1440] = 60,
    ) -> None:
        guild_id = _require_guild_id(interaction)
        overview = operational_intelligence_service.overview(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
            event_limit=8,
        )
        anomalies = overview["anomalies"]
        incidents = overview["incidents"]["active"][:5]
        snapshot = _snapshot_from_health(overview["health"], overview["generated_at"])
        trend = overview["trend"]
        command_intelligence = overview["command_intelligence"]
        pressure = overview["pressure"]
        recurrence_map = _recurrence_by_fingerprint(overview["anomaly_memory"])

        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Incidents - {guild_name}",
            (
                f"**{len(incidents)}** active incident(s). "
                "Incidents are durable anomaly fingerprints with linked telemetry."
            ),
            status=overview["incidents"]["highest_severity"],
        )
        embed.add_field(name="Window", value=window_label(window_minutes), inline=True)
        embed.add_field(name="New Signals", value=str(len(anomalies["signals"])), inline=True)
        embed.add_field(name="Ops Pressure", value=pressure_label(pressure["score"]), inline=True)
        embed.add_field(name="Health", value=f"**{snapshot.score}/100**\n{severity_label(snapshot.status)}", inline=True)
        if incidents:
            for incident in incidents:
                incident = {**incident, "recurrence": recurrence_map.get(incident["fingerprint"])}
                embed.add_field(
                    name=f"{badge(incident['severity'])} {incident['title']}",
                    value=_format_incident(incident),
                    inline=False,
                )
        else:
            embed.add_field(
                name="Incident Queue",
                value="No active incidents. Recent telemetry is below incident thresholds.",
                inline=False,
            )
        embed.add_field(
            name="Incident Signal Breakdown",
            value=join_lines([
                trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
                trend_line("Sessions", trend["current"]["sessions"], trend["previous"]["sessions"]),
                trend_line("Rate limits", trend["current"]["rate_limits"], trend["previous"]["rate_limits"]),
            ]),
            inline=False,
        )
        embed.add_field(
            name="What Changed",
            value=format_what_changed(trend),
            inline=False,
        )
        embed.add_field(
            name="Pressure Sources",
            value=format_actor_pressure(command_intelligence),
            inline=False,
        )
        embed.add_field(
            name="Recommended Response",
            value=format_recommendations(overview["recommendations"]),
            inline=False,
        )

        embed.set_footer(text="Axiom Operations | Incident lifecycle backed by telemetry links")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ops.command(
        name="report",
        description="[Admin] Summarize health, anomalies, incidents, and operational memory.",
    )
    @app_commands.describe(
        window_minutes="Lookback window in minutes (default: 60)."
    )
    @app_commands.guild_only()
    @is_admin()
    async def ops_report(
        self,
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 15, 1440] = 60,
    ) -> None:
        guild_id = _require_guild_id(interaction)
        overview = operational_intelligence_service.overview(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
            event_limit=8,
        )
        health = overview["health"]
        anomalies = overview["anomalies"]
        incidents = overview["incidents"]
        timeline = overview["timeline"]
        trend = overview["trend"]
        command_intelligence = overview["command_intelligence"]
        pressure = overview["pressure"]

        snapshot = _snapshot_from_health(health, overview["generated_at"])
        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Report - {guild_name}",
            _executive_summary(
                snapshot,
                len(anomalies["signals"]),
                incidents["active_count"],
                trend,
                pressure,
            ),
            status=health["status"],
        )
        embed.add_field(
            name="Operational Summary",
            value=join_lines([
                f"Events: **{health['total_events']}**",
                f"Active sessions: **{health['active_sessions']}**",
                f"Unique users: **{health['unique_users']}**",
                (
                    f"Last event: <t:{int(health['last_event_ts'])}:R>"
                    if health["last_event_ts"]
                    else "Last event: Never"
                ),
            ]),
            inline=True,
        )
        embed.add_field(
            name="Risk",
            value=(
                f"Anomalies: **{len(anomalies['signals'])}**\n"
                f"Highest severity: {severity_label(anomalies['highest_severity'])}\n"
                f"Active incidents: **{incidents['active_count']}**\n"
                f"Ops pressure: **{pressure['score']}/100**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Pressure Drivers",
            value=bullet_lines(
                pressure["drivers"],
                empty="No active pressure drivers.",
            ),
            inline=False,
        )
        embed.add_field(
            name="Trend Comparison",
            value=join_lines([
                trend_line("Events", trend["current"]["events"], trend["previous"]["events"]),
                trend_line("Commands", trend["current"]["commands"], trend["previous"]["commands"]),
                trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
                trend_line("Rate limits", trend["current"]["rate_limits"], trend["previous"]["rate_limits"]),
            ]),
            inline=False,
        )
        embed.add_field(
            name="What Changed",
            value=format_what_changed(trend),
            inline=False,
        )
        embed.add_field(
            name="Command Usage Intelligence",
            value=format_command_intelligence(command_intelligence),
            inline=False,
        )
        recurring = overview["anomaly_memory"]["recurring_signals"]
        if recurring:
            embed.add_field(
                name="Recurring Patterns",
                value=bullet_lines(
                    (
                        f"**{item['title']}** recurred **{item['occurrences']}** time(s); "
                        f"last seen <t:{int(item['last_seen_ts'])}:R>"
                    )
                    for item in recurring[:3]
                ),
                inline=False,
            )
        memory_items = timeline[:4]
        embed.add_field(
            name="Operational Memory",
            value=(
                "\n".join(
                    f"{badge(item['severity'])} `{item['kind']}` {item['title']} - {item['description']}"
                    for item in memory_items
                )
                if memory_items
                else "No recent operational timeline entries."
            ),
            inline=False,
        )
        if anomalies["signals"]:
            embed.add_field(
                name="Anomaly Explanation",
                value=join_lines(
                    (
                        f"- **{signal['title']}**: {signal['count']} / {signal['threshold']} "
                        f"for `{signal['anomaly_type']}`"
                    )
                    for signal in anomalies["signals"][:4]
                ),
                inline=False,
            )
        embed.add_field(
            name="Recommendations",
            value=format_recommendations(overview["recommendations"]),
            inline=False,
        )
        embed.set_footer(text="Axiom Operations | Discord-first operational report")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ops_health",
        description="[Admin] Compatibility alias for /ops status.",
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
        await self._send_status(interaction, window_minutes)

    @app_commands.command(
        name="ops_anomalies",
        description="[Admin] Compatibility alias for /ops anomalies.",
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
        await self._send_anomalies(interaction, window_minutes)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OperationsCog(bot))
