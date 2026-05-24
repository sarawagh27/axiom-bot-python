"""
cogs/guild_settings.py - Per-guild configuration slash commands.
All commands require Administrator or Manage Guild permission.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import CONFIG
from core.guild_config import GuildConfig, guild_config_manager
from services.audit_service import audit_service
from util.discord_ui import (
    AXIOM_OPS_FOOTER,
    error_text,
    make_embed,
    status_label,
    success_text,
    watch_text,
)
from util.permissions import is_admin

log = logging.getLogger("axiom.cogs.guild_settings")


def _settings_embed(cfg: GuildConfig, guild: discord.Guild) -> discord.Embed:
    """Build a formatted embed showing the current guild config."""
    embed = make_embed(
        "Server Controls",
        f"Operational controls for **{guild.name}**.",
        kind="ops",
        footer="Use /settings_reset to restore defaults",
    )

    embed.add_field(
        name="Ping Session Policy",
        value=(
            f"Status: {status_label('success' if cfg.pingbomb_enabled else 'error')}\n"
            f"Max count: `{cfg.max_count}`\n"
            f"Interval window: `{cfg.min_interval}s` - `{cfg.max_interval}s`\n"
            f"Cooldown: `{cfg.cooldown_seconds}s`"
        ),
        inline=False,
    )

    if cfg.allowed_channel_ids:
        channels = ", ".join(f"<#{cid}>" for cid in cfg.allowed_channel_ids)
    else:
        channels = "All channels. No channel restriction is active."

    embed.add_field(name="Allowed Channels", value=channels, inline=False)
    return embed


class GuildSettingsCog(commands.Cog, name="Settings"):
    """Per-guild configuration commands for server admins."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="settings",
        description="View Axiom's current settings for this server.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def settings(self, interaction: discord.Interaction) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)
        embed = _settings_embed(cfg, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_set_max_count",
        description="[Admin] Set the maximum number of pings allowed per ping session.",
    )
    @app_commands.describe(value=f"Max pings (1-{CONFIG.pingbomb_max_count})")
    @app_commands.guild_only()
    @is_admin()
    async def settings_set_max_count(
        self,
        interaction: discord.Interaction,
        value: app_commands.Range[int, 1, 50],
    ) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)
        old = cfg.max_count
        cfg.max_count = value
        guild_config_manager.set(cfg)

        audit_service.log_admin_action(
            "SET_MAX_COUNT",
            interaction.user.id,
            interaction.guild_id,
            {"old": old, "new": value},
        )

        embed = make_embed(
            "Setting Updated",
            success_text(f"Max ping count set to `{value}`. Previous value: `{old}`."),
            kind="success",
            footer=AXIOM_OPS_FOOTER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_set_cooldown",
        description="[Admin] Set the cooldown duration after a ping session.",
    )
    @app_commands.describe(seconds="Cooldown in seconds (10-3600)")
    @app_commands.guild_only()
    @is_admin()
    async def settings_set_cooldown(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 10, 3600],
    ) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)
        old = cfg.cooldown_seconds
        cfg.cooldown_seconds = seconds
        guild_config_manager.set(cfg)

        audit_service.log_admin_action(
            "SET_COOLDOWN",
            interaction.user.id,
            interaction.guild_id,
            {"old": old, "new": seconds},
        )

        embed = make_embed(
            "Setting Updated",
            success_text(f"Cooldown set to `{seconds}s`. Previous value: `{old}s`."),
            kind="success",
            footer=AXIOM_OPS_FOOTER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_set_min_interval",
        description="[Admin] Set the minimum allowed interval between pings.",
    )
    @app_commands.describe(seconds="Minimum interval in seconds (1.0-30.0)")
    @app_commands.guild_only()
    @is_admin()
    async def settings_set_min_interval(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[float, 1.0, 30.0],
    ) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)
        old = cfg.min_interval
        cfg.min_interval = seconds
        guild_config_manager.set(cfg)

        embed = make_embed(
            "Setting Updated",
            success_text(f"Minimum interval set to `{seconds}s`. Previous value: `{old}s`."),
            kind="success",
            footer=AXIOM_OPS_FOOTER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_toggle_pingbomb",
        description="[Admin] Enable or disable controlled ping sessions for this server.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def settings_toggle_pingbomb(self, interaction: discord.Interaction) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)
        cfg.pingbomb_enabled = not cfg.pingbomb_enabled
        guild_config_manager.set(cfg)

        state = "enabled" if cfg.pingbomb_enabled else "disabled"

        audit_service.log_admin_action(
            "TOGGLE_PINGBOMB",
            interaction.user.id,
            interaction.guild_id,
            {"enabled": cfg.pingbomb_enabled},
        )

        embed = make_embed(
            "Setting Updated",
            success_text(f"Controlled ping sessions are now {state} for this server."),
            kind="success" if cfg.pingbomb_enabled else "warning",
            footer=AXIOM_OPS_FOOTER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_add_channel",
        description="[Admin] Restrict controlled ping sessions to a specific channel.",
    )
    @app_commands.describe(channel="The channel to allow controlled ping sessions in")
    @app_commands.guild_only()
    @is_admin()
    async def settings_add_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)

        if channel.id in cfg.allowed_channel_ids:
            await interaction.response.send_message(
                watch_text(f"{channel.mention} is already allowed."),
                ephemeral=True,
            )
            return

        cfg.allowed_channel_ids.append(channel.id)
        guild_config_manager.set(cfg)

        embed = make_embed(
            "Channel Added",
            success_text(
                f"{channel.mention} added. Controlled ping sessions are now limited to "
                f"{', '.join(f'<#{c}>' for c in cfg.allowed_channel_ids)}."
            ),
            kind="success",
            footer=AXIOM_OPS_FOOTER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_remove_channel",
        description="[Admin] Remove a channel restriction for controlled ping sessions.",
    )
    @app_commands.describe(channel="The channel to remove from the allowed list")
    @app_commands.guild_only()
    @is_admin()
    async def settings_remove_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)

        if channel.id not in cfg.allowed_channel_ids:
            await interaction.response.send_message(
                error_text(f"{channel.mention} is not currently restricted."),
                ephemeral=True,
            )
            return

        cfg.allowed_channel_ids.remove(channel.id)
        guild_config_manager.set(cfg)

        if cfg.allowed_channel_ids:
            remaining = ", ".join(f"<#{c}>" for c in cfg.allowed_channel_ids)
            msg = f"{channel.mention} removed. Remaining allowed channels: {remaining}."
        else:
            msg = (
                f"{channel.mention} removed. No channel restriction is active; "
                "controlled ping sessions are available in all channels."
            )

        embed = make_embed(
            "Channel Removed",
            success_text(msg),
            kind="warning",
            footer=AXIOM_OPS_FOOTER,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="settings_reset",
        description="[Admin] Reset all Axiom settings for this server to defaults.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def settings_reset(self, interaction: discord.Interaction) -> None:
        guild_config_manager.reset(interaction.guild_id)

        audit_service.log_admin_action(
            "SETTINGS_RESET", interaction.user.id, interaction.guild_id
        )

        cfg = guild_config_manager.get(interaction.guild_id)
        embed = _settings_embed(cfg, interaction.guild)
        embed.title = "Settings Reset"
        embed.description = success_text("Server controls were restored to defaults.")
        embed.colour = discord.Colour.gold()
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildSettingsCog(bot))
