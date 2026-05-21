"""
cogs/operations.py - operational intelligence commands for server admins.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.anomaly_detection import AnomalySignal, anomaly_detector
from core.incidents import incident_service
from core.server_health import ServerHealthSnapshot, server_health_analyzer
from services.operational_intelligence import operational_intelligence_service
from util.discord_ui import badge, join_lines, make_embed
from util.permissions import is_admin


SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "watch": 2, "high": 3, "degraded": 3, "critical": 4}
ALERT_DEDUP_SECONDS = 3600


def _clip(value: str, limit: int = 1024) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 20].rstrip()}... [truncated]"


def _window_label(window_minutes: int) -> str:
    if window_minutes % 1440 == 0:
        return f"{window_minutes // 1440}d"
    if window_minutes % 60 == 0:
        return f"{window_minutes // 60}h"
    return f"{window_minutes}m"


def _severity_label(value: str) -> str:
    return f"{badge(value)} `{value}`"


def _require_guild_id(interaction: discord.Interaction) -> int:
    if interaction.guild_id is None:
        raise RuntimeError("Operations commands require a guild context.")
    return interaction.guild_id


def _pressure_ratio(count: int, threshold: int) -> str:
    if threshold <= 0:
        return "n/a"
    return f"{count / threshold:.1f}x threshold"


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
        f"Signal: **{signal.count}** / **{signal.threshold}** ({_pressure_ratio(signal.count, signal.threshold)})",
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
    return _clip("\n".join(parts))


def _format_incident(incident: dict) -> str:
    linked_events = incident.get("linked_event_ids") or []
    parts = [
        f"`{incident['incident_id']}` - {_severity_label(incident['severity'])} - **{incident['status']}**",
        incident["description"],
        (
            f"Signal: **{incident['count']}** / **{incident['threshold']}** "
            f"({_pressure_ratio(incident['count'], incident['threshold'])})"
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
    return _clip("\n".join(parts))


def _trend_comparison(guild_id: int, window_seconds: int) -> dict[str, Any]:
    from core.database import db
    from core.telemetry import EventName

    now = time.time()
    events = db.get_operational_events(guild_id, window_seconds * 2)
    current = [event for event in events if event["timestamp"] >= now - window_seconds]
    previous = [
        event
        for event in events
        if now - (window_seconds * 2) <= event["timestamp"] < now - window_seconds
    ]

    def summary(items: list[dict[str, Any]]) -> dict[str, int]:
        counts = Counter(event["event_type"] for event in items)
        severity = Counter(event["severity"] for event in items)
        return {
            "events": len(items),
            "commands": counts.get(EventName.COMMAND_USED, 0),
            "sessions": counts.get(EventName.SESSION_STARTED, 0),
            "rate_limits": counts.get(EventName.COMMAND_RATE_LIMITED, 0),
            "rejections": counts.get(EventName.COMMAND_REJECTED, 0),
            "errors": severity.get("error", 0) + severity.get("critical", 0),
        }

    return {"current": summary(current), "previous": summary(previous)}


def _trend_line(label: str, current: int, previous: int) -> str:
    if current == previous:
        marker = "steady"
    elif current > previous:
        marker = f"up +{current - previous}"
    else:
        marker = f"down -{previous - current}"
    return f"{label}: **{current}** ({marker} vs previous window)"


def _recommendations(
    snapshot: ServerHealthSnapshot,
    anomaly_signals: list[AnomalySignal],
    incidents: list[dict[str, Any]],
    trend: dict[str, Any],
) -> list[str]:
    recs: list[str] = []
    current = trend["current"]
    previous = trend["previous"]
    anomaly_types = {signal.anomaly_type for signal in anomaly_signals}

    if incidents:
        recs.append("Review active incidents first; they already have linked telemetry and a stable fingerprint.")
    if "repeated_failures" in anomaly_types or current["errors"] > previous["errors"]:
        recs.append("Inspect recent error events and pause new ping sessions until failures stop clustering.")
    if "cooldown_abuse" in anomaly_types or current["rate_limits"] or current["rejections"] >= 3:
        recs.append("Check whether cooldowns or allowed-channel policy need tightening for the noisy actor.")
    if "abnormal_ping_session_activity" in anomaly_types or snapshot.active_sessions:
        recs.append("Confirm active sessions are intentional; stop or slow any session creating avoidable pressure.")
    if "suspicious_command_spike" in anomaly_types:
        recs.append("Compare top commands against planned admin activity before treating the spike as misuse.")
    if not recs:
        recs.append("No immediate action needed. Keep normal monitoring and review again if pressure rises.")
    return recs[:4]


def _executive_summary(
    snapshot: ServerHealthSnapshot,
    anomaly_count: int,
    incident_count: int,
    trend: dict[str, Any],
) -> str:
    current = trend["current"]
    previous = trend["previous"]
    if snapshot.status == "critical" or incident_count:
        posture = "Active operational pressure is present."
    elif snapshot.status in {"degraded", "watch"} or anomaly_count:
        posture = "The server is mostly functional, with warning signals worth watching."
    else:
        posture = "The server is quiet and inside expected operating bounds."

    movement = "steady"
    if current["errors"] > previous["errors"] or current["rate_limits"] > previous["rate_limits"]:
        movement = "worsening"
    elif current["errors"] < previous["errors"] and current["rate_limits"] <= previous["rate_limits"]:
        movement = "improving"

    return (
        f"{posture} Health is **{snapshot.score}/100** with **{anomaly_count}** anomaly "
        f"signal(s), **{incident_count}** active incident(s), and a **{movement}** trend."
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

            embed = make_embed(
                f"Ops Alert - {guild.name}",
                (
                    "Axiom detected high-confidence operational pressure in the last **15m**. "
                    "This alert was sent proactively because the signal is high severity or above."
                ),
                status=report.highest_severity,
            )
            for signal in fresh_signals:
                embed.add_field(
                    name=f"{badge(signal.severity)} {signal.title}",
                    value=_format_anomaly(signal),
                    inline=False,
                )
            embed.add_field(
                name="Suggested Action",
                value=join_lines(
                    f"- {item}"
                    for item in _recommendations(
                        server_health_analyzer.snapshot(guild.id, 900),
                        fresh_signals,
                        incident_service.active_incidents(guild.id, limit=3),
                        _trend_comparison(guild.id, 900),
                    )
                ),
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
        snapshot = server_health_analyzer.snapshot(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
        )
        anomaly_report = anomaly_detector.detect(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
        )
        incident_service.reconcile_anomalies(anomaly_report)
        incidents = incident_service.active_incidents(guild_id)
        trend = _trend_comparison(guild_id, window_minutes * 60)

        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Status - {guild_name}",
            _executive_summary(snapshot, len(anomaly_report.signals), len(incidents), trend),
            status=snapshot.status,
        )
        embed.add_field(name="Window", value=_window_label(window_minutes), inline=True)
        embed.add_field(name="Health", value=f"**{snapshot.score}/100**\n{_severity_label(snapshot.status)}", inline=True)
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
                _trend_line("Events", trend["current"]["events"], trend["previous"]["events"]),
                _trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
                _trend_line("Rate limits", trend["current"]["rate_limits"], trend["previous"]["rate_limits"]),
            ]),
            inline=False,
        )
        embed.add_field(
            name="Signals",
            value=join_lines(f"- {signal}" for signal in snapshot.signals),
            inline=False,
        )
        embed.add_field(
            name="Recommended Actions",
            value=join_lines(
                f"- {item}"
                for item in _recommendations(snapshot, anomaly_report.signals, incidents, trend)
            ),
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
        report = anomaly_detector.detect(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
        )
        incident_service.reconcile_anomalies(report)
        trend = _trend_comparison(guild_id, window_minutes * 60)
        incidents = incident_service.active_incidents(guild_id, limit=5)
        snapshot = server_health_analyzer.snapshot(guild_id, window_minutes * 60)

        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Anomalies - {guild_name}",
            (
                f"**{len(report.signals)}** signal(s) detected in the last **{_window_label(window_minutes)}**. "
                "Each signal includes why it matters and what to check next."
            ),
            status=report.highest_severity,
        )
        embed.add_field(name="Events Analyzed", value=str(report.total_events), inline=True)
        embed.add_field(name="Highest Severity", value=_severity_label(report.highest_severity), inline=True)
        embed.add_field(
            name="Trend",
            value=join_lines([
                _trend_line("Commands", trend["current"]["commands"], trend["previous"]["commands"]),
                _trend_line("Rejections", trend["current"]["rejections"], trend["previous"]["rejections"]),
                _trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
            ]),
            inline=False,
        )

        if report.signals:
            for signal in report.signals[:5]:
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
            name="Suggested Actions",
            value=join_lines(f"- {item}" for item in _recommendations(snapshot, report.signals, incidents, trend)),
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
        report = anomaly_detector.detect(
            guild_id=guild_id,
            window_seconds=window_minutes * 60,
        )
        incident_service.reconcile_anomalies(report)
        incidents = incident_service.active_incidents(guild_id, limit=5)
        snapshot = server_health_analyzer.snapshot(guild_id, window_minutes * 60)
        trend = _trend_comparison(guild_id, window_minutes * 60)

        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Incidents - {guild_name}",
            (
                f"**{len(incidents)}** active incident(s). "
                "Incidents are durable anomaly fingerprints with linked telemetry."
            ),
            status=incident_service.active_snapshot(guild_id)["highest_severity"],
        )
        embed.add_field(name="Window", value=_window_label(window_minutes), inline=True)
        embed.add_field(name="New Signals", value=str(len(report.signals)), inline=True)
        embed.add_field(name="Health", value=f"**{snapshot.score}/100**\n{_severity_label(snapshot.status)}", inline=True)
        if incidents:
            for incident in incidents:
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
                _trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
                _trend_line("Sessions", trend["current"]["sessions"], trend["previous"]["sessions"]),
                _trend_line("Rate limits", trend["current"]["rate_limits"], trend["previous"]["rate_limits"]),
            ]),
            inline=False,
        )
        embed.add_field(
            name="Suggested Actions",
            value=join_lines(f"- {item}" for item in _recommendations(snapshot, report.signals, incidents, trend)),
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
        analytics = overview["analytics"]
        timeline = overview["timeline"]
        trend = _trend_comparison(guild_id, window_minutes * 60)

        snapshot = ServerHealthSnapshot(
            guild_id=guild_id,
            score=health["score"],
            status=health["status"],
            window_seconds=health["window_seconds"],
            total_events=health["total_events"],
            active_sessions=health["active_sessions"],
            unique_users=health["unique_users"],
            severity_counts=health["severity_counts"],
            event_counts=health["event_counts"],
            last_event_ts=health["last_event_ts"],
            generated_at=overview["generated_at"],
            signals=health["signals"],
        )
        guild_name = interaction.guild.name if interaction.guild else "this server"
        embed = make_embed(
            f"Ops Report - {guild_name}",
            _executive_summary(
                snapshot,
                len(anomalies["signals"]),
                incidents["active_count"],
                trend,
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
                f"Highest severity: {_severity_label(anomalies['highest_severity'])}\n"
                f"Active incidents: **{incidents['active_count']}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Trend Comparison",
            value=join_lines([
                _trend_line("Events", trend["current"]["events"], trend["previous"]["events"]),
                _trend_line("Commands", trend["current"]["commands"], trend["previous"]["commands"]),
                _trend_line("Errors", trend["current"]["errors"], trend["previous"]["errors"]),
                _trend_line("Rate limits", trend["current"]["rate_limits"], trend["previous"]["rate_limits"]),
            ]),
            inline=False,
        )
        top_commands = analytics["top_commands"][:3]
        embed.add_field(
            name="Top Commands",
            value=(
                "\n".join(
                    f"`/{item['command']}`: **{item['uses']}** use(s)"
                    for item in top_commands
                )
                if top_commands
                else "No command usage recorded in this window."
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
            value=join_lines(
                f"- {item}"
                for item in _recommendations(
                    snapshot,
                    [AnomalySignal(**signal) for signal in anomalies["signals"]],
                    incidents["active"],
                    trend,
                )
            ),
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
