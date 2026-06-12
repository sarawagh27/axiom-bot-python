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

    def __init__(self, session: Session, invoker_id: int, alert_id: int) -> None:
        super().__init__(timeout=600)  # 10-minute button TTL
        self._session = session
        self._invoker_id = invoker_id
        self._alert_id = alert_id
        self._update_button_states()

    # ------------------------------------------------------------------
    # Interaction guard
    # ------------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = (interaction.data or {}).get("custom_id")
        if custom_id == "pb_ack":
            return True

        is_invoker = interaction.user.id == self._invoker_id
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_invoker or is_admin):
            await interaction.response.send_message(
                "Only the session owner or an admin can control this pingbomb.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Acknowledge", style=discord.ButtonStyle.success, custom_id="pb_ack")
    async def acknowledge_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        from core.database import db

        result = db.acknowledge_pingbomb_alert(self._alert_id, interaction.user.id)
        if result == "not_recipient":
            await interaction.response.send_message(
                "You are not listed as a recipient for this alert.",
                ephemeral=True,
            )
            return
        if result == "already_acknowledged":
            await interaction.response.send_message("You already acknowledged this alert.", ephemeral=True)
            return

        await interaction.response.send_message("Acknowledged.", ephemeral=True)
        summary = db.get_pingbomb_ack_summary(self._alert_id)
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            self.apply_acknowledgement_field(embed, summary)
            await interaction.message.edit(embed=embed, view=self)

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

        if session.state not in (SessionState.RUNNING, SessionState.PENDING):
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
        self._apply_current_acknowledgement_field(embed)
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
        self._apply_current_acknowledgement_field(embed)
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
        self._apply_current_acknowledgement_field(embed)
        await interaction.response.edit_message(embed=embed, view=self)

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
                item.disabled = item.custom_id != "pb_ack"

    def _update_button_states(self) -> None:
        # Always use the live session state from session_manager
        live = session_manager.get(self._session.guild_id, self._session.user_id)
        state = live.state if live else self._session.state
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            cid = item.custom_id
            if cid == "pb_ack":
                item.disabled = False
                continue
            if cid == "pb_pause":
                # Enable pause when RUNNING or PENDING (engine may not have started yet)
                item.disabled = state not in (SessionState.RUNNING, SessionState.PENDING)
            elif cid == "pb_resume":
                item.disabled = state != SessionState.PAUSED
            elif cid == "pb_stop":
                item.disabled = state in (SessionState.STOPPED, SessionState.COMPLETED)

    def _apply_current_acknowledgement_field(self, embed: discord.Embed) -> None:
        from core.database import db

        self.apply_acknowledgement_field(embed, db.get_pingbomb_ack_summary(self._alert_id))

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

    @staticmethod
    def acknowledgement_text(summary: dict[str, int]) -> str:
        return f"**{summary['acknowledged']} / {summary['total_recipients']}** acknowledged"

    @classmethod
    def apply_acknowledgement_field(
        cls,
        embed: discord.Embed,
        summary: dict[str, int],
    ) -> None:
        value = cls.acknowledgement_text(summary)
        for index, field in enumerate(embed.fields):
            if field.name == "Acknowledgements":
                embed.set_field_at(index, name="Acknowledgements", value=value, inline=True)
                return
        embed.add_field(name="Acknowledgements", value=value, inline=True)
