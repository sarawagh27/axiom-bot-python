"""
core/database.py — SQLite database manager.
Handles guild configs, usage stats, and cooldowns persistently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional

from config import CONFIG
from core.telemetry import EventName, EventSeverity, TelemetryEvent
from core.telemetry.events import legacy_aliases_for

log = logging.getLogger("axiom.database")

_DB_PATH = os.path.join("data", "axiom.db")


class Database:
    """Async-safe SQLite wrapper using a single connection with WAL mode."""

    def __init__(self) -> None:
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open connection and create tables. Call once at startup."""
        os.makedirs("data", exist_ok=True)
        self._conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        log.info("Database connected: %s", _DB_PATH)

    def _create_tables(self) -> None:
        c = self._conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS guild_configs (
                guild_id     INTEGER PRIMARY KEY,
                max_count    INTEGER NOT NULL DEFAULT 50,
                min_interval REAL    NOT NULL DEFAULT 1.0,
                max_interval REAL    NOT NULL DEFAULT 60.0,
                cooldown_sec INTEGER NOT NULL DEFAULT 60,
                allowed_channels TEXT NOT NULL DEFAULT '[]',
                pingbomb_enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS usage_stats (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                command      TEXT    NOT NULL,
                target_id    INTEGER,
                count        INTEGER NOT NULL DEFAULT 1,
                timestamp    REAL    NOT NULL DEFAULT (unixepoch())
            );

            CREATE INDEX IF NOT EXISTS idx_stats_guild
                ON usage_stats (guild_id);

            CREATE INDEX IF NOT EXISTS idx_stats_user
                ON usage_stats (guild_id, user_id);

            CREATE TABLE IF NOT EXISTS operational_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER,
                event_type   TEXT    NOT NULL,
                severity     TEXT    NOT NULL DEFAULT 'info',
                source       TEXT    NOT NULL,
                user_id      INTEGER,
                target_id    INTEGER,
                command      TEXT,
                metadata     TEXT    NOT NULL DEFAULT '{}',
                timestamp    REAL    NOT NULL DEFAULT (unixepoch()),
                schema_version INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_operational_events_guild_time
                ON operational_events (guild_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_operational_events_type_time
                ON operational_events (event_type, timestamp);

            CREATE INDEX IF NOT EXISTS idx_operational_events_severity_time
                ON operational_events (severity, timestamp);

            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                anomaly_type TEXT NOT NULL,
                event_type TEXT,
                actor_id INTEGER,
                target_id INTEGER,
                command TEXT,
                count INTEGER NOT NULL,
                threshold INTEGER NOT NULL,
                first_seen_ts REAL NOT NULL,
                last_seen_ts REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                acknowledged_at REAL,
                resolved_at REAL
            );

            DROP INDEX IF EXISTS idx_incidents_active_fingerprint;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_active_fingerprint
                ON incidents (guild_id, fingerprint)
                WHERE status IN ('open', 'acknowledged');

            CREATE INDEX IF NOT EXISTS idx_incidents_guild_status
                ON incidents (guild_id, status, updated_at);

            CREATE TABLE IF NOT EXISTS incident_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                timestamp REAL NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents (incident_id)
            );

            CREATE INDEX IF NOT EXISTS idx_incident_timeline_incident_time
                ON incident_timeline (incident_id, timestamp);

            CREATE TABLE IF NOT EXISTS incident_event_links (
                incident_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                linked_at REAL NOT NULL,
                PRIMARY KEY (incident_id, event_id),
                FOREIGN KEY (incident_id) REFERENCES incidents (incident_id),
                FOREIGN KEY (event_id) REFERENCES operational_events (id)
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER,
                channel_id   INTEGER,
                user_id      INTEGER NOT NULL,
                note         TEXT    NOT NULL,
                due_at       INTEGER NOT NULL,
                timezone     TEXT    NOT NULL DEFAULT 'UTC',
                source       TEXT    NOT NULL DEFAULT '',
                created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
                delivered_at INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_reminders_user_due
                ON reminders (user_id, due_at)
                WHERE delivered_at IS NULL;

            CREATE INDEX IF NOT EXISTS idx_reminders_pending_due
                ON reminders (due_at)
                WHERE delivered_at IS NULL;

            CREATE TABLE IF NOT EXISTS user_timezones (
                user_id    INTEGER PRIMARY KEY,
                timezone   TEXT    NOT NULL,
                updated_at INTEGER NOT NULL DEFAULT (unixepoch())
            );
        """)
        self._ensure_operational_events_schema()
        self._conn.commit()

    def _ensure_operational_events_schema(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(operational_events)").fetchall()
        }
        if "schema_version" not in columns:
            self._conn.execute(
                "ALTER TABLE operational_events "
                "ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
            )

    # ------------------------------------------------------------------
    # Guild Config
    # ------------------------------------------------------------------

    def get_guild_config(self, guild_id: int) -> dict:
        row = self._conn.execute(
            "SELECT * FROM guild_configs WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        if row is None:
            return self._default_config(guild_id)
        return {
            "guild_id": row["guild_id"],
            "max_count": row["max_count"],
            "min_interval": row["min_interval"],
            "max_interval": row["max_interval"],
            "cooldown_seconds": row["cooldown_sec"],
            "allowed_channel_ids": json.loads(row["allowed_channels"]),
            "pingbomb_enabled": bool(row["pingbomb_enabled"]),
        }

    def save_guild_config(self, cfg: dict) -> None:
        self._conn.execute("""
            INSERT INTO guild_configs
                (guild_id, max_count, min_interval, max_interval,
                 cooldown_sec, allowed_channels, pingbomb_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                max_count        = excluded.max_count,
                min_interval     = excluded.min_interval,
                max_interval     = excluded.max_interval,
                cooldown_sec     = excluded.cooldown_sec,
                allowed_channels = excluded.allowed_channels,
                pingbomb_enabled = excluded.pingbomb_enabled
        """, (
            cfg["guild_id"],
            cfg["max_count"],
            cfg["min_interval"],
            cfg["max_interval"],
            cfg["cooldown_seconds"],
            json.dumps(cfg["allowed_channel_ids"]),
            int(cfg["pingbomb_enabled"]),
        ))
        self._conn.commit()

    def reset_guild_config(self, guild_id: int) -> None:
        self._conn.execute(
            "DELETE FROM guild_configs WHERE guild_id = ?", (guild_id,)
        )
        self._conn.commit()

    def _default_config(self, guild_id: int) -> dict:
        return {
            "guild_id": guild_id,
            "max_count": CONFIG.pingbomb_max_count,
            "min_interval": CONFIG.pingbomb_min_interval,
            "max_interval": CONFIG.pingbomb_max_interval,
            "cooldown_seconds": CONFIG.pingbomb_cooldown_seconds,
            "allowed_channel_ids": [],
            "pingbomb_enabled": True,
        }

    # ------------------------------------------------------------------
    # Usage Stats
    # ------------------------------------------------------------------

    def record_usage(
        self,
        guild_id: int,
        user_id: int,
        command: str,
        target_id: Optional[int] = None,
        count: int = 1,
    ) -> None:
        self._conn.execute("""
            INSERT INTO usage_stats (guild_id, user_id, command, target_id, count)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, command, target_id, count))
        self._conn.commit()
        self.record_operational_event(
            event_type=EventName.COMMAND_USED,
            severity=EventSeverity.INFO,
            source="usage_stats",
            guild_id=guild_id,
            user_id=user_id,
            target_id=target_id,
            command=command,
            metadata={"count": count},
        )

    def get_guild_stats(self, guild_id: int) -> dict:
        """Returns aggregate stats for a guild."""
        row = self._conn.execute("""
            SELECT
                COUNT(*) as total_uses,
                SUM(count) as total_pings,
                COUNT(DISTINCT user_id) as unique_users
            FROM usage_stats
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()

        top_users = self._conn.execute("""
            SELECT user_id, SUM(count) as total
            FROM usage_stats
            WHERE guild_id = ?
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 3
        """, (guild_id,)).fetchall()

        top_commands = self._conn.execute("""
            SELECT command, COUNT(*) as uses
            FROM usage_stats
            WHERE guild_id = ?
            GROUP BY command
            ORDER BY uses DESC
            LIMIT 5
        """, (guild_id,)).fetchall()

        return {
            "total_uses": row["total_uses"] or 0,
            "total_pings": row["total_pings"] or 0,
            "unique_users": row["unique_users"] or 0,
            "top_users": [(r["user_id"], r["total"]) for r in top_users],
            "top_commands": [(r["command"], r["uses"]) for r in top_commands],
        }

    def get_user_stats(self, guild_id: int, user_id: int) -> dict:
        row = self._conn.execute("""
            SELECT
                COUNT(*) as total_uses,
                SUM(count) as total_pings,
                MAX(timestamp) as last_used
            FROM usage_stats
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()

        return {
            "total_uses": row["total_uses"] or 0,
            "total_pings": row["total_pings"] or 0,
            "last_used": row["last_used"],
        }

    # ------------------------------------------------------------------
    # Operational Events
    # ------------------------------------------------------------------

    def record_operational_event(
        self,
        event_type: str,
        source: str,
        severity: str = "info",
        guild_id: Optional[int] = None,
        user_id: Optional[int] = None,
        target_id: Optional[int] = None,
        command: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Persist a structured operational event for analytics and health scoring."""
        event = TelemetryEvent(
            event_name=event_type,
            severity=severity,
            source=source,
            guild_id=guild_id,
            user_id=user_id,
            target_id=target_id,
            command=command,
            metadata=metadata or {},
            timestamp=timestamp or time.time(),
        )
        self._conn.execute("""
            INSERT INTO operational_events (
                guild_id, event_type, severity, source, user_id, target_id,
                command, metadata, timestamp, schema_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, event.to_storage_tuple())
        self._conn.commit()

    def get_operational_event_summary(
        self,
        guild_id: int,
        window_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Return aggregate operational events for a guild over a recent window."""
        events = self.get_operational_events(guild_id, window_seconds)
        unique_users = {event["user_id"] for event in events if event["user_id"] is not None}
        severity_counts: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        for event in events:
            severity_counts[event["severity"]] = severity_counts.get(event["severity"], 0) + 1
            event_counts[event["event_type"]] = event_counts.get(event["event_type"], 0) + 1

        return {
            "window_seconds": window_seconds,
            "total_events": len(events),
            "unique_users": len(unique_users),
            "last_event_ts": max((event["timestamp"] for event in events), default=None),
            "severity_counts": severity_counts,
            "event_counts": dict(sorted(event_counts.items(), key=lambda item: (-item[1], item[0]))),
        }

    def get_recent_operational_events(
        self,
        guild_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT id, event_type, severity, source, user_id, target_id, command,
                   metadata, timestamp, schema_version
            FROM operational_events
            WHERE guild_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (guild_id, limit)).fetchall()

        return [self._event_row_to_dict(row) for row in rows]

    def get_operational_events(
        self,
        guild_id: int,
        window_seconds: int = 3600,
        event_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Return raw operational events for analyzers and reports."""
        since = time.time() - window_seconds
        params: list[Any] = [guild_id, since]
        event_filter = ""

        if event_types:
            expanded_event_types: list[str] = []
            for event_type in event_types:
                expanded_event_types.extend(sorted(legacy_aliases_for(event_type)))
            placeholders = ", ".join("?" for _ in expanded_event_types)
            event_filter = f" AND event_type IN ({placeholders})"
            params.extend(expanded_event_types)

        rows = self._conn.execute(f"""
            SELECT id, event_type, severity, source, user_id, target_id, command,
                   metadata, timestamp, schema_version
            FROM operational_events
            WHERE guild_id = ? AND timestamp >= ?{event_filter}
            ORDER BY timestamp ASC
        """, params).fetchall()

        return [self._event_row_to_dict(row) for row in rows]

    def get_operational_events_after(
        self,
        guild_id: int,
        after_id: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return operational events newer than a cursor ID."""
        rows = self._conn.execute("""
            SELECT id, event_type, severity, source, user_id, target_id, command,
                   metadata, timestamp, schema_version
            FROM operational_events
            WHERE guild_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
        """, (guild_id, after_id, limit)).fetchall()

        return [self._event_row_to_dict(row) for row in rows]

    def get_latest_operational_event_id(self, guild_id: int) -> int:
        row = self._conn.execute("""
            SELECT COALESCE(MAX(id), 0) as latest_id
            FROM operational_events
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()
        return row["latest_id"] or 0

    def list_observed_guild_ids(self) -> list[int]:
        """Return guild IDs seen by config, usage, or operational telemetry."""
        rows = self._conn.execute("""
            SELECT guild_id FROM guild_configs
            UNION
            SELECT guild_id FROM usage_stats
            UNION
            SELECT guild_id FROM operational_events WHERE guild_id IS NOT NULL
            ORDER BY guild_id ASC
        """).fetchall()
        return [row["guild_id"] for row in rows]

    def get_command_usage_summary(
        self,
        guild_id: int,
        window_seconds: int = 3600,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Return command usage counts for a recent window."""
        since = time.time() - window_seconds
        rows = self._conn.execute("""
            SELECT command, COUNT(*) as uses, COALESCE(SUM(count), 0) as volume
            FROM usage_stats
            WHERE guild_id = ? AND timestamp >= ?
            GROUP BY command
            ORDER BY uses DESC, command ASC
            LIMIT ?
        """, (guild_id, since, limit)).fetchall()

        return [
            {
                "command": row["command"],
                "uses": row["uses"],
                "volume": row["volume"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------

    def create_reminder(
        self,
        *,
        user_id: int,
        guild_id: Optional[int],
        channel_id: Optional[int],
        note: str,
        due_at: int,
        timezone: str,
        source: str,
    ) -> dict[str, Any]:
        row = self._conn.execute("""
            INSERT INTO reminders (
                guild_id, channel_id, user_id, note, due_at, timezone, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id, guild_id, channel_id, user_id, note, due_at,
                      timezone, source, created_at
        """, (guild_id, channel_id, user_id, note, due_at, timezone, source)).fetchone()
        self._conn.commit()
        return dict(row)

    def list_reminders(self, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT id, guild_id, channel_id, user_id, note, due_at, timezone, source, created_at
            FROM reminders
            WHERE user_id = ? AND delivered_at IS NULL
            ORDER BY due_at ASC, id ASC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def list_pending_reminders(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT id, guild_id, channel_id, user_id, note, due_at, timezone, source, created_at
            FROM reminders
            WHERE delivered_at IS NULL
            ORDER BY due_at ASC, id ASC
        """).fetchall()
        return [dict(row) for row in rows]

    def get_reminder(self, reminder_id: int, user_id: int | None = None) -> Optional[dict[str, Any]]:
        params: list[Any] = [reminder_id]
        user_filter = ""
        if user_id is not None:
            user_filter = " AND user_id = ?"
            params.append(user_id)
        row = self._conn.execute(f"""
            SELECT id, guild_id, channel_id, user_id, note, due_at, timezone, source, created_at
            FROM reminders
            WHERE id = ? AND delivered_at IS NULL{user_filter}
        """, params).fetchone()
        return dict(row) if row else None

    def delete_reminder(self, reminder_id: int, user_id: int) -> Optional[dict[str, Any]]:
        reminder = self.get_reminder(reminder_id, user_id)
        if reminder is None:
            return None
        self._conn.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        self._conn.commit()
        return reminder

    def clear_reminders(self, user_id: int) -> int:
        cursor = self._conn.execute(
            "DELETE FROM reminders WHERE user_id = ? AND delivered_at IS NULL",
            (user_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def mark_reminder_delivered(self, reminder_id: int, *, delivered_at: Optional[int] = None) -> None:
        self._conn.execute(
            "UPDATE reminders SET delivered_at = ? WHERE id = ?",
            (delivered_at or int(time.time()), reminder_id),
        )
        self._conn.commit()

    def set_user_timezone(self, user_id: int, timezone_name: str) -> None:
        self._conn.execute("""
            INSERT INTO user_timezones (user_id, timezone, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                timezone = excluded.timezone,
                updated_at = excluded.updated_at
        """, (user_id, timezone_name, int(time.time())))
        self._conn.commit()

    def get_user_timezone(self, user_id: int) -> Optional[str]:
        row = self._conn.execute(
            "SELECT timezone FROM user_timezones WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["timezone"] if row else None

    def reset_user_timezone(self, user_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM user_timezones WHERE user_id = ?",
            (user_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------

    def create_incident(
        self,
        incident_id: str,
        guild_id: int,
        fingerprint: str,
        severity: str,
        status: str,
        title: str,
        description: str,
        anomaly_type: str,
        event_type: Optional[str],
        actor_id: Optional[int],
        target_id: Optional[int],
        command: Optional[str],
        count: int,
        threshold: int,
        first_seen_ts: float,
        last_seen_ts: float,
    ) -> dict[str, Any]:
        now = time.time()
        self._conn.execute("""
            INSERT INTO incidents (
                incident_id, guild_id, fingerprint, severity, status, title,
                description, anomaly_type, event_type, actor_id, target_id,
                command, count, threshold, first_seen_ts, last_seen_ts,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
            guild_id,
            fingerprint,
            severity,
            status,
            title,
            description,
            anomaly_type,
            event_type,
            actor_id,
            target_id,
            command,
            count,
            threshold,
            first_seen_ts,
            last_seen_ts,
            now,
            now,
        ))
        self._conn.commit()
        return self.get_incident(incident_id)

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        row = self._conn.execute("""
            SELECT *
            FROM incidents
            WHERE incident_id = ?
        """, (incident_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown incident: {incident_id}")
        return self._incident_row_to_dict(row)

    def get_active_incident_by_fingerprint(
        self,
        guild_id: int,
        fingerprint: str,
    ) -> Optional[dict[str, Any]]:
        row = self._conn.execute("""
            SELECT *
            FROM incidents
            WHERE guild_id = ?
              AND fingerprint = ?
              AND status IN ('open', 'acknowledged')
            ORDER BY updated_at DESC
            LIMIT 1
        """, (guild_id, fingerprint)).fetchone()
        if row is None:
            return None
        return self._incident_row_to_dict(row)

    def update_incident_observation(
        self,
        incident_id: str,
        severity: str,
        count: int,
        last_seen_ts: float,
    ) -> dict[str, Any]:
        self._conn.execute("""
            UPDATE incidents
            SET severity = ?,
                count = ?,
                last_seen_ts = ?,
                updated_at = ?
            WHERE incident_id = ?
        """, (severity, count, last_seen_ts, time.time(), incident_id))
        self._conn.commit()
        return self.get_incident(incident_id)

    def update_incident_status(
        self,
        incident_id: str,
        status: str,
        timestamp: float,
    ) -> dict[str, Any]:
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, timestamp]
        if status == "acknowledged":
            fields.append("acknowledged_at = ?")
            params.append(timestamp)
        if status == "resolved":
            fields.append("resolved_at = ?")
            params.append(timestamp)
        params.append(incident_id)
        self._conn.execute(f"""
            UPDATE incidents
            SET {", ".join(fields)}
            WHERE incident_id = ?
        """, params)
        self._conn.commit()
        return self.get_incident(incident_id)

    def list_incidents(
        self,
        guild_id: int,
        statuses: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [guild_id]
        status_filter = ""
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            status_filter = f" AND status IN ({placeholders})"
            params.extend(statuses)
        params.append(limit)
        rows = self._conn.execute(f"""
            SELECT *
            FROM incidents
            WHERE guild_id = ?{status_filter}
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    ELSE 1
                END DESC,
                updated_at DESC
            LIMIT ?
        """, params).fetchall()
        return [self._incident_row_to_dict(row) for row in rows]

    def add_incident_timeline_event(
        self,
        incident_id: str,
        guild_id: int,
        event_type: str,
        severity: str,
        title: str,
        description: str,
        metadata: Optional[dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> dict[str, Any]:
        self._conn.execute("""
            INSERT INTO incident_timeline (
                incident_id, guild_id, event_type, severity, title,
                description, metadata, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
            guild_id,
            event_type,
            severity,
            title,
            description,
            json.dumps(metadata or {}, default=str, sort_keys=True),
            timestamp or time.time(),
        ))
        self._conn.commit()
        row = self._conn.execute("""
            SELECT *
            FROM incident_timeline
            WHERE id = last_insert_rowid()
        """).fetchone()
        return self._incident_timeline_row_to_dict(row)

    def get_incident_timeline(
        self,
        incident_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT *
            FROM incident_timeline
            WHERE incident_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        """, (incident_id, limit)).fetchall()
        return [self._incident_timeline_row_to_dict(row) for row in rows]

    def link_incident_event(self, incident_id: str, event_id: int) -> bool:
        cursor = self._conn.execute("""
            INSERT OR IGNORE INTO incident_event_links (incident_id, event_id, linked_at)
            VALUES (?, ?, ?)
        """, (incident_id, event_id, time.time()))
        self._conn.commit()
        return cursor.rowcount > 0

    def list_incident_event_links(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT incident_id, event_id, linked_at
            FROM incident_event_links
            WHERE incident_id = ?
            ORDER BY linked_at ASC
        """, (incident_id,)).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            log.info("Database connection closed.")

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return TelemetryEvent.from_record(row).to_dict()

    def _incident_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        incident = dict(row)
        incident["timeline"] = self.get_incident_timeline(incident["incident_id"], limit=10)
        incident["linked_event_ids"] = [
            link["event_id"]
            for link in self.list_incident_event_links(incident["incident_id"])
        ]
        return incident

    def _incident_timeline_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"])
        return item


# Module-level singleton
db = Database()
