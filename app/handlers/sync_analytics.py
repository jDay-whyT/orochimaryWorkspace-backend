"""Handler for /sync_analytics command."""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.roles import can_edit
from app.services import NotionClient
from app.services.analytics import run_analytics_sync

LOGGER = logging.getLogger(__name__)
router = Router()


@router.message(Command("sync_analytics"))
async def cmd_sync_analytics(
    message: Message,
    config: Config,
    notion: NotionClient,
) -> None:
    """Sync Notion → Google Sheets and write winrates back to Notion."""
    if not can_edit(message.from_user.id, config):
        await message.answer("⛔ Нет доступа.")
        return

    status_msg = await message.answer("⏳ Синхронизация...")

    try:
        result = await run_analytics_sync(
            notion=notion,
            db_models=config.db_models,
            db_orders=config.db_orders,
            db_planner=config.db_planner,
            db_accounting=config.db_accounting,
        )
    except Exception as exc:
        LOGGER.exception("Analytics sync failed: %s", exc)
        await status_msg.edit_text(f"❌ Ошибка синхронизации:\n<code>{exc}</code>", parse_mode="HTML")
        return

    elapsed = round(result.elapsed_sec)
    errors_block = ""
    if result.errors:
        errors_block = "\n" + "\n".join(f"⚠️ {e}" for e in result.errors)

    report = (
        f"✅ Синхронизация завершена за {elapsed}s\n"
        f"├ Моделей: {result.n_models}\n"
        f"├ Ордеров: {result.n_orders} (за 2 мес)\n"
        f"├ Съёмок: {result.n_shoots}\n"
        f"├ Аккаунтинг: {result.n_accounting}\n"
        f"├ Forms: {result.n_forms}\n"
        f"└ Winrate обновлён: {result.n_winrate} моделей"
        f"{errors_block}"
    )

    await status_msg.edit_text(report)
