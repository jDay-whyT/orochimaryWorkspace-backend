"""One-way status sync: Models.status -> current month's Accounting.status.

Models is the single source of truth. Past months are never touched (the
salary report reads each month's own status). Runs hourly alongside the WML
sync; never raises.
"""

import logging
from datetime import datetime

from aiogram import Bot

from app.config import Config
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


async def sync_accounting_status(config: Config, notion: NotionClient) -> list[str]:
    """Align this month's Accounting statuses with Models. Returns change lines."""
    yyyy_mm = datetime.now(config.timezone).strftime("%Y-%m")
    models = await notion.query_all_models(config.db_models)
    records = await notion.query_accounting_for_month(config.db_accounting, yyyy_mm)

    model_by_id = {m.page_id.replace("-", ""): m for m in models}
    changes: list[str] = []
    for record in records:
        if not record.model_id:
            continue
        model = model_by_id.get(record.model_id.replace("-", ""))
        if model is None or not model.status:
            continue
        target = _MODEL_TO_ACCOUNTING.get(model.status.strip().lower())
        if target is None or (record.status or "").strip().lower() == target:
            continue
        await notion.update_accounting_status(record.page_id, target)
        changes.append(f"{model.title}: {record.status or '—'} → {target}")

    if changes:
        LOGGER.info("Accounting status sync (%s): %d changed: %s", yyyy_mm, len(changes), changes)
    return changes


async def run_status_sync(bot: Bot, config: Config, notion: NotionClient) -> None:
    """Scheduled entry point. Never raises; failures are reported to the owner."""
    try:
        await sync_accounting_status(config, notion)
    except Exception as e:
        LOGGER.exception("Accounting status sync failed")
        if config.owner_telegram_id:
            try:
                await bot.send_message(config.owner_telegram_id, f"⚠️ Status sync failed: {e}")
            except Exception:
                LOGGER.exception("Failed to notify owner of status sync failure")
