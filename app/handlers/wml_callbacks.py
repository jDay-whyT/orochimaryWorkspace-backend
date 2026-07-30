"""Callback handler for the "Add to Notion" button on WML new-profile notifications.

callback_data carries only the WML numeric profile id (wml_add:{id}) — on
press we re-fetch that profile fresh from WML rather than relying on a
snapshot cached from whenever the notify was sent, so there is no separate
token/state store to expire or lose across a Cloud Run restart.
"""
import asyncio
import logging

import requests
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.services.notion import NotionClient
from app.services.wml_client import fetch_profile_by_id, strip_wml_suffix
from app.utils.telegram import safe_edit_message, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("wml_add:"))
async def cb_wml_add(query: CallbackQuery, config: Config, notion: NotionClient) -> None:
    await safe_query_answer(query, "Додаю...")
    wml_id = query.data.split(":", 1)[1]

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

    await notion.create_model_from_wml(
        database_id=config.db_models,
        title=title,
        scoutname=detail.scout.strip().lower() if detail.scout else None,
        project=detail.office or None,
        language=detail.language,
        location=detail.location,
        comment=detail.comment,
    )

    extra_lines = []
    if detail.tg_content_manager:
        extra_lines.append(f"TG контент-менеджер: {detail.tg_content_manager}")
    if detail.model_telegram:
        extra_lines.append(f"TG моделі: {detail.model_telegram}")
    extra = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

    await safe_edit_message(query, f"✅ {title} додано в Notion.{extra}")
