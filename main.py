"""
main.py — Axiom bot entry point.
Initialises logging, database, loads config, boots the bot.
"""

import asyncio
import logging
import logging.handlers
import os
import sys

from aiohttp import web

from config import CONFIG
from bot.client import AxiomBot
from core.database import db


async def health_check(request):
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.getLogger("axiom.main").info(f"Web server started on port {port}")


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

    await start_web_server()

    # Connect database
    db.connect()
    log.info("Database ready.")

    retry_delay = 60
    max_delay = 300

    while True:
        try:
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
        db.close()
