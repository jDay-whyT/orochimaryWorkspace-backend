import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.filters.topic_access import TopicAccessMessageFilter
from app.roles import is_authorized
from app.services import NotionClient, ModelsService
from app.state import MemoryState, RecentModels, generate_token
from app.utils.navigation import format_breadcrumbs
from app.keyboards.inline import build_main_menu_keyboard, models_keyboard

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())


def _main_menu_text(model_name: str | None = None) -> str:
    label = model_name or "—"
    return f"{format_breadcrumbs(['🏠 Главное меню'])}\n\nМодель: {label}"


@router.message(Command("start"))
async def cmd_start(message: Message, config: Config, memory_state: MemoryState) -> None:
    """Handle /start command."""
    user_id = message.from_user.id

    if not is_authorized(user_id, config):
        await message.answer(
            "⛔ Access denied.\n\n"
            "You are not authorized to use this bot.\n"
            "Contact administrator to get access."
        )
        LOGGER.info("NLP msg from user_id=%s text=%r", user_id, message.text)
        LOGGER.warning("Unauthorized access attempt from user %s", user_id)
        return

    LOGGER.info("User %s started bot", user_id)

    token = generate_token()
    memory_state.transition(message.chat.id, message.from_user.id, flow="nlp_idle", k=token)
    await message.answer(
        f"{_main_menu_text()}\n\nВыберите раздел:",
        reply_markup=build_main_menu_keyboard(token=token),
        parse_mode="HTML",
    )


@router.message(Command("трико"))
async def cmd_select_model(message: Message, config: Config, memory_state: MemoryState) -> None:
    """Select active model once for all modules."""
    if not is_authorized(message.from_user.id, config):
        return

    service = ModelsService(config)
    try:
        models = await service.search_models("")
    finally:
        await service.close()

    recent = [(m["id"], m["name"]) for m in models[:9]]
    token = generate_token()
    memory_state.transition(message.chat.id, message.from_user.id, flow="nlp_select_model", k=token)
    await message.answer(
        f"{format_breadcrumbs(['🏠 Главное меню', '🤖 Выбор модели'])}\n\nВыберите модель:",
        reply_markup=models_keyboard(prefix="main", recent=recent, show_search=False, back_to="menu", token=token),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("main|select_model|"))
async def main_select_model_callback(call: CallbackQuery, config: Config, memory_state: MemoryState) -> None:
    parts = (call.data or "").split("|")
    model_id = parts[2] if len(parts) > 2 else ""

    service = ModelsService(config)
    try:
        model = await service.get_model_by_id(model_id)
    finally:
        await service.close()

    if not model:
        await call.answer("Модель не найдена", show_alert=True)
        return

    token = generate_token()
    memory_state.transition(
        call.message.chat.id,
        call.from_user.id,
        flow="nlp_idle",
        model_id=model["id"],
        model_name=model["name"],
        k=token,
    )
    await call.message.edit_text(
        f"{_main_menu_text(model['name'])}\n\nВыберите раздел:",
        reply_markup=build_main_menu_keyboard(token=token),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("menu"))
async def menu_callback(call: CallbackQuery, memory_state: MemoryState) -> None:
    """Open unified main menu from inline navigation."""
    state = memory_state.get(call.message.chat.id, call.from_user.id) or {}
    token = generate_token()
    memory_state.transition(
        call.message.chat.id,
        call.from_user.id,
        flow="nlp_idle",
        model_id=state.get("model_id"),
        model_name=state.get("model_name"),
        k=token,
    )
    await call.message.edit_text(
        f"{_main_menu_text(state.get('model_name'))}\n\nВыберите раздел:",
        reply_markup=build_main_menu_keyboard(token=token),
    )
    await call.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, memory_state: MemoryState) -> None:
    """Reset current flow and return user to main menu."""
    memory_state.clear(message.chat.id, message.from_user.id)
    await message.answer(f"{format_breadcrumbs(['🏠 Меню'])}\n\nТекущий флоу отменен.")


# ==================== NLP Router ====================

@router.message(F.text)
async def handle_nlp_message(
    message: Message,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle NLP text messages (router-based)."""
    user_id = message.from_user.id
    LOGGER.info("TEXT_HANDLER HIT user=%s text=%r", user_id, message.text[:80])

    if not is_authorized(user_id, config):
        LOGGER.warning("TEXT_HANDLER BLOCKED by is_authorized user=%s", user_id)
        return

    from app.router import route_message

    await route_message(message, config, notion, memory_state, recent_models)
