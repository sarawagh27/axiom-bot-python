"""
core/anomaly_detection.py - telemetry-backed anomaly detection.

The detector consumes operational_events so Discord commands, exports, and
future background jobs can all use the same analysis contract.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from core.telemetry import EventName


@dataclass(frozen=True)
class AnomalyRuleConfig:
    session_starts_per_user: int = 3
    session_starts_guild: int = 6
    session_pings_guild: int = 120
    cooldown_rejections_per_user: int = 3
    rate_limits_per_user: int = 3
    command_uses_per_user: int = 12
    command_uses_per_command: int = 20
    command_uses_guild: int = 40
    errors_total: int = 3
    rejected_commands_total: int = 12


@dataclass(frozen=True)
class AnomalySignal:
    anomaly_type: str
    severity: str
    title: str
    description: str
    count: int
    threshold: int
    guild_id: int
    window_seconds: int
    actor_id: int | None = None
    target_id: int | None = None
    command: str | None = None
    event_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnomalyDetectionReport:
    guild_id: int
    window_seconds: int
    generated_at: float
    total_events: int
    signals: list[AnomalySignal]

    @property
    def highest_severity(self) -> str:
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        if not self.signals:
            return "none"
        return max(self.signals, key=lambda signal: order[signal.severity]).severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "window_seconds": self.window_seconds,
            "generated_at": self.generated_at,
            "total_events": self.total_events,
            "highest_severity": self.highest_severity,
            "signals": [signal.to_dict() for signal in self.signals],
        }


class AnomalyDetector:
    """Detects early abuse and reliability anomalies from operational telemetry."""

    def __init__(self, config: AnomalyRuleConfig | None = None) -> None:
        self._config = config or AnomalyRuleConfig()

    def detect(self, guild_id: int, window_seconds: int = 3600) -> AnomalyDetectionReport:
        from core.database import db

        events = db.get_operational_events(guild_id, window_seconds)
        signals: list[AnomalySignal] = []
        signals.extend(self._detect_ping_session_activity(guild_id, window_seconds, events))
        signals.extend(self._detect_cooldown_abuse(guild_id, window_seconds, events))
        signals.extend(self._detect_command_spikes(guild_id, window_seconds, events))
        signals.extend(self._detect_repeated_failures(guild_id, window_seconds, events))

        return AnomalyDetectionReport(
            guild_id=guild_id,
            window_seconds=window_seconds,
            generated_at=time.time(),
            total_events=len(events),
            signals=sorted(
                signals,
                key=lambda signal: (
                    {"critical": 0, "high": 1, "medium": 2, "low": 3}[signal.severity],
                    -signal.count,
                    signal.anomaly_type,
                ),
            ),
        )

    def _detect_ping_session_activity(
        self,
        guild_id: int,
        window_seconds: int,
        events: list[dict[str, Any]],
    ) -> list[AnomalySignal]:
        cfg = self._config
        starts = [e for e in events if e["event_type"] == EventName.SESSION_STARTED]
        pings = [e for e in events if e["event_type"] == EventName.SESSION_PING]
        signals: list[AnomalySignal] = []

        if len(starts) >= cfg.session_starts_guild:
            signals.append(AnomalySignal(
                anomaly_type="abnormal_ping_session_activity",
                severity="high",
                title="High ping session volume",
                description="The guild started more ping sessions than expected for the window.",
                count=len(starts),
                threshold=cfg.session_starts_guild,
                guild_id=guild_id,
                window_seconds=window_seconds,
                event_type=EventName.SESSION_STARTED,
            ))

        if len(pings) >= cfg.session_pings_guild:
            signals.append(AnomalySignal(
                anomaly_type="abnormal_ping_session_activity",
                severity="high",
                title="High ping delivery volume",
                description="Ping delivery events exceeded the expected operating band.",
                count=len(pings),
                threshold=cfg.session_pings_guild,
                guild_id=guild_id,
                window_seconds=window_seconds,
                event_type=EventName.SESSION_PING,
            ))

        starts_by_user = Counter(e["user_id"] for e in starts if e["user_id"] is not None)
        for user_id, count in starts_by_user.items():
            if count >= cfg.session_starts_per_user:
                signals.append(AnomalySignal(
                    anomaly_type="abnormal_ping_session_activity",
                    severity="medium",
                    title="Repeated ping sessions from one user",
                    description="A single user started several ping sessions in the lookback window.",
                    count=count,
                    threshold=cfg.session_starts_per_user,
                    guild_id=guild_id,
                    window_seconds=window_seconds,
                    actor_id=user_id,
                    event_type=EventName.SESSION_STARTED,
                ))

        return signals

    def _detect_cooldown_abuse(
        self,
        guild_id: int,
        window_seconds: int,
        events: list[dict[str, Any]],
    ) -> list[AnomalySignal]:
        cfg = self._config
        cooldown_rejections = [
            e for e in events
            if e["event_type"] == EventName.COMMAND_REJECTED
            and e["metadata"].get("reason") == "cooldown"
        ]
        rate_limits = [
            e for e in events
            if e["event_type"] == EventName.COMMAND_RATE_LIMITED
        ]
        signals: list[AnomalySignal] = []

        cooldowns_by_user = Counter(e["user_id"] for e in cooldown_rejections if e["user_id"] is not None)
        for user_id, count in cooldowns_by_user.items():
            if count >= cfg.cooldown_rejections_per_user:
                signals.append(AnomalySignal(
                    anomaly_type="cooldown_abuse",
                    severity="medium",
                    title="Repeated cooldown hits",
                    description="A user repeatedly retried while still on cooldown.",
                    count=count,
                    threshold=cfg.cooldown_rejections_per_user,
                    guild_id=guild_id,
                    window_seconds=window_seconds,
                    actor_id=user_id,
                    command="pingbomb",
                    event_type=EventName.COMMAND_REJECTED,
                ))

        rate_limits_by_user = Counter(e["user_id"] for e in rate_limits if e["user_id"] is not None)
        for user_id, count in rate_limits_by_user.items():
            if count >= cfg.rate_limits_per_user:
                signals.append(AnomalySignal(
                    anomaly_type="cooldown_abuse",
                    severity="high",
                    title="Repeated rate-limit pressure",
                    description="A user repeatedly hit the command or API protection layer.",
                    count=count,
                    threshold=cfg.rate_limits_per_user,
                    guild_id=guild_id,
                    window_seconds=window_seconds,
                    actor_id=user_id,
                    event_type=EventName.COMMAND_RATE_LIMITED,
                ))

        return signals

    def _detect_command_spikes(
        self,
        guild_id: int,
        window_seconds: int,
        events: list[dict[str, Any]],
    ) -> list[AnomalySignal]:
        cfg = self._config
        command_events = [e for e in events if e["event_type"] == EventName.COMMAND_USED]
        signals: list[AnomalySignal] = []

        if len(command_events) >= cfg.command_uses_guild:
            signals.append(AnomalySignal(
                anomaly_type="suspicious_command_spike",
                severity="medium",
                title="Guild command spike",
                description="Command usage exceeded the expected guild-wide volume.",
                count=len(command_events),
                threshold=cfg.command_uses_guild,
                guild_id=guild_id,
                window_seconds=window_seconds,
                event_type=EventName.COMMAND_USED,
            ))

        by_user: Counter[int] = Counter()
        by_command: Counter[str] = Counter()
        for event in command_events:
            user_id = event["user_id"]
            command = event["command"]
            if user_id is not None:
                by_user[user_id] += 1
            if command:
                by_command[command] += 1

        for user_id, count in by_user.items():
            if count >= cfg.command_uses_per_user:
                signals.append(AnomalySignal(
                    anomaly_type="suspicious_command_spike",
                    severity="medium",
                    title="User command spike",
                    description="One user used Axiom commands unusually often.",
                    count=count,
                    threshold=cfg.command_uses_per_user,
                    guild_id=guild_id,
                    window_seconds=window_seconds,
                    actor_id=user_id,
                    event_type=EventName.COMMAND_USED,
                ))

        for command, count in by_command.items():
            if count >= cfg.command_uses_per_command:
                signals.append(AnomalySignal(
                    anomaly_type="suspicious_command_spike",
                    severity="medium",
                    title="Command-specific spike",
                    description="One command accounted for unusually high activity.",
                    count=count,
                    threshold=cfg.command_uses_per_command,
                    guild_id=guild_id,
                    window_seconds=window_seconds,
                    command=command,
                    event_type=EventName.COMMAND_USED,
                ))

        return signals

    def _detect_repeated_failures(
        self,
        guild_id: int,
        window_seconds: int,
        events: list[dict[str, Any]],
    ) -> list[AnomalySignal]:
        cfg = self._config
        errors = [e for e in events if e["severity"] in {"error", "critical"}]
        rejections = [e for e in events if e["event_type"] == EventName.COMMAND_REJECTED]
        signals: list[AnomalySignal] = []

        if len(errors) >= cfg.errors_total:
            signals.append(AnomalySignal(
                anomaly_type="repeated_failures",
                severity="critical" if any(e["severity"] == "critical" for e in errors) else "high",
                title="Repeated command or runtime failures",
                description="Errors exceeded the expected operating band.",
                count=len(errors),
                threshold=cfg.errors_total,
                guild_id=guild_id,
                window_seconds=window_seconds,
                event_type=EventName.COMMAND_ERROR,
            ))

        if len(rejections) >= cfg.rejected_commands_total:
            signals.append(AnomalySignal(
                anomaly_type="repeated_failures",
                severity="medium",
                title="Repeated command rejections",
                description="Many commands were rejected by permissions, cooldowns, or policy checks.",
                count=len(rejections),
                threshold=cfg.rejected_commands_total,
                guild_id=guild_id,
                window_seconds=window_seconds,
                event_type=EventName.COMMAND_REJECTED,
            ))

        return signals


anomaly_detector = AnomalyDetector()
