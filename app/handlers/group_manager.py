import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from app.config import Config

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

TOPICS_TO_CREATE: tuple[str, ...] = (
    "OF",
    "Twitter",
    "Reddit",
    "Orders",
    "Description",
)

async def _bot_can_manage_topics(message: Message) -> tuple[bool, str | None]:
    bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
    status = getattr(bot_member, "status", "")

    if status not in {"administrator", "creator"}:
        return False, "❌ Не могу создать топики: бот не админ в этом чате."

    can_manage_topics = status == "creator" or bool(getattr(bot_member, "can_manage_topics", False))
    if not can_manage_topics:
        return False, "❌ Не могу создать топики: у бота нет права can_manage_topics."

    return True, None


@router.message(F.text.regexp(r"(?<!\w)паркур(?!\w)"))
async def create_group_topics(message: Message, config: Config) -> None:
    if not message.from_user or message.from_user.id not in config.allowed_editors:
        return

    if message.chat.type not in {"group", "supergroup"}:
        return

    can_manage, error_message = await _bot_can_manage_topics(message)
    if not can_manage:
        await message.answer(error_message)
        return

    try:
        for topic_name in TOPICS_TO_CREATE:
            await message.bot.create_forum_topic(
                chat_id=message.chat.id,
                name=topic_name,
            )

        await message.bot.send_message(chat_id=message.chat.id, text="✅ Готово")
    except TelegramForbiddenError:
        await message.answer("❌ Не могу создать топики: недостаточно прав в этом чате.")
    except TelegramBadRequest as exc:
        LOGGER.warning("Failed to create forum topics in chat_id=%s: %s", message.chat.id, exc)
        await message.answer(f"❌ Не удалось создать топики: {exc.message}")
