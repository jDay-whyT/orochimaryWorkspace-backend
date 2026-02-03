"""Report handlers for NLP routing."""

import logging
from datetime import datetime

from aiogram.types import Message, CallbackQuery
from aiogram import F, Router

from app.config import Config
from app.services import NotionClient
from app.keyboards.inline import nlp_report_keyboard
from app.utils import escape_html, format_date_short
from app.roles import is_authorized


LOGGER = logging.getLogger(__name__)
router = Router()


async def handle_report_nlp(
    message: Message, model: dict, config: Config, notion: NotionClient
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
    month_str = now.strftime("%B %Y")  # e.g., "February 2026"

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

    await message.answer(
        f"📊 <b>{escape_html(model_name)}</b> | {month_str}\n\n"
        f"📁 Файлов: {files_str}\n"
        f"📦 Заказов: {orders_str}\n",
        reply_markup=nlp_report_keyboard(model_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("nlp:report_"))
async def handle_report_callback(
    query: CallbackQuery, config: Config, notion: NotionClient
) -> None:
    """Handle report detail callbacks."""
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return

    parts = query.data.split(":", 2)
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    model_id = parts[2]

    try:
        if action == "report_orders":
            # Show open orders details
            orders = await notion.query_open_orders(config.db_orders, model_id)

            if not orders:
                await query.answer("Нет открытых заказов", show_alert=True)
                return

            # Get model name
            model = await notion.get_model(model_id)
            model_name = model.title if model else "модели"

            # Format orders list
            orders_text = "\n".join(
                f"• {o.order_type or 'order'} · {format_date_short(o.in_date)}"
                for o in orders[:10]  # Limit to 10
            )

            if len(orders) > 10:
                orders_text += f"\n\n...и еще {len(orders) - 10}"

            # Check if message exists before editing
            if query.message:
                await query.message.edit_text(
                    f"📦 <b>Открытые заказы: {escape_html(model_name)}</b>\n\n"
                    f"{orders_text}",
                    reply_markup=nlp_report_keyboard(model_id),
                    parse_mode="HTML",
                )
            await query.answer()

        elif action == "report_accounting":
            # Show accounting details
            records = await notion.query_accounting_current_month(
                config.db_accounting, model_id
            )

            if not records:
                await query.answer("Нет данных по учету", show_alert=True)
                return

            # Get model name
            model = await notion.get_model(model_id)
            model_name = model.title if model else "модели"

            # Format accounting list
            accounting_text = "\n".join(
                f"• {rec.title}: {rec.amount or 0} файлов ({int((rec.percent or 0) * 100)}%)"
                for rec in records[:5]  # Limit to 5
            )

            # Check if message exists before editing
            if query.message:
                await query.message.edit_text(
                    f"📁 <b>Учет файлов: {escape_html(model_name)}</b>\n\n"
                    f"{accounting_text}",
                    reply_markup=nlp_report_keyboard(model_id),
                    parse_mode="HTML",
                )
            await query.answer()

    except Exception as e:
        LOGGER.exception("Error in report callback: %s", e)
        await query.answer("Ошибка. Попробуйте снова.", show_alert=True)
