import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

LOGGER = logging.getLogger(__name__)

_MANAGED_PREFIXES = ("orders|", "planner|", "account|")
_ALLOWED_STALE_ACTIONS = {"back", "cancel"}


class TokenValidationMiddleware(BaseMiddleware):
    """Reject stale callback buttons for legacy non-NLP routers."""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        callback_data = event.data or ""
        if not callback_data.startswith(_MANAGED_PREFIXES):
            return await handler(event, data)

        parts = callback_data.split("|")
        if len(parts) < 3:
            return await handler(event, data)

        action = parts[1]
        if action in _ALLOWED_STALE_ACTIONS:
            return await handler(event, data)

        memory_state = data.get("memory_state")
        if memory_state is None:
            return await handler(event, data)

        chat_id = event.message.chat.id if event.message else event.from_user.id
        user_id = event.from_user.id
        state = memory_state.get(chat_id, user_id) or {}
        state_token = state.get("k")

        # no token in state -> backward compatible behavior
        if not state_token:
            return await handler(event, data)

        callback_token = parts[-1] if len(parts) >= 4 else ""
        if callback_token == state_token:
            return await handler(event, data)

        LOGGER.info(
            "Stale callback rejected: user=%s chat=%s action=%s data=%s",
            user_id,
            chat_id,
            action,
            callback_data,
        )
        await event.answer("Сессия устарела, откройте меню заново", show_alert=True)
        return None
