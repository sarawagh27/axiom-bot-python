"""
bot/client.py — Axiom's discord.ext.commands.Bot subclass.
Handles intent setup, cog loading, and slash command tree sync.
"""

import logging

import discord
from discord.ext import commands

from config import CONFIG
from bot.loader import load_all_cogs
# error handler loaded as a cog automatically

log = logging.getLogger("axiom.client")


class AxiomBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",          # Fallback prefix (slash commands are primary)
            intents=intents,
            help_command=None,           # Slash-only; suppress default help
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Called once by discord.py after login, before on_ready."""
        await load_all_cogs(self)

        if CONFIG.dev_guild_id:
            guild = discord.Object(id=CONFIG.dev_guild_id)

            if CONFIG.clear_global_commands_on_dev_sync:
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                log.warning(
                    "Cleared global slash commands before dev guild sync. "
                    "Set CLEAR_GLOBAL_COMMANDS_ON_DEV_SYNC=false after duplicates disappear."
                )

            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to dev guild %s", CONFIG.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally")

    async def on_ready(self) -> None:
        log.info(
            "Axiom ready | logged in as %s (ID: %s) | guilds: %d",
            self.user,
            self.user.id,
            len(self.guilds),
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="/pingbomb | Axiom",
            )
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild: %s (ID: %s)", guild.name, guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        log.info("Removed from guild: %s (ID: %s)", guild.name, guild.id)
