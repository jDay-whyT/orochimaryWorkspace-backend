"""One-way status sync: Models.status -> each model's working Accounting record.

Models is the single source of truth. Only the working record is touched (see
`accounting.working_records`) — archived months live in other databases.
Runs hourly alongside the WML sync; never raises.

Until STATUS_SYNC_APPLY=1 it only reports what it would change. It also reports
models that have more than one record in Accounting (duplicates). Each report is
one message to the owner, re-sent only when its list changes.
"""

import hashlib
import logging
from datetime import datetime
from html import escape

from aiogram import Bot

from app.config import Config
from app.services.accounting import working_records
from app.services.notion import NotionClient

LOGGER = logging.getLogger(__name__)

# Models has "looted"; Accounting has no such option — it means the model is gone.
_MODEL_TO_ACCOUNTING = {
    "new": "new",
    "work": "work",
    "inactive": "inactive",
    "stop": "stop",
    "looted": "stop",
}

REPORT_SIG_KEY = "status_sync:report_sig"
DUPLICATES_SIG_KEY = "status_sync:duplicates_sig"


async def sync_accounting_status(
    config: Config, notion: NotionClient, apply: bool,
) -> tuple[list[str], list[str]]:
    """Align working Accounting records with Models.

    Returns (status change lines, duplicate-record lines).
    """
    yyyy_mm = datetime.now(config.timezone).strftime("%Y-%m")
    models = await notion.query_all_models(config.db_models)
    records = await notion.query_all_accounting(config.db_accounting)
    working, duplicates = working_records(records, yyyy_mm)

    titles = {m.page_id.replace("-", ""): m.title for m in models}
    dup_lines = [f"{titles.get(key, '?')}: {len(group)} записи" for key, group in duplicates.items()]

    changes: list[str] = []
    for model in models:
        record = working.get(model.page_id.replace("-", ""))
        if record is None or not model.status:
            continue
        # Never revive a `stop` page: it holds a dead month's never-zeroed numbers,
        # and anything but `stop` puts it back into /reports. A model that returned
        # to work gets a fresh record when files are next added.
        if (record.status or "").strip().lower() == "stop":
            continue
        target = _MODEL_TO_ACCOUNTING.get(model.status.strip().lower())
        if target is None or (record.status or "").strip().lower() == target:
            continue
        if apply:
            await notion.update_accounting_status(record.page_id, target)
        changes.append(f"{model.title}: {record.status or '—'} → {target}")

    if changes:
        LOGGER.info("Accounting status sync (apply=%s): %d: %s", apply, len(changes), changes)
    return changes, dup_lines


async def _report(bot: Bot, config: Config, redis, sig_key: str, header: str, items: list[str]) -> None:
    """One message to the owner, re-sent only when the list changes."""
    lines = sorted(f"• {escape(item)}" for item in items)
    sig = hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()
    if redis is not None and await redis.get(sig_key) == sig:
        return
    text = f"{header} ({len(lines)})\n\n" + "\n".join(lines)
    if len(text) > 4000:
        text = text[: text.rfind("\n", 0, 4000)] + "\n…"
    await bot.send_message(config.owner_telegram_id, text, parse_mode="HTML")
    if redis is not None:
        await redis.set(sig_key, sig)


async def run_status_sync(bot: Bot, config: Config, notion: NotionClient, redis=None) -> None:
    """Scheduled entry point. Never raises; failures are reported to the owner."""
    try:
        changes, duplicates = await sync_accounting_status(config, notion, apply=config.status_sync_apply)
        if not config.owner_telegram_id:
            return
        if changes and not config.status_sync_apply:
            await _report(
                bot, config, redis, REPORT_SIG_KEY,
                "🔎 <b>Статусы Accounting ≠ Models</b>\n"
                "Пока только отчёт — ничего не меняю (включить: STATUS_SYNC_APPLY=1).",
                changes,
            )
        if duplicates:
            await _report(
                bot, config, redis, DUPLICATES_SIG_KEY,
                "⚠️ <b>Дубли в Accounting</b> — у модели больше одной записи, лишние удали вручную",
                duplicates,
            )
    except Exception as e:
        LOGGER.exception("Accounting status sync failed")
        if config.owner_telegram_id:
            try:
                await bot.send_message(config.owner_telegram_id, f"⚠️ Status sync failed: {e}")
            except Exception:
                LOGGER.exception("Failed to notify owner of status sync failure")
