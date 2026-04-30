"""
app/services/action_planner.py  — Hour 7

Executes the List[Action] produced by RuleEngine.
Sends bot replies, owner alerts, mechanic alerts, and creates procurement tickets.
Each action type is a separate method — easy to swap the messenger adapter.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.schemas.fleet_update import Action, FleetUpdate

logger = logging.getLogger(__name__)


class ActionPlanner:
    """
    Executes actions.  Messenger-agnostic — the send_message callable
    is injected so the same planner works with Telegram and MAX.
    """

    def __init__(self, send_message_fn=None):
        """
        send_message_fn: async callable(chat_id: str, text: str, reply_markup=None) -> None
        If None, actions are logged only (useful for testing).
        """
        self._send = send_message_fn

    async def execute_all(self, update: FleetUpdate) -> None:
        """Execute all planned actions on a processed FleetUpdate."""
        for action in update.actions:
            await self._dispatch(action, update)

        # Send the operator reply (always last)
        if update.reply_text:
            markup = self._confirmation_keyboard() if update.needs_confirmation else None
            await self._send_to(update.chat_id, update.reply_text, markup)

    async def _dispatch(self, action: Action, update: FleetUpdate) -> None:
        t = action.action_type
        if t == "reply_operator":
            await self._send_to(update.chat_id, action.message)
        elif t == "alert_owner":
            await self._alert_owner(update, action.message, action.priority)
        elif t == "alert_mechanic":
            await self._alert_mechanic(update, action.message)
        elif t == "nudge_operator":
            await self._send_to(update.chat_id, action.message)
        elif t == "create_incident":
            logger.info(f"Incident created: {action.payload} — {action.message}")
        elif t == "set_machine_status":
            logger.info(f"Machine status → {action.payload.get('status')} (machine_id={update.machine_id})")
        elif t == "create_procurement_ticket":
            logger.info(f"Procurement ticket: {action.message}")
        else:
            logger.warning(f"Unknown action type: {t}")

    async def _alert_owner(
        self, update: FleetUpdate, message: str, priority: str
    ) -> None:
        # In production: look up owner's chat_id from DB and send
        # For now: log + placeholder
        logger.info(f"[OWNER ALERT][{priority.upper()}] {message}")
        # TODO: await self._send_to(owner_chat_id, f"🔔 {message}")

    async def _alert_mechanic(self, update: FleetUpdate, message: str) -> None:
        logger.info(f"[MECHANIC ALERT] {message}")
        # TODO: await self._send_to(mechanic_chat_id, f"🔧 {message}")

    async def _send_to(
        self,
        chat_id: str,
        text:    str,
        markup:  Optional[dict] = None,
    ) -> None:
        if self._send:
            await self._send(chat_id, text, markup)
        else:
            logger.info(f"[BOT REPLY → {chat_id}] {text}")

    @staticmethod
    def _confirmation_keyboard() -> dict:
        """Inline keyboard for confirmation flow."""
        return {
            "inline_keyboard": [[
                {"text": "Верно ✓",    "callback_data": "confirm"},
                {"text": "Исправить ✗","callback_data": "correct"},
            ]]
        }


action_planner = ActionPlanner()
