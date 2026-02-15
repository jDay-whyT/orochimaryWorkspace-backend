from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from app.state import MemoryState
from app.utils.telegram import safe_edit_message


def _is_callback_target(target: Message | CallbackQuery) -> bool:
    return hasattr(target, "data") and hasattr(target, "message")


async def clear_previous_screen_keyboard(target: Message | CallbackQuery, memory_state: MemoryState) -> None:
    """Best-effort cleanup of keyboard from previously tracked screen message."""
    if _is_callback_target(target):
        message = target.message
        user_id = target.from_user.id
    else:
        message = target
        user_id = target.from_user.id

    if not message:
        return

    chat_id = message.chat.id
    state = memory_state.get(chat_id, user_id) or {}
    prev_message_id = state.get("screen_message_id")
    if not prev_message_id:
        return

    current_message_id = getattr(message, "message_id", None)
    if current_message_id and current_message_id == prev_message_id:
        return

    try:
        await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=prev_message_id, reply_markup=None)
    except Exception:
        return


async def render_screen(
    target: Message | CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
    memory_state: MemoryState | None = None,
) -> None:
    """Render unified screen message: edit for callbacks, send for text entries."""
    if _is_callback_target(target):
        await safe_edit_message(target, text, reply_markup=reply_markup, parse_mode=parse_mode)
        if memory_state and target.message:
            memory_state.update(target.message.chat.id, target.from_user.id, screen_message_id=target.message.message_id)
        return

    sent = await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    if memory_state:
        await clear_previous_screen_keyboard(target, memory_state)
        memory_state.update(target.chat.id, target.from_user.id, screen_message_id=sent.message_id)
