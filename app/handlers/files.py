from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.filters.flow import FlowFilter
from app.keyboards.inline import (
    build_file_type_keyboard,
    build_files_add_keyboard,
    build_files_keyboard,
)
from app.state import MemoryState, generate_token

router = Router()


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id


def _strip_token(callback_data: str) -> str:
    return (callback_data or "").split("|", 1)[0]


@router.callback_query(F.data.startswith("files:"))
async def files_menu_router(call: CallbackQuery, memory_state: MemoryState) -> None:
    """Unified files module handlers."""
    data = _strip_token(call.data)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "menu"
    chat_id, user_id = _state_ids_from_query(call)

    if action == "menu":
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            "🏠 > 📁 Файлы\n\n📁 Файлы",
            reply_markup=build_files_keyboard(token=token),
        )
    elif action == "stats":
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        stats_text = (
            "📊 Статистика за текущий месяц:\n\n"
            "custom: 45\n"
            "short: 1\n"
            "reel: 12\n"
            "story: 8"
        )
        await call.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"files:menu|{token}")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data=f"menu|{token}")],
            ]),
        )
    elif action == "add":
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            "➕ Добавить файл",
            reply_markup=build_files_add_keyboard(token=token),
        )
    elif action == "upload":
        memory_state.transition(chat_id, user_id, flow="nlp_files_upload", k=generate_token())
        await call.message.answer("Отправьте файлы (фото/видео):")
    elif action == "select_type":
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            "📂 Выберите тип файла:",
            reply_markup=build_file_type_keyboard(token=token),
        )
    elif action == "type":
        file_type = parts[2] if len(parts) > 2 else "custom"
        token = generate_token()
        await call.message.edit_text(
            f"✅ Файл сохранён как: {file_type}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data=f"menu|{token}")]
            ]),
        )
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)

    await call.answer()


@router.message(FlowFilter({"nlp_files_upload"}), F.content_type.in_({"photo", "video", "document"}))
async def receive_files(msg: Message, memory_state: MemoryState) -> None:
    """Receive files and show type selector."""
    token = generate_token()
    memory_state.transition(msg.chat.id, msg.from_user.id, flow="nlp_idle", k=token)
    await msg.answer(
        "Выберите тип файла:",
        reply_markup=build_file_type_keyboard(token=token),
    )
