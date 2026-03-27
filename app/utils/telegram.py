"""Telegram-related utilities."""
import asyncio

from aiogram.types import CallbackQuery
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter


async def safe_edit_message(
    query: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> Message | None:
    """Safely edit message, ignoring 'message is not modified' errors.

    Args:
        query: The callback query containing the message to edit
        text: The new message text
        reply_markup: Optional reply markup (keyboard)
        parse_mode: Message parse mode (default: HTML)

    Returns:
        Updated Message object if edited successfully, None if it was not modified
        or message is None.

    Raises:
        TelegramBadRequest: For other Telegram errors (not message is not modified)
    """
    # Check if message exists
    if not query.message:
        return None

    retried_after_flood = False
    while True:
        try:
            return await query.message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramRetryAfter as e:
            if retried_after_flood:
                raise
            retried_after_flood = True
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                # Message content is identical, silently ignore
                return None
            # Re-raise other TelegramBadRequest errors
            raise
