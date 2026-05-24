"""Discord response styling helpers for Axiom."""

from __future__ import annotations

import time
from typing import Iterable

import discord


class AxiomColor:
    PRIMARY = discord.Colour.from_rgb(79, 91, 213)
    SUCCESS = discord.Colour.from_rgb(45, 156, 116)
    WARNING = discord.Colour.from_rgb(201, 144, 58)
    DANGER = discord.Colour.from_rgb(196, 73, 73)
    NEUTRAL = discord.Colour.from_rgb(98, 110, 128)


AXIOM_FOOTER = "Axiom | Discord operations"
AXIOM_OPS_FOOTER = "Axiom Operations | Intelligence layer"


STATUS_BADGES = {
    "ok": "[OK]",
    "success": "[OK]",
    "healthy": "[OK]",
    "watch": "[WATCH]",
    "degraded": "[DEGRADED]",
    "critical": "[CRITICAL]",
    "none": "[CLEAR]",
    "clear": "[CLEAR]",
    "low": "[LOW]",
    "medium": "[MEDIUM]",
    "high": "[HIGH]",
    "warning": "[WATCH]",
    "error": "[ERROR]",
    "danger": "[CRITICAL]",
}

STATUS_LABELS = {
    "ok": "OK",
    "success": "OK",
    "healthy": "Healthy",
    "watch": "Watch",
    "degraded": "Degraded",
    "critical": "Critical",
    "none": "Clear",
    "clear": "Clear",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "warning": "Watch",
    "error": "Error",
    "danger": "Critical",
}


def badge(value: str) -> str:
    return STATUS_BADGES.get(value.lower(), f"[{value.upper()}]")


def status_label(value: str) -> str:
    normalized = value.lower()
    return f"{badge(normalized)} {STATUS_LABELS.get(normalized, normalized.title())}"


def severity_colour(value: str) -> discord.Colour:
    normalized = value.lower()
    if normalized in {"healthy", "none", "low", "success"}:
        return AxiomColor.SUCCESS
    if normalized in {"watch", "medium", "warning"}:
        return AxiomColor.WARNING
    if normalized in {"degraded", "critical", "high", "error", "danger"}:
        return AxiomColor.DANGER
    return AxiomColor.PRIMARY


def make_embed(
    title: str,
    description: str | None = None,
    *,
    colour: discord.Colour | None = None,
    status: str | None = None,
    footer: str = AXIOM_FOOTER,
) -> discord.Embed:
    prefix = f"{badge(status)} " if status else ""
    embed = discord.Embed(
        title=f"{prefix}{title}",
        description=description,
        colour=colour or (severity_colour(status) if status else AxiomColor.PRIMARY),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=footer)
    return embed


def metric(name: str, value: object) -> str:
    return f"{name}: **{value}**"


def field_line(name: str, value: object) -> str:
    return f"{name}: **{value}**"


def command_line(command: str, description: str) -> str:
    return f"`/{command}` - {description}"


def join_lines(lines: Iterable[str], empty: str = "No data available.") -> str:
    materialized = [line for line in lines if line]
    return "\n".join(materialized) if materialized else empty


def bullet_list(lines: Iterable[str], empty: str = "No data available.") -> str:
    return join_lines((f"- {line}" for line in lines if line), empty=empty)


def success_text(message: str) -> str:
    return f"[OK] {message}"


def error_text(message: str) -> str:
    return f"[ERROR] {message}"


def watch_text(message: str) -> str:
    return f"[WATCH] {message}"


def compact_timestamp(timestamp: float | int | None) -> str:
    if not timestamp:
        return "Never"
    return f"<t:{int(timestamp)}:R>"


def utc_now_ts() -> int:
    return int(time.time())
