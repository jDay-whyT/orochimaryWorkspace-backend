import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

from app.config import Config
from app.filters.topic_access import TopicAccessMessageFilter
from app.roles import is_authorized
from app.services import NotionClient
from app.services.scout_card import build_scout_report_card
from app.state import MemoryState, RecentModels

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())


@router.message(Command("start"))
async def cmd_start(message: Message, config: Config) -> None:
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

    await message.answer(
        "👋 Привет! Это бот для ведение моделей в Notion\n\n"
        "📝 <b>Примеры команд:</b>\n"
        "• три кастома клещ — бот создаст 3 заказа\n"
        "• клещ 30 файлов — добавит файлы в учет месяца\n"
        "• сьемка\шут клещ — создаст сьемку в планере\n"
        "Просто пиши мне текстом! 🚀",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )


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

    if (
        message.chat.id == config.scouts_chat_id
        and user_id in config.report_viewers
        and user_id not in config.allowed_editors
    ):
        from app.router.model_resolver import resolve_model
        text = (message.text or "").strip()
        resolution = await resolve_model(
            query=text,
            user_id=user_id,
            db_models=config.db_models,
            notion=notion,
            recent_models=recent_models,
        )
        model = resolution.get("model") if resolution.get("status") in {"found", "confirm"} else None
        if not model:
            await message.answer("Модель не найдена")
            return
        card = await build_scout_report_card(model["name"])
        if not card:
            await message.answer("Модель не найдена")
            return
        await message.answer(card)
        return

    # Import router
    from app.router import route_message

    # Route the message
    await route_message(message, config, notion, memory_state, recent_models)
