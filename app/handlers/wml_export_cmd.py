"""/wml_test_orders — owner-only test push of a month's orders to the WML CRM.

Shows what would be sent (counts + one example request); nothing leaves until
the owner presses the button. Re-running is safe: orders that already have a
`wml_id` in Notion are skipped.
"""
import html
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Config
from app.services.notion import NotionClient
from app.services.wml_api import WmlApi
from app.services.wml_export import pick_files, pick_month_orders, send_files, send_orders
from app.utils.locks import release_write_lock, try_acquire_write_lock
from app.utils.telegram import is_owner_callback, safe_edit_message, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()

TEST_MONTH = "2026-09"
TEST_LIMIT = 100


def _type_counts(items) -> str:
    counts: dict[str, int] = {}
    for order, _ in items:
        counts[order.order_type or "?"] = counts.get(order.order_type or "?", 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


@router.message(Command("wml_test_orders"))
async def cmd_wml_test_orders(message: Message, command: CommandObject, config: Config, notion: NotionClient) -> None:
    if message.chat.type != "private":
        return
    if not config.owner_telegram_id or message.from_user.id != config.owner_telegram_id:
        return

    batch = await pick_month_orders(config, notion, TEST_MONTH, TEST_LIMIT)
    if not batch.items:
        await message.answer(f"Нечего отправлять за {TEST_MONTH} (уже отправлено: {batch.already_sent}).")
        return

    closed = sum(1 for _, p in batch.items if "out" in p)
    skipped = ", ".join(f"{reason} {n}" for reason, n in batch.skipped.most_common()) or "—"
    example = json.dumps(batch.items[0][1], ensure_ascii=False)
    text = (
        f"📤 <b>Тест выгрузки заказов в CRM за {TEST_MONTH}</b>\n\n"
        f"К отправке: <b>{len(batch.items)}</b> ({html.escape(_type_counts(batch.items))})\n"
        f"Закрытых (с out): {closed}, открытых: {len(batch.items) - closed}\n"
        f"Пропущено: {html.escape(skipped)}\n"
        f"Уже отправлены раньше: {batch.already_sent}\n\n"
        f"Пример запроса:\n<code>{html.escape(example)}</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📤 Отправить {len(batch.items)} в CRM", callback_data=f"wml_orders_send:{TEST_MONTH}"),
    ]])
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("wml_orders_send:"))
async def cb_wml_orders_send(query: CallbackQuery, config: Config, notion: NotionClient, redis=None) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Нет доступа", show_alert=True)
        return
    yyyy_mm = query.data.split(":", 1)[1]

    lock_key = f"wml_orders_send_lock:{yyyy_mm}"
    if not await try_acquire_write_lock(redis, lock_key):
        await safe_query_answer(query, "⏳ Уже отправляется...", show_alert=True)
        return
    try:
        await safe_query_answer(query, "Отправляю...")
        if not config.wml_username or not config.wml_password:
            await safe_edit_message(query, "⚠️ WML логин не настроен.")
            return
        # Re-pick at press time: anything sent meanwhile already has a wml_id.
        batch = await pick_month_orders(config, notion, yyyy_mm, TEST_LIMIT)
        await safe_edit_message(query, f"⏳ Отправляю {len(batch.items)} заказов…")
        sent, errors = await send_orders(WmlApi(config.wml_username, config.wml_password), notion, batch.items)

        lines = [f"✅ Отправлено в CRM: <b>{sent}</b> из {len(batch.items)}."]
        if errors:
            lines.append(f"\n⚠️ Ошибки ({len(errors)}):")
            lines.extend(f"• {html.escape(e[:200])}" for e in errors[:15])
        await safe_edit_message(query, "\n".join(lines), parse_mode="HTML")
    except Exception as e:
        LOGGER.exception("WML test orders send failed")
        await safe_edit_message(query, f"⚠️ Не получилось: {html.escape(str(e))}", parse_mode="HTML")
    finally:
        await release_write_lock(redis, lock_key)


# ---------------------------------------------------------------------------
# /wml_test_files [N] — monthly file counts (N = only the N biggest by Total)
# ---------------------------------------------------------------------------

def _top(batch, top: int):
    """Keep only the `top` models with the most files (0 = all)."""
    if top:
        batch.items = sorted(batch.items, key=lambda item: item[1]["total"], reverse=True)[:top]
    return batch


@router.message(Command("wml_test_files"))
async def cmd_wml_test_files(message: Message, command: CommandObject, config: Config, notion: NotionClient) -> None:
    if message.chat.type != "private":
        return
    if not config.owner_telegram_id or message.from_user.id != config.owner_telegram_id:
        return

    from datetime import datetime
    top = int(command.args) if command.args and command.args.strip().isdigit() else 0
    batch = _top(await pick_files(config, notion, datetime.now(config.timezone).strftime("%Y-%m")), top)
    if not batch.items:
        await message.answer("Нечего отправлять.")
        return

    skipped = ", ".join(f"{reason} {n}" for reason, n in batch.skipped.most_common()) or "—"
    total_files = sum(p["total"] for _, p in batch.items)
    example = json.dumps(batch.items[0][1], ensure_ascii=False)
    text = (
        f"📁 <b>Тест выгрузки файлов в CRM за {batch.month}</b>"
        f"{f' — топ {top} по Total' if top else ''}\n\n"
        f"Моделей: <b>{len(batch.items)}</b>, файлов всего: {total_files}\n"
        f"Пропущено: {html.escape(skipped)}\n\n"
        f"Пример запроса:\n<code>{html.escape(example)}</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📤 Отправить {len(batch.items)} в CRM", callback_data=f"wml_files_send:{top}"),
    ]])
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("wml_files_send"))
async def cb_wml_files_send(query: CallbackQuery, config: Config, notion: NotionClient, redis=None) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Нет доступа", show_alert=True)
        return

    lock_key = "wml_files_send_lock"
    if not await try_acquire_write_lock(redis, lock_key):
        await safe_query_answer(query, "⏳ Уже отправляется...", show_alert=True)
        return
    try:
        await safe_query_answer(query, "Отправляю...")
        if not config.wml_username or not config.wml_password:
            await safe_edit_message(query, "⚠️ WML логин не настроен.")
            return
        from datetime import datetime
        top_arg = query.data.partition(":")[2]
        top = int(top_arg) if top_arg.isdigit() else 0
        batch = _top(await pick_files(config, notion, datetime.now(config.timezone).strftime("%Y-%m")), top)
        await safe_edit_message(query, f"⏳ Отправляю файлы {len(batch.items)} моделей за {batch.month}…")
        sent, errors = await send_files(WmlApi(config.wml_username, config.wml_password), batch.items)

        lines = [f"✅ Файлы отправлены в CRM: <b>{sent}</b> из {len(batch.items)} моделей ({batch.month})."]
        if errors:
            lines.append(f"\n⚠️ Ошибки ({len(errors)}):")
            lines.extend(f"• {html.escape(e[:200])}" for e in errors[:15])
        await safe_edit_message(query, "\n".join(lines), parse_mode="HTML")
    except Exception as e:
        LOGGER.exception("WML test files send failed")
        await safe_edit_message(query, f"⚠️ Не получилось: {html.escape(str(e))}", parse_mode="HTML")
    finally:
        await release_write_lock(redis, lock_key)
