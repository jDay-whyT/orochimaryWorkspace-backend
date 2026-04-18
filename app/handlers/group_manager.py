import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from app.config import Config
from app.router.command_filters import normalize_text

LOGGER = logging.getLogger(__name__)
router = Router()

TOPICS_TO_CREATE: tuple[tuple[str, str], ...] = (
    ("OF", "5181620069708333851"),
    ("Twitter", "5330337435500951363"),
    ("Reddit", "5330321861949539755"),
    ("Orders", "5364036341610858181"),
    ("Description", "5334882760735598374"),
)


def _is_parkour_trigger(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(re.search(r"(?<!\w)паркур(?!\w)", normalized, re.IGNORECASE))


async def _bot_can_manage_topics(message: Message) -> tuple[bool, str | None]:
    bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
    status = getattr(bot_member, "status", "")

    if status not in {"administrator", "creator"}:
        return False, "❌ Не могу создать топики: бот не админ в этом чате."

    can_manage_topics = status == "creator" or bool(getattr(bot_member, "can_manage_topics", False))
    if not can_manage_topics:
        return False, "❌ Не могу создать топики: у бота нет права can_manage_topics."

    return True, None


@router.message(F.text)
async def create_group_topics(message: Message, config: Config) -> None:
    if not message.from_user or message.from_user.id not in config.allowed_editors:
        return

    if message.chat.type not in {"group", "supergroup"}:
        return

    if not _is_parkour_trigger(message.text or ""):
        return

    can_manage, error_message = await _bot_can_manage_topics(message)
    if not can_manage:
        await message.answer(error_message)
        return

    try:
        for topic_name, custom_emoji_id in TOPICS_TO_CREATE:
            await message.bot.create_forum_topic(
                chat_id=message.chat.id,
                name=topic_name,
                icon_custom_emoji_id=custom_emoji_id,
            )

        await message.bot.send_message(chat_id=message.chat.id, text="✅ Готово")
    except TelegramForbiddenError:
        await message.answer("❌ Не могу создать топики: недостаточно прав в этом чате.")
    except TelegramBadRequest as exc:
        LOGGER.warning("Failed to create forum topics in chat_id=%s: %s", message.chat.id, exc)
        await message.answer(f"❌ Не удалось создать топики: {exc.message}")
