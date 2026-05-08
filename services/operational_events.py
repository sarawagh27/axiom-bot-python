"""
services/operational_events.py - durable operational telemetry.

This is the shared event spine for health scoring, anomaly detection,
analytics exports, and future dashboard views.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

log = logging.getLogger("axiom.operations")


class OperationalEventSeverity:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class OperationalEventType:
    ADMIN_ACTION = "admin_action"
    BOT_LIFECYCLE = "bot_lifecycle"
    COMMAND_ERROR = "command_error"
    COMMAND_RATE_LIMITED = "command_rate_limited"
    COMMAND_REJECTED = "command_rejected"
    COMMAND_USED = "command_used"
    GUILD_JOINED = "guild_joined"
    GUILD_REMOVED = "guild_removed"
    SESSION_COMPLETED = "session_completed"
    SESSION_ENDED = "session_ended"
    SESSION_PING = "session_ping"
    SESSION_STARTED = "session_started"
    SESSION_STOPPED = "session_stopped"


_SESSION_EVENT_MAP = {
    "PING": OperationalEventType.SESSION_PING,
    "SESSION_START": OperationalEventType.SESSION_STARTED,
    "SESSION_COMPLETE": OperationalEventType.SESSION_COMPLETED,
    "SESSION_END": OperationalEventType.SESSION_ENDED,
    "SESSION_STOPPED": OperationalEventType.SESSION_STOPPED,
}


class OperationalEventRecorder:
    """Writes operational events to SQLite and structured logs."""

    def record(
        self,
        event_type: str,
        source: str,
        *,
        severity: str = OperationalEventSeverity.INFO,
        guild_id: Optional[int] = None,
        user_id: Optional[int] = None,
        target_id: Optional[int] = None,
        command: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        payload = {
            "ts": time.time(),
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "guild_id": guild_id,
            "user_id": user_id,
            "target_id": target_id,
            "command": command,
            "metadata": metadata or {},
        }

        log.info(json.dumps(payload, default=str, sort_keys=True))

        try:
            from core.database import db

            db.record_operational_event(
                event_type=event_type,
                severity=severity,
                source=source,
                guild_id=guild_id,
                user_id=user_id,
                target_id=target_id,
                command=command,
                metadata=metadata,
                timestamp=payload["ts"],
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("axiom.operations").error(
                "Failed to persist operational event %s: %s",
                event_type,
                exc,
            )

    def record_session_event(
        self,
        event: str,
        session: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        event_type = _SESSION_EVENT_MAP.get(event, event.lower())
        severity = OperationalEventSeverity.INFO
        if event_type in {OperationalEventType.SESSION_STOPPED}:
            severity = OperationalEventSeverity.WARNING

        self.record(
            event_type=event_type,
            source="pingbomb_engine",
            severity=severity,
            guild_id=session.guild_id,
            user_id=session.user_id,
            target_id=session.target_id,
            metadata={
                "channel_id": session.channel_id,
                "state": session.state.name,
                "count": session.count,
                "pings_sent": session.pings_sent,
                **(metadata or {}),
            },
        )

    def record_admin_action(
        self,
        action: str,
        admin_id: int,
        guild_id: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.record(
            event_type=OperationalEventType.ADMIN_ACTION,
            source="admin",
            guild_id=guild_id,
            user_id=admin_id,
            metadata={"action": action, **(metadata or {})},
        )

    def record_command_error(
        self,
        command: str,
        guild_id: Optional[int],
        user_id: Optional[int],
        error: Exception,
    ) -> None:
        event_type = OperationalEventType.COMMAND_ERROR
        severity = OperationalEventSeverity.ERROR
        if error.__class__.__name__ in {
            "CommandOnCooldown",
            "MissingPermissions",
            "BotMissingPermissions",
            "NoPrivateMessage",
            "CheckFailure",
        }:
            event_type = OperationalEventType.COMMAND_REJECTED
            severity = OperationalEventSeverity.WARNING

        self.record(
            event_type=event_type,
            source="app_command_error_handler",
            severity=severity,
            guild_id=guild_id,
            user_id=user_id,
            command=command,
            metadata={
                "error_type": error.__class__.__name__,
                "error": str(error),
            },
        )


operational_event_recorder = OperationalEventRecorder()
