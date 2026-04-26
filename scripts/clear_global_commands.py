"""
Clear Axiom's global slash commands.

Use this when Discord shows duplicate commands because both global commands and
dev-guild commands are registered for the same bot. Guild commands remain intact.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import discord
from discord import app_commands

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import CONFIG


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("axiom.scripts.clear_global_commands")


async def main() -> None:
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    try:
        await client.login(CONFIG.token)
        log.info("Logged in as %s. Clearing global slash commands...", client.user)
        tree.clear_commands(guild=None)
        synced = await tree.sync()
        log.info("Global slash command sync complete. Remaining global commands: %d", len(synced))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
