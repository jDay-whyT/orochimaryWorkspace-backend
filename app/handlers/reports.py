"""Report handlers for NLP routing."""

import logging
from datetime import datetime

from aiogram.types import Message
from aiogram import Router

from app.config import Config
from app.filters.topic_access import TopicAccessMessageFilter
from app.services import NotionClient
from app.keyboards.inline import nlp_report_keyboard
from app.utils import escape_html
from app.state import MemoryState
from app.utils.accounting import format_accounting_progress


LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())


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
        files_str = format_accounting_progress(total, record.status)
    else:
        files_str = format_accounting_progress(0, None)

    orders_str = f"{len(open_orders)} открытых"

    if memory_state:
        memory_state.set(message.chat.id, message.from_user.id, {
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
        memory_state.update(message.chat.id, message.from_user.id, screen_message_id=sent.message_id)
