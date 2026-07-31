"""Callback handler for the "Добавить в таблицу" button on unmatched salary
report rows (models whose manager block exists in the sheet but who don't
have a row yet — see app.services.salary_sheet_writer.insert_new_model_row).

The row is read from the Redis cache /reports populated when it sent the
button (see salary_pending_redis_key) — NOT re-fetched from Notion. A button
press used to re-run the full month's Accounting/Orders/Models query just to
recover one row's data; in prod (2026-07-31) that took 90-250s per press
(Notion was under load) and once left the shared Sheets aiohttp session
stale enough to fail with a broken-pipe error on the eventual Sheets call.
Falls back to a full re-fetch only if the cache entry is missing/expired or
Redis isn't configured, so a stale/cold cache degrades to "slow" rather than
"broken".
"""
import dataclasses
import json
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.services.notion import NotionClient
from app.services.salary_report import ModelSalaryRow, build_salary_report, salary_pending_redis_key
from app.services.salary_sheet_writer import insert_new_model_row, tab_title_for_month
from app.services.sheets import SheetsClient
from app.utils.locks import release_write_lock, try_acquire_write_lock
from app.utils.telegram import is_owner_callback, safe_edit_message, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()


async def _load_row(redis, notion: NotionClient, config: Config, yyyy_mm: str, model_id: str) -> ModelSalaryRow | None:
    if redis is not None:
        cached = await redis.get(salary_pending_redis_key(yyyy_mm, model_id))
        if cached:
            return ModelSalaryRow(**json.loads(cached))

    accounting_records = await notion.query_accounting_for_month(config.db_accounting, yyyy_mm)
    tango_records = await notion.query_tango_accounting(config.db_accounting)
    seen_ids = {r.page_id for r in accounting_records}
    accounting_records += [r for r in tango_records if r.page_id not in seen_ids]
    orders = await notion.query_orders_closed_in_month(config.db_orders, yyyy_mm)
    models = await notion.query_all_models(config.db_models)
    report = build_salary_report(accounting_records, orders, models)
    return next((r for rows in report.values() for r in rows if r.model_id == model_id), None)


@router.callback_query(F.data.startswith("salary_add:"))
async def cb_salary_add(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    sheets: SheetsClient | None,
    redis=None,
) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Нет доступа", show_alert=True)
        return

    parts = query.data.split(":", 2)
    if len(parts) != 3:
        await safe_query_answer(query, "⚠️ Некорректные данные", show_alert=True)
        return
    _, yyyy_mm, model_id = parts

    lock_key = f"salary_add_lock:{yyyy_mm}:{model_id}"
    if not await try_acquire_write_lock(redis, lock_key):
        await safe_query_answer(query, "⏳ Уже добавляется...", show_alert=True)
        return

    try:
        await safe_query_answer(query, "Добавляю...")

        if sheets is None or not config.salary_sheet_id:
            await safe_edit_message(query, "⚠️ Google Sheets для ЗП не настроен.")
            return

        try:
            row = await _load_row(redis, notion, config, yyyy_mm, model_id)
        except Exception:
            LOGGER.exception("Failed to fetch salary data for %s add of %s", yyyy_mm, model_id)
            await safe_edit_message(query, "⚠️ Не удалось получить данные из Notion, попробуй позже.")
            return

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

        if redis is not None:
            await redis.delete(salary_pending_redis_key(yyyy_mm, model_id))

        await safe_edit_message(
            query,
            f"✅ {row.model_name} добавлена в таб {tab_name} (строка {new_row}).\n"
            f"⚠️ Формулу Оплаты у {row.manager} бот не трогал — поправь диапазон SUM вручную.",
        )
    finally:
        await release_write_lock(redis, lock_key)


@router.callback_query(F.data.startswith("salary_reject:"))
async def cb_salary_reject(query: CallbackQuery, config: Config) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Нет доступа", show_alert=True)
        return
    await safe_query_answer(query, "Отклонено")
    await safe_edit_message(query, "❌ Отклонено.")
