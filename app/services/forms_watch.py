"""Tell the owner about new questionnaires in the Forms database.

Runs hourly alongside the WML sync. Redis keeps a cursor (newest `created_time`
seen) plus the ids already announced — Notion's created_time is minute-granular,
so two forms in the same minute are told apart by id. The very first run only
records the current state (no flood of old forms). Never raises.
"""

import logging
import os
from datetime import datetime, timezone
from html import escape
from typing import Any

from aiogram import Bot

from app.config import Config
from app.services.notion import NotionClient, _extract_any_title, _extract_multi_select, _extract_rich_text
from app.utils.constants import DB_FORMS_DEFAULT

LOGGER = logging.getLogger(__name__)

LAST_SEEN_KEY = "forms:last_seen"
SENT_IDS_KEY = "forms:sent_ids"
_SENT_IDS_TTL_SECONDS = 30 * 24 * 60 * 60


def format_form(page: dict[str, Any]) -> str:
    name = _extract_any_title(page) or "без имени"
    parts = [f"📝 <b>Новая анкета: {escape(name)}</b>"]
    lang = _extract_rich_text(page, "lang")
    platforms = _extract_multi_select(page, "optional")
    if lang:
        parts.append(f"Язык: {escape(lang)}")
    if platforms:
        parts.append(f"Платформы: {escape(', '.join(platforms))}")
    url = page.get("url")
    if url:
        parts.append(f'<a href="{escape(url, quote=True)}">Открыть в Notion</a>')
    return "\n".join(parts)


async def check_new_forms(bot: Bot, config: Config, notion: NotionClient, redis) -> int:
    """Send one message per form created since the last run. Returns how many were sent."""
    if redis is None or not config.owner_telegram_id:
        return 0
    db_forms = os.getenv("DB_FORMS", DB_FORMS_DEFAULT).strip()
    last_seen = await redis.get(LAST_SEEN_KEY)
    if not last_seen:
        # First run: start watching from now instead of announcing every old form.
        # Same format as Notion's created_time, so plain string comparison works.
        await redis.set(LAST_SEEN_KEY, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00.000Z"))
        return 0

    pages = await notion.query_pages_created_after(db_forms, last_seen)
    sent = 0
    for page in pages:
        page_id = page.get("id") or ""
        if await redis.sismember(SENT_IDS_KEY, page_id):
            continue
        await bot.send_message(config.owner_telegram_id, format_form(page), parse_mode="HTML",
                               disable_web_page_preview=True)
        sent += 1
        # Remember right after sending, so a later failure never re-sends this one.
        await redis.sadd(SENT_IDS_KEY, page_id)
        await redis.expire(SENT_IDS_KEY, _SENT_IDS_TTL_SECONDS)
        await redis.set(LAST_SEEN_KEY, max(last_seen, page.get("created_time") or last_seen))
    return sent


async def run_forms_watch(bot: Bot, config: Config, notion: NotionClient, redis) -> None:
    """Scheduled entry point. Never raises."""
    try:
        await check_new_forms(bot, config, notion, redis)
    except Exception:
        LOGGER.exception("Forms watch failed")
