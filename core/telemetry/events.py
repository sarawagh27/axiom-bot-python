"""Structured telemetry event contracts for Axiom.

This module is the canonical observability boundary. Storage, operational
snapshots, anomaly detection, and emitters should all speak this contract
instead of passing unconstrained event dictionaries around.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping


SCHEMA_VERSION = 1


class TelemetryValidationError(ValueError):
    """Raised when an event cannot satisfy Axiom's telemetry contract."""


class EventSeverity:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    ALL = {INFO, WARNING, ERROR, CRITICAL}


class EventName:
    ADMIN_ACTION = "admin.action"
    BOT_LIFECYCLE = "bot.lifecycle"
    COMMAND_ERROR = "command.error"
    COMMAND_RATE_LIMITED = "command.rate_limited"
    COMMAND_REJECTED = "command.rejected"
    COMMAND_USED = "command.used"
    GUILD_JOINED = "guild.joined"
    GUILD_REMOVED = "guild.removed"
    INCIDENT_ACKNOWLEDGED = "incident.acknowledged"
    INCIDENT_LINKED = "incident.linked"
    INCIDENT_OPENED = "incident.opened"
    INCIDENT_RESOLVED = "incident.resolved"
    SESSION_COMPLETED = "session.completed"
    SESSION_ENDED = "session.ended"
    SESSION_PING = "session.ping"
    SESSION_STARTED = "session.started"
    SESSION_STOPPED = "session.stopped"

    ALL = {
        ADMIN_ACTION,
        BOT_LIFECYCLE,
        COMMAND_ERROR,
        COMMAND_RATE_LIMITED,
        COMMAND_REJECTED,
        COMMAND_USED,
        GUILD_JOINED,
        GUILD_REMOVED,
        INCIDENT_ACKNOWLEDGED,
        INCIDENT_LINKED,
        INCIDENT_OPENED,
        INCIDENT_RESOLVED,
        SESSION_COMPLETED,
        SESSION_ENDED,
        SESSION_PING,
        SESSION_STARTED,
        SESSION_STOPPED,
    }


_LEGACY_EVENT_ALIASES = {
    "admin_action": EventName.ADMIN_ACTION,
    "bot_lifecycle": EventName.BOT_LIFECYCLE,
    "command_error": EventName.COMMAND_ERROR,
    "command_rate_limited": EventName.COMMAND_RATE_LIMITED,
    "command_rejected": EventName.COMMAND_REJECTED,
    "command_used": EventName.COMMAND_USED,
    "guild_joined": EventName.GUILD_JOINED,
    "guild_removed": EventName.GUILD_REMOVED,
    "incident_acknowledged": EventName.INCIDENT_ACKNOWLEDGED,
    "incident_linked": EventName.INCIDENT_LINKED,
    "incident_opened": EventName.INCIDENT_OPENED,
    "incident_resolved": EventName.INCIDENT_RESOLVED,
    "session_completed": EventName.SESSION_COMPLETED,
    "session_ended": EventName.SESSION_ENDED,
    "session_ping": EventName.SESSION_PING,
    "session_started": EventName.SESSION_STARTED,
    "session_stopped": EventName.SESSION_STOPPED,
    "PING": EventName.SESSION_PING,
    "SESSION_START": EventName.SESSION_STARTED,
    "SESSION_COMPLETE": EventName.SESSION_COMPLETED,
    "SESSION_END": EventName.SESSION_ENDED,
    "SESSION_STOPPED": EventName.SESSION_STOPPED,
}

_CANONICAL_TO_LEGACY = {
    canonical: legacy
    for legacy, canonical in _LEGACY_EVENT_ALIASES.items()
    if legacy.islower()
}


def normalize_event_name(event_name: str) -> str:
    """Return the canonical dotted event name for a raw or legacy name."""
    normalized = _LEGACY_EVENT_ALIASES.get(event_name, event_name)
    if normalized not in EventName.ALL:
        raise TelemetryValidationError(f"Unknown telemetry event name: {event_name}")
    return normalized


