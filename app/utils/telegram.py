"""Telegram-related utilities."""
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest


async def safe_edit_message(
    query: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """Safely edit message, ignoring 'message is not modified' errors.

    Args:
        query: The callback query containing the message to edit
        text: The new message text
        reply_markup: Optional reply markup (keyboard)
        parse_mode: Message parse mode (default: HTML)

    Returns:
        True if message was edited successfully, False if it was not modified or message is None.

    Raises:
        TelegramBadRequest: For other Telegram errors (not message is not modified)
    """
    # Check if message exists
    if not query.message:
        return False

    try:
        await query.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Message content is identical, silently ignore
            return False
        # Re-raise other TelegramBadRequest errors
        raise
