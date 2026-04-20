import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.filters.topic_access import TopicAccessMessageFilter
from app.roles import is_authorized
from app.services import NotionClient, NotionAccounting, NotionPlanner, NotionOrder
from app.utils.formatting import today

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())

_MONTHS_RU_SHORT = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


@dataclass
class RedditBoardRow:
    model_id: str
    model_name: str
    is_new: bool = False
    reddit_files: int | None = None
    comm_reddit: str | None = None
    last_shoot_date: str | None = None
    last_shoot_status: str | None = None
    next_shoot_date: str | None = None
    next_shoot_status: str | None = None
    verif_count: int | None = None
    verif_date: str | None = None


def _mid(value: str | None) -> str:
    return (value or "").replace("-", "")


def _format_day_mon(date_str: str | None) -> str:
    if not date_str:
        return "—"
    try:
        d = date.fromisoformat(date_str[:10])
    except (TypeError, ValueError):
        return "—"
    return f"{d.day:02d} {_MONTHS_RU_SHORT[d.month - 1]}"


def _format_shoot(date_str: str | None, status: str | None) -> str:
    if not date_str:
        return "—"
    status_text = status or "—"
    return f"{_format_day_mon(date_str)} · {status_text}"


def _fmt_model_name(record: NotionAccounting | NotionPlanner | NotionOrder) -> str:
    return record.model_title or record.title or "?"


@router.message(Command("reddit"))
async def cmd_reddit(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    if not is_authorized(message.from_user.id, config):
        return

    # CRM topic only (in addition to TopicAccessMessageFilter)
    if message.chat.type not in {"group", "supergroup"} or message.message_thread_id != config.crm_topic_thread_id:
        return

    yyyy_mm = today(config.timezone).strftime("%Y-%m")

    accounting_task = notion.query_reddit_accounting(config.db_accounting, yyyy_mm)
    planner_task = notion.query_reddit_shoots(config.db_planner)
    orders_task = notion.query_verif_reddit_orders(config.db_orders)
    accounting, planner, orders = await asyncio.gather(accounting_task, planner_task, orders_task)

    board = _build_reddit_board_rows(accounting, planner, orders, today(config.timezone))
    text = _format_reddit_board_text(board, config)
    await message.answer(text, parse_mode="HTML")


def _build_reddit_board_rows(
    accounting: list[NotionAccounting],
    planner: list[NotionPlanner],
    orders: list[NotionOrder],
    today_date: date,
) -> list[RedditBoardRow]:
    rows: dict[str, RedditBoardRow] = {}

    for acc in accounting:
        model_id = _mid(acc.model_id)
        if not model_id:
            continue
        rows[model_id] = RedditBoardRow(
            model_id=model_id,
            model_name=_fmt_model_name(acc),
            is_new=False,
            reddit_files=acc.reddit_files,
            comm_reddit=acc.comm_reddit,
        )

    planner_by_model: dict[str, list[NotionPlanner]] = {}
    for shoot in planner:
        model_id = _mid(shoot.model_id)
        if not model_id:
            continue
        planner_by_model.setdefault(model_id, []).append(shoot)

    for model_id, model_shoots in planner_by_model.items():
        row = rows.get(model_id)
        if row is None:
            row = RedditBoardRow(
                model_id=model_id,
                model_name=_fmt_model_name(model_shoots[0]),
                is_new=True,
            )
            rows[model_id] = row

        done_shoots = [s for s in model_shoots if s.status == "done" and s.date]
        if done_shoots:
            done_shoots.sort(key=lambda s: s.date or "", reverse=True)
            row.last_shoot_date = done_shoots[0].date
            row.last_shoot_status = done_shoots[0].status

        next_shoots = [
            s for s in model_shoots
            if s.status in {"planned", "scheduled", "rescheduled"} and s.date
        ]
        if next_shoots:
            future_shoots = [s for s in next_shoots if (s.date or "") >= today_date.isoformat()]
            pool = future_shoots or next_shoots
            pool.sort(key=lambda s: s.date or "")
            row.next_shoot_date = pool[0].date
            row.next_shoot_status = pool[0].status

    for order in orders:
        model_id = _mid(order.model_id)
        if not model_id:
            continue
        row = rows.get(model_id)
        if row is None:
            row = RedditBoardRow(
                model_id=model_id,
                model_name=_fmt_model_name(order),
                is_new=True,
            )
            rows[model_id] = row

        if row.verif_count is not None:
            continue
        row.verif_count = order.count
        row.verif_date = order.in_date

    return sorted(rows.values(), key=lambda x: x.model_name.lower())


def _format_reddit_board_text(rows: list[RedditBoardRow], config: Config) -> str:
    if not rows:
        return "📭 Reddit board пуст"

    now = today(config.timezone)
    month_label = _MONTHS_RU_SHORT[now.month - 1]

    cards: list[str] = []
    for row in rows:
        new_badge = " 🆕" if row.is_new else ""
        model_line = f"📌 <b>{html.escape(row.model_name)}</b>{new_badge}"
        last_line = f"📅 Прошлая съёмка: {_format_shoot(row.last_shoot_date, row.last_shoot_status)}"
        next_line = f"📅 Следующая: {_format_shoot(row.next_shoot_date, row.next_shoot_status)}"
        files_line = f"📁 Reddit файлов ({month_label}): {row.reddit_files if row.reddit_files is not None else '—'}"

        if row.verif_count is None or not row.verif_date:
            verif_line = "📋 Вериф: —"
        else:
            verif_line = f"📋 Вериф: open · {row.verif_count} шт · {_format_day_mon(row.verif_date)}"

        comment_line = f"💬 {html.escape(row.comm_reddit) if row.comm_reddit else '—'}"
        cards.append("\n".join([model_line, last_line, next_line, files_line, verif_line, comment_line]))

    return "\n\n".join(cards)
