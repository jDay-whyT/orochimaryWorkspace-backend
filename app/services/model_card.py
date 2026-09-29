"""Model Card service — builds CRM model card text and data."""

import asyncio
import html
import logging
import time
from datetime import date, datetime

from app.config import Config
from app.services.notion import NotionClient, NotionPlanner, _parse_accounting, _parse_note, _parse_order, _parse_planner

LOGGER = logging.getLogger(__name__)

_NOTE_PREVIEW_CHARS = 100

# ===== TTL Cache =====

CARD_CACHE_TTL: float = 120.0  # seconds for successful results
CARD_CACHE_ERROR_TTL: float = 5.0  # seconds for error/placeholder results

# key → (text, timestamp, is_error)
_card_cache: dict[str, tuple[str, float, bool]] = {}


def _cache_get(key: str, notion: NotionClient | None = None) -> str | None:
    """Return cached text if still valid, else None.

    A card built before the bot wrote something for this model (order, files,
    shoot, note...) is stale even inside the TTL.
    """
    entry = _card_cache.get(key)
    if entry is None:
        return None
    text, ts, is_error = entry
    ttl = CARD_CACHE_ERROR_TTL if is_error else CARD_CACHE_TTL
    last_write = getattr(notion, "last_write_at", None) if notion is not None else None
    written_at = last_write(key) if callable(last_write) else None
    written_since = isinstance(written_at, (int, float)) and written_at >= ts
    if time.monotonic() - ts > ttl or written_since:
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
    cached = _cache_get(cache_key, notion)
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
    """Build model card text; returns (card_text, open_orders_count), count is -1 if Notion failed."""
    cache_key = model_id.lower()
    cached = _cache_get(cache_key, notion)
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
    shoot_lines: list[str] = []
    files_lines = ["—"]
    has_error = False
    open_orders_count = -1

    yyyy_mm = now.strftime("%Y-%m")

    async def _no_notes():
        return []

    async def _none():
        return None

    last_done = getattr(notion, "query_last_done_shoot", None)
    get_model = getattr(notion, "get_model", None)
    results = await asyncio.gather(
        notion.query_open_orders(config.db_orders, model_page_id=model_id),
        # open shoots and the last done one separately: done shoots pile up over time
        notion.query_upcoming_shoots(config.db_planner, model_page_id=model_id),
        last_done(config.db_planner, model_id) if callable(last_done) else _none(),
        notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm),
        notion.get_recent_notes(config.db_notes, model_id, limit=1) if config.db_notes else _no_notes(),
        get_model(model_id) if callable(get_model) else _none(),
        return_exceptions=True,
    )

    orders_result, shoots_result, last_result, accounting_result, notes_result, model_result = results

    # Database queries lag a few seconds behind writes: swap in what the bot just wrote
    if not isinstance(orders_result, Exception):
        orders_result = _with_recent_writes(
            notion, config.db_orders, model_id, orders_result, _parse_order,
            keep=lambda o: (o.status or "") == "Open" and not o.out_date,
        )
    if not isinstance(shoots_result, Exception):
        shoots_result = _with_recent_writes(
            notion, config.db_planner, model_id, shoots_result, _parse_planner,
            keep=lambda s: (s.status or "").lower() in _OPEN_SHOOTS,
        )
    if not isinstance(last_result, NotionPlanner):
        last_result = None
    done = _with_recent_writes(
        notion, config.db_planner, model_id, [last_result] if last_result else [], _parse_planner,
        keep=lambda s: (s.status or "").lower() == "done",
    )
    last_result = max(done, key=lambda s: s.date or "", default=None)
    if not isinstance(accounting_result, Exception):
        records = _with_recent_writes(
            notion, config.db_accounting, model_id, [accounting_result] if accounting_result else [],
            _parse_accounting, keep=lambda r: True, add_new=accounting_result is None,
        )
        accounting_result = records[0] if records else None
    if config.db_notes and not isinstance(notes_result, Exception):
        notes_result = _with_recent_writes(
            notion, config.db_notes, model_id, notes_result, _parse_note, keep=lambda n: True, new_first=True,
        )

    # Orders open count
    if isinstance(orders_result, Exception):
        LOGGER.warning("model_card: failed to fetch orders for %s", model_id)
        orders_line = "—"
        has_error = True
    else:
        orders = orders_result
        open_orders_count = len(orders)
        overdue = sum(1 for order in orders if _calc_days_open(order.in_date, today) > 3)
        orders_line = f"{open_orders_count} open"
        if overdue > 0:
            orders_line += f" · ⚠️ {overdue} overdue"

    # Next shoot (earliest open, dated first) and the last done one
    if isinstance(shoots_result, Exception):
        LOGGER.warning("model_card: failed to fetch shoots for %s", model_id)
        has_error = True
    else:
        open_shoots = sorted(shoots_result, key=lambda sh: sh.date or "9999")
        nearest = open_shoots[0] if open_shoots else None
        if nearest is None:
            shoot_lines.append("📅 Next: —")
        else:
            parsed = _parse_iso_date(nearest.date)
            day = f"<b>{_format_date_card(nearest.date)}</b>" if parsed else "no date yet"
            content = ", ".join(nearest.content or []) or "—"
            mark = "⚠️ " if parsed and parsed < today else ""
            shoot_lines.append(f"📅 Next: {mark}{day} · {html.escape(content)} · {nearest.status or 'planned'}")
        if last_result is not None:
            content = ", ".join(last_result.content or []) or "—"
            shoot_lines.append(f"    Last: {_format_date_card(last_result.date)} · {html.escape(content)}")

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
            total = sum(value for _, value in typed_counts)
            files_lines = [f"<b>{total}</b> files"]
            parts = [f"{label} {value}" for label, value in typed_counts if value > 0]
            if parts:
                files_lines.append("    " + " · ".join(parts))
        else:
            files_lines = ["<b>0</b> files"]

    safe_name = html.escape(model_name.upper())
    month_label = _month_ru(now.month)
    status = getattr(model_result, "status", None) if not isinstance(model_result, Exception) else None
    header = f"📌 <b>{safe_name}</b>" + (f" · {html.escape(status)}" if isinstance(status, str) and status else "")

    lines = [header, "", f"📦 Orders: {orders_line}"]
    lines.extend(shoot_lines)
    lines.append(f"📁 {month_label}: {files_lines[0]}")
    lines.extend(files_lines[1:])

    # Only the latest note, first line, capped — full text lives in Notion.
    if not isinstance(notes_result, Exception) and notes_result:
        note = notes_result[0]
        date_str = _format_date_card(note.date) if note.date else "?"
        note_text = (note.text or "").strip()
        first_line = note_text.split("\n", 1)[0]
        if len(first_line) > _NOTE_PREVIEW_CHARS:
            first_line = first_line[:_NOTE_PREVIEW_CHARS].rstrip() + "…"
        elif first_line != note_text:
            first_line += " …"
        lines.extend(["", f"📝 {date_str} · {html.escape(first_line)}"])

    text = "\n".join(lines)
    return text, has_error, open_orders_count


