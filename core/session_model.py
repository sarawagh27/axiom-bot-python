"""
core/session_model.py — Session dataclass and state enum.
Represents the full lifecycle of a single pingbomb session.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class SessionState(Enum):
    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPED = auto()
    COMPLETED = auto()


@dataclass
class Session:
    # Identity
    guild_id: int
    user_id: int
    target_id: int
    channel_id: int

    # Config
    count: int
    interval: float          # seconds between pings

    # Runtime state
    state: SessionState = SessionState.PENDING
    pings_sent: int = 0
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    # asyncio task handle — set by the engine after spawning
    task: Optional[asyncio.Task] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def key(self) -> tuple[int, int]:
        """Unique session key: (guild_id, user_id)."""
        return (self.guild_id, self.user_id)

    @property
    def pings_remaining(self) -> int:
        return max(0, self.count - self.pings_sent)

    @property
    def is_active(self) -> bool:
        return self.state in (SessionState.RUNNING, SessionState.PAUSED)

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at or time.monotonic()
        return end - self.started_at

    # ------------------------------------------------------------------
    # State transitions (guard-checked)
    # ------------------------------------------------------------------

    def transition(self, new_state: SessionState) -> None:
        _VALID: dict[SessionState, set[SessionState]] = {
            SessionState.PENDING:   {SessionState.RUNNING, SessionState.STOPPED},
            SessionState.RUNNING:   {SessionState.PAUSED, SessionState.STOPPED, SessionState.COMPLETED},
            SessionState.PAUSED:    {SessionState.RUNNING, SessionState.STOPPED},
            SessionState.STOPPED:   set(),
            SessionState.COMPLETED: set(),
        }
        allowed = _VALID.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self.state.name} → {new_state.name}"
            )
        self.state = new_state

        now = time.monotonic()
        if new_state == SessionState.RUNNING and self.started_at is None:
            self.started_at = now
        if new_state in (SessionState.STOPPED, SessionState.COMPLETED):
            self.ended_at = now

    def to_dict(self) -> dict:
        """Serialisable snapshot for audit logging."""
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "target_id": self.target_id,
            "channel_id": self.channel_id,
            "count": self.count,
            "interval": self.interval,
            "state": self.state.name,
            "pings_sent": self.pings_sent,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed": round(self.elapsed, 3),
        }
