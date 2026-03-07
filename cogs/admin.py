"""
cogs/admin.py — Admin-only slash commands for Axiom.
Force-stop sessions, inspect state, flush cooldowns.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.session_manager import session_manager
from core.cooldown_manager import cooldown_manager
from services.audit_service import audit_service
from util.permissions import is_admin
from util.time_utils import format_duration

log = logging.getLogger("axiom.cogs.admin")


class AdminCog(commands.Cog, name="Admin"):
    """Administrative commands (requires Administrator or Manage Guild)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /admin_sessions — list all active sessions in the guild
    # ------------------------------------------------------------------

    @app_commands.command(
        name="admin_sessions",
        description="[Admin] List all active pingbomb sessions in this guild.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def admin_sessions(self, interaction: discord.Interaction) -> None:
        sessions = [
            s for s in session_manager.active_sessions()
            if s.guild_id == interaction.guild_id
        ]

        if not sessions:
            await interaction.response.send_message(
                "No active sessions in this guild.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🔍 Active Sessions ({len(sessions)})",
            colour=discord.Colour.blurple(),
        )
        for s in sessions:
            embed.add_field(
                name=f"User <@{s.user_id}>",
                value=(
                    f"→ Target: <@{s.target_id}>\n"
                    f"→ Progress: {s.pings_sent}/{s.count}\n"
                    f"→ State: {s.state.name}\n"
                    f"→ Elapsed: {format_duration(s.elapsed)}"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /admin_stop_session — force-stop one user's session
    # ------------------------------------------------------------------

    @app_commands.command(
        name="admin_stop_session",
        description="[Admin] Force-stop a user's active pingbomb session.",
    )
    @app_commands.describe(user="The member whose session to stop")
    @app_commands.guild_only()
    @is_admin()
    async def admin_stop_session(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        stopped = session_manager.stop_session(interaction.guild_id, user.id)

        audit_service.log_admin_action(
            action="FORCE_STOP_SESSION",
            admin_id=interaction.user.id,
            guild_id=interaction.guild_id,
            details={"target_user": user.id, "success": stopped},
        )

        if stopped:
            log.warning(
                "Admin %s force-stopped session for user %s in guild %s",
                interaction.user.id, user.id, interaction.guild_id,
            )
            await interaction.response.send_message(
                f"✅ Stopped session for {user.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} has no active session.", ephemeral=True
            )

    # ------------------------------------------------------------------
    # /admin_stop_all — force-stop ALL sessions in the guild
    # ------------------------------------------------------------------

    @app_commands.command(
        name="admin_stop_all",
        description="[Admin] Force-stop ALL active pingbomb sessions in this guild.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def admin_stop_all(self, interaction: discord.Interaction) -> None:
        count = session_manager.force_stop_all(interaction.guild_id)

        audit_service.log_admin_action(
            action="FORCE_STOP_ALL",
            admin_id=interaction.user.id,
            guild_id=interaction.guild_id,
            details={"sessions_stopped": count},
        )

        log.warning(
            "Admin %s force-stopped all sessions (%d) in guild %s",
            interaction.user.id, count, interaction.guild_id,
        )
        await interaction.response.send_message(
            f"✅ Force-stopped **{count}** session(s).", ephemeral=True
        )

    # ------------------------------------------------------------------
    # /admin_clear_cooldown — clear a user's cooldown
    # ------------------------------------------------------------------

    @app_commands.command(
        name="admin_clear_cooldown",
        description="[Admin] Clear the pingbomb cooldown for a specific user.",
    )
    @app_commands.describe(user="The member whose cooldown to clear")
    @app_commands.guild_only()
    @is_admin()
    async def admin_clear_cooldown(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        cleared = cooldown_manager.clear_cooldown(interaction.guild_id, user.id)

        audit_service.log_admin_action(
            action="CLEAR_COOLDOWN",
            admin_id=interaction.user.id,
            guild_id=interaction.guild_id,
            details={"target_user": user.id, "success": cleared},
        )

        if cleared:
            await interaction.response.send_message(
                f"✅ Cooldown cleared for {user.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} is not on cooldown.", ephemeral=True
            )

    # ------------------------------------------------------------------
    # /admin_clear_all_cooldowns — clear all guild cooldowns
    # ------------------------------------------------------------------

    @app_commands.command(
        name="admin_clear_all_cooldowns",
        description="[Admin] Clear all pingbomb cooldowns in this guild.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def admin_clear_all_cooldowns(self, interaction: discord.Interaction) -> None:
        count = cooldown_manager.clear_all_guild(interaction.guild_id)

        audit_service.log_admin_action(
            action="CLEAR_ALL_COOLDOWNS",
            admin_id=interaction.user.id,
            guild_id=interaction.guild_id,
            details={"cleared": count},
        )

        await interaction.response.send_message(
            f"✅ Cleared **{count}** cooldown(s) in this guild.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
