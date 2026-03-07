"""
core/pingbomb_engine.py — Pingbomb engine.
Spawns and manages asyncio tasks that drive the ping loop for each session.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from core.session_model import Session, SessionState
from core.session_manager import session_manager
from core.cooldown_manager import cooldown_manager
from core.rate_limiter import rate_limiter
from services.audit_service import audit_service

log = logging.getLogger("axiom.engine")

# How often (seconds) the paused-state poll loop checks for resume
_PAUSE_POLL_INTERVAL = 0.25


class PingbombEngine:
    """
    Orchestrates pingbomb sessions.
    Each session runs in its own asyncio Task — isolated, cancellable.
    """

    def __init__(self, bot: discord.Client) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def launch(self, session: Session, cooldown_override: int = None, anonymous: bool = False) -> None:
        """
        Transition session to RUNNING and spawn the ping loop task.
        Called by the pingbomb cog after session is created.
        """
        session._cooldown_override = cooldown_override
        session._anonymous = anonymous
        session.transition(SessionState.RUNNING)
        task = asyncio.create_task(
            self._ping_loop(session),
            name=f"pingbomb-{session.guild_id}-{session.user_id}",
        )
        session.task = task
        audit_service.log_event("SESSION_START", session)
        log.info(
            "Pingbomb launched: guild=%s user=%s target=%s count=%s interval=%.1fs",
            session.guild_id, session.user_id, session.target_id,
            session.count, session.interval,
        )

    # ------------------------------------------------------------------
    # Core ping loop
    # ------------------------------------------------------------------

    async def _ping_loop(self, session: Session) -> None:
        try:
            channel = self._bot.get_channel(session.channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(session.channel_id)

            target = channel.guild.get_member(session.target_id)
            if target is None:
                target = await channel.guild.fetch_member(session.target_id)

            while session.pings_sent < session.count:
                # ── Pause gate ──────────────────────────────────────────
                if session.state == SessionState.PAUSED:
                    await self._wait_for_resume(session)

                # ── Abort gate ──────────────────────────────────────────
                if session.state == SessionState.STOPPED:
                    break

                # ── Rate limiter ─────────────────────────────────────────
                await rate_limiter.acquire(session.guild_id, session.user_id)

                # ── Send the ping ────────────────────────────────────────
                try:
                    await channel.send(
                        f"{target.mention}",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    session.pings_sent += 1
                    audit_service.log_event("PING", session, extra={"ping_n": session.pings_sent})

                except discord.Forbidden:
                    log.warning(
                        "Missing permissions to send in channel %s — aborting session",
                        session.channel_id,
                    )
                    break

                except discord.HTTPException as exc:
                    log.error("HTTPException during ping: %s", exc)
                    # Brief back-off then retry
                    await asyncio.sleep(2.0)
                    continue

                # ── Interval sleep ───────────────────────────────────────
                if session.pings_sent < session.count:
                    await asyncio.sleep(session.interval)

            # ── Natural completion ───────────────────────────────────────
            if session.state == SessionState.RUNNING:
                session.transition(SessionState.COMPLETED)
                audit_service.log_event("SESSION_COMPLETE", session)
                log.info(
                    "Pingbomb completed: guild=%s user=%s pings=%s/%s",
                    session.guild_id, session.user_id,
                    session.pings_sent, session.count,
                )
                await self._on_complete(session, channel)

        except asyncio.CancelledError:
            log.info(
                "Pingbomb task cancelled: guild=%s user=%s pings_sent=%s",
                session.guild_id, session.user_id, session.pings_sent,
            )
            if session.state not in (SessionState.STOPPED, SessionState.COMPLETED):
                session.state = SessionState.STOPPED

        except Exception as exc:  # noqa: BLE001
            log.exception(
                "Unexpected error in ping loop (guild=%s user=%s): %s",
                session.guild_id, session.user_id, exc,
            )
            session.state = SessionState.STOPPED

        finally:
            await self._cleanup(session)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _wait_for_resume(self, session: Session) -> None:
        """Poll until the session leaves PAUSED state."""
        log.debug("Session paused: guild=%s user=%s", session.guild_id, session.user_id)
        while session.state == SessionState.PAUSED:
            await asyncio.sleep(_PAUSE_POLL_INTERVAL)
        log.debug("Session resumed: guild=%s user=%s", session.guild_id, session.user_id)

    async def _on_complete(self, session: Session, channel: discord.TextChannel) -> None:
        """Send a completion notice to the channel."""
        try:
            initiator = channel.guild.get_member(session.user_id)
            name = initiator.display_name if initiator else f"<@{session.user_id}>"
            embed = discord.Embed(
                title="✅ Pingbomb Complete",
                description=(
                    f"**{session.pings_sent}** pings sent to <@{session.target_id}>.\n"
                    f"Initiated by **{name}**."
                ),
                colour=discord.Colour.green(),
            )
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _cleanup(self, session: Session) -> None:
        """Post-session cleanup: remove from registry, start cooldown, free bucket."""
        session_manager.destroy(session.guild_id, session.user_id)
        cd = getattr(session, "_cooldown_override", None)
        cooldown_manager.start_cooldown(session.guild_id, session.user_id, duration=cd)
        rate_limiter.cleanup(session.guild_id, session.user_id)
        audit_service.log_event("SESSION_END", session)
