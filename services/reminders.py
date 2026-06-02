"""Reminder parsing, formatting, and lightweight domain helpers."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from util.time_utils import parse_duration


MAX_REMINDER_SECONDS = 365 * 24 * 3600
DEFAULT_TIMEZONE = "UTC"

_SPACE_RE = re.compile(r"\s+")
_RELATIVE_RE = re.compile(
    r"^(?:in\s+)?(?=.*\d)\s*"
    r"(?:(?P<days>\d+)\s*(?:d|day|days)\s*)?"
    r"(?:(?P<hours>\d+)\s*(?:h|hr|hrs|hour|hours)\s*)?"
    r"(?:(?P<minutes>\d+)\s*(?:m|min|mins|minute|minutes)\s*)?"
    r"(?:(?P<seconds>\d+)\s*(?:s|sec|secs|second|seconds)\s*)?$",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)?\b",
    re.IGNORECASE,
)

_TIMEZONE_ALIASES = {
    "UTC": "UTC",
    "GMT": "UTC",
    "IST": "Asia/Kolkata",
    "PST": "Etc/GMT+7",
    "EST": "Etc/GMT+5",
    "CST": "Etc/GMT+6",
    "MST": "Etc/GMT+7",
}
_DISPLAY_ABBREVIATIONS = {
    "Etc/GMT+7": "PST",
    "Etc/GMT+5": "EST",
    "Etc/GMT+6": "CST",
    "Asia/Kolkata": "IST",
    "UTC": "UTC",
}
_DAY_NAMES = {name.lower(): index for index, name in enumerate(calendar.day_name)}
_DAY_SHORT_NAMES = {name.lower(): index for index, name in enumerate(calendar.day_abbr)}


@dataclass(frozen=True)
class ReminderParseResult:
    due_at: datetime
    input_timezone: str
    user_timezone: str
    used_explicit_timezone: bool
    source: str


@dataclass(frozen=True)
class ReminderRecord:
    id: int
    user_id: int
    guild_id: int | None
    channel_id: int | None
    note: str
    due_at: int
    timezone: str
    source: str
    created_at: int


class ReminderParseError(ValueError):
    """Raised when reminder input cannot be resolved to one future instant."""


def normalize_timezone(value: str | None) -> str:
    if value is None or not value.strip():
        return DEFAULT_TIMEZONE
    cleaned = value.strip()
    alias = _TIMEZONE_ALIASES.get(cleaned.upper())
    candidate = alias or cleaned
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise ReminderParseError("unknown timezone") from exc
    return candidate


def timezone_label(zone_name: str, at: datetime | None = None) -> str:
    instant = at or datetime.now(UTC)
    if zone_name in _DISPLAY_ABBREVIATIONS:
        return _DISPLAY_ABBREVIATIONS[zone_name]
    zone = ZoneInfo(zone_name)
    label = instant.astimezone(zone).tzname()
    return label or zone_name


def timezone_view(zone_name: str, at: datetime | None = None) -> str:
    return f"{zone_name} ({timezone_label(zone_name, at)})"


def parse_reminder_time(
    value: str,
    *,
    now: datetime | None = None,
    user_timezone: str | None = None,
) -> ReminderParseResult:
    source = _clean(value)
    if not source:
        raise ReminderParseError("empty reminder time")

    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    default_zone = normalize_timezone(user_timezone)
    text, explicit_zone = _extract_timezone(source)
    input_zone = explicit_zone or default_zone
    zone = _zoneinfo(input_zone)
    local_now = now_utc.astimezone(zone)

    due_local = _parse_relative(text, local_now) or _parse_natural(text, local_now)
    if due_local is None:
        raise ReminderParseError("unrecognized reminder time")

    due_utc = due_local.astimezone(UTC)
    if due_utc <= now_utc:
        raise ReminderParseError("reminder time is in the past")
    if (due_utc - now_utc).total_seconds() > MAX_REMINDER_SECONDS:
        raise ReminderParseError("reminder time is too far away")

    return ReminderParseResult(
        due_at=due_utc,
        input_timezone=input_zone,
        user_timezone=default_zone,
        used_explicit_timezone=explicit_zone is not None,
        source=source,
    )


def format_confirmation(result: ReminderParseResult) -> str:
    input_line = format_clock(result.due_at, result.input_timezone)
    if result.used_explicit_timezone and result.input_timezone != result.user_timezone:
        user_line = format_clock(result.due_at, result.user_timezone)
        return f"{input_line}\n-> {user_line}\n\nI'll remind you then."
    friendly = format_due_label(result.due_at, result.user_timezone, include_time=True)
    return f"I'll remind you {friendly}."


def format_clock(due_at: datetime, zone_name: str) -> str:
    local = due_at.astimezone(_zoneinfo(zone_name))
    return f"{_format_time(local)} {timezone_label(zone_name, due_at)}"


def format_due_label(
    due_at: datetime | int,
    zone_name: str,
    *,
    now: datetime | None = None,
    include_time: bool = False,
) -> str:
    due_utc = _coerce_utc(due_at)
    local_due = due_utc.astimezone(_zoneinfo(zone_name))
    local_now = (now or datetime.now(UTC)).astimezone(_zoneinfo(zone_name))
    due_date = local_due.date()
    today = local_now.date()
    tomorrow = today + timedelta(days=1)

    if due_date == today:
        day = "today"
    elif due_date == tomorrow:
        day = "tomorrow"
    elif 0 <= (due_date - today).days < 7:
        day = calendar.day_name[local_due.weekday()]
    else:
        day = f"{calendar.month_abbr[local_due.month]} {local_due.day}"

    if include_time:
        return f"{day} at {_format_time(local_due)}"
    if due_date in {today, tomorrow}:
        return f"{day.title()} \u2022 {_format_time(local_due)}"
    return f"{day} \u2022 {_format_time(local_due)}"


def format_relative_due(
    due_at: datetime | int,
    *,
    now: datetime | None = None,
) -> str:
    due_utc = _coerce_utc(due_at)
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    seconds = max(0, int((due_utc - now_utc).total_seconds()))
    if seconds < 60:
        return "In under a minute"
    minutes = seconds // 60
    if minutes < 60:
        return f"In {minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 24:
        return f"In {hours} hour{'s' if hours != 1 else ''}"
    days = hours // 24
    return f"In {days} day{'s' if days != 1 else ''}"


def clean_reminder_note(value: str) -> str:
    cleaned = _SPACE_RE.sub(" ", value.strip())
    return cleaned[:300].rstrip()


def _extract_timezone(value: str) -> tuple[str, str | None]:
    parts = value.rsplit(" ", 1)
    if len(parts) != 2:
        return value, None
    head, tail = parts[0].strip(), parts[1].strip()
    if not tail:
        return value, None
    try:
        return head, normalize_timezone(tail)
    except ReminderParseError:
        if "/" in tail or tail.upper() in _TIMEZONE_ALIASES:
            raise
        return value, None


def _parse_relative(value: str, local_now: datetime) -> datetime | None:
    duration_text = re.sub(r"^in\s+", "", value, flags=re.IGNORECASE).strip()
    duration = None if re.fullmatch(r"\d+(?:\.\d+)?", duration_text) else parse_duration(duration_text)
    if duration is None:
        match = _RELATIVE_RE.fullmatch(value)
        if not match:
            return None
        duration = (
            int(match.group("days") or 0) * 86400
            + int(match.group("hours") or 0) * 3600
            + int(match.group("minutes") or 0) * 60
            + int(match.group("seconds") or 0)
        )
    if duration <= 0:
        return None
    return local_now + timedelta(seconds=duration)


def _parse_natural(value: str, local_now: datetime) -> datetime | None:
    text = value.lower().strip()
    text = re.sub(r"\bat\b", " ", text)
    text = _SPACE_RE.sub(" ", text).strip()

    target_date = local_now.date()
    default_time = time(9, 0)

    if text in {"next week"}:
        return datetime.combine(target_date + timedelta(days=7), default_time, local_now.tzinfo)
    if text.startswith("tomorrow"):
        target_date += timedelta(days=1)
        remainder = text.removeprefix("tomorrow").strip()
        parsed_time = _parse_time_hint(remainder) or _period_default(remainder)
        if parsed_time is None and remainder:
            return None
        parsed_time = parsed_time or default_time
        return datetime.combine(target_date, parsed_time, local_now.tzinfo)
    if text.startswith("tonight"):
        remainder = text.removeprefix("tonight").strip()
        parsed_time = _parse_time_hint(remainder) or time(20, 0)
        return _roll_forward(datetime.combine(target_date, parsed_time, local_now.tzinfo), local_now)

    weekday_result = _parse_weekday(text, local_now, default_time)
    if weekday_result is not None:
        return weekday_result

    parsed_time = _parse_time_hint(text)
    if parsed_time is not None:
        return _roll_forward(datetime.combine(target_date, parsed_time, local_now.tzinfo), local_now)

    return None


def _parse_weekday(text: str, local_now: datetime, default_time: time) -> datetime | None:
    words = text.split()
    if not words:
        return None
    force_next = words[0] == "next"
    day_word = words[1] if force_next and len(words) > 1 else words[0]
    weekday = _DAY_NAMES.get(day_word)
    if weekday is None:
        weekday = _DAY_SHORT_NAMES.get(day_word)
    if weekday is None:
        return None
    days_ahead = (weekday - local_now.weekday()) % 7
    if days_ahead == 0 or force_next:
        days_ahead = days_ahead or 7
    target_date = local_now.date() + timedelta(days=days_ahead)
    remainder = " ".join(words[2:] if force_next else words[1:])
    remainder = re.sub(r"\bat\b", " ", remainder).strip()
    parsed_time = _parse_time_hint(remainder) or _period_default(remainder)
    if parsed_time is None and remainder:
        return None
    parsed_time = parsed_time or default_time
    return datetime.combine(target_date, parsed_time, local_now.tzinfo)


def _parse_time_hint(value: str) -> time | None:
    text = value.strip().lower()
    if not text:
        return None
    if text == "noon":
        return time(12, 0)
    if text == "midnight":
        return time(0, 0)
    match = _TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group("hour"))
    minute_text = match.group("minute")
    minute = int(minute_text or 0)
    meridiem = (match.group("meridiem") or "").replace(".", "").lower()
    if minute > 59:
        return None
    if not meridiem and minute_text is None:
        return None
    if meridiem:
        if hour < 1 or hour > 12:
            return None
        if meridiem.startswith("p") and hour != 12:
            hour += 12
        if meridiem.startswith("a") and hour == 12:
            hour = 0
    elif hour > 23:
        return None
    return time(hour, minute)


def _period_default(value: str) -> time | None:
    if value == "morning":
        return time(9, 0)
    if value == "afternoon":
        return time(14, 0)
    if value == "evening":
        return time(18, 0)
    if value == "night":
        return time(20, 0)
    return None


def _roll_forward(candidate: datetime, local_now: datetime) -> datetime:
    if candidate <= local_now:
        return candidate + timedelta(days=1)
    return candidate


def _format_time(value: datetime) -> str:
    hour = value.hour % 12 or 12
    meridiem = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {meridiem}"


def _coerce_utc(value: datetime | int) -> datetime:
    if isinstance(value, int):
        return datetime.fromtimestamp(value, UTC)
    return value.astimezone(UTC)


def _zoneinfo(zone_name: str) -> tzinfo:
    if zone_name.startswith("Etc/GMT"):
        return ZoneInfo(zone_name)
    if zone_name == "UTC":
        return UTC
    return ZoneInfo(zone_name)


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())
