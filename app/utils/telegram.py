"""Telegram-related utilities."""
import asyncio

from aiogram.types import CallbackQuery
from aiogram.types import InaccessibleMessage, Message
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter

_MAX_NETWORK_RETRIES = 2
_NETWORK_RETRY_DELAY = 1.0


async def safe_edit_message(
    query: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> Message | None:
    if not query.message or isinstance(query.message, InaccessibleMessage):
        return None

    retried_after_flood = False
    network_retries = 0
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
) -> Message | None:
    retried_after_flood = False
    network_retries = 0
    while True:
        try:
            return await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramRetryAfter as e:
            if retried_after_flood:
                raise
            retried_after_flood = True
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError:
            if network_retries >= _MAX_NETWORK_RETRIES:
                raise
            network_retries += 1
            await asyncio.sleep(_NETWORK_RETRY_DELAY)
