"""Orchestrates the WML CRM -> Notion/Telegram sync.

Runs on a schedule (Cloud Scheduler -> /internal/scrape-wml). Never lets an
exception disappear silently: any failure is reported to the owner via
Telegram instead of the job just quietly doing nothing.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

import requests
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Config
from app.services.notion import NotionClient, NotionModel
from app.services.wml_client import WmlProfile, WmlProfileDetail, fetch_profile_detail_html, fetch_statistics_html, parse_profile_detail, parse_statistics

LOGGER = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    return title.strip().lower()


_TANGO_SLOT_RE = re.compile(r"^танго\s+(\d+)")


def _tango_fallback_key(key: str) -> str | None:
    """WML sometimes glues a "Танго" annotation onto an already-onboarded
    model's name: "ХанамиТанго"/"Смайл Танго" (base name + Tango suffix), or
    "Танго 26 ( сигма)"/"Танго 16 (Бьякуя)" (slot number + free-text note).
    Both forms fail an exact title match; this recovers the base identity
    (bare name, or slot number) so real duplicates aren't flagged as new.

    IMPORTANT — this must NEVER strip a bare "Танго <name>" prefix (no slot
    number) down to just "<name>": unlike the suffix form (confirmed via
    screenshots to be the same already-onboarded model, just WML CRM listing
    it twice), a Tango-prefixed name without a number is its own persistent
    Notion page, separate from the bare-name model (e.g. "ТангоКейптаун" is
    NOT the same record as "КЕЙПТАУН" — see [[project_wml_sync_feature]]).
    Confirmed live 2026-07-31: an earlier version of this function did strip
    that prefix and wrongly matched "Танго Кейптаун" to the bare "КЕЙПТАУН"
    page instead of leaving them distinct. See `_tango_prefix_collapse_key`
    for the safe way to match cosmetic spacing differences on that form.

    Applied to BOTH sides of the match (see `build_notion_title_index`) —
    the annotation, and its free-text note, can land on either the WML name
    or the existing Notion title, and the two notes don't have to agree
    (e.g. WML "Танго 34 John" vs Notion "Танго 34 ЕКБ" — same slot, only the
    slot number is the real identity). Returns None if no Tango annotation
    is present (nothing to fall back to)."""
    slot_match = _TANGO_SLOT_RE.match(key)
    if slot_match:
        return f"танго {slot_match.group(1)}"
    if key.endswith("танго") and len(key) > len("танго"):
        return key[: -len("танго")].strip()
    return None


def _tango_prefix_collapse_key(key: str) -> str | None:
    """For a bare "Танго <name>" prefix (no slot number) — NOT a candidate
    for `_tango_fallback_key`, which would wrongly conflate it with the
    unrelated bare-name model. This only collapses internal whitespace, so
    "танго кейптаун" (spaced) and "тангокейптаун" (concatenated) resolve to
    the same identity as each other, while staying completely distinct from
    "кейптаун" alone. Returns None if the key isn't Tango-prefixed."""
    if not key.startswith("танго") or _TANGO_SLOT_RE.match(key):
        return None
    return re.sub(r"\s+", "", key)


@dataclass
class NotionTitleIndex:
    by_title: dict[str, NotionModel]
    ambiguous: set[str]
    tango_alias: dict[str, NotionModel]
    tango_ambiguous: set[str]
    tango_prefix_collapse: dict[str, NotionModel]
    tango_prefix_collapse_ambiguous: set[str]


def build_notion_title_index(existing: list[NotionModel]) -> NotionTitleIndex:
    """Three lookups over existing Notion models: raw normalized titles, a
    Tango-fallback alias for titles that carry their own Tango annotation
    (so a WML name with a different note for the same slot/base name still
    resolves — see _tango_fallback_key), and a whitespace-collapsed index
    for bare Tango-prefixed titles (see _tango_prefix_collapse_key) — kept
    separate so it can never match against an unrelated bare-name model."""
    by_title: dict[str, NotionModel] = {}
    ambiguous: set[str] = set()
    tango_alias: dict[str, NotionModel] = {}
    tango_ambiguous: set[str] = set()
    tango_prefix_collapse: dict[str, NotionModel] = {}
    tango_prefix_collapse_ambiguous: set[str] = set()
    for m in existing:
        key = _normalize_title(m.title)
        if key in by_title:
            ambiguous.add(key)
        else:
            by_title[key] = m

        tango_key = _tango_fallback_key(key)
        if tango_key:
            if tango_key in tango_alias:
                tango_ambiguous.add(tango_key)
            else:
                tango_alias[tango_key] = m

        collapse_key = _tango_prefix_collapse_key(key)
        if collapse_key:
            if collapse_key in tango_prefix_collapse:
                tango_prefix_collapse_ambiguous.add(collapse_key)
            else:
                tango_prefix_collapse[collapse_key] = m

    return NotionTitleIndex(
        by_title, ambiguous, tango_alias, tango_ambiguous,
        tango_prefix_collapse, tango_prefix_collapse_ambiguous,
    )


