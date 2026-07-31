"""Telegram-related utilities."""
import asyncio

from aiogram.types import CallbackQuery
from aiogram.types import InaccessibleMessage, Message
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter

from app.config import Config

_MAX_NETWORK_RETRIES = 2
_NETWORK_RETRY_DELAY = 1.0
_MAX_FLOOD_RETRIES = 3


def is_owner_callback(query: CallbackQuery, config: Config) -> bool:
    """True only if the pressing user is the configured bot owner.

    These buttons are only ever sent to the owner's private chat, but
    Telegram forwards inline keyboards with working callback_data to whoever
    a message ends up with — this check makes handlers self-defending
    instead of relying solely on that delivery assumption.
    """
    return bool(config.owner_telegram_id) and bool(query.from_user) and query.from_user.id == config.owner_telegram_id


async def safe_edit_message(
    query: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> Message | None:
    if not query.message or isinstance(query.message, InaccessibleMessage):
        return None

    flood_retries = 0
    network_retries = 0
    while True:
        try:
            return await query.message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramRetryAfter as e:
            if flood_retries >= _MAX_FLOOD_RETRIES:
                raise
            flood_retries += 1
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError:
            if network_retries >= _MAX_NETWORK_RETRIES:
                raise
            network_retries += 1
            await asyncio.sleep(_NETWORK_RETRY_DELAY)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return None
            if "message to edit not found" in str(e):
                return None
            raise


async def safe_answer(
    message: Message,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> Message:
    flood_retries = 0
    network_retries = 0
    while True:
        try:
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramRetryAfter as e:
            if flood_retries >= _MAX_FLOOD_RETRIES:
                raise
            flood_retries += 1
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError:
            if network_retries >= _MAX_NETWORK_RETRIES:
                raise
            network_retries += 1
            await asyncio.sleep(_NETWORK_RETRY_DELAY)
        except TelegramBadRequest:
            raise


async def safe_query_answer(
    query: CallbackQuery,
    text: str = "",
    show_alert: bool = False,
) -> None:
    try:
        await query.answer(text, show_alert=show_alert)
    except (TelegramNetworkError, TelegramBadRequest, asyncio.TimeoutError):
        pass
