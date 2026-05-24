"""Usage statistics command."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from util.discord_ui import AXIOM_OPS_FOOTER, make_embed

log = logging.getLogger("axiom.cogs.stats")


class StatsCog(commands.Cog, name="Stats"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="stats",
        description="View Axiom usage statistics for this server.",
    )
    @app_commands.describe(
        user="View stats for a specific user. Leave empty for server stats."
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
            data = db.get_user_stats(interaction.guild_id, user.id)
            embed = make_embed(
                "Usage Profile",
                f"{user.display_name} activity in this server.",
                footer=AXIOM_OPS_FOOTER,
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Commands", value=f"**{data['total_uses']}**", inline=True)
            embed.add_field(name="Pings", value=f"**{data['total_pings'] or 0}**", inline=True)
            embed.add_field(
                name="Last Active",
                value=f"<t:{int(data['last_used'])}:R>" if data["last_used"] else "No recorded activity.",
                inline=True,
            )
        else:
            data = db.get_guild_stats(interaction.guild_id)
            embed = make_embed(
                "Server Usage",
                f"{interaction.guild.name} command and ping activity.",
                footer=AXIOM_OPS_FOOTER,
            )
            embed.add_field(name="Commands", value=f"**{data['total_uses']}**", inline=True)
            embed.add_field(name="Pings", value=f"**{data['total_pings']}**", inline=True)
            embed.add_field(name="Unique Users", value=f"**{data['unique_users']}**", inline=True)

            if data["top_users"]:
                top_users = "\n".join(
                    f"{index + 1}. <@{uid}> - **{total}** ping(s)"
                    for index, (uid, total) in enumerate(data["top_users"])
                )
                embed.add_field(name="Top Pingers", value=top_users, inline=False)

            if data["top_commands"]:
                top_commands = "\n".join(
                    f"`/{cmd}` - **{uses}** use(s)"
                    for cmd, uses in data["top_commands"]
                )
                embed.add_field(name="Most Used Commands", value=top_commands, inline=False)

            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
