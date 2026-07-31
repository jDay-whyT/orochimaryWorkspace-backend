"""Callback handler for the "Добавить в таблицу" button on unmatched salary
report rows (models whose manager block exists in the sheet but who don't
have a row yet — see app.services.salary_sheet_writer.insert_new_model_row).

Re-runs the same Notion aggregation used by /reports for the single model on
button press, rather than trusting a snapshot from whenever the button was
sent, so the written row reflects current data and there's no separate
token/state store to expire or lose across a Cloud Run restart (mirrors the
wml_add callback's re-fetch pattern).
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.services.notion import NotionClient
from app.services.salary_report import build_salary_report
from app.services.salary_sheet_writer import insert_new_model_row, tab_title_for_month
from app.services.sheets import SheetsClient
from app.utils.telegram import safe_edit_message, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("salary_add:"))
async def cb_salary_add(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    sheets: SheetsClient | None,
) -> None:
    await safe_query_answer(query, "Добавляю...")
    _, yyyy_mm, model_id = query.data.split(":", 2)

    if sheets is None or not config.salary_sheet_id:
        await safe_edit_message(query, "⚠️ Google Sheets для ЗП не настроен.")
        return

    try:
        accounting_records = await notion.query_accounting_for_month(config.db_accounting, yyyy_mm)
        tango_records = await notion.query_tango_accounting(config.db_accounting)
        seen_ids = {r.page_id for r in accounting_records}
        accounting_records += [r for r in tango_records if r.page_id not in seen_ids]
        orders = await notion.query_orders_closed_in_month(config.db_orders, yyyy_mm)
        models = await notion.query_all_models(config.db_models)
    except Exception:
        LOGGER.exception("Failed to fetch salary data for %s add of %s", yyyy_mm, model_id)
        await safe_edit_message(query, "⚠️ Не удалось получить данные из Notion, попробуй позже.")
        return

    report = build_salary_report(accounting_records, orders, models)
    row = next((r for rows in report.values() for r in rows if r.model_id == model_id), None)
    if row is None:
        await safe_edit_message(query, "⚠️ Модель больше не найдена в отчёте за этот месяц.")
        return

    tab_name = tab_title_for_month(yyyy_mm)
    try:
        tabs = await sheets.get_sheet_tabs(config.salary_sheet_id)
        sheet_id = tabs.get(tab_name)
        if sheet_id is None:
            await safe_edit_message(query, f"⚠️ Таб {tab_name} не найден.")
            return
        grid = await sheets.get_tab_grid(config.salary_sheet_id, tab_name)
        new_row = await insert_new_model_row(
            sheets, config.salary_sheet_id, tab_name, sheet_id, grid, row.manager, row,
        )
    except Exception:
        LOGGER.exception("Failed to insert salary row for %s in %s", model_id, tab_name)
        await safe_edit_message(query, "⚠️ Не удалось записать в Google Sheets, попробуй позже.")
        return

    if new_row is None:
        await safe_edit_message(
            query, f"⚠️ Менеджер {row.manager} не найден в табе {tab_name} — добавь вручную."
        )
        return

    await safe_edit_message(
        query,
        f"✅ {row.model_name} добавлена в таб {tab_name} (строка {new_row}).\n"
        f"⚠️ Формулу Оплаты у {row.manager} бот не трогал — поправь диапазон SUM вручную.",
    )


@router.callback_query(F.data.startswith("salary_reject:"))
async def cb_salary_reject(query: CallbackQuery) -> None:
    await safe_query_answer(query, "Отклонено")
    await safe_edit_message(query, "❌ Отклонено.")
