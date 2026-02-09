"""Report handlers for NLP routing."""

import logging
from datetime import datetime

from aiogram.types import Message
from aiogram import Router

from app.config import Config
from app.services import NotionClient
from app.keyboards.inline import nlp_report_keyboard
from app.utils import escape_html
from app.state import MemoryState


LOGGER = logging.getLogger(__name__)
router = Router()


async def handle_report_nlp(
    message: Message,
    model: dict,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState | None = None,
) -> None:
    """
    Handle report request from NLP message.

    Shows compact report with:
    - Accounting data (current month)
    - Open orders count
    - Inline buttons for details
    """
    model_id = model["id"]
    model_name = model["name"]

    now = datetime.now(tz=config.timezone)
    yyyy_mm = now.strftime("%Y-%m")
    fpm = config.files_per_month

    try:
        record = await notion.get_monthly_record(
            config.db_accounting, model_id, yyyy_mm,
        )
    except Exception as e:
        LOGGER.exception("Failed to query accounting: %s", e)
        record = None

    try:
        open_orders = await notion.query_open_orders(config.db_orders, model_id)
    except Exception as e:
        LOGGER.exception("Failed to query open orders: %s", e)
        open_orders = []

    if record:
        total = record.files
        pct = min(100, round(total / fpm * 100)) if fpm > 0 else 0
        over = max(0, total - fpm)
        over_str = f" +{over}" if over > 0 else ""
        files_str = f"{total}/{fpm} ({pct}%){over_str}"
    else:
        files_str = f"0/{fpm} (0%)"

    orders_str = f"{len(open_orders)} открытых"

    if memory_state:
        memory_state.set(message.from_user.id, {
            "flow": "nlp_report",
            "model_id": model_id,
            "model_name": model_name,
        })

    sent = await message.answer(
        f"📊 <b>{escape_html(model_name)}</b> · {yyyy_mm}\n\n"
        f"📁 Файлов: {files_str}\n"
        f"📦 Заказов: {orders_str}\n",
        reply_markup=nlp_report_keyboard(model_id),
        parse_mode="HTML",
    )
    if memory_state and sent:
        memory_state.update(message.from_user.id, screen_message_id=sent.message_id)
