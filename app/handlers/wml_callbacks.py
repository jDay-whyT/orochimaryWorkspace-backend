"""Callback handler for the "Add to Notion" button on WML new-profile notifications.

callback_data carries only the WML numeric profile id (wml_add:{id}) — on
press we re-fetch that profile fresh from WML rather than relying on a
snapshot cached from whenever the notify was sent, so there is no separate
token/state store to expire or lose across a Cloud Run restart.
"""
import asyncio
import logging
from datetime import datetime

import requests
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Config
from app.services.notion import NotionClient
from app.services.wml_client import fetch_profile_by_id, strip_wml_suffix
from app.utils.locks import release_write_lock, try_acquire_write_lock
from app.utils.telegram import is_owner_callback, safe_edit_message, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()

NO_ASSIST = "-"


async def _show_manager_picker(query: CallbackQuery, config: Config, notion: NotionClient,
                               wml_id: str, tango: str) -> None:
    """Step 1 of "Add": pick the manager (Accounting `assist`) before anything is written."""
    try:
        managers = await notion.get_select_options(config.db_accounting, "assist")
    except Exception:
        LOGGER.exception("Failed to read Accounting assist options")
        managers = []
    buttons = [InlineKeyboardButton(text=m, callback_data=f"wml_add:{wml_id}:{tango}:{m}")
               for m in managers if len(f"wml_add:{wml_id}:{tango}:{m}".encode()) <= 64]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([
        InlineKeyboardButton(text="без менеджера", callback_data=f"wml_add:{wml_id}:{tango}:{NO_ASSIST}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"wml_reject:{wml_id}"),
    ])
    await safe_query_answer(query)
    text = (query.message.html_text if query.message and query.message.html_text else "")
    await safe_edit_message(query, f"{text}\n\n👤 Менеджер?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("wml_add:"))
async def cb_wml_add(query: CallbackQuery, config: Config, notion: NotionClient, redis=None) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Немає доступу", show_alert=True)
        return

    parts = query.data.split(":", 3)
    wml_id = parts[1]
    tango = parts[2] if len(parts) > 2 else "0"
    has_tango_date = tango == "1"
    if len(parts) < 4:  # card button (or an old card): choose the manager first
        await _show_manager_picker(query, config, notion, wml_id, tango)
        return
    assist = None if parts[3] == NO_ASSIST else parts[3]

    lock_key = f"wml_add_lock:{wml_id}"
    if not await try_acquire_write_lock(redis, lock_key):
        await safe_query_answer(query, "⏳ Вже додається...", show_alert=True)
        return

    try:
        await safe_query_answer(query, "Додаю...")

        if not config.wml_username or not config.wml_password:
            await safe_edit_message(query, "⚠️ WML креди не налаштовані.")
            return

        try:
            session = requests.Session()
            detail = await asyncio.to_thread(
                fetch_profile_by_id, session, config.wml_username, config.wml_password, wml_id
            )
        except Exception as e:
            LOGGER.exception("Failed to fetch WML profile %s for Notion add", wml_id)
            await safe_edit_message(query, f"⚠️ Не вдалось отримати дані з WML: {e}")
            return

        if not detail.wml_name:
            await safe_edit_message(query, "⚠️ Профіль не знайдено на WML.")
            return

        title = strip_wml_suffix(detail.wml_name)
        if title is None:
            await safe_edit_message(query, "⛔ Профіль виключено (ИИ).")
            return

        existing = await notion.query_all_models(config.db_models)
        if any(m.title.strip().lower() == title.lower() for m in existing):
            await safe_edit_message(query, f"ℹ️ {title} вже є в Notion.")
            return

        project = detail.office or None
        if not project and has_tango_date:
            project = "TANGO"

        from app.handlers import models as models_list

        model_page_id = await notion.create_model_from_wml(
            database_id=config.db_models,
            title=title,
            scoutname=detail.scout.strip().lower() if detail.scout else None,
            project=project,
            language=detail.language,
            location=detail.location,
            comment=detail.comment,
        )
        await models_list.invalidate()  # the new model must be findable right away

        yyyy_mm = datetime.now(tz=config.timezone).strftime("%Y-%m")
        try:
            await notion.create_new_model_accounting(
                config.db_accounting, model_page_id, title, yyyy_mm, assist=assist,
            )
            accounting_line = f"\nAccounting: {assist or 'без менеджера'}"
        except Exception:
            LOGGER.exception("Accounting record for new model %s failed", title)
            accounting_line = "\n⚠️ Accounting не створено, додай вручну."

        extra_lines = []
        if detail.tg_content_manager:
            extra_lines.append(f"TG контент-менеджер: {detail.tg_content_manager}")
        if detail.model_telegram:
            extra_lines.append(f"TG моделі: {detail.model_telegram}")
        extra = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

        await safe_edit_message(query, f"✅ {title} додано в Notion.{accounting_line}{extra}")
    finally:
        await release_write_lock(redis, lock_key)


@router.callback_query(F.data.startswith("wml_reject:"))
async def cb_wml_reject(query: CallbackQuery, config: Config) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Немає доступу", show_alert=True)
        return
    await safe_query_answer(query, "Відхилено")
    await safe_edit_message(query, "❌ Відхилено.")
