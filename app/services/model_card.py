"""
Model Card service — builds universal model card text and data.

Card format:
  📌 {MODEL}
  📦 Заказы: open {N}
  📅 Съёмка: {next_date} ({status}) или "нет"
  📁 Файлы ({month}): {files}/200 ({pct}%) +{over}

Data sources:
  - Orders: Notion Orders DB (status=Open)
  - Shoots: Notion Planner DB (upcoming scheduled)
  - Files:  Notion Accounting DB (current month, one record per model)

All Notion calls are wrapped in try/except — if Notion is unavailable
the card still renders with "—" placeholders.

In-memory TTL cache avoids repeated Notion queries within a short window.
"""

import html
import logging
import time
from datetime import date, datetime

from app.config import Config
from app.services.notion import NotionClient
from app.utils.accounting import format_accounting_progress

LOGGER = logging.getLogger(__name__)

# ===== TTL Cache =====

CARD_CACHE_TTL: float = 20.0  # seconds for successful results
CARD_CACHE_ERROR_TTL: float = 5.0  # seconds for error/placeholder results

# key → (text, timestamp, is_error)
_card_cache: dict[str, tuple[str, float, bool]] = {}


def _cache_get(key: str) -> str | None:
    """Return cached text if still valid, else None."""
    entry = _card_cache.get(key)
    if entry is None:
        return None
    text, ts, is_error = entry
    ttl = CARD_CACHE_ERROR_TTL if is_error else CARD_CACHE_TTL
    if time.monotonic() - ts > ttl:
        _card_cache.pop(key, None)
        return None
    return text


def _cache_set(key: str, text: str, is_error: bool = False) -> None:
    """Store text in cache."""
    _card_cache[key] = (text, time.monotonic(), is_error)


def clear_card_cache() -> None:
    """Clear the entire card cache (useful for tests)."""
    _card_cache.clear()
    _orders_count_cache.clear()


# ===== Card builder =====

async def build_model_card_text(
    model_id: str,
    model_name: str,
    config: Config,
    notion: NotionClient,
) -> str:
    """
    Build universal model card text with live data from Notion.

    Returns HTML-formatted string ready for Telegram parse_mode="HTML".
    Results are cached in-memory for CARD_CACHE_TTL seconds.
    """
    cache_key = model_id.lower()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    text, is_error = await _build_card_text_impl(model_id, model_name, config, notion)
    _cache_set(cache_key, text, is_error)
    return text


async def build_model_card(
    model_id: str,
    model_name: str,
    config: Config,
    notion: NotionClient,
) -> tuple[str, int]:
    """
    Build model card text AND return open_orders count.

    Returns:
        (card_text, open_orders_count)
        open_orders_count is -1 if Notion failed.
    """
    cache_key = model_id.lower()
    cached = _cache_get(cache_key)
    cached_orders = _orders_count_cache.get(cache_key)
    if cached is not None and cached_orders is not None:
        return cached, cached_orders

    text, is_error = await _build_card_text_impl(model_id, model_name, config, notion)
    _cache_set(cache_key, text, is_error)

    open_orders = _extract_orders_count(text)
    _orders_count_cache[cache_key] = open_orders
    return text, open_orders


# Parallel cache for orders count (same TTL as card cache)
_orders_count_cache: dict[str, int] = {}


def _extract_orders_count(text: str) -> int:
    """Extract open orders count from card text. Returns -1 on error."""
    import re
    m = re.search(r'open (\d+)', text)
    if m:
        return int(m.group(1))
    return -1


async def _build_card_text_impl(
    model_id: str,
    model_name: str,
    config: Config,
    notion: NotionClient,
) -> tuple[str, bool]:
    """
    Actual card building logic. Returns (text, is_error).
    is_error=True when any Notion call failed (contains "—").
    """
    now = datetime.now(tz=config.timezone)

    orders_count = "—"
    shoot_line = "—"
    files_line = format_accounting_progress(0, None)
    month_label = _month_ru(now.month)
    has_error = False

    # Orders open count
    try:
        orders = await notion.query_open_orders(
            config.db_orders, model_page_id=model_id,
        )
        orders_count = str(len(orders))
    except Exception:
        LOGGER.warning("model_card: failed to fetch orders for %s", model_id)
        orders_count = "—"
        has_error = True

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
            shoot_line = "—"
    except Exception:
        LOGGER.warning("model_card: failed to fetch shoots for %s", model_id)
        shoot_line = "—"
        has_error = True

    # Files current month
    try:
        yyyy_mm = now.strftime("%Y-%m")
        record = await notion.get_monthly_record(
            config.db_accounting, model_id, yyyy_mm,
        )
        if record:
            total_files = record.files
            files_line = format_accounting_progress(total_files, record.status)
        else:
            files_line = format_accounting_progress(0, None)
    except Exception:
        LOGGER.warning("model_card: failed to fetch accounting for %s", model_id)
        files_line = "—"
        has_error = True

    safe_name = html.escape(model_name)

    text = (
        f"📌 <b>{safe_name}</b>\n"
        f"📦 Заказы: open {orders_count}\n"
        f"📅 Съёмка: {shoot_line}\n"
        f"📁 Файлы ({month_label}): {files_line}\n\n"
        f"Что делаем?"
    )
    return text, has_error


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
