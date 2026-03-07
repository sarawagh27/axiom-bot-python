"""
utils/permissions.py — Permission check helpers and decorators for Axiom.
"""

from __future__ import annotations

import discord
from discord import app_commands


def is_admin():
    """
    app_commands check: user must have Administrator or Manage Guild permission.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        if interaction.user.guild_permissions.manage_guild:
            return True
        raise app_commands.MissingPermissions(["administrator"])
    return app_commands.check(predicate)


def is_moderator():
    """
    app_commands check: user must have Manage Messages or higher.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        perms = interaction.user.guild_permissions
        if any([perms.administrator, perms.manage_guild, perms.manage_messages]):
            return True
        raise app_commands.MissingPermissions(["manage_messages"])
    return app_commands.check(predicate)


def bot_has_permissions(**required: bool):
    """
    app_commands check: bot must have the specified permissions in the channel.
    Pass keyword args matching discord.Permissions field names.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        bot_member = interaction.guild.me
        channel_perms = interaction.channel.permissions_for(bot_member)
        missing = [
            perm for perm, needed in required.items()
            if needed and not getattr(channel_perms, perm, False)
        ]
        if missing:
            raise app_commands.BotMissingPermissions(missing)
        return True
    return app_commands.check(predicate)


def can_ping_target(target: discord.Member, invoker: discord.Member) -> bool:
    """
    Returns False if the invoker is trying to pingbomb someone with
    a higher top role (basic anti-abuse check).
    """
    if invoker.guild_permissions.administrator:
        return True
    return invoker.top_role < target.top_role or target.bot is False
