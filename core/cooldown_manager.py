"""
core/cooldown_manager.py — Per-user cooldown tracking with configurable TTL.
Cooldown is applied AFTER a session ends (start + blast window = full lockout).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger("axiom.cooldown_manager")


class CooldownManager:
    """
    Tracks cooldown expiry timestamps keyed by (guild_id, user_id).
    All times are monotonic seconds.
    """

    def __init__(self, default_cooldown: float) -> None:
        self._default_cooldown = default_cooldown
        # Maps (guild_id, user_id) → expiry monotonic timestamp
        self._expiry: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, guild_id: int, user_id: int) -> Optional[float]:
        """
        Returns seconds remaining on cooldown, or None if not on cooldown.
        Automatically cleans up expired entries.
        """
        key = (guild_id, user_id)
        expiry = self._expiry.get(key)
        if expiry is None:
            return None

        remaining = expiry - time.monotonic()
        if remaining <= 0:
            del self._expiry[key]
            return None

        return remaining

    def start_cooldown(
        self,
        guild_id: int,
        user_id: int,
        duration: Optional[float] = None,
    ) -> None:
        """Start (or reset) a cooldown for a user."""
        ttl = duration if duration is not None else self._default_cooldown
        key = (guild_id, user_id)
        self._expiry[key] = time.monotonic() + ttl
        log.debug(
            "Cooldown started: guild=%s user=%s ttl=%.1fs",
            guild_id, user_id, ttl,
        )

    def clear_cooldown(self, guild_id: int, user_id: int) -> bool:
        """Admin: forcibly clear a user's cooldown. Returns True if cleared."""
        key = (guild_id, user_id)
        if key in self._expiry:
            del self._expiry[key]
            log.info("Cooldown cleared by admin: guild=%s user=%s", guild_id, user_id)
            return True
        return False

    def clear_all_guild(self, guild_id: int) -> int:
        """Admin: clear all cooldowns in a guild. Returns count cleared."""
        keys = [k for k in self._expiry if k[0] == guild_id]
        for key in keys:
            del self._expiry[key]
        if keys:
            log.info("Cleared %d cooldowns for guild=%s", len(keys), guild_id)
        return len(keys)

    def is_on_cooldown(self, guild_id: int, user_id: int) -> bool:
        return self.check(guild_id, user_id) is not None

    def all_active(self) -> list[tuple[tuple[int, int], float]]:
        """Returns list of ((guild_id, user_id), remaining) for active cooldowns."""
        now = time.monotonic()
        return [
            (key, expiry - now)
            for key, expiry in self._expiry.items()
            if expiry > now
        ]


# Module-level singleton (initialised lazily from CONFIG in engine)
from config import CONFIG  # noqa: E402
cooldown_manager = CooldownManager(default_cooldown=CONFIG.pingbomb_cooldown_seconds)
