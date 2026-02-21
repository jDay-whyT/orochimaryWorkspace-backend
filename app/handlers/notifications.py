import logging
from datetime import date, timedelta

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

SHOOTS_DAYS = 5

_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

STATUS_EMOJI = {
    "planned": "🕐",
    "scheduled": "✅",
    "rescheduled": "🔄",
}


def _format_shoot_card(shoot) -> str:
    """Format a single shoot as a forwarding-ready card."""
    model = (shoot.model_title or shoot.title or "?").upper()

    if shoot.date:
        d = date.fromisoformat(shoot.date) if isinstance(shoot.date, str) else shoot.date
        weekday = _WEEKDAYS_RU[d.weekday()]
        date_str = f"{format_date_short(d)} ({weekday})"
    else:
        date_str = "—"

    status_icon = STATUS_EMOJI.get(shoot.status or "", "📷")
    content = ", ".join(shoot.content) if shoot.content else "—"

    lines = [
        f"{status_icon} <b>{model}</b>",
        f"📅 {date_str}",
        f"📌 {content}",
    ]

    if shoot.location:
        lines.append(f"📍 {shoot.location}")

    if shoot.comments:
        lines.append(f"💬 {shoot.comments}")

    return "\n".join(lines)


@router.message(Command("shoots"))
async def cmd_upcoming_shoots(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show upcoming shoots for the next 7 days, one message per shoot."""
    tz = config.timezone
    today_date = today(tz)
    date_to = today_date + timedelta(days=SHOOTS_DAYS - 1)

    shoots = await notion.query_shoots_in_date_range(
        database_id=config.db_planner,
        date_from=today_date,
        date_to=date_to,
    )

    if not shoots:
        await message.answer(f"✅ Съёмок в ближайшие {SHOOTS_DAYS} дн. нет")
        return

    await message.answer(
        f"📷 <b>Ближайшие съёмки — {SHOOTS_DAYS} дн. ({len(shoots)} шт.)</b>",
        parse_mode="HTML",
    )

    for shoot in shoots:
        await message.answer(_format_shoot_card(shoot), parse_mode="HTML")
