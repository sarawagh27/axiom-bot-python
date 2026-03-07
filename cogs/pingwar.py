"""
cogs/pingwar.py — /pingwar command.
Two users go head to head. Bot pings them back and forth.
Whoever clicks Stop first loses. After max rounds it's a draw.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from util.permissions import bot_has_permissions

log = logging.getLogger("axiom.cogs.pingwar")

_MAX_ROUNDS = 20
_PING_INTERVAL = 2.0  # seconds between each volley


class PingWarView(discord.ui.View):
    """Stop button shown to both players during the war."""

    def __init__(self, player1: discord.Member, player2: discord.Member) -> None:
        super().__init__(timeout=300)
        self.player1 = player1
        self.player2 = player2
        self.loser: discord.Member | None = None
        self._stopped = asyncio.Event()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await interaction.response.send_message(
                "You're not part of this ping war!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🏳️ Surrender", style=discord.ButtonStyle.danger)
    async def surrender(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.loser = interaction.user
        button.disabled = True
        await interaction.response.edit_message(view=self)
        self._stopped.set()
        self.stop()

    async def wait_for_stop(self) -> bool:
        """Returns True if someone surrendered, False if timed out."""
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=300)
            return True
        except asyncio.TimeoutError:
            return False


class PingWarCog(commands.Cog, name="PingWar"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Track active wars per guild to prevent duplicates
        self._active: set[int] = set()

    @app_commands.command(
        name="pingwar",
        description="Challenge someone to a ping war — whoever surrenders first loses!",
    )
    @app_commands.describe(
        opponent="The member to challenge",
        rounds=f"Max rounds before draw (1–{_MAX_ROUNDS}, default 10)",
    )
    @app_commands.guild_only()
    @bot_has_permissions(send_messages=True, manage_messages=True)
    async def pingwar(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        rounds: app_commands.Range[int, 1, 20] = 10,
    ) -> None:
        guild_id = interaction.guild_id
        challenger = interaction.user

        # Guild feature check
        if not guild_config_manager.get(guild_id).pingbomb_enabled:
            await interaction.response.send_message(
                "❌ Axiom commands are disabled on this server.", ephemeral=True
            )
            return

        # Guards
        if opponent.id == challenger.id:
            await interaction.response.send_message(
                "You can't start a ping war with yourself.", ephemeral=True
            )
            return
        if opponent.bot:
            await interaction.response.send_message(
                "You can't ping war a bot.", ephemeral=True
            )
            return
        if guild_id in self._active:
            await interaction.response.send_message(
                "There's already an active ping war in this server. Wait for it to finish.",
                ephemeral=True,
            )
            return

        # Send challenge embed
        challenge_embed = discord.Embed(
            title="⚔️ Ping War Challenge!",
            description=(
                f"{challenger.mention} has challenged {opponent.mention} to a **Ping War!**\n\n"
                f"**{rounds} rounds** • Whoever surrenders first **loses**.\n\n"
                f"{opponent.mention} — do you accept? *(Auto-starts in 15s)*"
            ),
            colour=discord.Colour.red(),
        )

        # Accept/Decline view for opponent
        accept_view = _AcceptView(challenger, opponent)
        await interaction.response.send_message(embed=challenge_embed, view=accept_view)

        accepted = await accept_view.wait_result()

        if accepted is False:
            decline_embed = discord.Embed(
                description=f"{opponent.mention} declined the ping war. 🐔",
                colour=discord.Colour.orange(),
            )
            await interaction.edit_original_response(embed=decline_embed, view=None)
            return

        # Start the war
        self._active.add(guild_id)
        channel = interaction.channel

        war_view = PingWarView(challenger, opponent)
        war_embed = discord.Embed(
            title="⚔️ PING WAR STARTED",
            description=(
                f"{challenger.mention} **VS** {opponent.mention}\n\n"
                f"**{rounds} rounds** • First to surrender loses!\n\n"
                f"Click **🏳️ Surrender** to tap out."
            ),
            colour=discord.Colour.red(),
        )
        await interaction.edit_original_response(embed=war_embed, view=war_view)

        try:
            players = [challenger, opponent]
            current = 0

            for round_num in range(1, rounds + 1):
                # Check if someone already surrendered
                if war_view._stopped.is_set():
                    break

                target = players[current % 2]
                try:
                    msg = await channel.send(
                        target.mention,
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    await asyncio.sleep(0.1)
                    await msg.delete()
                except discord.HTTPException:
                    pass

                current += 1

                # Wait for interval or surrender
                try:
                    await asyncio.wait_for(
                        asyncio.shield(war_view._stopped.wait()),
                        timeout=_PING_INTERVAL,
                    )
                    break  # Someone surrendered during wait
                except asyncio.TimeoutError:
                    pass

            # Determine result
            if war_view.loser:
                winner = opponent if war_view.loser.id == challenger.id else challenger
                result_embed = discord.Embed(
                    title="⚔️ Ping War Over!",
                    description=(
                        f"🏆 {winner.mention} **wins!**\n"
                        f"🏳️ {war_view.loser.mention} surrendered after **{current}** round(s)."
                    ),
                    colour=discord.Colour.gold(),
                )
            else:
                result_embed = discord.Embed(
                    title="⚔️ Ping War — Draw!",
                    description=(
                        f"{challenger.mention} and {opponent.mention} both survived "
                        f"**{rounds}** rounds. It's a **draw!** 🤝"
                    ),
                    colour=discord.Colour.blurple(),
                )

            await interaction.edit_original_response(embed=result_embed, view=None)
            log.info("Ping war ended: guild=%s challenger=%s opponent=%s rounds=%s",
                     guild_id, challenger.id, opponent.id, current)

        finally:
            self._active.discard(guild_id)


class _AcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member) -> None:
        super().__init__(timeout=15)
        self.challenger = challenger
        self.opponent = opponent
        self._result: bool | None = None
        self._event = asyncio.Event()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "Only the challenged player can accept or decline.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._result = True
        self._event.set()
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._result = False
        self._event.set()
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self._result = True  # Auto-accept after 15s
        self._event.set()

    async def wait_result(self) -> bool | None:
        await self._event.wait()
        return self._result


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingWarCog(bot))