# ===== Helpers =====

_OPEN_SHOOTS = {"planned", "scheduled", "rescheduled"}

def _with_recent_writes(notion, database_id, model_id, items, parse, keep, add_new=True, new_first=False):
    """Replace query results with the versions the bot just wrote, drop ones that no
    longer qualify (e.g. an order just closed) and add pages just created for this model."""
    recent_pages = getattr(notion, "recent_pages_in", None)
    if not callable(recent_pages) or not database_id:
        return items
    pages = recent_pages(database_id)
    if not isinstance(pages, list):
        return items
    try:
        fresh = {}
        for page in pages:
            parsed = parse(page)
            fresh[parsed.page_id] = parsed
    except Exception:
        LOGGER.warning("model_card: could not use recent writes", exc_info=True)
        return items
    if not fresh:
        return items
    model_key = (model_id or "").replace("-", "")
    seen = {item.page_id for item in items}
    merged = [fresh.get(item.page_id, item) for item in items]
    merged = [item for item in merged if keep(item)]
    if add_new:
        created_ids = {p["id"] for p in recent_pages(database_id, created_only=True)}
        created = [
            item for pid, item in fresh.items()
            if pid in created_ids and pid not in seen
            and (item.model_id or "").replace("-", "") == model_key and keep(item)
        ]
        merged = created + merged if new_first else merged + created
    return merged


_MONTHS_RU = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
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
