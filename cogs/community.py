"""Phase 1 Discord-native utility, moderation, and community commands."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from services.operational_events import (
    OperationalEventSeverity,
    OperationalEventType,
    operational_event_recorder,
)
from util.discord_ui import AxiomColor, join_lines, make_embed
from util.permissions import bot_has_permissions, is_moderator
from util.time_utils import format_duration, parse_duration


POLL_EMOJIS = ("1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3")
AFK_REASON_LIMIT = 140
AFK_REPLY_COOLDOWN_SECONDS = 90
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class AfkStatus:
    reason: str | None
    since: float


def _clean_afk_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    cleaned = _WHITESPACE_RE.sub(" ", reason.strip())
    if not cleaned:
        return None
    if len(cleaned) <= AFK_REASON_LIMIT:
        return cleaned
    return f"{cleaned[: AFK_REASON_LIMIT - 1].rstrip()}..."


def _format_afk_duration(since: float, now: float | None = None) -> str:
    elapsed = max(0, int((now or time.time()) - since))
    if elapsed < 60:
        return "<1m"

    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes}m")
    return " ".join(parts[:2])


def _format_afk_set_confirmation(status: AfkStatus) -> str:
    if status.reason:
        return f"You're now AFK.\nReason: {status.reason}"
    return "You're now AFK."


def _format_afk_removed(status: AfkStatus, now: float | None = None) -> str:
    return f"Welcome back.\nAFK removed after {_format_afk_duration(status.since, now)}."


def _format_afk_mention(display_name: str, status: AfkStatus, now: float | None = None) -> str:
    duration = _format_afk_duration(status.since, now)
    line = f"{display_name} is currently away - back in {duration}."
    if status.reason:
        line = f"{line}\nReason: {status.reason}"
    return line


def _record_success(
    command: str,
    interaction: discord.Interaction,
    *,
    target: discord.abc.User | None = None,
    severity: str = OperationalEventSeverity.INFO,
    metadata: dict | None = None,
) -> None:
    from core.database import db

    if interaction.guild_id:
        db.record_usage(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            command=command,
            target_id=target.id if target else None,
        )
    operational_event_recorder.record(
        event_type=OperationalEventType.COMMAND_USED,
        source="community_cog",
        severity=severity,
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        target_id=target.id if target else None,
        command=command,
        metadata=metadata or {},
    )


def _member_is_protected(
    actor: discord.Member,
    target: discord.Member,
    guild: discord.Guild,
) -> bool:
    if target == guild.owner:
        return True
    if actor == guild.owner:
        return False
    return target.top_role >= actor.top_role


def _bot_member_is_blocked(target: discord.Member, guild: discord.Guild) -> bool:
    bot_member = guild.me
    return bot_member is not None and target.top_role >= bot_member.top_role


def _moderation_block_reason(
    actor: discord.Member,
    target: discord.Member,
    guild: discord.Guild,
) -> str | None:
    if target == actor:
        return "You cannot use this moderation action on yourself."
    if target.bot:
        return "Bot accounts are protected from this moderation action."
    if _member_is_protected(actor, target, guild):
        return "That member is protected by role hierarchy."
    if _bot_member_is_blocked(target, guild):
        return "Axiom's role is not high enough to moderate that member."
    return None


def _user_label(user: discord.abc.User) -> str:
    return f"{user.mention} (`{user.id}`)"


def _format_permissions(member: discord.Member) -> str:
    permissions = member.guild_permissions
    highlights = []
    if permissions.administrator:
        highlights.append("Administrator")
    if permissions.manage_guild:
        highlights.append("Manage Server")
    if permissions.manage_messages:
        highlights.append("Manage Messages")
    if permissions.moderate_members:
        highlights.append("Moderate Members")
    if permissions.ban_members:
        highlights.append("Ban Members")
    return ", ".join(highlights) if highlights else "Standard member"


class CommunityCog(commands.Cog, name="Community"):
    """Polished Phase 1 Discord UX commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._afk: dict[tuple[int, int], AfkStatus] = {}
        self._afk_reply_cooldowns: dict[tuple[int, int, int], float] = {}
        self._reminders: set[asyncio.Task] = set()

    @app_commands.command(name="server", description="View this server's operational profile.")
    @app_commands.guild_only()
    async def server(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None

        embed = make_embed(
            "Server Profile",
            f"{guild.name} operational snapshot",
            colour=AxiomColor.PRIMARY,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Members", value=str(guild.member_count or 0), inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Boost Tier", value=f"Tier {guild.premium_tier}", inline=True)
        embed.add_field(
            name="Operational Read",
            value="Use `/ops status` for live health, incident, and anomaly context.",
            inline=False,
        )
        _record_success("server", interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="userinfo", description="View a member's account and server profile.")
    @app_commands.describe(member="Member to inspect. Defaults to you.")
    @app_commands.guild_only()
    async def userinfo(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        member = member or interaction.user
        assert isinstance(member, discord.Member)

        embed = make_embed(
            "User Profile",
            _user_label(member),
            colour=member.colour if member.colour.value else AxiomColor.PRIMARY,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=True)
        embed.add_field(name="Permissions", value=_format_permissions(member), inline=False)
        embed.add_field(
            name="Status",
            value="Bot account" if member.bot else "Human member",
            inline=True,
        )
        _record_success("userinfo", interaction, target=member)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="avatar", description="Get a user's avatar.")
    @app_commands.describe(member="Member whose avatar you want. Defaults to you.")
    async def avatar(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        member = member or interaction.user
        embed = make_embed("Avatar", _user_label(member), colour=AxiomColor.PRIMARY)
        embed.set_image(url=member.display_avatar.url)
        embed.add_field(name="Direct Link", value=f"[Open avatar]({member.display_avatar.url})", inline=False)
        _record_success("avatar", interaction, target=member)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn", description="[Mod] Warn a member and record the action.")
    @app_commands.describe(member="Member to warn.", reason="Reason for the warning.")
    @app_commands.guild_only()
    @is_moderator()
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        block_reason = _moderation_block_reason(interaction.user, member, guild)
        if block_reason:
            await interaction.response.send_message(block_reason, ephemeral=True)
            return

        operational_event_recorder.record_admin_action(
            "warn",
            interaction.user.id,
            guild.id,
            {"target_id": member.id, "reason": reason},
        )
        _record_success("warn", interaction, target=member, metadata={"reason": reason})

        try:
            await member.send(f"You were warned in {guild.name}: {reason}")
            dm_status = "DM delivered"
        except discord.HTTPException:
            dm_status = "DM unavailable"

        embed = make_embed("Warning Issued", status="warning")
        embed.add_field(name="Member", value=_user_label(member), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Delivery", value=dm_status, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mute", description="[Mod] Timeout a member for a duration.")
    @app_commands.describe(member="Member to timeout.", duration="Duration like 10m, 1h, or 1h30m.", reason="Moderation reason.")
    @app_commands.guild_only()
    @is_moderator()
    @bot_has_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str = "No reason provided.",
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        perms = interaction.user.guild_permissions
        if not any([perms.administrator, perms.manage_guild, perms.moderate_members]):
            await interaction.response.send_message(
                "You need Moderate Members to use this command.",
                ephemeral=True,
            )
            return
        seconds = parse_duration(duration)
        if seconds is None or seconds <= 0 or seconds > 28 * 24 * 3600:
            await interaction.response.send_message(
                "Use a duration between 1s and 28d, such as `10m` or `2h`.",
                ephemeral=True,
            )
            return
        block_reason = _moderation_block_reason(interaction.user, member, guild)
        if block_reason:
            await interaction.response.send_message(block_reason, ephemeral=True)
            return

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        operational_event_recorder.record_admin_action(
            "mute",
            interaction.user.id,
            guild.id,
            {"target_id": member.id, "duration_seconds": seconds, "reason": reason},
        )
        _record_success("mute", interaction, target=member, metadata={"duration_seconds": seconds})

        embed = make_embed("Member Muted", status="warning")
        embed.add_field(name="Member", value=_user_label(member), inline=False)
        embed.add_field(name="Duration", value=format_duration(seconds), inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ban", description="[Mod] Ban a member.")
    @app_commands.describe(member="Member to ban.", reason="Moderation reason.", delete_message_days="Delete recent message history, 0-7 days.")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided.",
        delete_message_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("You need Ban Members to use this command.", ephemeral=True)
            return
        block_reason = _moderation_block_reason(interaction.user, member, guild)
        if block_reason:
            await interaction.response.send_message(block_reason, ephemeral=True)
            return

        await member.ban(reason=reason, delete_message_days=delete_message_days)
        operational_event_recorder.record_admin_action(
            "ban",
            interaction.user.id,
            guild.id,
            {"target_id": member.id, "reason": reason, "delete_message_days": delete_message_days},
        )
        _record_success("ban", interaction, target=member, severity=OperationalEventSeverity.WARNING)

        embed = make_embed("Member Banned", status="critical")
        embed.add_field(name="Member", value=_user_label(member), inline=False)
        embed.add_field(name="Message Cleanup", value=f"{delete_message_days} day(s)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="purge", description="[Mod] Delete recent messages from this channel.")
    @app_commands.describe(amount="Number of messages to delete, 1-100.", reason="Audit reason.")
    @app_commands.guild_only()
    @is_moderator()
    @bot_has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        reason: str = "No reason provided.",
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send("Purge can only run in text channels.", ephemeral=True)
            return
        deleted = await interaction.channel.purge(limit=amount, reason=reason)
        operational_event_recorder.record_admin_action(
            "purge",
            interaction.user.id,
            interaction.guild_id,
            {"channel_id": interaction.channel_id, "amount": len(deleted), "reason": reason},
        )
        _record_success("purge", interaction, metadata={"amount": len(deleted)})

        embed = make_embed("Messages Purged", status="success")
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        embed.add_field(name="Deleted", value=str(len(deleted)), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="poll", description="Create a clean poll with 2-4 choices.")
    @app_commands.describe(question="Poll question.", options="Choices separated by |, for example: Yes | No | Maybe")
    @app_commands.guild_only()
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str = "Yes | No",
    ) -> None:
        choices = [item.strip() for item in options.split("|") if item.strip()]
        if len(choices) < 2 or len(choices) > 4:
            await interaction.response.send_message("Polls need 2-4 choices separated by `|`.", ephemeral=True)
            return

        embed = make_embed("Poll", question, colour=AxiomColor.PRIMARY)
        embed.add_field(
            name="Choices",
            value=join_lines(
                f"{POLL_EMOJIS[index]} {choice}"
                for index, choice in enumerate(choices)
            ),
            inline=False,
        )
        embed.set_footer(text=f"Poll by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        for emoji in POLL_EMOJIS[:len(choices)]:
            await message.add_reaction(emoji)
        _record_success("poll", interaction, metadata={"choice_count": len(choices)})

    @app_commands.command(name="remind", description="Set a lightweight reminder.")
    @app_commands.describe(duration="When to remind you, like 10m or 2h.", note="Reminder text.")
    async def remind(
        self,
        interaction: discord.Interaction,
        duration: str,
        note: str,
    ) -> None:
        seconds = parse_duration(duration)
        if seconds is None or seconds <= 0 or seconds > 7 * 24 * 3600:
            await interaction.response.send_message(
                "Use a reminder duration between 1s and 7d, such as `15m` or `2h`.",
                ephemeral=True,
            )
            return

        due_at = int(time.time() + seconds)
        embed = make_embed("Reminder Set", status="success")
        embed.add_field(name="When", value=f"<t:{due_at}:R>", inline=True)
        embed.add_field(name="Note", value=note, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        _record_success("remind", interaction, metadata={"duration_seconds": seconds})

        task = asyncio.create_task(
            self._deliver_reminder(
                interaction.user,
                interaction.channel,
                seconds,
                note,
                due_at,
            )
        )
        self._reminders.add(task)
        task.add_done_callback(self._reminders.discard)

    async def _deliver_reminder(
        self,
        user: discord.abc.User,
        channel: discord.abc.Messageable | None,
        seconds: float,
        note: str,
        due_at: int,
    ) -> None:
        await asyncio.sleep(seconds)
        embed = make_embed("Reminder Due", note, status="watch")
        embed.add_field(name="Scheduled For", value=f"<t:{due_at}:R>", inline=True)
        try:
            await user.send(embed=embed)
        except discord.HTTPException:
            if channel:
                await channel.send(content=user.mention, embed=embed)

    @app_commands.command(name="afk", description="Set an AFK status for this server.")
    @app_commands.describe(reason="Optional short reason.")
    @app_commands.guild_only()
    async def afk(
        self,
        interaction: discord.Interaction,
        reason: str | None = None,
    ) -> None:
        status = AfkStatus(
            reason=_clean_afk_reason(reason),
            since=time.time(),
        )
        self._afk[(interaction.guild_id, interaction.user.id)] = status
        _record_success(
            "afk",
            interaction,
            metadata={"has_reason": status.reason is not None},
        )
        await interaction.response.send_message(
            _format_afk_set_confirmation(status),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return

        key = (message.guild.id, message.author.id)
        if key in self._afk:
            status = self._afk.pop(key)
            self._clear_afk_reply_cooldowns(message.guild.id, message.author.id)
            try:
                await message.channel.send(
                    _format_afk_removed(status),
                    delete_after=8,
                )
            except discord.HTTPException:
                pass

        mentioned = self._mentionable_afk_members(message)
        if not mentioned:
            return

        lines = []
        now = time.time()
        for member in mentioned[:3]:
            status = self._afk[(message.guild.id, member.id)]
            lines.append(_format_afk_mention(member.display_name, status, now))
        try:
            await message.reply("\n\n".join(lines), mention_author=False, delete_after=20)
        except discord.HTTPException:
            pass

    def _mentionable_afk_members(self, message: discord.Message) -> list[discord.Member]:
        now = time.time()
        members: list[discord.Member] = []
        for member in message.mentions:
            afk_key = (message.guild.id, member.id)
            if afk_key not in self._afk or member.id == message.author.id:
                continue
            cooldown_key = (message.guild.id, message.author.id, member.id)
            if self._afk_reply_cooldowns.get(cooldown_key, 0) > now:
                continue
            self._afk_reply_cooldowns[cooldown_key] = now + AFK_REPLY_COOLDOWN_SECONDS
            members.append(member)
        self._afk_reply_cooldowns = {
            key: expires_at
            for key, expires_at in self._afk_reply_cooldowns.items()
            if expires_at > now
        }
        return members

    def _clear_afk_reply_cooldowns(self, guild_id: int, user_id: int) -> None:
        self._afk_reply_cooldowns = {
            key: expires_at
            for key, expires_at in self._afk_reply_cooldowns.items()
            if not (key[0] == guild_id and key[2] == user_id)
        }


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommunityCog(bot))
