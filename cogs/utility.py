"""
cogs/utility.py — General utility slash commands: /status, /help, /info, /ping.
"""

from __future__ import annotations

import logging
import platform
import time

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("axiom.cogs.utility")

_START_TIME = time.monotonic()


class UtilityCog(commands.Cog, name="Utility"):
    """General utility commands available to all users."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /ping — latency check
    # ------------------------------------------------------------------

    @app_commands.command(name="ping", description="Check Axiom's latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        ws_latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"WebSocket latency: **{ws_latency}ms**",
            colour=discord.Colour.green() if ws_latency < 150 else discord.Colour.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /status — bot runtime info
    # ------------------------------------------------------------------

    @app_commands.command(name="status", description="View Axiom's runtime status.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        from core.session_manager import session_manager
        from core.cooldown_manager import cooldown_manager

        uptime_s = int(time.monotonic() - _START_TIME)
        h, r = divmod(uptime_s, 3600)
        m, s = divmod(r, 60)

        active_sessions = len([
            sess for sess in session_manager.active_sessions()
            if sess.guild_id == interaction.guild_id
        ])
        active_cooldowns = len([
            (key, _) for (key, _) in cooldown_manager.all_active()
            if key[0] == interaction.guild_id
        ])

        embed = discord.Embed(title="⚙️ Axiom Status", colour=discord.Colour.blurple())
        embed.add_field(name="Uptime", value=f"{h}h {m}m {s}s", inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Active Sessions (this guild)", value=str(active_sessions), inline=True)
        embed.add_field(name="Active Cooldowns (this guild)", value=str(active_cooldowns), inline=True)
        embed.add_field(
            name="Python",
            value=f"{platform.python_version()}",
            inline=True,
        )
        embed.set_footer(text="Axiom — Pingbomb Engine")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /info — about Axiom
    # ------------------------------------------------------------------

    @app_commands.command(name="info", description="About Axiom.")
    async def info(self, interaction: discord.Interaction) -> None:
        from config import CONFIG

        embed = discord.Embed(
            title="💣 Axiom — Pingbomb Bot",
            description=(
                "Axiom is a modular Discord bot built around a production-quality "
                "pingbomb session engine with rate-limiting, cooldown management, "
                "session control, and a full audit trail."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="💣 Pingbomb",
            value=(
                "`/pingbomb` — Spam ping a user (pause/stop/anonymous)\n"
                "`/pingbomb_status` — Check your active session"
            ),
            inline=False,
        )
        embed.add_field(
            name="👻 Ghost Ping",
            value=(
                "`/ghostping` — Ghost ping one user (up to 10x)\n"
                "`/massghost` — Ghost ping up to 20 users at once (up to 20x each)"
            ),
            inline=False,
        )
        embed.add_field(
            name="⏰ Scheduled",
            value=(
                "`/schedule_pingbomb` — Schedule a pingbomb for later\n"
                "`/schedule_list` — View your pending scheduled jobs\n"
                "`/schedule_cancel` — Cancel a scheduled job (Admin)"
            ),
            inline=False,
        )
        embed.add_field(
            name="📢 Echo",
            value="`/echo` — Make the bot send a message anonymously in any channel",
            inline=False,
        )
        embed.add_field(
            name="🔧 Utility",
            value=(
                "`/ping` — Latency check\n"
                "`/status` — Bot runtime stats\n"
                "`/info` — About Axiom\n"
                "`/help` — Full command list"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Default Limits",
            value=(
                f"Max pings: **{CONFIG.pingbomb_max_count}**\n"
                f"Min interval: **{CONFIG.pingbomb_min_interval}s**\n"
                f"Cooldown: **{CONFIG.pingbomb_cooldown_seconds}s**\n"
                f"*(Admins can change these per server with `/settings`)*"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /help — command listing
    # ------------------------------------------------------------------

    @app_commands.command(name="help", description="List all available commands.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="📖 Axiom Commands", colour=discord.Colour.blurple())

        sections = {
            "💣 Pingbomb": [
                ("`/pingbomb`", "Spam ping a user — supports pause, stop & anonymous mode"),
                ("`/pingbomb_status`", "Check your current active session"),
            ],
            "👻 Ghost Ping": [
                ("`/ghostping`", "Ghost ping one user (up to 10x) — no trace left"),
                ("`/massghost`", "Ghost ping up to 20 users at once (up to 20x each)"),
            ],
            "⏰ Scheduled": [
                ("`/schedule_pingbomb`", "Schedule a pingbomb to fire after a delay e.g. 5m, 1h"),
                ("`/schedule_list`", "View your pending scheduled jobs"),
                ("`/schedule_cancel`", "Cancel a scheduled job by ID (Admin)"),
            ],
            "📢 Echo": [
                ("`/echo`", "Make the bot say something anonymously in any channel"),
            ],
            "🔧 Utility": [
                ("`/ping`", "Check bot latency"),
                ("`/status`", "View bot runtime stats"),
                ("`/info`", "About Axiom"),
                ("`/help`", "This message"),
            ],
            "⚙️ Settings (Admin)": [
                ("`/settings`", "View this server's current settings"),
                ("`/settings_set_max_count`", "Set max pings per pingbomb"),
                ("`/settings_set_cooldown`", "Set cooldown duration"),
                ("`/settings_set_min_interval`", "Set minimum ping interval"),
                ("`/settings_toggle_pingbomb`", "Enable or disable pingbomb entirely"),
                ("`/settings_add_channel`", "Restrict commands to specific channels"),
                ("`/settings_remove_channel`", "Remove a channel restriction"),
                ("`/settings_reset`", "Reset all settings to defaults"),
            ],
            "🛡️ Admin": [
                ("`/admin_sessions`", "List all active sessions in this server"),
                ("`/admin_stop_session`", "Force-stop a specific user's session"),
                ("`/admin_stop_all`", "Force-stop ALL active sessions"),
                ("`/admin_clear_cooldown`", "Clear a specific user's cooldown"),
                ("`/admin_clear_all_cooldowns`", "Clear all cooldowns in this server"),
            ],
        }

        for section, cmds in sections.items():
            value = "\n".join(f"{cmd} — {desc}" for cmd, desc in cmds)
            embed.add_field(name=section, value=value, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
