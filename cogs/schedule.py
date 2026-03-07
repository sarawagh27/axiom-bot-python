"""
cogs/schedule.py — /schedule_pingbomb command.
Schedule a pingbomb to fire after a delay. Everyone can use it.
Admins can cancel any scheduled bomb with /schedule_cancel.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.session_manager import session_manager
from core.cooldown_manager import cooldown_manager
from core.pingbomb_engine import PingbombEngine
from core.guild_config import guild_config_manager
from util.permissions import is_admin
from util.time_utils import parse_duration, format_duration

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

    # ------------------------------------------------------------------
    # /schedule_pingbomb
    # ------------------------------------------------------------------

    @app_commands.command(
        name="schedule_pingbomb",
        description="Schedule a pingbomb to fire after a delay.",
    )
    @app_commands.describe(
        target="The member to pingbomb",
        delay="When to fire e.g. 10s, 5m, 1h",
        count="Number of pings (1–50)",
        interval="Seconds between pings (1–60)",
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

        # Guild check
        guild_cfg = guild_config_manager.get(guild_id)
        if not guild_cfg.pingbomb_enabled:
            await interaction.response.send_message(
                "❌ Axiom commands are disabled on this server.", ephemeral=True
            )
            return

        if target.id == user_id:
            await interaction.response.send_message(
                "You can't schedule a pingbomb on yourself.", ephemeral=True
            )
            return
        if target.bot:
            await interaction.response.send_message(
                "You can't pingbomb a bot.", ephemeral=True
            )
            return

        # Parse delay
        seconds = parse_duration(delay)
        if seconds is None or seconds < 5:
            await interaction.response.send_message(
                "❌ Invalid delay. Use formats like `30s`, `5m`, `1h`. Minimum is 5 seconds.",
                ephemeral=True,
            )
            return
        if seconds > 86400:  # 24h max
            await interaction.response.send_message(
                "❌ Maximum schedule delay is 24 hours.", ephemeral=True
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

        task = asyncio.create_task(
            self._run_job(job),
            name=f"schedule-{job_id}",
        )
        job.task = task
        self._jobs[job_id] = job

        embed = discord.Embed(
            title="⏰ Pingbomb Scheduled",
            description=(
                f"Pingbomb on {target.mention} scheduled to fire in **{format_duration(seconds)}**.\n"
                f"**{count}** pings • every **{interval}s**\n"
                f"{'👤 Anonymous' if anonymous else ''}\n\n"
                f"Job ID: `{job_id}` *(admins can cancel with `/schedule_cancel`)*"
            ),
            colour=discord.Colour.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log.info("Scheduled job %s: guild=%s user=%s target=%s delay=%ss",
                 job_id, guild_id, user_id, target.id, seconds)

    # ------------------------------------------------------------------
    # /schedule_cancel — admin only
    # ------------------------------------------------------------------

    @app_commands.command(
        name="schedule_cancel",
        description="[Admin] Cancel a scheduled pingbomb by job ID.",
    )
    @app_commands.describe(job_id="The job ID shown when the bomb was scheduled")
    @app_commands.guild_only()
    @is_admin()
    async def schedule_cancel(
        self, interaction: discord.Interaction, job_id: str
    ) -> None:
        job = self._jobs.get(job_id)

        if job is None or job.guild_id != interaction.guild_id:
            await interaction.response.send_message(
                f"❌ Job `{job_id}` not found or already fired.", ephemeral=True
            )
            return

        job.cancelled = True
        if job.task and not job.task.done():
            job.task.cancel()
        self._jobs.pop(job_id, None)

        await interaction.response.send_message(
            f"✅ Scheduled job `{job_id}` cancelled.", ephemeral=True
        )
        log.info("Job %s cancelled by admin %s", job_id, interaction.user.id)

    # ------------------------------------------------------------------
    # /schedule_list — see pending jobs
    # ------------------------------------------------------------------

    @app_commands.command(
        name="schedule_list",
        description="List your pending scheduled pingbombs.",
    )
    @app_commands.guild_only()
    async def schedule_list(self, interaction: discord.Interaction) -> None:
        is_admin_user = interaction.user.guild_permissions.administrator

        if is_admin_user:
            jobs = [j for j in self._jobs.values() if j.guild_id == interaction.guild_id]
        else:
            jobs = [j for j in self._jobs.values()
                    if j.guild_id == interaction.guild_id and j.user_id == interaction.user.id]

        if not jobs:
            await interaction.response.send_message(
                "No pending scheduled jobs.", ephemeral=True
            )
            return

        embed = discord.Embed(title="⏰ Scheduled Pingbombs", colour=discord.Colour.blurple())
        now = time.monotonic()
        for job in jobs:
            remaining = max(0, job.fire_at - now)
            embed.add_field(
                name=f"Job `{job.job_id}`",
                value=(
                    f"Target: <@{job.target_id}>\n"
                    f"Fires in: **{format_duration(remaining)}**\n"
                    f"Pings: {job.count} × {job.interval}s"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Internal job runner
    # ------------------------------------------------------------------

    async def _run_job(self, job: ScheduledJob) -> None:
        try:
            delay = job.fire_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

            if job.cancelled:
                return

            # Check if target is still in server
            guild = self.bot.get_guild(job.guild_id)
            if guild is None:
                return
            target = guild.get_member(job.target_id)
            if target is None:
                return

            # Check for existing session
            if session_manager.has_active(job.guild_id, job.user_id):
                log.warning("Scheduled job %s skipped — user already has active session", job.job_id)
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
