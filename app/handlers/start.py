import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

from app.config import Config
from app.filters.topic_access import TopicAccessMessageFilter
from app.roles import is_authorized
from app.services import NotionClient
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
        "👋 Привет! Это бот для ведения моделей.\n\n"
        "<b>Как работать:</b>\n"
        "1. Напиши имя модели, например: клещ. Откроется её карточка.\n"
        "2. Дальше кнопками: 📦 Заказы · 📅 Съёмка · 📁 Файлы · 📝 Заметка.\n\n"
        "🔔 Я буду присылать уведомления о проблемных моделях.",
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

    text = (message.text or "").strip()

    # Import router
    from app.router import route_message

    # Route the message
    await route_message(message, config, notion, memory_state, recent_models)
