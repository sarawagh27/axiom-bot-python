"""
main.py — Axiom bot entry point.
Initialises logging, loads config, boots the bot.
"""

import asyncio
import logging
import logging.handlers
import os
import sys

from config import CONFIG
from bot.client import AxiomBot


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — runtime log
    file_handler = logging.handlers.RotatingFileHandler(
        filename="logs/axiom.log",
        maxBytes=CONFIG.log_max_bytes,
        backupCount=CONFIG.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, CONFIG.log_level.upper(), logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Quieten noisy discord.py internals slightly
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    log = logging.getLogger("axiom.main")
    log.info("Axiom starting up...")

    async with AxiomBot() as bot:
        await bot.start(CONFIG.token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
