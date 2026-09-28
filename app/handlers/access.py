"""Access requests: unknown user /start in DM -> owner approves with a manager button.

/access (owner) lists who has access and lets the owner revoke approved managers.
"""

import html
import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.services import access
from app.services.notion import NotionClient
from app.utils.telegram import is_owner_callback

LOGGER = logging.getLogger(__name__)

router = Router()

_PREFIX = "acc"


class WithoutAccess(BaseFilter):
    """User has no access yet (users with access fall through to start.router)."""

    async def __call__(self, message: Message, config: Config) -> bool:
        user = message.from_user
        return bool(user) and user.id != config.owner_telegram_id and user.id not in config.allowed_editors


def _request_keyboard(user_id: int, assists: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=a, callback_data=f"{_PREFIX}:ok:{user_id}:{a}")] for a in assists]
    rows.append([InlineKeyboardButton(text="Без напоминаний", callback_data=f"{_PREFIX}:ok:{user_id}:{access.NO_ASSIST}")])
    rows.append([InlineKeyboardButton(text="❌ Отклонить", callback_data=f"{_PREFIX}:no:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _assist_options(config: Config, notion: NotionClient) -> list[str]:
    try:
        options = await notion.get_select_options(config.db_accounting, "assist")
    except Exception:
        LOGGER.exception("access: failed to read Accounting assist options")
        options = sorted(config.manager_targets)
    # callback_data is limited to 64 bytes
    return [o for o in options if len(f"{_PREFIX}:ok:{10**13}:{o}".encode()) <= 64]


def _user_line(user_id: int, username: str | None, name: str) -> str:
    handle = f"@{html.escape(username)}" if username else "без username"
    return f"{html.escape(name) or '—'} ({handle}, ID <code>{user_id}</code>)"


@router.message(Command("start"), F.chat.type == "private", WithoutAccess())
async def access_request(message: Message, config: Config, notion: NotionClient, redis: Any = None) -> None:
    """/start in DM from someone without access -> request to the owner."""
    user = message.from_user
    if redis is None or not config.owner_telegram_id:
        await message.answer("⛔ No access. Contact the admin.")
        return

    if not await access.save_request(redis, user.id, user.username, user.full_name or ""):
        request = await access.get_request(redis, user.id) or {}
        if request.get("status") == "rejected":
            await message.answer("⛔ No access. Contact the admin.")
        else:
            await message.answer("⏳ Your request is with the admin, please wait.")
        return

    assists = await _assist_options(config, notion)
    await message.bot.send_message(
        config.owner_telegram_id,
        "🔑 <b>Запрос доступа</b>\n"
        f"{_user_line(user.id, user.username, user.full_name or '')}\n\n"
        "Выбери менеджера (значение assist в Accounting): ему будут приходить напоминания по его моделям, "
        "а тебе — вечерний дайджест его записей.",
        reply_markup=_request_keyboard(user.id, assists),
        parse_mode="HTML",
    )
    LOGGER.info("access: request from user %s (@%s)", user.id, user.username)
    await message.answer("📨 Request sent to the admin. I'll message you once it's approved.")


@router.callback_query(F.data.startswith(f"{_PREFIX}:"))
async def access_callback(query: CallbackQuery, config: Config, redis: Any = None) -> None:
    if not is_owner_callback(query, config):
        await query.answer("Только для админа", show_alert=True)
        return
    if redis is None:
        await query.answer("Redis недоступен", show_alert=True)
        return

    parts = (query.data or "").split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    try:
        user_id = int(parts[2])
    except (IndexError, ValueError):
        await query.answer("Некорректная кнопка", show_alert=True)
        return

    if action == "ok" and len(parts) == 4:
        assist = parts[3]
        info = await access.approve(config, redis, user_id, assist)
        who = access.label(user_id, info)
        role = "без напоминаний" if assist == access.NO_ASSIST else f"менеджер <b>{html.escape(assist)}</b>"
        await query.message.edit_text(f"✅ Доступ открыт: {html.escape(who)} — {role}.", parse_mode="HTML")
        try:
            await query.bot.send_message(user_id, "✅ Access granted. Press /start.")
        except Exception:
            LOGGER.warning("access: could not notify approved user %s", user_id)
        LOGGER.info("access: approved %s as %s", user_id, assist)
    elif action == "no":
        info = await access.reject(redis, user_id)
        await query.message.edit_text(f"❌ Отклонено: {html.escape(access.label(user_id, info))}.", parse_mode="HTML")
        LOGGER.info("access: rejected %s", user_id)
    elif action == "rm":
        info = await access.revoke(config, redis, user_id)
        who = access.label(user_id, info or {})
        await query.message.edit_text(f"🚫 Доступ убран: {html.escape(who)}.", parse_mode="HTML")
        LOGGER.info("access: revoked %s", user_id)
    await query.answer()


@router.message(Command("access"))
async def access_list(message: Message, config: Config, redis: Any = None) -> None:
    """Owner: who has access; approved managers get a revoke button."""
    if not config.owner_telegram_id or message.from_user.id != config.owner_telegram_id:
        return
    managers = await access.load(redis) if redis is not None else {}
    lines = ["🔑 <b>Доступ к боту</b>", "", "<b>Из настроек Cloud Run:</b>"]
    for user_id in sorted(u for u in config.allowed_editors if access.is_env_editor(u, config)):
        lines.append(f"• <code>{user_id}</code>")
    lines += ["", "<b>Одобрены в боте:</b>"]
    buttons = []
    for user_id, info in sorted(managers.items(), key=lambda kv: kv[1].get("approved_at", "")):
        who = access.label(user_id, info)
        assist = info.get("assist") or access.NO_ASSIST
        lines.append(f"• {html.escape(who)} — {html.escape(assist)} (<code>{user_id}</code>)")
        buttons.append([InlineKeyboardButton(text=f"🚫 Убрать {who}", callback_data=f"{_PREFIX}:rm:{user_id}")])
    if not managers:
        lines.append("— пока никого")
    await message.answer("\n".join(lines), parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)
