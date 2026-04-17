"""
core/guild_config.py — Per-guild configuration manager.
Now backed by SQLite via core/database.py instead of JSON.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import CONFIG

log = logging.getLogger("axiom.guild_config")


@dataclass
class GuildConfig:
    guild_id: int
    max_count: int = CONFIG.pingbomb_max_count
    min_interval: float = CONFIG.pingbomb_min_interval
    max_interval: float = CONFIG.pingbomb_max_interval
    cooldown_seconds: int = CONFIG.pingbomb_cooldown_seconds
    allowed_channel_ids: list = None
    pingbomb_enabled: bool = True

    def __post_init__(self):
        if self.allowed_channel_ids is None:
            self.allowed_channel_ids = []

    def to_dict(self) -> dict:
        return {
            "guild_id": self.guild_id,
            "max_count": self.max_count,
            "min_interval": self.min_interval,
            "max_interval": self.max_interval,
            "cooldown_seconds": self.cooldown_seconds,
            "allowed_channel_ids": self.allowed_channel_ids,
            "pingbomb_enabled": self.pingbomb_enabled,
        }

    @staticmethod
    def from_dict(data: dict) -> "GuildConfig":
        return GuildConfig(
            guild_id=data["guild_id"],
            max_count=data.get("max_count", CONFIG.pingbomb_max_count),
            min_interval=data.get("min_interval", CONFIG.pingbomb_min_interval),
            max_interval=data.get("max_interval", CONFIG.pingbomb_max_interval),
            cooldown_seconds=data.get("cooldown_seconds", CONFIG.pingbomb_cooldown_seconds),
            allowed_channel_ids=data.get("allowed_channel_ids", []),
            pingbomb_enabled=data.get("pingbomb_enabled", True),
        )


class GuildConfigManager:
    """Manages per-guild configuration backed by SQLite."""

    def __init__(self) -> None:
        self._cache: dict[int, GuildConfig] = {}

    def get(self, guild_id: int) -> GuildConfig:
        if guild_id not in self._cache:
            from core.database import db
            data = db.get_guild_config(guild_id)
            self._cache[guild_id] = GuildConfig.from_dict(data)
        return self._cache[guild_id]

    def set(self, config: GuildConfig) -> None:
        self._cache[config.guild_id] = config
        from core.database import db
        db.save_guild_config(config.to_dict())
        log.info("Guild config saved for guild %s", config.guild_id)

    def reset(self, guild_id: int) -> None:
        self._cache.pop(guild_id, None)
        from core.database import db
        db.reset_guild_config(guild_id)
        log.info("Guild config reset for guild %s", guild_id)

    def is_channel_allowed(self, guild_id: int, channel_id: int) -> bool:
        cfg = self.get(guild_id)
        if not cfg.allowed_channel_ids:
            return True
        return channel_id in cfg.allowed_channel_ids

    def is_pingbomb_enabled(self, guild_id: int) -> bool:
        return self.get(guild_id).pingbomb_enabled

    def all_configs(self) -> list[GuildConfig]:
        return list(self._cache.values())


guild_config_manager = GuildConfigManager()
