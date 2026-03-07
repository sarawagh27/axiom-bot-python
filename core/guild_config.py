"""
core/guild_config.py — Per-guild configuration manager.
Stores guild-specific settings in a local JSON file (data/guild_configs.json).
Falls back to global CONFIG defaults when no guild override exists.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional

from config import CONFIG

log = logging.getLogger("axiom.guild_config")

_DATA_DIR = "data"
_CONFIG_FILE = os.path.join(_DATA_DIR, "guild_configs.json")


@dataclass
class GuildConfig:
    guild_id: int

    # Pingbomb settings
    max_count: int = CONFIG.pingbomb_max_count
    min_interval: float = CONFIG.pingbomb_min_interval
    max_interval: float = CONFIG.pingbomb_max_interval
    cooldown_seconds: int = CONFIG.pingbomb_cooldown_seconds

    # Channel restrictions (empty = all channels allowed)
    allowed_channel_ids: list[int] = None

    # Feature toggles
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
    """
    Manages per-guild configuration.
    Persists to data/guild_configs.json automatically on every write.
    """

    def __init__(self) -> None:
        self._configs: dict[int, GuildConfig] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        os.makedirs(_DATA_DIR, exist_ok=True)
        if not os.path.exists(_CONFIG_FILE):
            log.info("No guild config file found — starting fresh.")
            return
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                raw: dict = json.load(f)
            for guild_id_str, data in raw.items():
                cfg = GuildConfig.from_dict(data)
                self._configs[cfg.guild_id] = cfg
            log.info("Loaded guild configs for %d guild(s).", len(self._configs))
        except Exception as exc:
            log.error("Failed to load guild configs: %s", exc)

    def _save(self) -> None:
        os.makedirs(_DATA_DIR, exist_ok=True)
        try:
            raw = {str(gid): cfg.to_dict() for gid, cfg in self._configs.items()}
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2)
        except Exception as exc:
            log.error("Failed to save guild configs: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, guild_id: int) -> GuildConfig:
        """Return guild config, creating a default one if not set."""
        if guild_id not in self._configs:
            self._configs[guild_id] = GuildConfig(guild_id=guild_id)
        return self._configs[guild_id]

    def set(self, config: GuildConfig) -> None:
        """Save a guild config and persist to disk."""
        self._configs[config.guild_id] = config
        self._save()
        log.info("Guild config saved for guild %s", config.guild_id)

    def reset(self, guild_id: int) -> None:
        """Reset a guild to default config."""
        self._configs[guild_id] = GuildConfig(guild_id=guild_id)
        self._save()
        log.info("Guild config reset for guild %s", guild_id)

    def is_channel_allowed(self, guild_id: int, channel_id: int) -> bool:
        """Returns True if the channel is allowed (or no restriction is set)."""
        cfg = self.get(guild_id)
        if not cfg.allowed_channel_ids:
            return True
        return channel_id in cfg.allowed_channel_ids

    def is_pingbomb_enabled(self, guild_id: int) -> bool:
        return self.get(guild_id).pingbomb_enabled

    def all_configs(self) -> list[GuildConfig]:
        return list(self._configs.values())


# Module-level singleton
guild_config_manager = GuildConfigManager()
