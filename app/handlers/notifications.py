import json
import logging
from datetime import timedelta
from html import escape
from pathlib import Path

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.filters.topic_access import ManagersTopicFilter
from app.services import NotionClient
from app.utils.formatting import today

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(ManagersTopicFilter())

SHOOTS_DAYS = 5
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
BOARD_STATE_PATH = Path(__file__).resolve().parents[2] / "board_state.json"


def _format_day_label(date_str: str) -> str:
    from datetime import datetime

    date_obj = datetime.fromisoformat(date_str).date()
    return date_obj.strftime("%d %b") + f" ({WEEKDAYS_RU[date_obj.weekday()]})"


def _format_board(shoots: list) -> str:
    if not shoots:
        return f"✅ Съёмок в ближайшие {SHOOTS_DAYS} дн. нет"

    grouped: dict[str, list] = {}
    for shoot in shoots:
        if not shoot.date:
            continue
        grouped.setdefault(shoot.date, []).append(shoot)

    total = sum(len(items) for items in grouped.values())
    lines = [f"📷 <b>Ближайшие съёмки — {SHOOTS_DAYS} дн. ({total} шт.)</b>"]

    for date_str in sorted(grouped.keys()):
        lines.append("")
        lines.append(escape(_format_day_label(date_str)))
        for shoot in grouped[date_str]:
            model = escape(shoot.model_title or shoot.title or "?")
            status = escape(shoot.status or "")
            lines.append(f"{model} — {status}")
            if shoot.content:
                lines.append(f"🚀 {escape(', '.join(shoot.content))}")
            if shoot.location:
                lines.append(f"📍 {escape(shoot.location)}")
            lines.append("")

    return "\n".join(lines).strip()


def _load_board_state() -> dict[str, int]:
    if not BOARD_STATE_PATH.exists():
        return {}
    try:
        return json.loads(BOARD_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        LOGGER.warning("Failed to read board state from %s", BOARD_STATE_PATH)
        return {}


def _save_board_state(message_id: int, chat_id: int) -> None:
    state = {"message_id": message_id, "chat_id": chat_id}
    BOARD_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )


async def update_board(bot: Bot, config: Config, notion: NotionClient) -> None:
    tz = config.timezone
    today_date = today(tz)
    date_to = today_date + timedelta(days=SHOOTS_DAYS - 1)

    shoots = await notion.query_shoots_in_date_range(
        database_id=config.db_planner,
        date_from=today_date,
        date_to=date_to,
        statuses=["planned", "scheduled", "rescheduled", "stacked"],
    )
    text = _format_board(shoots)

    state = _load_board_state()
    message_id = state.get("message_id")
    chat_id = state.get("chat_id") or config.managers_chat_id

    if message_id and chat_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
            return
        except Exception:
            LOGGER.info("Failed to edit board message, sending new one", exc_info=True)

    sent = await bot.send_message(
        chat_id=config.managers_chat_id,
        message_thread_id=config.managers_topic_thread_id,
        text=text,
        parse_mode="HTML",
    )
    _save_board_state(message_id=sent.message_id, chat_id=sent.chat.id)


@router.message(Command("shoots"))
async def cmd_upcoming_shoots(
    message: Message,
    bot: Bot,
    config: Config,
    notion: NotionClient,
) -> None:
    """Update managers board with upcoming shoots (/shoots)."""
    await update_board(bot, config, notion)
    await message.answer("✅ Доска съёмок обновлена", parse_mode="HTML")
