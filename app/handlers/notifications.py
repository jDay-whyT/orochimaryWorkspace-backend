import json
import logging
from datetime import date, timedelta
from pathlib import Path

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

SHOOTS_DAYS = 5
BOARD_STATE_FILE = Path(__file__).parent.parent.parent / "board_state.json"

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _load_board_state() -> dict | None:
    try:
        if BOARD_STATE_FILE.exists():
            with BOARD_STATE_FILE.open() as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_board_state(state: dict) -> None:
    try:
        with BOARD_STATE_FILE.open("w") as f:
            json.dump(state, f)
    except Exception as e:
        LOGGER.warning("Failed to save board state: %s", e)


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
    header = f"📷 Ближайшие съёмки — {SHOOTS_DAYS} дн. ({total} шт.)"

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


@router.message(Command("shoots"))
async def cmd_upcoming_shoots(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show upcoming shoots board for the next 5 days (/shoots)."""
    tz = config.timezone
    today_date = today(tz)
    date_to = today_date + timedelta(days=SHOOTS_DAYS - 1)

    shoots = await notion.query_shoots_in_date_range(
        database_id=config.db_planner,
        date_from=today_date,
        date_to=date_to,
    )

    text = _format_board(shoots)

    state = _load_board_state()
    if state and state.get("message_id") and config.managers_chat_id:
        try:
            await message.bot.edit_message_text(
                chat_id=config.managers_chat_id,
                message_id=state["message_id"],
                text=text,
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    sent = await message.answer(text, parse_mode="HTML")
    _save_board_state({"message_id": sent.message_id, "chat_id": sent.chat.id})
