import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

from app.config import Config
from app.roles import is_authorized, get_user_role
from app.state import RecentModels

LOGGER = logging.getLogger(__name__)
router = Router()


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

    role = get_user_role(user_id, config)
    LOGGER.info("User %s started bot with role %s", user_id, role.value)

    await message.answer(
        "👋 Привет! Я бот для управления моделями.\n\n"
        "📝 <b>Примеры запросов:</b>\n"
        "• три кастома мелиса — создать 3 заказа\n"
        "• мелиса 30 файлов — добавить файлы\n"
        "• репорт мелиса — статистика за месяц\n"
        "• сводка — открыть меню сводки\n"
        "• заказы — открыть меню заказов\n"
        "• планировщик — открыть планировщик\n"
        "• аккаунт — открыть меню аккаунта\n\n"
        "Просто пиши мне текстом! 🚀",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )


# ==================== NLP Router ====================

@router.message(F.text)
async def handle_nlp_message(
    message: Message,
    config: Config,
    notion,
    memory_state,
    recent_models: RecentModels,
) -> None:
    """Handle NLP text messages (router-based)."""
    if not is_authorized(message.from_user.id, config):
        return

    # Import router
    from app.router import route_message

    # Route the message
    await route_message(message, config, notion, memory_state, recent_models)
