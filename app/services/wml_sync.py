"""Orchestrates the WML CRM -> Notion/Telegram sync.

Runs on a schedule (Cloud Scheduler -> /internal/scrape-wml). Never lets an
exception disappear silently: any failure is reported to the owner via
Telegram instead of the job just quietly doing nothing.
"""
import asyncio
import logging
from datetime import date, datetime

import requests
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Config
from app.services.notion import NotionClient, NotionModel
from app.services.wml_client import WmlProfile, WmlProfileDetail, fetch_profile_detail_html, fetch_statistics_html, parse_profile_detail, parse_statistics

LOGGER = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    return title.strip().lower()


def _parse_wml_date(raw: str | None) -> date | None:
    """WML dates are dd.mm.yyyy, sometimes with trailing "(upd: ...)" noise."""
    if not raw:
        return None
    first = raw.split("(")[0].strip()
    try:
        return datetime.strptime(first, "%d.%m.%Y").date()
    except ValueError:
        return None


def _parse_notion_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


async def run_wml_sync(bot, config: Config, notion: NotionClient) -> None:
    """Scrape WML, diff against Notion, notify the owner. Never raises."""
    if not config.owner_telegram_id:
        LOGGER.warning("WML sync skipped: OWNER_TELEGRAM_ID not configured")
        return

    try:
        await _run_wml_sync_inner(bot, config, notion)
    except Exception as e:
        LOGGER.exception("WML sync failed")
        try:
            await bot.send_message(
                chat_id=config.owner_telegram_id,
                text=f"⚠️ WML sync failed: {e}",
            )
        except Exception:
            LOGGER.exception("Failed to notify owner of WML sync failure")


async def _run_wml_sync_inner(bot, config: Config, notion: NotionClient) -> None:
    if not config.wml_username or not config.wml_password:
        raise RuntimeError("WML_USERNAME/WML_PASSWORD not configured")

    session = requests.Session()
    html = await asyncio.to_thread(
        fetch_statistics_html, session, config.wml_username, config.wml_password
    )
    profiles = parse_statistics(html)

    existing = await notion.query_all_models(config.db_models)
    by_title: dict[str, NotionModel] = {}
    ambiguous: set[str] = set()
    for m in existing:
        key = _normalize_title(m.title)
        if key in by_title:
            ambiguous.add(key)
        else:
            by_title[key] = m

    for profile in profiles:
        key = _normalize_title(profile.name)
        if key in ambiguous:
            LOGGER.warning("Skipping ambiguous Notion title match for WML profile: %s", profile.name)
            continue

        model = by_title.get(key)
        if model is None:
            await _notify_new_profile(bot, config, session, profile)
            continue

        wml_fansly = _parse_wml_date(profile.fansly_date)
        notion_fansly = _parse_notion_date(model.fansly)
        if wml_fansly and wml_fansly != notion_fansly:
            await notion.update_model_fansly(model.page_id, wml_fansly)
            await bot.send_message(
                chat_id=config.owner_telegram_id,
                text=f"📌 <b>{profile.name}</b> йде на Fansly: {wml_fansly.strftime('%d.%m.%Y')}",
                parse_mode="HTML",
            )


async def _notify_new_profile(bot, config: Config, session: requests.Session, profile: WmlProfile) -> None:
    detail: WmlProfileDetail | None = None
    if profile.profile_url:
        try:
            detail_html = await asyncio.to_thread(fetch_profile_detail_html, session, profile.profile_url)
            detail = parse_profile_detail(detail_html)
        except Exception:
            LOGGER.exception("Failed to fetch WML profile detail for %s", profile.name)

    lines = [f"🆕 <b>{profile.name}</b>", f"Register: {profile.register_date}"]
    if profile.office:
        lines.append(f"Office: {profile.office}")
    if profile.scout:
        lines.append(f"Scout: {profile.scout}")
    if profile.fansly_date:
        lines.append(f"Fansly: {profile.fansly_date}")
    if detail:
        if detail.location:
            lines.append(f"Location: {detail.location}")
        if detail.language:
            lines.append(f"Language: {detail.language}")
        if detail.tg_content_manager:
            lines.append(f"TG Content Manager: {detail.tg_content_manager}")
        if detail.model_telegram:
            lines.append(f"TG моделі: {detail.model_telegram}")
        if detail.comment:
            lines.append(f"Comment: {detail.comment}")

    keyboard = None
    if profile.wml_id:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="➕ Додати в Notion", callback_data=f"wml_add:{profile.wml_id}")
            ]]
        )

    await bot.send_message(
        chat_id=config.owner_telegram_id,
        text="\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
