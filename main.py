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
from keep_alive import keep_alive


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        filename="logs/axiom.log",
        maxBytes=CONFIG.log_max_bytes,
        backupCount=CONFIG.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, CONFIG.log_level.upper(), logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    log = logging.getLogger("axiom.main")
    log.info("Axiom starting up...")
    keep_alive()

    retry_delay = 60
    max_delay = 300

    while True:
        try:
            log.info(f"Waiting {retry_delay}s before connecting to Discord...")
            await asyncio.sleep(retry_delay)

            async with AxiomBot() as bot:
                await bot.start(CONFIG.token)

        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                log.warning(f"Rate limited by Discord. Waiting {retry_delay}s before retry...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)
            else:
                log.error(f"Bot crashed: {e}. Restarting in 60s...")
                retry_delay = 60
                await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