def legacy_aliases_for(event_name: str) -> set[str]:
    """Return raw storage names that may represent the canonical event."""
    canonical = normalize_event_name(event_name)
    aliases = {canonical}
    legacy = _CANONICAL_TO_LEGACY.get(canonical)
    if legacy:
        aliases.add(legacy)
    return aliases


def normalize_severity(severity: str) -> str:
    normalized = severity.lower()
    if normalized not in EventSeverity.ALL:
        raise TelemetryValidationError(f"Unknown telemetry severity: {severity}")
    return normalized


def _optional_int(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise TelemetryValidationError(f"{name} must be an int or None")
    return value


def _metadata_from_raw(raw_metadata: Any) -> dict[str, Any]:
    if raw_metadata is None:
        return {}
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    if isinstance(raw_metadata, str):
        try:
            parsed = json.loads(raw_metadata)
        except json.JSONDecodeError as exc:
            raise TelemetryValidationError("metadata must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise TelemetryValidationError("metadata JSON must decode to an object")
        return parsed
    raise TelemetryValidationError("metadata must be a dict, JSON object string, or None")


def _record_get(record: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return record[key]
    except (KeyError, IndexError):
        return default


@dataclass(frozen=True)
class TelemetryEvent:
    """Validated telemetry event used across persistence and intelligence systems."""

    event_name: str
    source: str
    severity: str = EventSeverity.INFO
    guild_id: int | None = None
    user_id: int | None = None
    target_id: int | None = None
    command: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    schema_version: int = SCHEMA_VERSION
    event_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_name", normalize_event_name(self.event_name))
        object.__setattr__(self, "severity", normalize_severity(self.severity))
        if not isinstance(self.source, str) or not self.source.strip():
            raise TelemetryValidationError("source must be a non-empty string")
        if self.schema_version != SCHEMA_VERSION:
            raise TelemetryValidationError(
                f"Unsupported telemetry schema version: {self.schema_version}"
            )
        for name in ("guild_id", "user_id", "target_id", "event_id"):
            _optional_int(name, getattr(self, name))
        if self.command is not None and not isinstance(self.command, str):
            raise TelemetryValidationError("command must be a string or None")
        if not isinstance(self.timestamp, (int, float)):
            raise TelemetryValidationError("timestamp must be numeric")
        object.__setattr__(self, "metadata", _metadata_from_raw(self.metadata))

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "TelemetryEvent":
        """Build a validated event from a SQLite row or row-like mapping."""
        schema_version = _record_get(record, "schema_version", SCHEMA_VERSION)
        return cls(
            event_id=_record_get(record, "id"),
            event_name=_record_get(record, "event_name") or _record_get(record, "event_type"),
            severity=_record_get(record, "severity", EventSeverity.INFO),
            source=_record_get(record, "source"),
            guild_id=_record_get(record, "guild_id"),
            user_id=_record_get(record, "user_id"),
            target_id=_record_get(record, "target_id"),
            command=_record_get(record, "command"),
            metadata=_metadata_from_raw(_record_get(record, "metadata")),
            timestamp=_record_get(record, "timestamp", time.time()),
            schema_version=schema_version or SCHEMA_VERSION,
        )

    def to_storage_tuple(self) -> tuple[Any, ...]:
        """Return values for the operational_events table."""
        return (
            self.guild_id,
            self.event_name,
            self.severity,
            self.source,
            self.user_id,
            self.target_id,
            self.command,
            json.dumps(self.metadata, default=str, sort_keys=True),
            float(self.timestamp),
            self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return storage/API compatible event payload."""
        return {
            "id": self.event_id,
            "event_name": self.event_name,
            "event_type": self.event_name,
            "severity": self.severity,
            "source": self.source,
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "target_id": self.target_id,
            "command": self.command,
            "metadata": dict(self.metadata),
            "timestamp": float(self.timestamp),
            "schema_version": self.schema_version,
        }
