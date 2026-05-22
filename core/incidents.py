"""Incident lifecycle domain service.

Incidents are durable operational records derived from anomaly signals. They
are intentionally separate from rendering so Discord commands and future
workers can share the same lifecycle rules.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from core.anomaly_detection import AnomalyDetectionReport, AnomalySignal
from core.telemetry import EventName


class IncidentSeverity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    ORDER = {LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}


class IncidentStatus:
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"

    ACTIVE = {OPEN, ACKNOWLEDGED}
    ALL = {OPEN, ACKNOWLEDGED, RESOLVED}


@dataclass(frozen=True)
class IncidentPolicy:
    """Controls which anomaly signals become incidents."""

    minimum_severity: str = IncidentSeverity.MEDIUM

    def should_open(self, signal: AnomalySignal) -> bool:
        return (
            IncidentSeverity.ORDER.get(signal.severity, 0)
            >= IncidentSeverity.ORDER[self.minimum_severity]
        )


class IncidentService:
    """Creates, updates, and snapshots operational incidents."""

    def __init__(self, policy: IncidentPolicy | None = None) -> None:
        self._policy = policy or IncidentPolicy()

    def reconcile_anomalies(
        self,
        report: AnomalyDetectionReport,
    ) -> list[dict[str, Any]]:
        """Ensure incident records exist for incident-worthy anomaly signals."""
        incidents: list[dict[str, Any]] = []
        for signal in report.signals:
            if not self._policy.should_open(signal):
                continue
            incidents.append(self.create_or_update_from_signal(signal, report.generated_at))
        return incidents

    def create_or_update_from_signal(
        self,
        signal: AnomalySignal,
        observed_at: float | None = None,
    ) -> dict[str, Any]:
        from core.database import db

        now = observed_at or time.time()
        fingerprint = self._fingerprint(signal)
        existing = db.get_active_incident_by_fingerprint(signal.guild_id, fingerprint)

        if existing:
            incident = db.update_incident_observation(
                incident_id=existing["incident_id"],
                severity=self._max_severity(existing["severity"], signal.severity),
                count=signal.count,
                last_seen_ts=now,
            )
            self._link_matching_events(incident["incident_id"], signal)
            return incident

        incident_id = self._new_incident_id()
        incident = db.create_incident(
            incident_id=incident_id,
            guild_id=signal.guild_id,
            fingerprint=fingerprint,
            severity=signal.severity,
            status=IncidentStatus.OPEN,
            title=signal.title,
            description=signal.description,
            anomaly_type=signal.anomaly_type,
            event_type=signal.event_type,
            actor_id=signal.actor_id,
            target_id=signal.target_id,
            command=signal.command,
            count=signal.count,
            threshold=signal.threshold,
            first_seen_ts=now,
            last_seen_ts=now,
        )
        db.add_incident_timeline_event(
            incident_id=incident_id,
            guild_id=signal.guild_id,
            event_type="incident.created",
            severity=signal.severity,
            title="Incident opened",
            description=signal.description,
            metadata=signal.to_dict(),
            timestamp=now,
        )
        self._emit_lifecycle_event(EventName.INCIDENT_OPENED, incident, signal.to_dict(), now)
        self._link_matching_events(incident_id, signal)
        return incident

    def acknowledge(
        self,
        incident_id: str,
        actor_id: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        incident = self._transition(
            incident_id=incident_id,
            status=IncidentStatus.ACKNOWLEDGED,
            event_name=EventName.INCIDENT_ACKNOWLEDGED,
            timeline_type="incident.acknowledged",
            title="Incident acknowledged",
            actor_id=actor_id,
            note=note,
        )
        return incident

    def resolve(
        self,
        incident_id: str,
        actor_id: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        incident = self._transition(
            incident_id=incident_id,
            status=IncidentStatus.RESOLVED,
            event_name=EventName.INCIDENT_RESOLVED,
            timeline_type="incident.resolved",
            title="Incident resolved",
            actor_id=actor_id,
            note=note,
        )
        return incident

    def active_incidents(self, guild_id: int, limit: int = 10) -> list[dict[str, Any]]:
        from core.database import db

        return db.list_incidents(guild_id, statuses=sorted(IncidentStatus.ACTIVE), limit=limit)

    def incident_timeline(self, incident_id: str, limit: int = 20) -> list[dict[str, Any]]:
        from core.database import db

        return db.get_incident_timeline(incident_id, limit=limit)

    def active_snapshot(self, guild_id: int, limit: int = 8) -> dict[str, Any]:
        incidents = self.active_incidents(guild_id, limit=limit)
        return {
            "active": incidents,
            "active_count": len(incidents),
            "highest_severity": self._highest_severity(incidents),
        }

    def fingerprint_for_signal(self, signal: AnomalySignal) -> str:
        return self._fingerprint(signal)

    def _transition(
        self,
        incident_id: str,
        status: str,
        event_name: str,
        timeline_type: str,
        title: str,
        actor_id: int | None,
        note: str | None,
    ) -> dict[str, Any]:
        from core.database import db

        if status not in IncidentStatus.ALL:
            raise ValueError(f"Unknown incident status: {status}")

        now = time.time()
        incident = db.update_incident_status(incident_id, status, now)
        metadata = {"actor_id": actor_id, "note": note}
        db.add_incident_timeline_event(
            incident_id=incident_id,
            guild_id=incident["guild_id"],
            event_type=timeline_type,
            severity=incident["severity"],
            title=title,
            description=note or title,
            metadata=metadata,
            timestamp=now,
        )
        self._emit_lifecycle_event(event_name, incident, metadata, now)
        return incident

    def _link_matching_events(self, incident_id: str, signal: AnomalySignal) -> None:
        if not signal.event_type:
            return

        from core.database import db

        events = db.get_operational_events(
            signal.guild_id,
            window_seconds=signal.window_seconds,
            event_types=[signal.event_type],
        )
        linked = 0
        for event in events:
            if signal.actor_id is not None and event.get("user_id") != signal.actor_id:
                continue
            if signal.command is not None and event.get("command") != signal.command:
                continue
            if db.link_incident_event(incident_id, event["id"]):
                linked += 1

        if linked:
            incident = db.get_incident(incident_id)
            db.add_incident_timeline_event(
                incident_id=incident_id,
                guild_id=signal.guild_id,
                event_type="incident.telemetry_linked",
                severity=signal.severity,
                title="Telemetry linked",
                description=f"Linked {linked} telemetry event(s) to this incident.",
                metadata={"linked_event_count": linked, "event_type": signal.event_type},
                timestamp=time.time(),
            )
            self._emit_lifecycle_event(
                EventName.INCIDENT_LINKED,
                incident,
                {"linked_event_count": linked, "event_type": signal.event_type},
            )

    def _emit_lifecycle_event(
        self,
        event_name: str,
        incident: dict[str, Any],
        metadata: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        from core.database import db

        db.record_operational_event(
            event_type=event_name,
            severity="info",
            source="incident_service",
            guild_id=incident["guild_id"],
            metadata={
                "incident_id": incident["incident_id"],
                "incident_severity": incident["severity"],
                "incident_status": incident["status"],
                **metadata,
            },
            timestamp=timestamp,
        )

    def _fingerprint(self, signal: AnomalySignal) -> str:
        parts = [
            signal.anomaly_type,
            signal.event_type or "any",
            str(signal.actor_id or "guild"),
            signal.command or "any",
            str(signal.target_id or "any"),
        ]
        return "|".join(parts)

    def _max_severity(self, current: str, candidate: str) -> str:
        if IncidentSeverity.ORDER.get(candidate, 0) > IncidentSeverity.ORDER.get(current, 0):
            return candidate
        return current

    def _highest_severity(self, incidents: list[dict[str, Any]]) -> str:
        if not incidents:
            return "none"
        return max(
            incidents,
            key=lambda item: IncidentSeverity.ORDER.get(item["severity"], 0),
        )["severity"]

    def _new_incident_id(self) -> str:
        return f"inc_{uuid.uuid4().hex[:12]}"


incident_service = IncidentService()