def resolve_wml_match(key: str, index: NotionTitleIndex) -> NotionModel | None:
    """Resolve a normalized WML profile name to an existing Notion model,
    trying an exact title match first, then the Tango-annotation fallback
    against both raw titles and the Tango-alias index, then the bare
    Tango-prefix whitespace-collapse index. Ambiguous keys are never
    guessed."""
    if key in index.ambiguous:
        return None

    model = index.by_title.get(key)
    if model is not None:
        return model

    fallback_key = _tango_fallback_key(key)
    if fallback_key:
        if fallback_key not in index.ambiguous:
            model = index.by_title.get(fallback_key)
        if model is None and fallback_key not in index.tango_ambiguous:
            model = index.tango_alias.get(fallback_key)
        if model:
            return model

    collapse_key = _tango_prefix_collapse_key(key)
    if collapse_key and collapse_key not in index.tango_prefix_collapse_ambiguous:
        model = index.tango_prefix_collapse.get(collapse_key)
    return model


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


WML_SEEN_REDIS_KEY = "wml:seen_ids"


async def run_wml_sync(bot, config: Config, notion: NotionClient, redis=None) -> None:
    """Scrape WML, diff against Notion, notify the owner. Never raises."""
    if not config.owner_telegram_id:
        LOGGER.warning("WML sync skipped: OWNER_TELEGRAM_ID not configured")
        return

    try:
        await _run_wml_sync_inner(bot, config, notion, redis)
    except Exception as e:
        LOGGER.exception("WML sync failed")
        try:
            await bot.send_message(
                chat_id=config.owner_telegram_id,
                text=f"⚠️ WML sync failed: {e}",
            )
        except Exception:
            LOGGER.exception("Failed to notify owner of WML sync failure")


async def _run_wml_sync_inner(bot, config: Config, notion: NotionClient, redis) -> None:
    if not config.wml_username or not config.wml_password:
        raise RuntimeError("WML_USERNAME/WML_PASSWORD not configured")

    session = requests.Session()
    html = await asyncio.to_thread(
        fetch_statistics_html, session, config.wml_username, config.wml_password
    )
    profiles = parse_statistics(html)

    existing = await notion.query_all_models(config.db_models)
    index = build_notion_title_index(existing)

    LOGGER.info("WML sync: %d WML profiles, %d Notion models (%d ambiguous titles)",
                len(profiles), len(existing), len(index.ambiguous))

    seen_ids: set[str] = set()
    if redis is not None:
        seen_ids = await redis.smembers(WML_SEEN_REDIS_KEY)

    for profile in profiles:
        key = _normalize_title(profile.name)
        if key in index.ambiguous:
            LOGGER.warning("Skipping ambiguous Notion title match for WML profile: %s", profile.name)
            continue

        model = resolve_wml_match(key, index)
        if model and key not in index.by_title:
            fallback_key = _tango_fallback_key(key) or _tango_prefix_collapse_key(key)
            LOGGER.info("WML profile matched via Tango-annotation fallback (%r -> %r): %s",
                        key, fallback_key, profile.name)

        if model is None:
            if profile.wml_id and profile.wml_id in seen_ids:
                LOGGER.info("WML profile new but already notified before, skipping: %s (id=%s)",
                            profile.name, profile.wml_id)
                continue
            LOGGER.info("WML profile NOT matched in Notion (treated as new): %r (key=%r)",
                        profile.name, key)
            await _notify_new_profile(bot, config, session, profile, redis)
            continue

        LOGGER.info("WML profile matched Notion page %s: %r", model.page_id, profile.name)

        wml_fansly = _parse_wml_date(profile.fansly_date)
        notion_fansly = _parse_notion_date(model.fansly)
        if wml_fansly and wml_fansly != notion_fansly:
            await notion.update_model_fansly(model.page_id, wml_fansly)
            await bot.send_message(
                chat_id=config.owner_telegram_id,
                text=f"📌 <b>{profile.name}</b> йде на Fansly: {wml_fansly.strftime('%d.%m.%Y')}",
                parse_mode="HTML",
            )


async def _notify_new_profile(bot, config: Config, session: requests.Session, profile: WmlProfile, redis) -> None:
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
        tango_flag = "1" if profile.tango_date else "0"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="➕ Додати в Notion", callback_data=f"wml_add:{profile.wml_id}:{tango_flag}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"wml_reject:{profile.wml_id}"),
            ]]
        )

    await bot.send_message(
        chat_id=config.owner_telegram_id,
        text="\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    if redis is not None and profile.wml_id:
        await redis.sadd(WML_SEEN_REDIS_KEY, profile.wml_id)
