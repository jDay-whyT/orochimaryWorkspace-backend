import html
import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.services import NotionClient
from app.services.salary_report import build_salary_report
from app.services.salary_sheet_writer import write_salary_report
from app.services.sheets import SheetsClient
from app.utils.formatting import today

LOGGER = logging.getLogger(__name__)
router = Router()

_YYYY_MM_RE = re.compile(r"^\d{4}-\d{2}$")


def _resolve_month(arg: str | None, config: Config) -> str | None:
    if not arg:
        return today(config.timezone).strftime("%Y-%m")
    arg = arg.strip()
    return arg if _YYYY_MM_RE.match(arg) else None


@router.message(Command("reports"))
async def cmd_reports(
    message: Message,
    command: CommandObject,
    config: Config,
    notion: NotionClient,
    sheets: SheetsClient | None,
) -> None:
    if message.chat.type != "private":
        return
    if not config.owner_telegram_id or message.from_user.id != config.owner_telegram_id:
        return

    if sheets is None or not config.salary_sheet_id:
        await message.answer("Google Sheets для ЗП не настроен (SALARY_SHEET_ID / GOOGLE_SERVICE_ACCOUNT_JSON отсутствуют).")
        return

    yyyy_mm = _resolve_month(command.args, config)
    if yyyy_mm is None:
        await message.answer("Формат месяца: /reports 2026-07")
        return

    await message.answer(f"Собираю отчёт за {yyyy_mm}…")

    try:
        accounting_records = await notion.query_accounting_for_month(config.db_accounting, yyyy_mm)
        tango_records = await notion.query_tango_accounting(config.db_accounting)
        seen_ids = {r.page_id for r in accounting_records}
        accounting_records += [r for r in tango_records if r.page_id not in seen_ids]
        orders = await notion.query_orders_closed_in_month(config.db_orders, yyyy_mm)
        models = await notion.query_all_models(config.db_models)
    except Exception:
        LOGGER.exception("Failed to fetch salary report data for %s", yyyy_mm)
        await message.answer("Не удалось собрать данные из Notion, попробуй позже.")
        return

    report = build_salary_report(accounting_records, orders, models)
    if not report:
        await message.answer(f"Нет данных за {yyyy_mm} (Accounting пуст).")
        return

    try:
        result = await write_salary_report(sheets, config.salary_sheet_id, yyyy_mm, report)
    except Exception:
        LOGGER.exception("Failed to write salary report to Sheets for %s", yyyy_mm)
        await message.answer("Не удалось записать отчёт в Google Sheets, попробуй позже.")
        return

    total_models = sum(len(rows) for rows in report.values())
    lines = [
        f"Готово — таб <b>{html.escape(result.tab_name)}</b> "
        f"({'создан' if result.created_new_tab else 'обновлён'}).",
        f"Моделей в отчёте: {total_models}, записано/обновлено: {result.updated_count}.",
    ]
    if result.unmatched_no_manager:
        lines.append("")
        lines.append(
            f"⚠️ Менеджер не найден в таблице ({len(result.unmatched_no_manager)}), добавь вручную:"
        )
        for row in result.unmatched_no_manager[:20]:
            lines.append(f"• {html.escape(row.manager)} — {html.escape(row.model_name)}")
        if len(result.unmatched_no_manager) > 20:
            lines.append(f"...и ещё {len(result.unmatched_no_manager) - 20}")

    await message.answer("\n".join(lines), parse_mode="HTML")

    for row in result.unmatched[:20]:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="➕ Добавить в таблицу",
                callback_data=f"salary_add:{yyyy_mm}:{row.model_id}",
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"salary_reject:{row.model_id}",
            ),
        ]])
        await message.answer(
            f"🆕 <b>{html.escape(row.model_name)}</b> ({html.escape(row.manager)}) "
            f"не найдена в табе <b>{html.escape(result.tab_name)}</b>.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    if len(result.unmatched) > 20:
        await message.answer(f"...и ещё {len(result.unmatched) - 20} без кнопки, добавь вручную.")
