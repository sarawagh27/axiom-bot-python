"""
core/session_manager.py — Singleton registry that manages all active Sessions.
Keyed by (guild_id, user_id) — one active session per user per guild.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.session_model import Session, SessionState

log = logging.getLogger("axiom.session_manager")


class SessionManager:
    """Thread-safe (asyncio single-threaded) in-memory session registry."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[int, int], Session] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        guild_id: int,
        user_id: int,
        target_id: int,
        channel_id: int,
        count: int,
        interval: float,
    ) -> Session:
        key = (guild_id, user_id)
        if key in self._sessions:
            raise ValueError(
                f"User {user_id} already has an active session in guild {guild_id}."
            )
        session = Session(
            guild_id=guild_id,
            user_id=user_id,
            target_id=target_id,
            channel_id=channel_id,
            count=count,
            interval=interval,
        )
        self._sessions[key] = session
        log.info(
            "Session created: guild=%s user=%s target=%s count=%s interval=%ss",
            guild_id, user_id, target_id, count, interval,
        )
        return session

    def get(self, guild_id: int, user_id: int) -> Optional[Session]:
        return self._sessions.get((guild_id, user_id))

    def destroy(self, guild_id: int, user_id: int) -> Optional[Session]:
        session = self._sessions.pop((guild_id, user_id), None)
        if session:
            log.info(
                "Session destroyed: guild=%s user=%s pings_sent=%s/%s state=%s",
                guild_id, user_id, session.pings_sent, session.count, session.state.name,
            )
        return session

    def has_active(self, guild_id: int, user_id: int) -> bool:
        session = self._sessions.get((guild_id, user_id))
        return session is not None and session.is_active

    # ------------------------------------------------------------------
    # Admin helpers
    # ------------------------------------------------------------------

    def all_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def active_sessions(self) -> list[Session]:
        return [s for s in self._sessions.values() if s.is_active]

    def force_stop_all(self, guild_id: int) -> int:
        """Force-stop all sessions in a guild. Returns count stopped."""
        count = 0
        keys_to_remove = [
            key for key in self._sessions
            if key[0] == guild_id and self._sessions[key].is_active
        ]
        for key in keys_to_remove:
            session = self._sessions.pop(key)
            if session.task and not session.task.done():
                session.task.cancel()
            count += 1
            log.warning("Force-stopped session: guild=%s user=%s", *key)
        return count

    def stop_session(self, guild_id: int, user_id: int) -> bool:
        """Admin: stop a specific session by IDs. Returns True if found."""
        session = self._sessions.get((guild_id, user_id))
        if not session:
            return False
        if session.task and not session.task.done():
            session.task.cancel()
        self.destroy(guild_id, user_id)
        return True


# Module-level singleton
session_manager = SessionManager()
