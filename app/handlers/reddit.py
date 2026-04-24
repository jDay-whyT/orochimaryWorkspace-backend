import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.roles import is_authorized
from app.services import NotionClient, NotionAccounting, NotionPlanner, NotionOrder
from app.utils.formatting import today

LOGGER = logging.getLogger(__name__)
router = Router()

_MONTHS_RU_SHORT = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


@dataclass
class RedditBoardRow:
    model_id: str
    model_name: str
    reddit_files: int | None = None
    comment: str | None = None
    last_shoot_date: str | None = None
    last_shoot_status: str | None = None
    next_shoot_date: str | None = None
    next_shoot_status: str | None = None
    verif_requested: int = 0
    verif_received: int = 0


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


_MONTHS_STRIP = (
    "январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь|"
    "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
)


def _extract_model_name_from_title(title: str) -> str:
    """Strip month suffix from accounting title. 'АКАЦИЯ апрель 2026' → 'АКАЦИЯ'"""
    cleaned = re.sub(
        rf'\s+({_MONTHS_STRIP})(\s+\d{{4}})?\s*$', '', title, flags=re.IGNORECASE
    ).strip()
    return cleaned or title


async def update_reddit_board(bot, config: Config, notion: NotionClient) -> None:
    """Fetch Reddit board data and post/edit the board message."""
    yyyy_mm = today(config.timezone).strftime("%Y-%m")

    accounting, planner, orders = await asyncio.gather(
        notion.query_reddit_accounting(config.db_accounting, yyyy_mm),
        notion.query_reddit_shoots(config.db_planner, yyyy_mm),
        notion.query_verif_reddit_orders(config.db_orders, yyyy_mm),
    )

    board = _build_reddit_board_rows(accounting, planner, orders, today(config.timezone))
    text = _format_reddit_board_text(board, config)

    message_id = config.reddit_board_message_id
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
                return
            LOGGER.warning("Failed to edit reddit board message: %s", e)

    if chat_id:
        sent = await bot.send_message(
            chat_id=chat_id,
            message_thread_id=config.reddit_board_topic_thread_id,
            text=text,
            parse_mode="HTML",
        )
        LOGGER.info(
            "New reddit board message sent: message_id=%s — add REDDIT_BOARD_MESSAGE_ID=%s to env",
            sent.message_id,
            sent.message_id,
        )


@router.message(Command("reddit"))
async def cmd_reddit(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    if not is_authorized(message.from_user.id, config):
        return
    await update_reddit_board(message.bot, config, notion)


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
        model_name = _extract_model_name_from_title(acc.title) if acc.title else acc.model_id or "?"
        rows[model_id] = RedditBoardRow(
            model_id=model_id,
            model_name=model_name,
            reddit_files=acc.reddit_files,
            comment=acc.comment,
        )

    planner_by_model: dict[str, list[NotionPlanner]] = {}
    for shoot in planner:
        model_id = _mid(shoot.model_id)
        if not model_id or model_id not in rows:
            continue  # skip — not in Accounting
        planner_by_model.setdefault(model_id, []).append(shoot)

    for model_id, model_shoots in planner_by_model.items():
        row = rows[model_id]

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
            future = [s for s in next_shoots if (s.date or "") >= today_date.isoformat()]
            pool = future or next_shoots
            pool.sort(key=lambda s: s.date or "")
            row.next_shoot_date = pool[0].date
            row.next_shoot_status = pool[0].status

    for order in orders:
        model_id = _mid(order.model_id)
        if not model_id or model_id not in rows:
            continue
        row = rows[model_id]
        row.verif_requested += int(order.count or 0)
        row.verif_received += int(order.received or 0)

    return sorted(rows.values(), key=lambda x: x.model_name.lower())


def _format_reddit_board_text(rows: list[RedditBoardRow], config: Config) -> str:
    if not rows:
        return "📭 Reddit board пуст"

    now = today(config.timezone)
    month_label = _MONTHS_RU_SHORT[now.month - 1]
    header_line = f"<b>Reddit · {month_label} {now.year}</b> — {len(rows)} моделей\n"

    cards: list[str] = []
    for row in rows:
        if row.next_shoot_date:
            d = date.fromisoformat(row.next_shoot_date[:10])
            day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            day_name = day_names[d.weekday()]
            header = f"{html.escape(row.model_name)}  {_format_day_mon(row.next_shoot_date)} ({day_name})"
        else:
            header = html.escape(row.model_name)

        lines = [f"<b>{header}</b>"]

        if row.next_shoot_date and row.next_shoot_status:
            lines.append(f"  └ {row.next_shoot_status}")
        else:
            lines.append("  └ not scheduled")

        if row.last_shoot_date:
            lines.append(f"  | last: <b>{_format_day_mon(row.last_shoot_date)}</b>")

        files_str = str(row.reddit_files) if row.reddit_files is not None else "—"
        if row.verif_requested > 0:
            stats = f"  ▸ reddit: <b>{files_str}</b> | verif: <b>{row.verif_received}/{row.verif_requested}</b>"
        else:
            stats = f"  ▸ reddit: <b>{files_str}</b>"
        lines.append(stats)

        if row.comment:
            lines.append(f"  💬 {html.escape(row.comment)}")

        cards.append("\n".join(lines))

    return header_line + "\n" + "\n\n".join(cards)
