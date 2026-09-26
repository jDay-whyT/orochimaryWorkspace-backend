"""Daily log of editor writes (orders, shoots, files) + evening digest to the owner.

Entries live in Redis under ``activity:YYYY-MM-DD`` (config timezone) for a few
days. Only users listed in ACTIVITY_DIGEST_USER_IDS are logged (e.g. a new
manager). Without Redis this is a no-op.
"""

import html
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from aiogram import Bot

from app.config import Config

LOGGER = logging.getLogger(__name__)

_KEY_TTL_SECONDS = 3 * 24 * 60 * 60
_redis: Any = None

_ACTION_LABELS = {
    "order": "📦 Заказы",
    "shoot": "📸 Съёмки",
    "files": "📁 Файлы",
}


def init(redis: Any) -> None:
    """Set the async Redis client used for the log (None disables logging)."""
    global _redis
    _redis = redis


def author_label(user: Any) -> str:
    """Human-readable author: @username, else full name, else Telegram ID."""
    username = getattr(user, "username", None)
    if isinstance(username, str) and username:
        return f"@{username}"
    full_name = getattr(user, "full_name", None)
    if isinstance(full_name, str) and full_name:
        return full_name
    return str(getattr(user, "id", "?"))


def _day_key(config: Config, when: datetime | None = None) -> str:
    when = when or datetime.now(tz=config.timezone)
    return f"activity:{when.strftime('%Y-%m-%d')}"


async def record(config: Config, user: Any, action: str, model_name: str, detail: str) -> None:
    """Append one write to today's log. Never raises."""
    if _redis is None or user is None:
        return
    if getattr(user, "id", None) not in config.digest_user_ids:
        return
    entry = {
        "author": author_label(user),
        "action": action,
        "model": model_name,
        "detail": detail,
    }
    try:
        key = _day_key(config)
        await _redis.rpush(key, json.dumps(entry, ensure_ascii=False))
        await _redis.expire(key, _KEY_TTL_SECONDS)
    except Exception:
        LOGGER.warning("Failed to record activity action=%s", action, exc_info=True)


def build_digest(entries: list[dict[str, str]], day_label: str) -> str | None:
    """Group entries by author and action. Returns None when there is nothing."""
    if not entries:
        return None
    by_author: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for e in entries:
        line = f"{html.escape(e.get('model', ''))} — {html.escape(e.get('detail', ''))}"
        by_author[e.get("author", "?")][e.get("action", "")].append(line)

    parts = [f"📋 <b>Сводка за {day_label}</b>"]
    for author, actions in by_author.items():
        parts.append(f"\n<b>{html.escape(author)}</b>")
        for action, lines in actions.items():
            parts.append(f"{_ACTION_LABELS.get(action, action)}:")
            parts.extend(f"• {line}" for line in lines)
    return "\n".join(parts)


async def send_daily_digest(bot: Bot, config: Config) -> None:
    """Send today's digest to the owner; silent when there was no activity."""
    if _redis is None or not config.owner_telegram_id:
        LOGGER.warning("Activity digest skipped: no Redis or OWNER_TELEGRAM_ID")
        return
    now = datetime.now(tz=config.timezone)
    raw = await _redis.lrange(_day_key(config, now), 0, -1)
    entries = []
    for item in raw:
        try:
            entries.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    text = build_digest(entries, now.strftime("%d.%m"))
    if not text:
        return
    # Telegram message limit is 4096 chars; the digest is short in practice.
    if len(text) > 4000:
        text = text[: text.rfind("\n", 0, 4000)] + "\n…"
    await bot.send_message(config.owner_telegram_id, text, parse_mode="HTML")
