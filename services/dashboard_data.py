"""
services/dashboard_data.py - data model for the operational dashboard.

Flask routes, future APIs, and dashboard jobs should consume this service
instead of duplicating telemetry queries.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any

from core.anomaly_detection import anomaly_detector
from core.server_health import server_health_analyzer
from services.operational_events import OperationalEventType


DEFAULT_WINDOW_SECONDS = 3600
LIVE_WINDOW_SECONDS = 300
DEFAULT_EVENT_LIMIT = 40


def _bucket_label(timestamp: float, bucket_seconds: int) -> str:
    bucket_start = math.floor(timestamp / bucket_seconds) * bucket_seconds
    return time.strftime("%H:%M", time.localtime(bucket_start))


def _status_label(status: str) -> str:
    return {
        "healthy": "HEALTHY",
        "watch": "DEGRADED",
        "degraded": "UNSTABLE",
        "critical": "CRITICAL",
    }.get(status, "UNKNOWN")


class DashboardDataService:
    """Builds JSON-ready operational intelligence snapshots."""

    def observed_guild_ids(self) -> list[int]:
        from core.database import db

        return db.list_observed_guild_ids()

    def resolve_guild_id(self, requested_guild_id: int | None = None) -> int | None:
        if requested_guild_id is not None:
            return requested_guild_id

        guild_ids = self.observed_guild_ids()
        if not guild_ids:
            return None
        return guild_ids[0]

    def overview(
        self,
        guild_id: int | None = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        event_limit: int = DEFAULT_EVENT_LIMIT,
    ) -> dict[str, Any]:
        resolved_guild_id = self.resolve_guild_id(guild_id)
        if resolved_guild_id is None:
            return self._empty_overview(window_seconds)

        health = self.health(resolved_guild_id, window_seconds)
        anomalies = self.anomalies(resolved_guild_id, window_seconds)
        events = self.events(resolved_guild_id, limit=event_limit)
        analytics = self.analytics(resolved_guild_id, window_seconds)
        live_metrics = self.live_metrics(resolved_guild_id)
        timeline = self.timeline(resolved_guild_id, window_seconds)

        return {
            "guild_id": resolved_guild_id,
            "window_seconds": window_seconds,
            "generated_at": time.time(),
            "health": health,
            "anomalies": anomalies,
            "events": events,
            "analytics": analytics,
            "live_metrics": live_metrics,
            "timeline": timeline,
            "guild_ids": self.observed_guild_ids(),
        }

    def health(self, guild_id: int, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> dict[str, Any]:
        snapshot = server_health_analyzer.snapshot(guild_id, window_seconds)
        event_counts = snapshot.event_counts
        anomaly_report = anomaly_detector.detect(guild_id, window_seconds)
        live_metrics = self.live_metrics(guild_id)
        score = max(0, snapshot.score - live_metrics["degradation_penalty"])
        status = self._status_from_score(score)

        return {
            "guild_id": guild_id,
            "score": score,
            "base_score": snapshot.score,
            "status": status,
            "status_label": _status_label(status),
            "window_seconds": snapshot.window_seconds,
            "total_events": snapshot.total_events,
            "active_sessions": snapshot.active_sessions,
            "unique_users": snapshot.unique_users,
            "last_event_ts": snapshot.last_event_ts,
            "severity_counts": snapshot.severity_counts,
            "event_counts": event_counts,
            "signals": snapshot.signals,
            "factors": {
                "rate_limit_pressure": event_counts.get(
                    OperationalEventType.COMMAND_RATE_LIMITED,
                    0,
                ),
                "anomaly_count": len(anomaly_report.signals),
                "command_failures": snapshot.severity_counts.get("error", 0)
                + snapshot.severity_counts.get("critical", 0),
                "active_ping_sessions": snapshot.active_sessions,
            },
            "live_metrics": live_metrics,
        }

    def anomalies(
        self,
        guild_id: int,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> dict[str, Any]:
        report = anomaly_detector.detect(guild_id, window_seconds)
        counts_by_type = Counter(signal.anomaly_type for signal in report.signals)
        counts_by_severity = Counter(signal.severity for signal in report.signals)

        return {
            **report.to_dict(),
            "counts_by_type": dict(counts_by_type),
            "counts_by_severity": dict(counts_by_severity),
        }

    def events(self, guild_id: int, limit: int = DEFAULT_EVENT_LIMIT) -> list[dict[str, Any]]:
        from core.database import db

        return db.get_recent_operational_events(guild_id, limit)

    def analytics(
        self,
        guild_id: int,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> dict[str, Any]:
        from core.database import db

        events = db.get_operational_events(guild_id, window_seconds)
        bucket_seconds = 3600
        command_buckets: Counter[str] = Counter()
        anomaly_buckets: Counter[str] = Counter()

        for event in events:
            label = _bucket_label(event["timestamp"], bucket_seconds)
            if event["event_type"] == OperationalEventType.COMMAND_USED:
                command_buckets[label] += 1
            if event["event_type"] in {
                OperationalEventType.COMMAND_ERROR,
                OperationalEventType.COMMAND_RATE_LIMITED,
                OperationalEventType.COMMAND_REJECTED,
                OperationalEventType.SESSION_STOPPED,
            }:
                anomaly_buckets[label] += 1

        event_counts = Counter(event["event_type"] for event in events)
        cooldown_triggers = sum(
            1
            for event in events
            if event["event_type"] == OperationalEventType.COMMAND_REJECTED
            and event["metadata"].get("reason") == "cooldown"
        )

        return {
            "commands_per_hour": self._series(command_buckets),
            "anomalies_per_hour": self._series(anomaly_buckets),
            "top_commands": db.get_command_usage_summary(guild_id, window_seconds),
            "ping_session_frequency": event_counts.get(
                OperationalEventType.SESSION_STARTED,
                0,
            ),
            "ping_delivery_events": event_counts.get(
                OperationalEventType.SESSION_PING,
                0,
            ),
            "cooldown_trigger_count": cooldown_triggers,
            "rate_limit_count": event_counts.get(
                OperationalEventType.COMMAND_RATE_LIMITED,
                0,
            ),
            "command_error_count": event_counts.get(
                OperationalEventType.COMMAND_ERROR,
                0,
            ),
        }

    def live_snapshot(
        self,
        guild_id: int | None = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        event_limit: int = DEFAULT_EVENT_LIMIT,
        after_id: int = 0,
    ) -> dict[str, Any]:
        resolved_guild_id = self.resolve_guild_id(guild_id)
        if resolved_guild_id is None:
            overview = self._empty_overview(window_seconds)
            overview["new_events"] = []
            overview["latest_event_id"] = 0
            return overview

        overview = self.overview(resolved_guild_id, window_seconds, event_limit)
        from core.database import db

        new_events = db.get_operational_events_after(
            resolved_guild_id,
            after_id=after_id,
            limit=event_limit,
        )
        overview["new_events"] = new_events
        overview["latest_event_id"] = db.get_latest_operational_event_id(resolved_guild_id)
        return overview

    def live_metrics(
        self,
        guild_id: int,
        window_seconds: int = LIVE_WINDOW_SECONDS,
    ) -> dict[str, Any]:
        from core.database import db

        events = db.get_operational_events(guild_id, window_seconds)
        event_counts = Counter(event["event_type"] for event in events)
        severity_counts = Counter(event["severity"] for event in events)
        cooldown_abuse = sum(
            1
            for event in events
            if event["event_type"] == OperationalEventType.COMMAND_REJECTED
            and event["metadata"].get("reason") == "cooldown"
        )
        anomaly_pressure = sum(
            event_counts.get(event_type, 0)
            for event_type in (
                OperationalEventType.COMMAND_ERROR,
                OperationalEventType.COMMAND_RATE_LIMITED,
                OperationalEventType.COMMAND_REJECTED,
                OperationalEventType.SESSION_STOPPED,
            )
        )
        error_spikes = severity_counts.get("error", 0) + severity_counts.get("critical", 0)
        command_throughput = event_counts.get(OperationalEventType.COMMAND_USED, 0)

        degradation_penalty = min(
            45,
            (anomaly_pressure * 2)
            + (cooldown_abuse * 2)
            + (error_spikes * 6)
            + min(command_throughput // 10, 8),
        )

        return {
            "window_seconds": window_seconds,
            "active_sessions": self.healthless_active_sessions(guild_id),
            "anomaly_pressure": anomaly_pressure,
            "cooldown_abuse": cooldown_abuse,
            "command_throughput": command_throughput,
            "error_spikes": error_spikes,
            "rate_limit_pressure": event_counts.get(
                OperationalEventType.COMMAND_RATE_LIMITED,
                0,
            ),
            "degradation_penalty": degradation_penalty,
        }

    def timeline(
        self,
        guild_id: int,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        events = self.events(guild_id, limit=limit)
        anomaly_report = anomaly_detector.detect(guild_id, window_seconds)

        items = [
            {
                "kind": "event",
                "timestamp": event["timestamp"],
                "severity": event["severity"],
                "title": event["event_type"],
                "description": self._event_description(event),
                "context": {
                    "event_id": event.get("id"),
                    "user_id": event.get("user_id"),
                    "target_id": event.get("target_id"),
                    "command": event.get("command"),
                },
            }
            for event in events
        ]
        items.extend(
            {
                "kind": "anomaly",
                "timestamp": anomaly_report.generated_at,
                "severity": signal.severity,
                "title": signal.title,
                "description": signal.description,
                "context": signal.to_dict(),
            }
            for signal in anomaly_report.signals
        )

        return sorted(items, key=lambda item: item["timestamp"], reverse=True)[:limit]

    def healthless_active_sessions(self, guild_id: int) -> int:
        from core.session_manager import session_manager

        return len([
            session for session in session_manager.active_sessions()
            if session.guild_id == guild_id
        ])

    def _series(self, buckets: Counter[str]) -> list[dict[str, Any]]:
        return [
            {"label": label, "value": buckets[label]}
            for label in sorted(buckets)
        ]

    def _status_from_score(self, score: int) -> str:
        if score >= 90:
            return "healthy"
        if score >= 70:
            return "watch"
        if score >= 40:
            return "degraded"
        return "critical"

    def _event_description(self, event: dict[str, Any]) -> str:
        parts = [f"source={event['source']}"]
        if event.get("command"):
            parts.append(f"command=/{event['command']}")
        if event.get("user_id"):
            parts.append(f"user={event['user_id']}")
        if event.get("target_id"):
            parts.append(f"target={event['target_id']}")
        return " | ".join(parts)

    def _empty_overview(self, window_seconds: int) -> dict[str, Any]:
        return {
            "guild_id": None,
            "window_seconds": window_seconds,
            "generated_at": time.time(),
            "health": {
                "guild_id": None,
                "score": 100,
                "status": "healthy",
                "status_label": "HEALTHY",
                "window_seconds": window_seconds,
                "total_events": 0,
                "active_sessions": 0,
                "unique_users": 0,
                "last_event_ts": None,
                "severity_counts": {},
                "event_counts": {},
                "signals": ["No guild telemetry has been recorded yet."],
                "factors": {
                    "rate_limit_pressure": 0,
                    "anomaly_count": 0,
                    "command_failures": 0,
                    "active_ping_sessions": 0,
                },
            },
            "anomalies": {
                "guild_id": None,
                "window_seconds": window_seconds,
                "generated_at": time.time(),
                "total_events": 0,
                "highest_severity": "none",
                "signals": [],
                "counts_by_type": {},
                "counts_by_severity": {},
            },
            "events": [],
            "analytics": {
                "commands_per_hour": [],
                "anomalies_per_hour": [],
                "top_commands": [],
                "ping_session_frequency": 0,
                "ping_delivery_events": 0,
                "cooldown_trigger_count": 0,
                "rate_limit_count": 0,
                "command_error_count": 0,
            },
            "live_metrics": {
                "window_seconds": LIVE_WINDOW_SECONDS,
                "active_sessions": 0,
                "anomaly_pressure": 0,
                "cooldown_abuse": 0,
                "command_throughput": 0,
                "error_spikes": 0,
                "rate_limit_pressure": 0,
                "degradation_penalty": 0,
            },
            "timeline": [],
            "new_events": [],
            "latest_event_id": 0,
            "guild_ids": [],
        }


dashboard_data_service = DashboardDataService()
