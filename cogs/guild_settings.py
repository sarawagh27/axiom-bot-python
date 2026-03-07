"""
cogs/guild_settings.py — Per-guild configuration slash commands.
All commands require Administrator or Manage Guild permission.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import CONFIG
from core.guild_config import guild_config_manager, GuildConfig
from services.audit_service import audit_service
from util.permissions import is_admin

log = logging.getLogger("axiom.cogs.guild_settings")


def _settings_embed(cfg: GuildConfig, guild: discord.Guild) -> discord.Embed:
    """Build a formatted embed showing the current guild config."""
    embed = discord.Embed(
        title=f"⚙️ Axiom Settings — {guild.name}",
        colour=discord.Colour.blurple(),
    )

    embed.add_field(
        name="💣 Pingbomb",
        value=(
            f"**Enabled:** {'✅ Yes' if cfg.pingbomb_enabled else '❌ No'}\n"
            f"**Max Pings:** {cfg.max_count}\n"
            f"**Min Interval:** {cfg.min_interval}s\n"
            f"**Max Interval:** {cfg.max_interval}s\n"
            f"**Cooldown:** {cfg.cooldown_seconds}s"
        ),
        inline=False,
    )

    if cfg.allowed_channel_ids:
        channels = ", ".join(f"<#{cid}>" for cid in cfg.allowed_channel_ids)
    else:
        channels = "All channels *(no restriction)*"

    embed.add_field(name="📢 Allowed Channels", value=channels, inline=False)
    embed.set_footer(text=f"Guild ID: {cfg.guild_id} • Use /settings_reset to restore defaults")
    return embed


class GuildSettingsCog(commands.Cog, name="Settings"):
    """Per-guild configuration commands for server admins."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /settings — view current config
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # /settings_set_max_count
    # ------------------------------------------------------------------

    @app_commands.command(
        name="settings_set_max_count",
        description="[Admin] Set the maximum number of pings allowed per pingbomb.",
    )
    @app_commands.describe(value=f"Max pings (1–{CONFIG.pingbomb_max_count})")
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
            "SET_MAX_COUNT", interaction.user.id, interaction.guild_id,
            {"old": old, "new": value},
        )

        embed = discord.Embed(
            title="✅ Setting Updated",
            description=f"**Max ping count** set to **{value}** (was {old})",
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /settings_set_cooldown
    # ------------------------------------------------------------------

    @app_commands.command(
        name="settings_set_cooldown",
        description="[Admin] Set the cooldown duration after a pingbomb session.",
    )
    @app_commands.describe(seconds="Cooldown in seconds (10–3600)")
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
            "SET_COOLDOWN", interaction.user.id, interaction.guild_id,
            {"old": old, "new": seconds},
        )

        embed = discord.Embed(
            title="✅ Setting Updated",
            description=f"**Cooldown** set to **{seconds}s** (was {old}s)",
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /settings_set_min_interval
    # ------------------------------------------------------------------

    @app_commands.command(
        name="settings_set_min_interval",
        description="[Admin] Set the minimum allowed interval between pings.",
    )
    @app_commands.describe(seconds="Minimum interval in seconds (1.0–30.0)")
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

        embed = discord.Embed(
            title="✅ Setting Updated",
            description=f"**Min interval** set to **{seconds}s** (was {old}s)",
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /settings_toggle_pingbomb
    # ------------------------------------------------------------------

    @app_commands.command(
        name="settings_toggle_pingbomb",
        description="[Admin] Enable or disable the pingbomb command for this server.",
    )
    @app_commands.guild_only()
    @is_admin()
    async def settings_toggle_pingbomb(self, interaction: discord.Interaction) -> None:
        cfg = guild_config_manager.get(interaction.guild_id)
        cfg.pingbomb_enabled = not cfg.pingbomb_enabled
        guild_config_manager.set(cfg)

        state = "✅ Enabled" if cfg.pingbomb_enabled else "❌ Disabled"

        audit_service.log_admin_action(
            "TOGGLE_PINGBOMB", interaction.user.id, interaction.guild_id,
            {"enabled": cfg.pingbomb_enabled},
        )

        embed = discord.Embed(
            title="✅ Setting Updated",
            description=f"**Pingbomb** is now **{state}** for this server.",
            colour=discord.Colour.green() if cfg.pingbomb_enabled else discord.Colour.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /settings_add_channel — restrict to specific channels
    # ------------------------------------------------------------------

    @app_commands.command(
        name="settings_add_channel",
        description="[Admin] Restrict pingbomb to a specific channel.",
    )
    @app_commands.describe(channel="The channel to allow pingbomb in")
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
                f"{channel.mention} is already in the allowed list.", ephemeral=True
            )
            return

        cfg.allowed_channel_ids.append(channel.id)
        guild_config_manager.set(cfg)

        embed = discord.Embed(
            title="✅ Channel Added",
            description=f"{channel.mention} added to allowed channels.\n\n"
                        f"Pingbomb can now only be used in: "
                        f"{', '.join(f'<#{c}>' for c in cfg.allowed_channel_ids)}",
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /settings_remove_channel
    # ------------------------------------------------------------------

    @app_commands.command(
        name="settings_remove_channel",
        description="[Admin] Remove a channel restriction for pingbomb.",
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
                f"{channel.mention} is not in the allowed list.", ephemeral=True
            )
            return

        cfg.allowed_channel_ids.remove(channel.id)
        guild_config_manager.set(cfg)

        if cfg.allowed_channel_ids:
            remaining = ", ".join(f"<#{c}>" for c in cfg.allowed_channel_ids)
            msg = f"{channel.mention} removed.\nAllowed channels: {remaining}"
        else:
            msg = f"{channel.mention} removed.\nNo restrictions — pingbomb allowed in **all channels**."

        embed = discord.Embed(
            title="✅ Channel Removed",
            description=msg,
            colour=discord.Colour.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /settings_reset — restore all defaults
    # ------------------------------------------------------------------

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
        embed.title = "🔄 Settings Reset to Defaults"
        embed.colour = discord.Colour.orange()
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildSettingsCog(bot))
