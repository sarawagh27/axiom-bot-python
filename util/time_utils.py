"""
utils/time_utils.py — Human-readable duration parsing and formatting.
"""

from __future__ import annotations

import re
from typing import Optional

# Regex: matches patterns like "10s", "2m", "1h", "1d", "1m30s"
_DURATION_RE = re.compile(
    r"(?:(?P<days>\d+)\s*d)?"
    r"(?:(?P<hours>\d+)\s*h)?"
    r"(?:(?P<minutes>\d+)\s*m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)\s*s)?",
    re.IGNORECASE,
)


def parse_duration(value: str) -> Optional[float]:
    """
    Parse a human duration string into total seconds (float).

    Examples
    --------
    >>> parse_duration("5s")
    5.0
    >>> parse_duration("2m")
    120.0
    >>> parse_duration("1d")
    86400.0
    >>> parse_duration("1m30s")
    90.0
    >>> parse_duration("1.5s")
    1.5
    >>> parse_duration("garbage")
    None
    """
    value = value.strip()

    # Plain numeric → treat as seconds
    try:
        return float(value)
    except ValueError:
        pass

    match = _DURATION_RE.fullmatch(value)
    if not match or not any(match.group(g) for g in ("days", "hours", "minutes", "seconds")):
        return None

    days = float(match.group("days") or 0)
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable string.

    Examples
    --------
    >>> format_duration(90)
    '1m 30s'
    >>> format_duration(3661)
    '1h 1m 1s'
    >>> format_duration(5)
    '5s'
    """
    total = int(seconds)
    d, remainder = divmod(total, 86400)
    h, remainder = divmod(remainder, 3600)
    m, s = divmod(remainder, 60)

    parts: list[str] = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")

    return " ".join(parts)


def format_relative(seconds: float) -> str:
    """Return a short 'in X' style label (e.g., 'in 5s', 'in 2m')."""
    return f"in {format_duration(seconds)}"
