import logging
from datetime import date, timedelta
from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
    WebAppInfo,
)

from app.config import Config
from app.services import NotionClient
from app.utils.formatting import MONTHS_SHORT, parse_date, today

LOGGER = logging.getLogger(__name__)
router = Router()

SHOOTS_DAYS = 7

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
    header = f"📷 <b>График съёмок на {SHOOTS_DAYS} дн.</b> ({total} шт)"

    days: dict[date, list] = {}
    for d, shoot in dated:
        days.setdefault(d, []).append(shoot)

    day_blocks = []
    for d, day_shoots in days.items():
        day_lines = [f"<b>┌ {_format_day_header(d)}</b>"]
        for shoot in day_shoots:
            model = shoot.model_title or shoot.title or "?"
            status = shoot.status or "—"
            day_lines.append(f"├ <b>{model}</b> — {status}")
            if shoot.content:
                day_lines.append(f"│  ▸ {' | '.join(shoot.content)}")
            if shoot.location:
                day_lines.append(f"│  • {shoot.location}")
        day_blocks.append("\n".join(day_lines))

    return header + "\n\n" + "\n\n".join(day_blocks)


def _sorted_days(shoots: list) -> dict[date, list]:
    dated = [(parse_date(s.date), s) for s in shoots if s.date]
    dated = sorted(((d, s) for d, s in dated if d is not None), key=lambda x: x[0])
    days: dict[date, list] = {}
    for d, shoot in dated:
        days.setdefault(d, []).append(shoot)
    return days


def _format_board_rich(shoots: list, today_date: date) -> str:
    """Rich message (Bot API 10.1+) HTML: one collapsible table per day.

    Today and tomorrow are expanded, later days are collapsed.
    """
    days = _sorted_days(shoots)
    if not days:
        return f"<p>✅ Съёмок в ближайшие {SHOOTS_DAYS} дн. нет</p>"

    total = sum(len(v) for v in days.values())
    parts = [f"<h3>📷 График съёмок на {SHOOTS_DAYS} дн. ({total} шт)</h3>"]
    for d, day_shoots in days.items():
        opened = " open" if d <= today_date + timedelta(days=1) else ""
        rows = []
        for shoot in day_shoots:
            model = escape(shoot.model_title or shoot.title or "?")
            status = escape(shoot.status or "—")
            content = escape(" | ".join(shoot.content)) if shoot.content else "—"
            location = escape(shoot.location) if shoot.location else "—"
            rows.append(
                f"<tr><td><b>{model}</b></td><td>{status}</td><td>{content}</td><td>{location}</td></tr>"
            )
        parts.append(
            f"<details{opened}><summary><b>{_format_day_header(d)}</b> · {len(day_shoots)}</summary>"
            "<table bordered striped compact>"
            "<tr><th>Модель</th><th>Статус</th><th>Контент</th><th>Локация</th></tr>"
            f"{''.join(rows)}</table></details>"
        )
    return "".join(parts)


async def _fetch_shoots(config: Config, notion: NotionClient) -> tuple[list, date]:
    today_date = today(config.timezone)
    date_to = today_date + timedelta(days=SHOOTS_DAYS - 1)
    shoots = await notion.query_shoots_in_date_range(
        database_id=config.db_planner,
        date_from=today_date,
        date_to=date_to,
    )
    return shoots, today_date


async def _fetch_board_text(config: Config, notion: NotionClient) -> str:
    shoots, _ = await _fetch_shoots(config, notion)
    return _format_board(shoots)


async def update_board(bot, config: Config, notion: NotionClient, rich: bool = True) -> None:
    """Fetch upcoming shoots and post/edit the board message in managers chat.

    rich=True uses Bot API 10.1 rich messages; the plain HTML text stays as fallback
    (if the rich edit/send is rejected, e.g. an old API or unsupported markup).
    """
    shoots, today_date = await _fetch_shoots(config, notion)
    text = _format_board(shoots)
    rich_message = InputRichMessage(html=_format_board_rich(shoots, today_date)) if rich else None

    message_id = config.board_message_id
    chat_id = config.managers_chat_id

    if message_id and chat_id:
        try:
            if rich_message:
                await bot.edit_message_text(chat_id=chat_id, message_id=message_id, rich_message=rich_message)
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML"
                )
            return
        except TelegramNetworkError as e:
            LOGGER.warning("Edit board timed out, skipping send: %s", e)
            return
        except Exception as e:
            err = str(e).lower()
            if "message is not modified" in err:
                return
            if "message to edit not found" not in err:
                LOGGER.warning("Failed to edit board message: %s", e)
                if rich_message:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML"
                        )
                    except Exception as fallback_err:
                        LOGGER.warning("HTML fallback edit failed too: %s", fallback_err)
                return
            LOGGER.warning("Board message gone, will send new: %s", e)

    if chat_id:
        sent = None
        if rich_message:
            try:
                sent = await bot.send_rich_message(
                    chat_id=chat_id,
                    message_thread_id=config.managers_topic_thread_id,
                    rich_message=rich_message,
                )
            except Exception as e:
                LOGGER.warning("Rich board send failed, falling back to HTML: %s", e)
        if sent is None:
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


@router.message(Command("scoutbutton"))
async def cmd_scout_button(message: Message, config: Config) -> None:
    """Send a forwardable Scout App button (owner only, private chat only)."""
    if message.chat.type != "private":
        return
    if (
        not message.from_user
        or not config.owner_telegram_id
        or message.from_user.id != config.owner_telegram_id
    ):
        await message.answer("⛔ Нет доступа.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Scout App", web_app=WebAppInfo(url=config.mini_app_url))]]
    )
    await message.answer("👇 Перешли это сообщение в группу:", reply_markup=keyboard)


@router.message(Command("shoots"))
async def cmd_upcoming_shoots(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show upcoming shoots board for the next 5 days (/shoots)."""
    if message.chat.type == "private":
        shoots, today_date = await _fetch_shoots(config, notion)
        try:
            await message.bot.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html=_format_board_rich(shoots, today_date)),
            )
        except Exception as e:
            LOGGER.warning("Rich board failed, falling back to HTML: %s", e)
            await message.answer(_format_board(shoots), parse_mode="HTML")
        return
    await update_board(message.bot, config, notion)
