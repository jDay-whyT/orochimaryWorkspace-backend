import html
import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.config import Config
from app.services import NotionClient
from app.utils.accounting import rename_month_in_title
from app.utils.constants import ACCOUNTING_STATUS_WORK
from app.utils.formatting import today

LOGGER = logging.getLogger(__name__)
router = Router()

_YYYY_MM_RE = re.compile(r"^\d{4}-\d{2}$")


def _resolve_month(arg: str | None, config: Config) -> str | None:
    if not arg:
        return today(config.timezone).strftime("%Y-%m")
    arg = arg.strip()
    return arg if _YYYY_MM_RE.match(arg) else None


@router.message(Command("rename_month"))
async def cmd_rename_month(
    message: Message,
    command: CommandObject,
    config: Config,
    notion: NotionClient,
) -> None:
    if message.chat.type != "private":
        return
    if not config.owner_telegram_id or message.from_user.id != config.owner_telegram_id:
        return

    yyyy_mm = _resolve_month(command.args, config)
    if yyyy_mm is None:
        await message.answer("Формат месяца: /rename_month 2026-08")
        return

    await message.answer(f"Переименовываю Accounting-записи (status=work) на {yyyy_mm}…")

    try:
        records = await notion.query_accounting_by_status(config.db_accounting, ACCOUNTING_STATUS_WORK)
    except Exception:
        LOGGER.exception("Failed to fetch accounting records by status for rename_month")
        await message.answer("Не удалось получить записи из Notion, попробуй позже.")
        return

    renamed = 0
    already_current = 0
    skipped: list[str] = []

    for record in records:
        new_title = rename_month_in_title(record.title, yyyy_mm)
        if new_title is None:
            skipped.append(record.title)
            continue
        if new_title == record.title:
            already_current += 1
            continue
        try:
            await notion.update_page_title(record.page_id, new_title)
            renamed += 1
        except Exception:
            LOGGER.exception("Failed to rename accounting page %s to '%s'", record.page_id, new_title)
            skipped.append(record.title)

    lines = [
        f"Готово. Переименовано: {renamed}, уже на {yyyy_mm}: {already_current}.",
    ]
    if skipped:
        lines.append("")
        lines.append(f"⚠️ Пропущено (не удалось распознать месяц в названии), проверь вручную ({len(skipped)}):")
        for title in skipped[:20]:
            lines.append(f"• {html.escape(title)}")
        if len(skipped) > 20:
            lines.append(f"...и ещё {len(skipped) - 20}")

    await message.answer("\n".join(lines), parse_mode="HTML")
