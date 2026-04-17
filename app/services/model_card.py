"""Model Card service — builds CRM model card text and data."""

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

    orders_line = "—"
    upcoming_shoot_line: str | None = None
    last_shoot_line: str | None = None
    files_line = "—"
    has_error = False
    open_orders_count = -1

    yyyy_mm = now.strftime("%Y-%m")
    results = await asyncio.gather(
        notion.query_open_orders(config.db_orders, model_page_id=model_id),
        notion.query_upcoming_shoots(
            config.db_planner,
            model_page_id=model_id,
            statuses=["planned", "scheduled", "rescheduled", "done"],
        ),
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
        overdue = sum(1 for order in orders if _calc_days_open(order.in_date, today) > 3)
        orders_line = f"{open_orders_count} откр"
        if overdue > 0:
            orders_line += f" · {overdue} просрочены"

    # Next shoot
    if isinstance(shoots_result, Exception):
        LOGGER.warning("model_card: failed to fetch shoots for %s", model_id)
        has_error = True
    else:
        shoots = shoots_result
        upcoming = []
        done = []
        for shoot in shoots:
            if not shoot.date:
                continue
            parsed = _parse_iso_date(shoot.date)
            if parsed is None:
                continue
            status = (shoot.status or "").lower()
            if status in {"scheduled", "planned"} and parsed >= today:
                upcoming.append((parsed, shoot))
            elif status == "done" and parsed <= today:
                done.append((parsed, shoot))
        if upcoming:
            upcoming.sort(key=lambda pair: pair[0])
            _, nearest = upcoming[0]
            s_date = _format_date_card(nearest.date)
            content = ", ".join(nearest.content or []) or "—"
            upcoming_shoot_line = f"{s_date} · {content}"
        if done:
            done.sort(key=lambda pair: pair[0], reverse=True)
            _, latest_done = done[0]
            done_date = _format_date_card(latest_done.date)
            content = ", ".join(latest_done.content or []) or "—"
            last_shoot_line = f"{done_date} · {content}"

    # Files current month
    if isinstance(accounting_result, Exception):
        LOGGER.warning("model_card: failed to fetch accounting for %s", model_id)
        files_line = "—"
        has_error = True
    else:
        record = accounting_result
        if record:
            typed_counts = [
                ("OF", int(getattr(record, "of_files", 0) or 0)),
                ("Reddit", int(getattr(record, "reddit_files", 0) or 0)),
                ("Twitter", int(getattr(record, "twitter_files", 0) or 0)),
                ("Fansly", int(getattr(record, "fansly_files", 0) or 0)),
                ("Social", int(getattr(record, "social_files", 0) or 0)),
                ("Request", int(getattr(record, "request_files", 0) or 0)),
            ]
            non_zero_parts = [f"{label}: {value}" for label, value in typed_counts if value > 0]
            if non_zero_parts:
                files_line = " | ".join(non_zero_parts)

    safe_name = html.escape(model_name.upper())
    month_label = _month_ru(now.month)

    lines = [
        f"📌 <b>{safe_name}</b>",
        "",
        f"📦 Заказы: {orders_line}",
    ]
    if upcoming_shoot_line is not None:
        lines.append(f"📅 Съёмка: {upcoming_shoot_line}")
    if last_shoot_line is not None:
        lines.append(f"📅 Последняя: {last_shoot_line}")
    lines.append(f"📁 Файлы ({month_label}): {files_line}")
    lines.extend(["", "Что делаем?"])

    text = "\n".join(lines)
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
