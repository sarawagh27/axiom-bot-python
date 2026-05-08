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
                timestamp    REAL    NOT NULL DEFAULT (unixepoch())
            );

            CREATE INDEX IF NOT EXISTS idx_operational_events_guild_time
                ON operational_events (guild_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_operational_events_type_time
                ON operational_events (event_type, timestamp);

            CREATE INDEX IF NOT EXISTS idx_operational_events_severity_time
                ON operational_events (severity, timestamp);
        """)
        self._conn.commit()

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
            event_type="command_used",
            severity="info",
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
        self._conn.execute("""
            INSERT INTO operational_events (
                guild_id, event_type, severity, source, user_id, target_id,
                command, metadata, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guild_id,
            event_type,
            severity,
            source,
            user_id,
            target_id,
            command,
            json.dumps(metadata or {}, default=str, sort_keys=True),
            timestamp or time.time(),
        ))
        self._conn.commit()

    def get_operational_event_summary(
        self,
        guild_id: int,
        window_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Return aggregate operational events for a guild over a recent window."""
        since = time.time() - window_seconds
        base_params = (guild_id, since)

        total_row = self._conn.execute("""
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT user_id) as unique_users,
                MAX(timestamp) as last_event_ts
            FROM operational_events
            WHERE guild_id = ? AND timestamp >= ?
        """, base_params).fetchone()

        severity_rows = self._conn.execute("""
            SELECT severity, COUNT(*) as count
            FROM operational_events
            WHERE guild_id = ? AND timestamp >= ?
            GROUP BY severity
        """, base_params).fetchall()

        event_rows = self._conn.execute("""
            SELECT event_type, COUNT(*) as count
            FROM operational_events
            WHERE guild_id = ? AND timestamp >= ?
            GROUP BY event_type
            ORDER BY count DESC, event_type ASC
        """, base_params).fetchall()

        return {
            "window_seconds": window_seconds,
            "total_events": total_row["total_events"] or 0,
            "unique_users": total_row["unique_users"] or 0,
            "last_event_ts": total_row["last_event_ts"],
            "severity_counts": {
                row["severity"]: row["count"] for row in severity_rows
            },
            "event_counts": {
                row["event_type"]: row["count"] for row in event_rows
            },
        }

    def get_recent_operational_events(
        self,
        guild_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT event_type, severity, source, user_id, target_id, command,
                   metadata, timestamp
            FROM operational_events
            WHERE guild_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (guild_id, limit)).fetchall()

        return [
            {
                "event_type": row["event_type"],
                "severity": row["severity"],
                "source": row["source"],
                "user_id": row["user_id"],
                "target_id": row["target_id"],
                "command": row["command"],
                "metadata": json.loads(row["metadata"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def get_operational_events(
        self,
        guild_id: int,
        window_seconds: int = 3600,
        event_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Return raw operational events for analyzers and dashboards."""
        since = time.time() - window_seconds
        params: list[Any] = [guild_id, since]
        event_filter = ""

        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            event_filter = f" AND event_type IN ({placeholders})"
            params.extend(event_types)

        rows = self._conn.execute(f"""
            SELECT event_type, severity, source, user_id, target_id, command,
                   metadata, timestamp
            FROM operational_events
            WHERE guild_id = ? AND timestamp >= ?{event_filter}
            ORDER BY timestamp ASC
        """, params).fetchall()

        return [
            {
                "event_type": row["event_type"],
                "severity": row["severity"],
                "source": row["source"],
                "user_id": row["user_id"],
                "target_id": row["target_id"],
                "command": row["command"],
                "metadata": json.loads(row["metadata"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

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

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            log.info("Database connection closed.")


# Module-level singleton
db = Database()
