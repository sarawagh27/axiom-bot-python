"""Operational intelligence snapshots for Discord-facing monitoring UX."""

from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any

from core.anomaly_detection import anomaly_detector
from core.incidents import incident_service
from core.server_health import server_health_analyzer
from core.telemetry import EventName


DEFAULT_WINDOW_SECONDS = 3600
LIVE_WINDOW_SECONDS = 300
DEFAULT_EVENT_LIMIT = 40
PRESSURE_EVENTS = {
    EventName.COMMAND_ERROR,
    EventName.COMMAND_RATE_LIMITED,
    EventName.COMMAND_REJECTED,
    EventName.SESSION_STOPPED,
}
SEVERITY_WEIGHTS = {"none": 0, "low": 8, "medium": 18, "high": 34, "critical": 50}


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


class OperationalIntelligenceService:
    """Builds reusable operational intelligence snapshots from telemetry."""

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
        incidents = self.incidents(resolved_guild_id, window_seconds)
        timeline = self.timeline(resolved_guild_id, window_seconds)
        trend = self.trend(resolved_guild_id, window_seconds)
        command_intelligence = self.command_intelligence(resolved_guild_id, window_seconds)
        anomaly_memory = self.anomaly_memory(resolved_guild_id, anomalies["signals"])
        pressure = self.pressure_score(
            health=health,
            anomalies=anomalies,
            incidents=incidents,
            live_metrics=live_metrics,
            trend=trend,
            anomaly_memory=anomaly_memory,
        )
        recommendations = self.recommendations(
            health=health,
            anomalies=anomalies,
            incidents=incidents,
            analytics=analytics,
            trend=trend,
            command_intelligence=command_intelligence,
            anomaly_memory=anomaly_memory,
            pressure=pressure,
        )

        return {
            "guild_id": resolved_guild_id,
            "window_seconds": window_seconds,
            "generated_at": time.time(),
            "health": health,
            "anomalies": anomalies,
            "events": events,
            "analytics": analytics,
            "live_metrics": live_metrics,
            "incidents": incidents,
            "timeline": timeline,
            "trend": trend,
            "command_intelligence": command_intelligence,
            "anomaly_memory": anomaly_memory,
            "pressure": pressure,
            "recommendations": recommendations,
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
                    EventName.COMMAND_RATE_LIMITED,
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
        incident_service.reconcile_anomalies(report)
        counts_by_type = Counter(signal.anomaly_type for signal in report.signals)
        counts_by_severity = Counter(signal.severity for signal in report.signals)

        return {
            **report.to_dict(),
            "counts_by_type": dict(counts_by_type),
            "counts_by_severity": dict(counts_by_severity),
        }

    def incidents(self, guild_id: int, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> dict[str, Any]:
        report = anomaly_detector.detect(guild_id, window_seconds)
        incident_service.reconcile_anomalies(report)
        return incident_service.active_snapshot(guild_id)

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
            if event["event_type"] == EventName.COMMAND_USED:
                command_buckets[label] += 1
            if event["event_type"] in {
                EventName.COMMAND_ERROR,
                EventName.COMMAND_RATE_LIMITED,
                EventName.COMMAND_REJECTED,
                EventName.SESSION_STOPPED,
            }:
                anomaly_buckets[label] += 1

        event_counts = Counter(event["event_type"] for event in events)
        cooldown_triggers = sum(
            1
            for event in events
            if event["event_type"] == EventName.COMMAND_REJECTED
            and event["metadata"].get("reason") == "cooldown"
        )

        return {
            "commands_per_hour": self._series(command_buckets),
            "anomalies_per_hour": self._series(anomaly_buckets),
            "top_commands": db.get_command_usage_summary(guild_id, window_seconds),
            "ping_session_frequency": event_counts.get(
                EventName.SESSION_STARTED,
                0,
            ),
            "ping_delivery_events": event_counts.get(
                EventName.SESSION_PING,
                0,
            ),
            "cooldown_trigger_count": cooldown_triggers,
            "rate_limit_count": event_counts.get(
                EventName.COMMAND_RATE_LIMITED,
                0,
            ),
            "command_error_count": event_counts.get(
                EventName.COMMAND_ERROR,
                0,
            ),
        }

    def trend(
        self,
        guild_id: int,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> dict[str, Any]:
        from core.database import db

        now = time.time()
        events = db.get_operational_events(guild_id, window_seconds * 2)
        current = [event for event in events if event["timestamp"] >= now - window_seconds]
        previous = [
            event
            for event in events
            if now - (window_seconds * 2) <= event["timestamp"] < now - window_seconds
        ]

        current_summary = self._event_window_summary(current)
        previous_summary = self._event_window_summary(previous)
        metrics = ("events", "commands", "sessions", "rate_limits", "rejections", "errors")
        deltas = {
            metric: current_summary[metric] - previous_summary[metric]
            for metric in metrics
        }

        worsening = (
            deltas["errors"] > 0
            or deltas["rate_limits"] > 0
            or deltas["rejections"] >= 3
        )
        improving = (
            deltas["errors"] < 0
            and deltas["rate_limits"] <= 0
            and deltas["rejections"] <= 0
        )
        direction = "steady"
        if worsening:
            direction = "worsening"
        elif improving:
            direction = "improving"

        return {
            "current": current_summary,
            "previous": previous_summary,
            "deltas": deltas,
            "direction": direction,
            "what_changed": self._what_changed(current, previous, deltas),
        }

    def command_intelligence(
        self,
        guild_id: int,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> dict[str, Any]:
        from core.database import db

        events = db.get_operational_events(guild_id, window_seconds)
        command_uses = Counter(
            event["command"]
            for event in events
            if event["event_type"] == EventName.COMMAND_USED and event.get("command")
        )
        pressure_by_command: Counter[str] = Counter()
        pressure_by_actor: Counter[int] = Counter()
        cooldowns_by_actor: Counter[int] = Counter()
        rate_limits_by_actor: Counter[int] = Counter()

        for event in events:
            command = event.get("command")
            user_id = event.get("user_id")
            is_cooldown = (
                event["event_type"] == EventName.COMMAND_REJECTED
                and event["metadata"].get("reason") == "cooldown"
            )
            is_pressure = event["event_type"] in PRESSURE_EVENTS or event["severity"] in {"error", "critical"}
            if is_pressure:
                if command:
                    pressure_by_command[command] += 1
                if user_id is not None:
                    pressure_by_actor[user_id] += 1
            if is_cooldown and user_id is not None:
                cooldowns_by_actor[user_id] += 1
            if event["event_type"] == EventName.COMMAND_RATE_LIMITED and user_id is not None:
                rate_limits_by_actor[user_id] += 1

        total_uses = sum(command_uses.values())
        top_command = command_uses.most_common(1)[0] if command_uses else None
        dominant_command = None
        if top_command and total_uses:
            share = top_command[1] / total_uses
            if top_command[1] >= 5 and share >= 0.6:
                dominant_command = {
                    "command": top_command[0],
                    "uses": top_command[1],
                    "share": round(share, 2),
                }

        return {
            "total_command_uses": total_uses,
            "top_commands": [
                {"command": command, "uses": uses}
                for command, uses in command_uses.most_common(5)
            ],
            "dominant_command": dominant_command,
            "pressure_by_command": [
                {"command": command, "events": count}
                for command, count in pressure_by_command.most_common(5)
            ],
            "noisy_actors": [
                {
                    "user_id": user_id,
                    "pressure_events": count,
                    "cooldown_hits": cooldowns_by_actor.get(user_id, 0),
                    "rate_limits": rate_limits_by_actor.get(user_id, 0),
                    "explanation": self._actor_pressure_explanation(
                        count,
                        cooldowns_by_actor.get(user_id, 0),
                        rate_limits_by_actor.get(user_id, 0),
                    ),
                }
                for user_id, count in pressure_by_actor.most_common(5)
            ],
        }

    def anomaly_memory(
        self,
        guild_id: int,
        signals: list[dict[str, Any]],
        limit: int = 80,
    ) -> dict[str, Any]:
        from core.anomaly_detection import AnomalySignal
        from core.database import db

        incidents = db.list_incidents(
            guild_id,
            statuses=["open", "acknowledged", "resolved"],
            limit=limit,
        )
        by_fingerprint: dict[str, list[dict[str, Any]]] = {}
        for incident in incidents:
            by_fingerprint.setdefault(incident["fingerprint"], []).append(incident)

        recurring_signals: list[dict[str, Any]] = []
        for raw_signal in signals:
            signal = AnomalySignal(**raw_signal)
            fingerprint = incident_service.fingerprint_for_signal(signal)
            matches = by_fingerprint.get(fingerprint, [])
            if len(matches) < 2:
                continue
            recurring_signals.append({
                "fingerprint": fingerprint,
                "title": raw_signal["title"],
                "anomaly_type": raw_signal["anomaly_type"],
                "severity": raw_signal["severity"],
                "occurrences": len(matches),
                "resolved_occurrences": sum(
                    1 for incident in matches if incident["status"] == "resolved"
                ),
                "last_seen_ts": max(incident["last_seen_ts"] for incident in matches),
            })

        recurring_incidents = [
            {
                "fingerprint": fingerprint,
                "title": matches[0]["title"],
                "anomaly_type": matches[0]["anomaly_type"],
                "occurrences": len(matches),
                "active": sum(1 for incident in matches if incident["status"] != "resolved"),
                "last_seen_ts": max(incident["last_seen_ts"] for incident in matches),
            }
            for fingerprint, matches in by_fingerprint.items()
            if len(matches) >= 2
        ]

        recurring_incidents.sort(key=lambda item: (-item["occurrences"], -item["last_seen_ts"]))
        recurring_signals.sort(key=lambda item: (-item["occurrences"], -item["last_seen_ts"]))
        return {
            "recurring_signals": recurring_signals[:5],
            "recurring_incidents": recurring_incidents[:5],
            "incident_fingerprint_count": len(by_fingerprint),
        }

    def pressure_score(
        self,
        *,
        health: dict[str, Any],
        anomalies: dict[str, Any],
        incidents: dict[str, Any],
        live_metrics: dict[str, Any],
        trend: dict[str, Any],
        anomaly_memory: dict[str, Any],
    ) -> dict[str, Any]:
        anomaly_pressure = sum(
            SEVERITY_WEIGHTS.get(signal["severity"], 0)
            for signal in anomalies.get("signals", [])
        )
        incident_pressure = min(30, incidents.get("active_count", 0) * 10)
        trend_pressure = 0
        if trend["deltas"]["errors"] > 0:
            trend_pressure += min(18, trend["deltas"]["errors"] * 6)
        if trend["deltas"]["rate_limits"] > 0:
            trend_pressure += min(12, trend["deltas"]["rate_limits"] * 3)
        live_pressure = min(24, live_metrics.get("anomaly_pressure", 0) * 3)
        recurrence_pressure = min(
            15,
            len(anomaly_memory.get("recurring_signals", [])) * 5
            + len(anomaly_memory.get("recurring_incidents", [])) * 3,
        )
        health_pressure = max(0, 100 - health["score"]) // 3
        score = min(
            100,
            anomaly_pressure
            + incident_pressure
            + trend_pressure
            + live_pressure
            + recurrence_pressure
            + health_pressure,
        )
        return {
            "score": score,
            "band": self._pressure_band(score),
            "drivers": self._pressure_drivers(
                anomaly_pressure=anomaly_pressure,
                incident_pressure=incident_pressure,
                trend_pressure=trend_pressure,
                live_pressure=live_pressure,
                recurrence_pressure=recurrence_pressure,
                health_pressure=health_pressure,
            ),
        }

    def recommendations(
        self,
        *,
        health: dict[str, Any],
        anomalies: dict[str, Any],
        incidents: dict[str, Any],
        analytics: dict[str, Any],
        trend: dict[str, Any],
        command_intelligence: dict[str, Any],
        anomaly_memory: dict[str, Any],
        pressure: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []
        anomaly_types = {
            signal["anomaly_type"]
            for signal in anomalies.get("signals", [])
        }

        if pressure["score"] >= 80:
            recommendations.append("Treat this as active ops pressure; stabilize incidents before new ping activity.")
        if incidents.get("active_count", 0):
            recommendations.append("Triage active incidents first; they already group related telemetry.")
        if "repeated_failures" in anomaly_types or trend["deltas"]["errors"] > 0:
            recommendations.append("Pause non-essential ping activity until command/runtime failures stop clustering.")
        if analytics.get("rate_limit_count", 0) or trend["deltas"]["rate_limits"] > 0:
            recommendations.append("Review rate-limit pressure by actor and command before loosening limits.")
        if analytics.get("cooldown_trigger_count", 0) >= 3:
            recommendations.append("Check whether repeated cooldown hits point to misuse or unclear operator expectations.")
        if command_intelligence.get("dominant_command"):
            command = command_intelligence["dominant_command"]["command"]
            recommendations.append(f"Audit `/{command}` usage; it dominates recent command traffic.")
        if anomaly_memory.get("recurring_signals"):
            recommendations.append("Treat recurring signals as a pattern, not a one-off; review prior incident context.")
        if health["active_sessions"]:
            recommendations.append("Confirm active sessions are intentional and stop any unnecessary session.")
        if not recommendations:
            recommendations.append("No immediate action needed; keep normal monitoring.")

        return recommendations[:4]

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
            if event["event_type"] == EventName.COMMAND_REJECTED
            and event["metadata"].get("reason") == "cooldown"
        )
        anomaly_pressure = sum(
            event_counts.get(event_type, 0)
            for event_type in (
                EventName.COMMAND_ERROR,
                EventName.COMMAND_RATE_LIMITED,
                EventName.COMMAND_REJECTED,
                EventName.SESSION_STOPPED,
            )
        )
        error_spikes = severity_counts.get("error", 0) + severity_counts.get("critical", 0)
        command_throughput = event_counts.get(EventName.COMMAND_USED, 0)

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
                EventName.COMMAND_RATE_LIMITED,
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
        for incident in incident_service.active_incidents(guild_id, limit=8):
            items.append({
                "kind": "incident",
                "timestamp": incident["updated_at"],
                "severity": incident["severity"],
                "title": incident["title"],
                "description": f"{incident['status']} incident {incident['incident_id']}",
                "context": {
                    "incident_id": incident["incident_id"],
                    "status": incident["status"],
                    "anomaly_type": incident["anomaly_type"],
                    "linked_event_ids": incident["linked_event_ids"],
                },
            })
            for entry in incident["timeline"][:3]:
                items.append({
                    "kind": "incident_timeline",
                    "timestamp": entry["timestamp"],
                    "severity": entry["severity"],
                    "title": entry["title"],
                    "description": entry["description"],
                    "context": {
                        "incident_id": entry["incident_id"],
                        "event_type": entry["event_type"],
                    },
                })

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

    def _event_window_summary(self, events: list[dict[str, Any]]) -> dict[str, int]:
        event_counts = Counter(event["event_type"] for event in events)
        severity_counts = Counter(event["severity"] for event in events)
        return {
            "events": len(events),
            "commands": event_counts.get(EventName.COMMAND_USED, 0),
            "sessions": event_counts.get(EventName.SESSION_STARTED, 0),
            "rate_limits": event_counts.get(EventName.COMMAND_RATE_LIMITED, 0),
            "rejections": event_counts.get(EventName.COMMAND_REJECTED, 0),
            "errors": severity_counts.get("error", 0) + severity_counts.get("critical", 0),
        }

    def _what_changed(
        self,
        current: list[dict[str, Any]],
        previous: list[dict[str, Any]],
        deltas: dict[str, int],
    ) -> list[str]:
        changes: list[str] = []
        current_commands = Counter(
            event["command"]
            for event in current
            if event["event_type"] == EventName.COMMAND_USED and event.get("command")
        )
        previous_commands = Counter(
            event["command"]
            for event in previous
            if event["event_type"] == EventName.COMMAND_USED and event.get("command")
        )

        for metric, label in (
            ("errors", "Error pressure"),
            ("rate_limits", "Rate-limit pressure"),
            ("rejections", "Rejected commands"),
            ("sessions", "Ping-session starts"),
            ("commands", "Command volume"),
        ):
            delta = deltas.get(metric, 0)
            if delta:
                direction = "rose" if delta > 0 else "fell"
                changes.append(f"{label} {direction} by {abs(delta)} compared with the prior window.")

        for command, count in current_commands.most_common(3):
            previous_count = previous_commands.get(command, 0)
            if count >= 3 and count > previous_count:
                changes.append(f"`/{command}` is up by {count - previous_count} use(s).")

        if not changes:
            changes.append("No material movement from the prior window.")
        return changes[:5]

    def _actor_pressure_explanation(
        self,
        pressure_events: int,
        cooldown_hits: int,
        rate_limits: int,
    ) -> str:
        if rate_limits >= 3:
            return "This looks like repeated protection-layer pressure."
        if cooldown_hits >= 3:
            return "This looks like repeated retries before cooldown expiry."
        if pressure_events >= 3:
            return "This actor is repeatedly associated with failed or rejected operations."
        return "Low-volume pressure, worth correlating with recent commands."

    def _pressure_band(self, score: int) -> str:
        if score >= 80:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 35:
            return "medium"
        if score > 0:
            return "low"
        return "none"

    def _pressure_drivers(
        self,
        *,
        anomaly_pressure: int,
        incident_pressure: int,
        trend_pressure: int,
        live_pressure: int,
        recurrence_pressure: int,
        health_pressure: int,
    ) -> list[str]:
        drivers = [
            ("Anomalies", anomaly_pressure),
            ("Incidents", incident_pressure),
            ("Trend movement", trend_pressure),
            ("Live pressure", live_pressure),
            ("Recurring patterns", recurrence_pressure),
            ("Health degradation", health_pressure),
        ]
        return [
            f"{label}: {value}"
            for label, value in sorted(drivers, key=lambda item: item[1], reverse=True)
            if value
        ][:4]

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
            "incidents": {
                "active": [],
                "active_count": 0,
                "highest_severity": "none",
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
            "trend": {
                "current": self._event_window_summary([]),
                "previous": self._event_window_summary([]),
                "deltas": {
                    "events": 0,
                    "commands": 0,
                    "sessions": 0,
                    "rate_limits": 0,
                    "rejections": 0,
                    "errors": 0,
                },
                "direction": "steady",
                "what_changed": ["No material movement from the prior window."],
            },
            "command_intelligence": {
                "total_command_uses": 0,
                "top_commands": [],
                "dominant_command": None,
                "pressure_by_command": [],
                "noisy_actors": [],
            },
            "anomaly_memory": {
                "recurring_signals": [],
                "recurring_incidents": [],
                "incident_fingerprint_count": 0,
            },
            "pressure": {
                "score": 0,
                "band": "none",
                "drivers": [],
            },
            "recommendations": ["No immediate action needed; keep normal monitoring."],
            "guild_ids": [],
        }


operational_intelligence_service = OperationalIntelligenceService()
