"""Admin-only operational controls."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.cooldown_manager import cooldown_manager
from core.session_manager import session_manager
from services.audit_service import audit_service
from util.discord_ui import AXIOM_OPS_FOOTER, make_embed, success_text
from util.permissions import is_admin
from util.time_utils import format_duration

log = logging.getLogger("axiom.cogs.admin")


class AdminCog(commands.Cog, name="Admin"):
    """Administrative commands for server operators."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="admin_sessions",
        description="[Admin] List all active ping sessions in this guild.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def admin_sessions(self, interaction: discord.Interaction) -> None:
        sessions = [
            session for session in session_manager.active_sessions()
            if session.guild_id == interaction.guild_id
        ]

        if not sessions:
            await interaction.response.send_message("No active ping sessions in this guild.", ephemeral=True)
            return

        embed = make_embed(
            "Active Sessions",
            f"Tracking **{len(sessions)}** active session(s).",
            footer=AXIOM_OPS_FOOTER,
        )
        for session in sessions:
            embed.add_field(
                name=f"User <@{session.user_id}>",
                value=(
                    f"Target: <@{session.target_id}>\n"
                    f"Progress: **{session.pings_sent}/{session.count}**\n"
                    f"State: **{session.state.name}**\n"
                    f"Elapsed: **{format_duration(session.elapsed)}**"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin_stop_session",
        description="[Admin] Force-stop a user's active ping session.",
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
                success_text(f"Stopped session for {user.mention}."),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} has no active session.",
                ephemeral=True,
            )

    @app_commands.command(
        name="admin_stop_all",
        description="[Admin] Force-stop all active ping sessions in this guild.",
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
            success_text(f"Force-stopped **{count}** session(s)."),
            ephemeral=True,
        )

    @app_commands.command(
        name="admin_clear_cooldown",
        description="[Admin] Clear the ping session cooldown for a specific user.",
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
                success_text(f"Cooldown cleared for {user.mention}."),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} is not on cooldown.",
                ephemeral=True,
            )

    @app_commands.command(
        name="admin_clear_all_cooldowns",
        description="[Admin] Clear all ping session cooldowns in this guild.",
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
            success_text(f"Cleared **{count}** cooldown(s) in this guild."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
