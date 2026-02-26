import logging
from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.filters.topic_access import TopicAccessMessageFilter
from app.services import NotionClient
from app.utils.formatting import format_date_short, today

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())

SHOOTS_DAYS = 7


def _format_shoots_report(shoots: list, days: int) -> str:
    """Format upcoming shoots list in the same style as the old Make.com template."""
    if not shoots:
        return f"✅ Съёмок в ближайшие {days} дн. нет"

    lines = [f"📷 <b>Ближайшие съёмки — {days} дн.:</b>\n"]
    for shoot in shoots:
        model = shoot.model_title or shoot.title or "?"
        date_str = format_date_short(shoot.date)
        content = ", ".join(shoot.content) if shoot.content else "—"

        lines.append(f"<b>{model}</b> — {date_str}")
        lines.append(f"📌 {content}\n")

    return "\n".join(lines).strip()


@router.message(Command("shoots"))
async def cmd_upcoming_shoots(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show upcoming shoots for the next 7 days (/shoots)."""
    tz = config.timezone
    today_date = today(tz)
    date_to = today_date + timedelta(days=SHOOTS_DAYS - 1)

    shoots = await notion.query_shoots_in_date_range(
        database_id=config.db_planner,
        date_from=today_date,
        date_to=date_to,
    )

    text = _format_shoots_report(shoots, SHOOTS_DAYS)
    await message.answer(text, parse_mode="HTML")
