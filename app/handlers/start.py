import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.keyboards import main_menu_keyboard
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
        LOGGER.warning("Unauthorized access attempt from user %s", user_id)
        return
    
    role = get_user_role(user_id, config)
    LOGGER.info("User %s started bot with role %s", user_id, role.value)

    await message.answer(
        "👋 Привет! Я бот для управления моделями.\n\n"
        "📝 <b>Примеры запросов:</b>\n"
        "• три кастома мелиса — создать 3 заказа\n"
        "• мелиса 30 файлов — добавить файлы\n"
        "• репорт мелиса — статистика за месяц\n\n"
        "Просто пиши мне текстом! 🚀\n\n"
        "Или используй меню ниже:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == "📊 Summary")
async def menu_summary(message: Message, config: Config, recent_models: RecentModels) -> None:
    """Handle Summary menu button."""
    if not is_authorized(message.from_user.id, config):
        return
    
    # Will be handled by summary handler
    from app.handlers.summary import show_summary_menu
    await show_summary_menu(message, config, recent_models)


@router.message(F.text == "📦 Orders")
async def menu_orders(message: Message, config: Config) -> None:
    """Handle Orders menu button."""
    if not is_authorized(message.from_user.id, config):
        return
    
    from app.handlers.orders import show_orders_menu
    await show_orders_menu(message, config)


@router.message(F.text == "📅 Planner")
async def menu_planner(message: Message, config: Config) -> None:
    """Handle Planner menu button."""
    if not is_authorized(message.from_user.id, config):
        return
    
    from app.handlers.planner import show_planner_menu
    await show_planner_menu(message, config)


@router.message(F.text == "💰 Account")
async def menu_account(message: Message, config: Config) -> None:
    """Handle Account menu button."""
    if not is_authorized(message.from_user.id, config):
        return

    from app.handlers.accounting import show_accounting_menu
    await show_accounting_menu(message, config)


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
