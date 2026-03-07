"""
bot/loader.py — Discovers and loads all cogs from the cogs/ package.
"""

import importlib
import logging
import pkgutil

import discord
from discord.ext import commands

import cogs

log = logging.getLogger("axiom.loader")

_COG_PACKAGE = "cogs"


async def load_all_cogs(bot: commands.Bot) -> None:
    """Iterate cogs package and load every module as a cog extension."""
    loaded: list[str] = []
    failed: list[tuple[str, Exception]] = []

    for module_info in pkgutil.iter_modules(cogs.__path__):
        ext = f"{_COG_PACKAGE}.{module_info.name}"
        try:
            await bot.load_extension(ext)
            loaded.append(ext)
            log.debug("Loaded cog: %s", ext)
        except Exception as exc:  # noqa: BLE001
            failed.append((ext, exc))
            log.error("Failed to load cog %s: %s", ext, exc, exc_info=True)

    log.info(
        "Cog loading complete — loaded: %d, failed: %d",
        len(loaded),
        len(failed),
    )

    if failed:
        names = ", ".join(name for name, _ in failed)
        log.warning("Cogs that failed to load: %s", names)
