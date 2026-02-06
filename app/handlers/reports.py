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

    # Get current month name
    now = datetime.now(tz=config.timezone)
    month_str = now.strftime("%B")  # e.g., "February"

    # Query accounting for current month
    try:
        accounting_records = await notion.query_accounting_current_month(
            config.db_accounting, model_id
        )
    except Exception as e:
        LOGGER.exception("Failed to query accounting: %s", e)
        accounting_records = []

    # Query open orders
    try:
        open_orders = await notion.query_open_orders(config.db_orders, model_id)
    except Exception as e:
        LOGGER.exception("Failed to query open orders: %s", e)
        open_orders = []

    # Calculate totals
    total_files = sum(
        rec.amount for rec in accounting_records if rec.amount is not None
    )
    avg_percent = (
        sum(rec.percent for rec in accounting_records if rec.percent is not None)
        / len(accounting_records)
        if accounting_records
        else 0
    )

    # Format report
    files_str = f"{total_files} ({int(avg_percent * 100)}%)"
    orders_str = f"{len(open_orders)} открытых"

    # Store model_id in memory for report detail callbacks (nlp:ro, nlp:ra)
    if memory_state:
        memory_state.set(message.from_user.id, {
            "flow": "nlp_report",
            "model_id": model_id,
            "model_name": model_name,
        })

    await message.answer(
        f"📊 <b>{escape_html(model_name)}</b> · {month_str}\n\n"
        f"📁 Файлов: {files_str}\n"
        f"📦 Заказов: {orders_str}\n",
        reply_markup=nlp_report_keyboard(),
        parse_mode="HTML",
    )
