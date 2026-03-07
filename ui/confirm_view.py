"""
ui/confirm_view.py — Reusable two-button confirm/cancel discord.ui.View.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import discord


class ConfirmView(discord.ui.View):
    """
    Presents Confirm / Cancel buttons.
    Awaitable: `result = await view.wait_result()` → True/False/None (timeout).

    Parameters
    ----------
    invoker_id : int
        Only this user can interact with the buttons.
    timeout : float
        Seconds before the view auto-expires (default 30).
    """

    def __init__(self, invoker_id: int, timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        self._invoker_id = invoker_id
        self._result: Optional[bool] = None
        self._event = asyncio.Event()

    # ------------------------------------------------------------------
    # Interaction guard
    # ------------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "This confirmation isn't for you.", ephemeral=True
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._result = True
        self._event.set()
        self._disable_all()
        await interaction.response.edit_message(
            content="✅ Confirmed.", view=self
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._result = False
        self._event.set()
        self._disable_all()
        await interaction.response.edit_message(
            content="❌ Cancelled.", view=self
        )
        self.stop()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _disable_all(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self) -> None:
        self._result = None
        self._event.set()

    async def wait_result(self) -> Optional[bool]:
        """Wait for user input. Returns True/False/None (timeout)."""
        await self._event.wait()
        return self._result
