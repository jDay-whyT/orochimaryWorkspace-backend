"""
Model Card service — builds universal model card text and data.

Card format:
  📌 {MODEL}
  📦 Заказы: open {N}
  📅 Съёмка: {next_date} ({status}) или "нет"
  📁 Файлы ({month}): {files}/180 ({pct}%) +{over}

Data sources:
  - Orders: Notion Orders DB (status=Open)
  - Shoots: Notion Planner DB (upcoming scheduled)
  - Files:  Notion Accounting DB (current month)

All Notion calls are wrapped in try/except — if Notion is unavailable
the card still renders with "—" placeholders.
"""

import html
import logging
from datetime import date, datetime

from app.config import Config
from app.services.notion import NotionClient

LOGGER = logging.getLogger(__name__)


async def build_model_card_text(
    model_id: str,
    model_name: str,
    config: Config,
    notion: NotionClient,
) -> str:
    """
    Build universal model card text with live data from Notion.

    Returns HTML-formatted string ready for Telegram parse_mode="HTML".
    """
    now = datetime.now(tz=config.timezone)
    files_per_month = config.files_per_month

    # --- Fetch data concurrently ---
    orders_count = "—"
    shoot_line = "нет"
    files_line = "0/{fpm} (0%)".format(fpm=files_per_month)
    month_label = _month_ru(now.month)

    # Orders open count
    try:
        orders = await notion.query_open_orders(
            config.db_orders, model_page_id=model_id,
        )
        orders_count = str(len(orders))
    except Exception:
        LOGGER.warning("model_card: failed to fetch orders for %s", model_id)
        orders_count = "—"

    # Next shoot
    try:
        shoots = await notion.query_upcoming_shoots(
            config.db_planner, model_page_id=model_id,
        )
        if shoots:
            s = shoots[0]
            s_date = _format_date_card(s.date)
            s_status = s.status or "planned"
            shoot_line = f"{s_date} ({s_status})"
        else:
            shoot_line = "нет"
    except Exception:
        LOGGER.warning("model_card: failed to fetch shoots for %s", model_id)
        shoot_line = "—"

    # Files current month
    try:
        month_str = now.strftime("%B")
        record = await notion.get_accounting_record(
            config.db_accounting, model_id, month_str,
        )
        if record:
            amount = record.amount or 0
            pct = int((amount / files_per_month) * 100) if files_per_month > 0 else 0
            over = max(0, amount - files_per_month)
            if over > 0:
                files_line = f"{amount}/{files_per_month} ({pct}%) +{over}"
            else:
                files_line = f"{amount}/{files_per_month} ({pct}%)"
        else:
            files_line = f"0/{files_per_month} (0%)"
    except Exception:
        LOGGER.warning("model_card: failed to fetch accounting for %s", model_id)
        files_line = "—"

    safe_name = html.escape(model_name)

    return (
        f"📌 <b>{safe_name}</b>\n"
        f"📦 Заказы: open {orders_count}\n"
        f"📅 Съёмка: {shoot_line}\n"
        f"📁 Файлы ({month_label}): {files_line}\n\n"
        f"Что делаем?"
    )


# ===== Helpers =====

_MONTHS_RU = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def _month_ru(month: int) -> str:
    """Return short Russian month name (1-indexed)."""
    if 1 <= month <= 12:
        return _MONTHS_RU[month - 1]
    return "?"


def _format_date_card(date_str: str | None) -> str:
    """Format ISO date string to DD.MM."""
    if not date_str:
        return "?"
    try:
        d = date.fromisoformat(date_str[:10])
        return d.strftime("%d.%m")
    except (ValueError, TypeError):
        return "?"
