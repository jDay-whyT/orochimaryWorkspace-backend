import html
import logging
from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InputRichMessage, Message

from app.config import Config
from app.services.sheets import SheetsClient
from app.services.tango_schedule import TangoScheduleEntry, build_tomorrow_schedule
from app.utils.formatting import today

LOGGER = logging.getLogger(__name__)
router = Router()


def _build_message_html(entries: list[TangoScheduleEntry], tomorrow_ddmm: str) -> str:
    rows = ["<tr><th>Модель</th><th>Время</th></tr>"]
    for entry in entries:
        name = html.escape(entry.model_name)
        if entry.url.startswith(("http://", "https://")):
            name = f'<a href="{html.escape(entry.url)}">{name}</a>'
        rows.append(f"<tr><td>{name}</td><td>{html.escape(entry.time)}</td></tr>")
    table = f"<table bordered striped>{''.join(rows)}</table>"
    header = f"<h3>Стримы на {tomorrow_ddmm} по Европе</h3>"
    footer = f"<footer>Всего стримов: {len(entries)}</footer>"
    return header + table + footer


@router.message(Command("tango"))
async def cmd_tango(message: Message, config: Config, sheets: SheetsClient | None) -> None:
    if message.chat.type != "private":
        return
    if not config.owner_telegram_id or message.from_user.id != config.owner_telegram_id:
        return

    if sheets is None or not config.sheet_id:
        await message.answer("Google Sheets не настроен (SHEET_ID / GOOGLE_SERVICE_ACCOUNT_JSON отсутствуют).")
        return

    tomorrow_ddmm = (today(config.timezone) + timedelta(days=1)).strftime("%d.%m")

    try:
        rows = await sheets.get_tab_rows(config.sheet_id, config.sheet_tab_name)
    except Exception as e:
        LOGGER.warning("Failed to fetch tango schedule sheet: %s", e)
        await message.answer("Не удалось получить расписание из Google Sheets, попробуй позже.")
        return

    entries = build_tomorrow_schedule(rows, tomorrow_ddmm)

    if not entries:
        await message.answer("На завтра ничего не запланировано")
        return

    await message.bot.send_rich_message(
        chat_id=message.chat.id,
        rich_message=InputRichMessage(html=_build_message_html(entries, tomorrow_ddmm)),
    )
