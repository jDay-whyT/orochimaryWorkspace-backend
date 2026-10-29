"""/lists and the "📋 Lists" button: overdue orders + low content on demand.

Same lists as the daily reminders. A manager (Accounting `assist`) sees only their
own models; the owner and other editors see everything.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.roles import can_edit
from app.services import NotionClient, access
from app.services.reminders import lists_text
from app.utils.telegram import safe_query_answer

LOGGER = logging.getLogger(__name__)

router = Router()


async def _text(user_id: int, config: Config, notion: NotionClient) -> str:
    try:
        return await lists_text(config, notion, access.manager_assist(user_id, config))
    except Exception:
        LOGGER.exception("Lists failed for %s", user_id)
        return "⚠️ Could not load the lists, try again in a minute."


@router.message(Command("lists"))
async def cmd_lists(message: Message, config: Config, notion: NotionClient) -> None:
    if not message.from_user or not can_edit(message.from_user.id, config):
        return
    await message.answer(await _text(message.from_user.id, config, notion), parse_mode="HTML")


@router.callback_query(F.data == "lists")
async def cb_lists(query: CallbackQuery, config: Config, notion: NotionClient) -> None:
    if not can_edit(query.from_user.id, config):
        await safe_query_answer(query)
        return
    await safe_query_answer(query, "Loading…")
    await query.message.answer(await _text(query.from_user.id, config, notion), parse_mode="HTML")
