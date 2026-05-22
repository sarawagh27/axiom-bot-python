"""Reusable text formatting for Discord operational intelligence embeds."""

from __future__ import annotations

from typing import Any, Iterable

from util.discord_ui import badge, join_lines


SEVERITY_TONE = {
    "none": "Clear",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "critical": "Critical",
    "healthy": "Healthy",
    "watch": "Watch",
    "degraded": "Degraded",
}


def clip(value: str, limit: int = 1024) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 20].rstrip()}... [truncated]"


def window_label(window_minutes: int) -> str:
    if window_minutes % 1440 == 0:
        return f"{window_minutes // 1440}d"
    if window_minutes % 60 == 0:
        return f"{window_minutes // 60}h"
    return f"{window_minutes}m"


def severity_label(value: str) -> str:
    normalized = value.lower()
    tone = SEVERITY_TONE.get(normalized, normalized.title())
    return f"{badge(normalized)} **{tone}**"


def pressure_label(score: int) -> str:
    if score >= 80:
        return f"**{score}/100**\n{severity_label('critical')}"
    if score >= 60:
        return f"**{score}/100**\n{severity_label('high')}"
    if score >= 35:
        return f"**{score}/100**\n{severity_label('medium')}"
    if score > 0:
        return f"**{score}/100**\n{severity_label('low')}"
    return f"**{score}/100**\n{severity_label('none')}"


def pressure_ratio(count: int, threshold: int) -> str:
    if threshold <= 0:
        return "n/a"
    return f"{count / threshold:.1f}x threshold"


def trend_line(label: str, current: int, previous: int) -> str:
    delta = current - previous
    if delta == 0:
        movement = "steady"
    elif delta > 0:
        movement = f"up {delta}"
    else:
        movement = f"down {abs(delta)}"
    return f"{label}: **{current}** ({movement} vs prior window)"


def bullet_lines(items: Iterable[str], *, empty: str = "No data available.") -> str:
    return join_lines((f"- {item}" for item in items), empty=empty)


def format_what_changed(trend: dict[str, Any]) -> str:
    return bullet_lines(
        trend.get("what_changed", [])[:4],
        empty="No material movement from the prior window.",
    )


def format_command_intelligence(command_intelligence: dict[str, Any]) -> str:
    lines: list[str] = []
    dominant = command_intelligence.get("dominant_command")
    if dominant:
        lines.append(
            f"Dominant command: `/{dominant['command']}` at **{int(dominant['share'] * 100)}%** of usage"
        )
    top_commands = command_intelligence.get("top_commands", [])[:3]
    if top_commands:
        lines.append(
            "Top commands: "
            + ", ".join(
                f"`/{item['command']}` **{item['uses']}**"
                for item in top_commands
            )
        )
    pressure = command_intelligence.get("pressure_by_command", [])[:2]
    if pressure:
        lines.append(
            "Pressure sources: "
            + ", ".join(
                f"`/{item['command']}` **{item['events']}**"
                for item in pressure
            )
        )
    return join_lines(lines, empty="No command pressure detected.")


def format_actor_pressure(command_intelligence: dict[str, Any]) -> str:
    actors = command_intelligence.get("noisy_actors", [])[:4]
    if not actors:
        return "No suspicious actor pressure detected."
    return bullet_lines(
        (
            f"<@{actor['user_id']}>: **{actor['pressure_events']}** pressure event(s), "
            f"**{actor['cooldown_hits']}** cooldown hit(s), **{actor['rate_limits']}** rate limit(s). "
            f"{actor['explanation']}"
        )
        for actor in actors
    )


def format_recommendations(items: list[str]) -> str:
    return bullet_lines(items[:4], empty="No immediate action needed.")
