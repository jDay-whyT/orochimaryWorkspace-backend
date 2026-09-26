"""/rename_month — close the month (owner only).

Shows the plan first; on the button: (1) push the closing month's final file
counts to the WML CRM, (2) rename every `work` Accounting record to the new
month and zero its counts + Content in one request each. Tango records are
not touched. The Notion archive copy is still made by hand BEFORE this.
"""
import html
import logging
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.services import NotionClient
from app.services.month_close import apply_close, month_label, plan_close
from app.services.wml_api import WmlApi
from app.services.wml_export import pick_files, send_files
from app.utils.formatting import today
from app.utils.locks import release_write_lock, try_acquire_write_lock
from app.utils.telegram import is_owner_callback, safe_edit_message, safe_query_answer

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
        await message.answer("Формат месяца: /rename_month 2026-10")
        return

    try:
        plan = await plan_close(config, notion, yyyy_mm)
    except Exception:
        LOGGER.exception("Failed to plan month close for %s", yyyy_mm)
        await message.answer("Не удалось получить записи из Notion, попробуй позже.")
        return

    renamed = sum(1 for item in plan.items if item.new_title)
    lines = [
        f"🗓 <b>Закрытие месяца → {html.escape(month_label(yyyy_mm))}</b>",
        "",
        "Сначала сделай копию баз в архив, если ещё не сделал.",
        "",
        "По кнопке бот:",
        "1. дошлёт в CRM последние цифры файлов за закрываемый месяц;",
        f"2. у <b>{len(plan.items)}</b> записей <code>work</code>: обнулит цифры и Content, "
        f"новое название получат {renamed};",
        f"Танго не трогаю: {plan.tango_skipped}.",
    ]
    if plan.titles_to_fix:
        lines.append("")
        lines.append(f"⚠️ Название не распознано, оставлю как есть ({len(plan.titles_to_fix)}):")
        lines.extend(f"• {html.escape(t)}" for t in plan.titles_to_fix[:15])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Закрыть месяц → {month_label(yyyy_mm)}", callback_data=f"close_month:{yyyy_mm}"),
    ]])
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("close_month:"))
async def cb_close_month(query: CallbackQuery, config: Config, notion: NotionClient, redis=None) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Нет доступа", show_alert=True)
        return
    yyyy_mm = query.data.split(":", 1)[1]

    lock_key = "close_month_lock"
    if not await try_acquire_write_lock(redis, lock_key):
        await safe_query_answer(query, "⏳ Уже закрывается...", show_alert=True)
        return
    try:
        await safe_query_answer(query, "Закрываю месяц...")
        lines: list[str] = []

        # 1. Final push of the closing month's counts, while records still hold them.
        if config.wml_username and config.wml_password:
            await safe_edit_message(query, "⏳ Досылаю цифры в CRM…")
            try:
                batch = await pick_files(config, notion, datetime.now(config.timezone).strftime("%Y-%m"))
                sent, errors = await send_files(WmlApi(config.wml_username, config.wml_password), batch.items)
                lines.append(f"📤 CRM ({batch.month}): отправлено {sent} из {len(batch.items)}.")
                lines.extend(f"  ⚠️ {html.escape(e[:150])}" for e in errors[:10])
            except Exception as e:
                LOGGER.exception("Final CRM files push failed before month close")
                lines.append(f"⚠️ В CRM дослать не получилось: {html.escape(str(e))}. Месяц всё равно закрываю.")

        # 2. Rename + zero, one request per record.
        await safe_edit_message(query, "⏳ Переименовываю и обнуляю записи…")
        plan = await plan_close(config, notion, yyyy_mm)
        done, errors = await apply_close(notion, plan, redis)
        lines.append(f"🗓 Записей обработано: {done} из {len(plan.items)} → {html.escape(month_label(yyyy_mm))}.")
        if errors:
            lines.append(f"⚠️ Ошибки ({len(errors)}):")
            lines.extend(f"• {html.escape(e[:150])}" for e in errors[:15])
        await safe_edit_message(query, "✅ Месяц закрыт.\n\n" + "\n".join(lines), parse_mode="HTML")
    except Exception as e:
        LOGGER.exception("Month close failed")
        await safe_edit_message(query, f"⚠️ Не получилось: {html.escape(str(e))}", parse_mode="HTML")
    finally:
        await release_write_lock(redis, lock_key)
