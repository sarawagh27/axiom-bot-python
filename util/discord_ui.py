"""Discord response styling helpers for Axiom."""

from __future__ import annotations

import time
from typing import Iterable

import discord


class AxiomColor:
    PRIMARY = discord.Colour.from_rgb(88, 101, 242)
    SUCCESS = discord.Colour.from_rgb(34, 197, 94)
    WARNING = discord.Colour.from_rgb(245, 158, 11)
    DANGER = discord.Colour.from_rgb(239, 68, 68)
    NEUTRAL = discord.Colour.from_rgb(100, 116, 139)


STATUS_BADGES = {
    "healthy": "[OK]",
    "watch": "[WATCH]",
    "degraded": "[DEGRADED]",
    "critical": "[CRITICAL]",
    "none": "[CLEAR]",
    "low": "[LOW]",
    "medium": "[MEDIUM]",
    "high": "[HIGH]",
}


def badge(value: str) -> str:
    return STATUS_BADGES.get(value.lower(), f"[{value.upper()}]")


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
) -> discord.Embed:
    prefix = f"{badge(status)} " if status else ""
    embed = discord.Embed(
        title=f"{prefix}{title}",
        description=description,
        colour=colour or (severity_colour(status) if status else AxiomColor.PRIMARY),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Axiom Operations")
    return embed


def metric(name: str, value: object) -> str:
    return f"{name}: **{value}**"


def join_lines(lines: Iterable[str], empty: str = "No data available.") -> str:
    materialized = [line for line in lines if line]
    return "\n".join(materialized) if materialized else empty


def compact_timestamp(timestamp: float | int | None) -> str:
    if not timestamp:
        return "Never"
    return f"<t:{int(timestamp)}:R>"


def utc_now_ts() -> int:
    return int(time.time())
