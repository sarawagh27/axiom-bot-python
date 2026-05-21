"""
core/server_health.py - operational health scoring for guilds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.session_manager import session_manager
from core.telemetry import EventName


@dataclass(frozen=True)
class ServerHealthSnapshot:
    guild_id: int
    score: int
    status: str
    window_seconds: int
    total_events: int
    active_sessions: int
    unique_users: int
    severity_counts: dict[str, int]
    event_counts: dict[str, int]
    last_event_ts: float | None
    generated_at: float
    signals: list[str]


class ServerHealthAnalyzer:
    """Turns recent operational telemetry into a compact guild health view."""

    def snapshot(self, guild_id: int, window_seconds: int = 3600) -> ServerHealthSnapshot:
        from core.database import db

        summary = db.get_operational_event_summary(guild_id, window_seconds)
        severity_counts: dict[str, int] = summary["severity_counts"]
        event_counts: dict[str, int] = summary["event_counts"]
        active_sessions = len([
            session for session in session_manager.active_sessions()
            if session.guild_id == guild_id
        ])

        score = self._score(severity_counts, event_counts)
        status = self._status(score)
        signals = self._signals(summary, active_sessions, score)

        return ServerHealthSnapshot(
            guild_id=guild_id,
            score=score,
            status=status,
            window_seconds=window_seconds,
            total_events=summary["total_events"],
            active_sessions=active_sessions,
            unique_users=summary["unique_users"],
            severity_counts=severity_counts,
            event_counts=event_counts,
            last_event_ts=summary["last_event_ts"],
            generated_at=time.time(),
            signals=signals,
        )

    def _score(
        self,
        severity_counts: dict[str, int],
        event_counts: dict[str, int],
    ) -> int:
        score = 100
        score -= min(severity_counts.get("critical", 0) * 30, 60)
        score -= min(severity_counts.get("error", 0) * 12, 48)
        score -= min(severity_counts.get("warning", 0) * 4, 24)
        score -= min(event_counts.get(EventName.COMMAND_RATE_LIMITED, 0) * 3, 24)
        score -= min(event_counts.get(EventName.SESSION_STOPPED, 0) * 5, 20)
        score -= min(event_counts.get(EventName.COMMAND_ERROR, 0) * 8, 32)
        return max(0, min(100, score))

    def _status(self, score: int) -> str:
        if score >= 90:
            return "healthy"
        if score >= 70:
            return "watch"
        if score >= 40:
            return "degraded"
        return "critical"

    def _signals(
        self,
        summary: dict[str, Any],
        active_sessions: int,
        score: int,
    ) -> list[str]:
        severity_counts = summary["severity_counts"]
        event_counts = summary["event_counts"]
        signals: list[str] = []

        if summary["total_events"] == 0:
            signals.append("No recent operational events recorded in this window.")
        if severity_counts.get("error", 0):
            signals.append(f"{severity_counts['error']} command/runtime error event(s).")
        if severity_counts.get("warning", 0):
            signals.append(f"{severity_counts['warning']} warning event(s), mostly policy or permission friction.")
        if event_counts.get(EventName.COMMAND_RATE_LIMITED, 0):
            signals.append(f"{event_counts[EventName.COMMAND_RATE_LIMITED]} rate-limit event(s).")
        if event_counts.get(EventName.SESSION_STARTED, 0):
            signals.append(f"{event_counts[EventName.SESSION_STARTED]} session(s) started.")
        if active_sessions:
            signals.append(f"{active_sessions} session(s) currently active.")
        if not signals and score >= 90:
            signals.append("Recent telemetry is quiet and within expected operating bounds.")

        return signals[:5]


server_health_analyzer = ServerHealthAnalyzer()
