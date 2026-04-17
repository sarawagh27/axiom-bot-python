"""
cogs/stats.py — /stats command.
Shows per-guild and per-user usage statistics from SQLite.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("axiom.cogs.stats")


class StatsCog(commands.Cog, name="Stats"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="stats",
        description="View Axiom usage statistics for this server.",
    )
    @app_commands.describe(
        user="View stats for a specific user (leave empty for server stats)"
    )
    @app_commands.guild_only()
    async def stats(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
    ) -> None:
        from core.database import db

        await interaction.response.defer(ephemeral=True)

        if user:
            # Per-user stats
            data = db.get_user_stats(interaction.guild_id, user.id)

            embed = discord.Embed(
                title=f"📊 Stats — {user.display_name}",
                colour=discord.Colour.blurple(),
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(
                name="Total Commands Used",
                value=f"**{data['total_uses']}**",
                inline=True,
            )
            embed.add_field(
                name="Total Pings Sent",
                value=f"**{data['total_pings'] or 0}**",
                inline=True,
            )
            if data["last_used"]:
                embed.add_field(
                    name="Last Active",
                    value=f"<t:{int(data['last_used'])}:R>",
                    inline=True,
                )
            embed.set_footer(text=f"Server: {interaction.guild.name}")

        else:
            # Server-wide stats
            data = db.get_guild_stats(interaction.guild_id)

            embed = discord.Embed(
                title=f"📊 Server Stats — {interaction.guild.name}",
                colour=discord.Colour.blurple(),
            )
            embed.add_field(
                name="Total Commands Used",
                value=f"**{data['total_uses']}**",
                inline=True,
            )
            embed.add_field(
                name="Total Pings Fired",
                value=f"**{data['total_pings']}**",
                inline=True,
            )
            embed.add_field(
                name="Unique Users",
                value=f"**{data['unique_users']}**",
                inline=True,
            )

            # Top users
            if data["top_users"]:
                medals = ["🥇", "🥈", "🥉"]
                top_str = "\n".join(
                    f"{medals[i]} <@{uid}> — **{total}** pings"
                    for i, (uid, total) in enumerate(data["top_users"])
                )
                embed.add_field(name="🏆 Top Pingers", value=top_str, inline=False)

            # Top commands
            if data["top_commands"]:
                cmd_str = "\n".join(
                    f"`/{cmd}` — {uses} uses"
                    for cmd, uses in data["top_commands"]
                )
                embed.add_field(name="📈 Most Used Commands", value=cmd_str, inline=False)

            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
