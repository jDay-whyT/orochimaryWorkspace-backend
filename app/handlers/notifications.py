import logging
import os
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.filters.topic_access import ManagersTopicFilter
from app.services import NotionClient
from app.utils.formatting import MONTHS_SHORT, parse_date, today

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(ManagersTopicFilter())

SHOOTS_DAYS = 3

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _format_day_header(d: date) -> str:
    return f"{d.day} {MONTHS_SHORT[d.month - 1]} ({WEEKDAYS_RU[d.weekday()]})"


def _format_board(shoots: list) -> str:
    if not shoots:
        return f"✅ Съёмок в ближайшие {SHOOTS_DAYS} дн. нет"

    dated = [(parse_date(s.date), s) for s in shoots if s.date]
    dated = [(d, s) for d, s in dated if d is not None]
    dated.sort(key=lambda x: x[0])

    if not dated:
        return f"✅ Съёмок в ближайшие {SHOOTS_DAYS} дн. нет"

    total = len(dated)
    header = f"📷 График съёмок на {SHOOTS_DAYS} дн. ({total} шт)"

    segments = []
    for d, shoot in dated:
        model = shoot.model_title or shoot.title or "?"
        status = shoot.status or "—"
        lines = [f"<b>{model}</b>  {_format_day_header(d)}"]
        lines.append(f"└ {status}")
        if shoot.content:
            lines.append(f"▸ {', '.join(shoot.content)}")
        if shoot.location:
            lines.append(f"• {shoot.location}")
        segments.append("\n".join(lines))

    return header + "\n\n" + "\n\n".join(segments)


async def update_board(bot, config: Config, notion: NotionClient) -> None:
    """Fetch upcoming shoots and post/edit the board message in managers chat."""
    tz = config.timezone
    today_date = today(tz)
    date_to = today_date + timedelta(days=SHOOTS_DAYS - 1)

    shoots = await notion.query_shoots_in_date_range(
        database_id=config.db_planner,
        date_from=today_date,
        date_to=date_to,
    )

    text = _format_board(shoots)

    message_id = int(os.getenv("BOARD_MESSAGE_ID", "0")) or None
    chat_id = config.managers_chat_id

    if message_id and chat_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML",
            )
            return
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return  # текст не изменился, всё ок
            LOGGER.warning("Failed to edit board message: %s", e)

    if chat_id:
        sent = await bot.send_message(
            chat_id=chat_id,
            message_thread_id=config.managers_topic_thread_id,
            text=text,
            parse_mode="HTML",
        )
        LOGGER.info(
            "New board message sent: message_id=%s chat_id=%s — add BOARD_MESSAGE_ID=%s to env",
            sent.message_id,
            sent.chat.id,
            sent.message_id,
        )


@router.message(Command("shoots"))
async def cmd_upcoming_shoots(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show upcoming shoots board for the next 5 days (/shoots)."""
    await update_board(message.bot, config, notion)
