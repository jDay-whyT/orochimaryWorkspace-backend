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

import asyncio
import html
import logging
import time
from datetime import date, datetime

from app.config import Config
from app.services.notion import NotionClient

LOGGER = logging.getLogger(__name__)

# ===== TTL Cache =====

CARD_CACHE_TTL: float = 120.0  # seconds for successful results
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

    text, is_error, _ = await _build_card_text_impl(model_id, model_name, config, notion)
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

    text, is_error, open_orders = await _build_card_text_impl(model_id, model_name, config, notion)
    _cache_set(cache_key, text, is_error)
    _orders_count_cache[cache_key] = open_orders
    return text, open_orders


# Parallel cache for orders count (same TTL as card cache)
_orders_count_cache: dict[str, int] = {}


async def _build_card_text_impl(
    model_id: str,
    model_name: str,
    config: Config,
    notion: NotionClient,
) -> tuple[str, bool, int]:
    """
    Actual card building logic. Returns (text, is_error, open_orders_count).
    is_error=True when any Notion call failed (contains "—").
    """
    now = datetime.now(tz=config.timezone)
    today = now.date()

    orders_line = "нет"
    shoot_line = "нет"
    files_line = "0"
    has_error = False
    open_orders_count = -1

    yyyy_mm = now.strftime("%Y-%m")
    results = await asyncio.gather(
        notion.query_open_orders(config.db_orders, model_page_id=model_id),
        notion.query_upcoming_shoots(config.db_planner, model_page_id=model_id),
        notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm),
        return_exceptions=True,
    )

    orders_result, shoots_result, accounting_result = results

    # Orders open count
    if isinstance(orders_result, Exception):
        LOGGER.warning("model_card: failed to fetch orders for %s", model_id)
        orders_line = "—"
        has_error = True
    else:
        orders = orders_result
        open_orders_count = len(orders)
        total = len(orders)
        overdue = sum(1 for order in orders if _calc_days_open(order.in_date, today) > 3)

        if total == 0:
            orders_line = "нет"
        elif overdue == 0:
            orders_line = f"{total} откр"
        else:
            orders_line = f"{total} откр · {overdue} >3д"

    # Next shoot
    if isinstance(shoots_result, Exception):
        LOGGER.warning("model_card: failed to fetch shoots for %s", model_id)
        shoot_line = "—"
        has_error = True
    else:
        shoots = shoots_result
        upcoming = []
        for shoot in shoots:
            if not shoot.date:
                continue
            if (shoot.status or "").lower() not in {"scheduled", "planned"}:
                continue
            parsed = _parse_iso_date(shoot.date)
            if parsed is None or parsed < today:
                continue
            upcoming.append((parsed, shoot))
        if upcoming:
            upcoming.sort(key=lambda pair: pair[0])
            _, nearest = upcoming[0]
            s_date = _format_date_card(nearest.date)
            content = "/".join(nearest.content or []) or "—"
            status = nearest.status or "planned"
            shoot_line = f"{s_date} · {content} · {status}"

    # Files current month
    if isinstance(accounting_result, Exception):
        LOGGER.warning("model_card: failed to fetch accounting for %s", model_id)
        files_line = "—"
        has_error = True
    else:
        record = accounting_result
        if record:
            total = int(getattr(record, "total", 0) or 0)
            if total == 0:
                total = int(getattr(record, "files", 0) or 0)
            typed_counts = [
                ("reddit", int(getattr(record, "reddit_files", 0) or 0)),
                ("twitter", int(getattr(record, "twitter_files", 0) or 0)),
                ("of", int(getattr(record, "of_files", 0) or 0)),
                ("fansly", int(getattr(record, "fansly_files", 0) or 0)),
                ("social", int(getattr(record, "social_files", 0) or 0)),
                ("req", int(getattr(record, "request_files", 0) or 0)),
            ]
            non_zero_parts = [f"{label} {value}" for label, value in typed_counts if value > 0]
            files_line = str(total) if not non_zero_parts else f"{total} · {', '.join(non_zero_parts)}"

    safe_name = html.escape(model_name)

    text = (
        f"📌 <b>{safe_name}</b>\n"
        f"\n"
        f"📦 {orders_line}\n"
        f"📅 {shoot_line}\n"
        f"📁 {files_line}"
    )
    return text, has_error, open_orders_count


# ===== Helpers =====

_MONTHS_RU = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def _format_date_card(date_str: str | None) -> str:
    """Format ISO date string to 'D mon' (e.g. 20 апр)."""
    if not date_str:
        return "?"
    try:
        d = date.fromisoformat(date_str[:10])
        return f"{d.day} {_month_ru(d.month)}"
    except (ValueError, TypeError):
        return "?"


def _parse_iso_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except (TypeError, ValueError):
        return None


def _calc_days_open(in_date_str: str | None, today: date) -> int:
    opened = _parse_iso_date(in_date_str)
    if opened is None:
        return 0
    return max(0, (today - opened).days)


def _month_ru(month: int) -> str:
    """Return short Russian month name (1-indexed)."""
    if 1 <= month <= 12:
        return _MONTHS_RU[month - 1]
    return "?"
