"""
ui/pingbomb_view.py — discord.ui.View with Stop / Pause / Resume buttons.
Buttons mutate the session state directly; the engine's loop reacts on next tick.
"""

from __future__ import annotations

import logging

import discord

from core.session_model import Session, SessionState
from core.session_manager import session_manager
from services.audit_service import audit_service

log = logging.getLogger("axiom.ui.pingbomb_view")


class PingbombView(discord.ui.View):
    """
    Control panel for a live pingbomb session.

    Parameters
    ----------
    session : Session
        The active session this view controls.
    invoker_id : int
        User who started the session (only they and admins can control it).
    """

    def __init__(self, session: Session, invoker_id: int) -> None:
        super().__init__(timeout=600)  # 10-minute button TTL
        self._session = session
        self._invoker_id = invoker_id
        self._update_button_states()

    # ------------------------------------------------------------------
    # Interaction guard
    # ------------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_invoker = interaction.user.id == self._invoker_id
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_invoker or is_admin):
            await interaction.response.send_message(
                "Only the session owner or an admin can control this pingbomb.",
                ephemeral=True,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    @discord.ui.button(label="⏸ Pause", style=discord.ButtonStyle.primary, custom_id="pb_pause")
    async def pause_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        session = self._get_live_session()
        if session is None:
            await interaction.response.send_message("Session no longer active.", ephemeral=True)
            self._disable_all()
            await interaction.message.edit(view=self)
            return

        if session.state != SessionState.RUNNING:
            await interaction.response.send_message(
                f"Session is not running (state: {session.state.name}).", ephemeral=True
            )
            return

        session.transition(SessionState.PAUSED)
        audit_service.log_event("SESSION_PAUSE", session, extra={"by": interaction.user.id})
        log.info("Session paused by %s: guild=%s user=%s", interaction.user.id,
                 session.guild_id, session.user_id)

        self._update_button_states()
        embed = self._build_status_embed(session, "⏸ Paused")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶ Resume", style=discord.ButtonStyle.success, custom_id="pb_resume")
    async def resume_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        session = self._get_live_session()
        if session is None:
            await interaction.response.send_message("Session no longer active.", ephemeral=True)
            self._disable_all()
            await interaction.message.edit(view=self)
            return

        if session.state != SessionState.PAUSED:
            await interaction.response.send_message(
                f"Session is not paused (state: {session.state.name}).", ephemeral=True
            )
            return

        session.transition(SessionState.RUNNING)
        audit_service.log_event("SESSION_RESUME", session, extra={"by": interaction.user.id})
        log.info("Session resumed by %s: guild=%s user=%s", interaction.user.id,
                 session.guild_id, session.user_id)

        self._update_button_states()
        embed = self._build_status_embed(session, "▶ Running")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, custom_id="pb_stop")
    async def stop_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        session = self._get_live_session()
        if session is None:
            await interaction.response.send_message("Session already ended.", ephemeral=True)
            self._disable_all()
            await interaction.message.edit(view=self)
            return

        # Guard: transition may fail if already stopped
        try:
            session.transition(SessionState.STOPPED)
        except ValueError:
            await interaction.response.send_message("Session is already stopped.", ephemeral=True)
            return

        if session.task and not session.task.done():
            session.task.cancel()

        audit_service.log_event("SESSION_STOP", session, extra={"by": interaction.user.id})
        log.info("Session stopped by %s: guild=%s user=%s pings=%s/%s",
                 interaction.user.id, session.guild_id, session.user_id,
                 session.pings_sent, session.count)

        self._disable_all()
        embed = self._build_status_embed(session, "⏹ Stopped")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    # ------------------------------------------------------------------
    # Timeout / cleanup
    # ------------------------------------------------------------------

    async def on_timeout(self) -> None:
        self._disable_all()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_live_session(self) -> Session | None:
        return session_manager.get(self._session.guild_id, self._session.user_id)

    def _disable_all(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    def _update_button_states(self) -> None:
        state = self._session.state
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            cid = item.custom_id
            if cid == "pb_pause":
                item.disabled = state != SessionState.RUNNING
            elif cid == "pb_resume":
                item.disabled = state != SessionState.PAUSED
            elif cid == "pb_stop":
                item.disabled = state in (SessionState.STOPPED, SessionState.COMPLETED)

    @staticmethod
    def _build_status_embed(session: Session, status: str) -> discord.Embed:
        colour_map = {
            "⏸ Paused": discord.Colour.orange(),
            "▶ Running": discord.Colour.green(),
            "⏹ Stopped": discord.Colour.red(),
        }
        embed = discord.Embed(
            title=f"💣 Pingbomb — {status}",
            colour=colour_map.get(status, discord.Colour.blurple()),
        )
        embed.add_field(name="Target", value=f"<@{session.target_id}>", inline=True)
        embed.add_field(
            name="Progress",
            value=f"{session.pings_sent} / {session.count}",
            inline=True,
        )
        embed.add_field(name="Interval", value=f"{session.interval}s", inline=True)
        return embed
