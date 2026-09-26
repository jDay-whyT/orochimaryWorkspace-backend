"""Morning reminders: long-open orders (daily) and low monthly content (on set days).

The owner gets the full list in DM; each manager (Accounting `assist`, mapped via
MANAGER_TELEGRAM_IDS) gets only their own models — in DM or in a group topic.
Silent when nothing is due.
One scheduled call: POST /internal/daily-reminders.
"""

import logging
from collections import defaultdict
from datetime import date, datetime
from html import escape

from aiogram import Bot

from app.config import Config
from app.services.notion import NotionAccounting, NotionClient

LOGGER = logging.getLogger(__name__)

CONTENT_REMINDER_DAYS = (20, 27)
CONTENT_STATUSES = ("work", "new")


def _key(page_id: str | None) -> str:
    return (page_id or "").replace("-", "")


def _days_open(in_date: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat((in_date or "")[:10])).days
    except ValueError:
        return None


def total_files(record: NotionAccounting) -> int:
    """All files for the month, Tango included (`files` alone leaves Tango out)."""
    return record.files + record.tango_files


Target = tuple[int, int | None]  # (chat_id, topic thread id or None)


def _route(lines_by_manager: dict[str | None, list[str]], config: Config) -> dict[Target, list[str]]:
    """Owner: everything. Mapped managers: their own lines. Same target never gets it twice."""
    owner: Target | None = (config.owner_telegram_id, None) if config.owner_telegram_id else None
    out: dict[Target, list[str]] = defaultdict(list)
    for manager, lines in lines_by_manager.items():
        if owner:
            out[owner].extend(lines)
        target = config.manager_targets.get((manager or "").strip().lower())
        if target and target != owner:
            out[target].extend(lines)
    return out


async def overdue_orders(config: Config, notion: NotionClient, today: date) -> dict[str | None, list[str]]:
    """Open orders older than OVERDUE_ORDER_DAYS, grouped by manager, oldest first."""
    orders = await notion.query_all_open_orders(config.db_orders)
    if not orders:
        return {}
    models = {_key(m.page_id): m.title for m in await notion.query_all_models(config.db_models)}
    records = await notion.query_accounting_for_month(config.db_accounting, today.strftime("%Y-%m"))
    manager_of = {_key(r.model_id): r.assist for r in records if r.model_id}

    rows: list[tuple[int, str | None, str]] = []
    for order in orders:
        days = _days_open(order.in_date, today)
        if days is None or days <= config.overdue_order_days:
            continue
        mid = _key(order.model_id)
        name = models.get(mid) or order.title
        rows.append((days, manager_of.get(mid), f"• {escape(name)} — {escape(order.order_type or '?')} · {days} дн"))

    grouped: dict[str | None, list[str]] = defaultdict(list)
    for _, manager, line in sorted(rows, key=lambda r: -r[0]):
        grouped[manager].append(line)
    return grouped


async def low_content(config: Config, notion: NotionClient, today: date) -> dict[str | None, list[str]]:
    """Models in `work`/`new` with fewer than LOW_CONTENT_THRESHOLD files this month."""
    models = [m for m in await notion.query_all_models(config.db_models)
              if (m.status or "").strip().lower() in CONTENT_STATUSES]
    records = await notion.query_accounting_for_month(config.db_accounting, today.strftime("%Y-%m"))
    record_of = {_key(r.model_id): r for r in records if r.model_id}

    rows: list[tuple[int, str | None, str]] = []
    for model in models:
        record = record_of.get(_key(model.page_id))
        files = total_files(record) if record else 0
        if files >= config.low_content_threshold:
            continue
        manager = record.assist if record else None
        rows.append((files, manager, f"• {escape(model.title)} — {files} файлов"))

    grouped: dict[str | None, list[str]] = defaultdict(list)
    for _, manager, line in sorted(rows, key=lambda r: r[0]):
        grouped[manager].append(line)
    return grouped


async def _send(bot: Bot, target: Target, header: str, lines: list[str]) -> None:
    text = f"{header} ({len(lines)})\n\n" + "\n".join(lines)
    if len(text) > 4000:
        text = text[: text.rfind("\n", 0, 4000)] + "\n…"
    chat_id, thread_id = target
    await bot.send_message(chat_id, text, parse_mode="HTML", message_thread_id=thread_id)


async def run_daily_reminders(bot: Bot, config: Config, notion: NotionClient) -> None:
    """Scheduled entry point. Never raises; each reminder fails independently."""
    today = datetime.now(config.timezone).date()

    jobs = [("⏳ <b>Заказы открыты дольше {n} дн</b>".format(n=config.overdue_order_days), overdue_orders)]
    if today.day in CONTENT_REMINDER_DAYS:
        jobs.append(("📉 <b>Мало контента за месяц (меньше {n} файлов)</b>".format(n=config.low_content_threshold),
                     low_content))

    for header, build in jobs:
        try:
            per_chat = _route(await build(config, notion, today), config)
            for target, lines in per_chat.items():
                if not lines:
                    continue
                try:
                    await _send(bot, target, header, lines)
                except Exception:
                    # e.g. a manager who never pressed Start — others still get theirs
                    LOGGER.exception("Reminder %s not delivered to %s", build.__name__, target)
        except Exception as e:
            LOGGER.exception("Reminder failed: %s", build.__name__)
            if config.owner_telegram_id:
                try:
                    await bot.send_message(config.owner_telegram_id, f"⚠️ Reminder failed ({build.__name__}): {e}")
                except Exception:
                    LOGGER.exception("Failed to notify owner of reminder failure")
