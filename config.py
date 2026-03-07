"""
config.py — Centralized configuration loader for Axiom.
Reads from environment variables / .env file and exposes typed constants.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"[Axiom] Required environment variable '{key}' is not set. "
            f"Copy .env.example to .env and fill in the values."
        )
    return value


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class BotConfig:
    token: str
    dev_guild_id: int | None

    # Pingbomb
    pingbomb_max_count: int
    pingbomb_min_interval: float
    pingbomb_max_interval: float
    pingbomb_cooldown_seconds: int

    # Rate limiter
    rate_limit_tokens: int
    rate_limit_refill_rate: float

    # Logging
    log_level: str
    log_max_bytes: int
    log_backup_count: int


def load_config() -> BotConfig:
    raw_guild = _optional("DEV_GUILD_ID", "")
    dev_guild_id = int(raw_guild) if raw_guild.strip() else None

    return BotConfig(
        token=_require("DISCORD_TOKEN"),
        dev_guild_id=dev_guild_id,
        pingbomb_max_count=int(_optional("PINGBOMB_MAX_COUNT", "50")),
        pingbomb_min_interval=float(_optional("PINGBOMB_MIN_INTERVAL", "1.0")),
        pingbomb_max_interval=float(_optional("PINGBOMB_MAX_INTERVAL", "60.0")),
        pingbomb_cooldown_seconds=int(_optional("PINGBOMB_COOLDOWN_SECONDS", "60")),
        rate_limit_tokens=int(_optional("RATE_LIMIT_TOKENS", "10")),
        rate_limit_refill_rate=float(_optional("RATE_LIMIT_REFILL_RATE", "1.0")),
        log_level=_optional("LOG_LEVEL", "INFO"),
        log_max_bytes=int(_optional("LOG_MAX_BYTES", str(5 * 1024 * 1024))),
        log_backup_count=int(_optional("LOG_BACKUP_COUNT", "3")),
    )


# Module-level singleton — import this everywhere
CONFIG = load_config()
