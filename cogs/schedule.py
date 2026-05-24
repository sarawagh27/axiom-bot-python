"""
cogs/schedule.py - Scheduled controlled ping sessions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_config import guild_config_manager
from core.pingbomb_engine import PingbombEngine
from core.session_manager import session_manager
from util.discord_ui import (
    AXIOM_OPS_FOOTER,
    error_text,
    make_embed,
    status_label,
    success_text,
    watch_text,
)
from util.permissions import is_admin
from util.time_utils import format_duration, parse_duration

log = logging.getLogger("axiom.cogs.schedule")


class ScheduledJob:
    def __init__(
        self,
        job_id: str,
        guild_id: int,
        user_id: int,
        target_id: int,
        channel_id: int,
        count: int,
        interval: float,
        fire_at: float,
        anonymous: bool = False,
    ) -> None:
        self.job_id = job_id
        self.guild_id = guild_id
        self.user_id = user_id
        self.target_id = target_id
        self.channel_id = channel_id
        self.count = count
        self.interval = interval
        self.fire_at = fire_at
        self.anonymous = anonymous
        self.task: Optional[asyncio.Task] = None
        self.cancelled = False


class ScheduleCog(commands.Cog, name="Schedule"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._engine = PingbombEngine(bot)
        self._jobs: dict[str, ScheduledJob] = {}
        self._counter = 0

    def _new_job_id(self, guild_id: int) -> str:
        self._counter += 1
        return f"{guild_id}-{self._counter}"

    @app_commands.command(
        name="schedule_pingbomb",
        description="Schedule a controlled ping session.",
    )
    @app_commands.describe(
        target="The member to ping",
        delay="When to start, such as 10s, 5m, or 1h",
        count="Number of pings (1-50)",
        interval="Seconds between pings (1-60)",
        anonymous="Hide your identity (default: False)",
    )
    @app_commands.guild_only()
    async def schedule_pingbomb(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        delay: str,
        count: app_commands.Range[int, 1, 50] = 5,
        interval: app_commands.Range[float, 1.0, 60.0] = 2.0,
        anonymous: bool = False,
    ) -> None:
        guild_id = interaction.guild_id
        user_id = interaction.user.id

        guild_cfg = guild_config_manager.get(guild_id)
        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(
                error_text("Controlled ping sessions are disabled on this server."),
                ephemeral=True,
            )
            return

        if target.id == user_id:
            await interaction.response.send_message(
                error_text("Choose another member for a scheduled ping session."),
                ephemeral=True,
            )
            return
        if target.bot:
            await interaction.response.send_message(
                error_text("Scheduled ping sessions cannot target bots."),
                ephemeral=True,
            )
            return

        seconds = parse_duration(delay)
        if seconds is None or seconds < 5:
            await interaction.response.send_message(
                error_text("Use a delay like `30s`, `5m`, or `1h`. Minimum delay is 5s."),
                ephemeral=True,
            )
            return
        if seconds > 86400:
            await interaction.response.send_message(
                error_text("Maximum schedule delay is 24h."),
                ephemeral=True,
            )
            return

        fire_at = time.monotonic() + seconds
        job_id = self._new_job_id(guild_id)

        job = ScheduledJob(
            job_id=job_id,
            guild_id=guild_id,
            user_id=user_id,
            target_id=target.id,
            channel_id=interaction.channel_id,
            count=count,
            interval=interval,
            fire_at=fire_at,
            anonymous=anonymous,
        )

        task = asyncio.create_task(self._run_job(job), name=f"schedule-{job_id}")
        job.task = task
        self._jobs[job_id] = job

        embed = make_embed(
            "Session Scheduled",
            success_text(
                f"Controlled ping session for {target.mention} starts in "
                f"`{format_duration(seconds)}`."
            ),
            kind="success",
            footer=AXIOM_OPS_FOOTER,
        )
        embed.add_field(
            name="Session Plan",
            value=(
                f"Count: `{count}`\n"
                f"Interval: `{interval}s`\n"
                f"Identity: `{'private' if anonymous else 'visible'}`\n"
                f"Job ID: `{job_id}`"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info(
            "Scheduled job %s: guild=%s user=%s target=%s delay=%ss",
            job_id,
            guild_id,
            user_id,
            target.id,
            seconds,
        )

    @app_commands.command(
        name="schedule_cancel",
        description="[Admin] Cancel a scheduled ping session by job ID.",
    )
    @app_commands.describe(job_id="The job ID shown when the session was scheduled")
    @app_commands.guild_only()
    @is_admin()
    async def schedule_cancel(
        self, interaction: discord.Interaction, job_id: str
    ) -> None:
        job = self._jobs.get(job_id)

        if job is None or job.guild_id != interaction.guild_id:
            await interaction.response.send_message(
                error_text(f"Job `{job_id}` was not found or already completed."),
                ephemeral=True,
            )
            return

        job.cancelled = True
        if job.task and not job.task.done():
            job.task.cancel()
        self._jobs.pop(job_id, None)

        await interaction.response.send_message(
            success_text(f"Scheduled job `{job_id}` cancelled."),
            ephemeral=True,
        )
        log.info("Job %s cancelled by admin %s", job_id, interaction.user.id)

    @app_commands.command(
        name="schedule_list",
        description="List pending scheduled ping sessions.",
    )
    @app_commands.guild_only()
    async def schedule_list(self, interaction: discord.Interaction) -> None:
        is_admin_user = interaction.user.guild_permissions.administrator

        if is_admin_user:
            jobs = [j for j in self._jobs.values() if j.guild_id == interaction.guild_id]
        else:
            jobs = [
                j
                for j in self._jobs.values()
                if j.guild_id == interaction.guild_id and j.user_id == interaction.user.id
            ]

        if not jobs:
            await interaction.response.send_message(
                watch_text("No scheduled ping sessions are pending."),
                ephemeral=True,
            )
            return

        embed = make_embed(
            "Scheduled Sessions",
            f"{status_label('watch')} {len(jobs)} pending session(s) in the queue.",
            kind="ops",
            footer=AXIOM_OPS_FOOTER,
        )
        now = time.monotonic()
        for job in jobs:
            remaining = max(0, job.fire_at - now)
            embed.add_field(
                name=f"Job {job.job_id}",
                value=(
                    f"Target: <@{job.target_id}>\n"
                    f"Starts in: `{format_duration(remaining)}`\n"
                    f"Plan: `{job.count}` pings at `{job.interval}s` intervals"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _run_job(self, job: ScheduledJob) -> None:
        try:
            delay = job.fire_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

            if job.cancelled:
                return

            guild = self.bot.get_guild(job.guild_id)
            if guild is None:
                return
            target = guild.get_member(job.target_id)
            if target is None:
                return

            if session_manager.has_active(job.guild_id, job.user_id):
                log.warning(
                    "Scheduled job %s skipped; user already has active session",
                    job.job_id,
                )
                return

            session = session_manager.create(
                guild_id=job.guild_id,
                user_id=job.user_id,
                target_id=job.target_id,
                channel_id=job.channel_id,
                count=job.count,
                interval=job.interval,
            )

            guild_cfg = guild_config_manager.get(job.guild_id)
            await self._engine.launch(
                session,
                cooldown_override=guild_cfg.cooldown_seconds,
                anonymous=job.anonymous,
            )
            log.info("Scheduled job %s fired", job.job_id)

        except asyncio.CancelledError:
            log.info("Scheduled job %s cancelled", job.job_id)
        except Exception as exc:
            log.exception("Scheduled job %s error: %s", job.job_id, exc)
        finally:
            self._jobs.pop(job.job_id, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ScheduleCog(bot))
