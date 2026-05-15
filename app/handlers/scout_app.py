"""Handler for /app command in the scout Telegram group."""
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.config import Config

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("app"))
async def scout_app_command(message: Message, config: Config) -> None:
    if not config.scouts_chat_id or message.chat.id != config.scouts_chat_id:
        return

    if not config.mini_app_url:
        LOGGER.error("/app: MINI_APP_URL env var not set — cannot send WebApp button")
        await message.answer("⚠️ Mini App URL not configured (MINI_APP_URL)")
        return

    if not message.from_user:
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Open Scout App",
            web_app=WebAppInfo(url=config.mini_app_url),
        )
    ]])

    # WebAppInfo buttons are not allowed in group chats — send via private DM.
    try:
        await message.bot.send_message(
            chat_id=message.from_user.id,
            text="Scout card viewer:",
            reply_markup=keyboard,
        )
        await message.reply("✅ Check your private chat with the bot.")
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.reply(
            "Start the bot in private first, then use /app here."
        )
