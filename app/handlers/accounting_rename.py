"""/rename_month — close the month (owner only).

Shows the plan first; on the button: (1) push the closing month's final file
counts and the current orders to the WML CRM, (2) rename every `work` Accounting record to the new
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
from app.services.salary_report import salary_reported_redis_key
from app.services.wml_api import WmlApi
from app.services.wml_export import pick_files, send_files
from app.services.wml_scheduled import push_orders_now
from app.utils.formatting import today
from app.utils.locks import release_write_lock, try_acquire_write_lock
from app.utils.telegram import is_owner_callback, safe_edit_message, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()

_YYYY_MM_RE = re.compile(r"^\d{4}-\d{2}$")


def previous_month(yyyy_mm: str) -> str:
    year, month = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


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
    redis=None,
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
        "1. дошлёт в CRM последние цифры файлов и текущие заказы (чтобы дата выхода дошла до удаления выполненных);",
        f"2. у <b>{len(plan.items)}</b> записей <code>work</code>: обнулит цифры и очистит Content (теги Reddit и Tango останутся), "
        f"новое название получат {renamed};",
        f"Танго не трогаю: {plan.tango_skipped}.",
    ]
    if plan.titles_to_fix:
        lines.append("")
        lines.append(f"⚠️ Название не распознано, оставлю как есть ({len(plan.titles_to_fix)}):")
        lines.extend(f"• {html.escape(t)}" for t in plan.titles_to_fix[:15])
    closing = previous_month(yyyy_mm)
    reported, reported_at = True, None
    if redis is not None:
        try:
            reported_at = await redis.get(salary_reported_redis_key(closing))
            reported = bool(reported_at)
        except Exception:
            LOGGER.warning("Could not read the salary-reported flag", exc_info=True)
    button = f"✅ Закрыть месяц → {month_label(yyyy_mm)}"
    if reported and reported_at:
        stamp = reported_at.decode() if isinstance(reported_at, bytes) else str(reported_at)
        lines.insert(1, f"📊 Отчёт за {html.escape(month_label(closing))} записан {html.escape(stamp[:16].replace('T', ' '))} UTC. "
                        f"Если цифры менялись позже, перезапусти <code>/reports {closing}</code>.\n")
    if not reported:
        lines.insert(1, f"⚠️ Отчёт за {html.escape(month_label(closing))} ещё не записан в Google-таблицу. "
                        f"Сначала <code>/reports {closing}</code> — после закрытия цифры обнулятся.\n")
        button = f"⚠️ Всё равно закрыть → {month_label(yyyy_mm)}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=button, callback_data=f"close_month:{yyyy_mm}"),
    ]])
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


def _orders_push_lines(report) -> list[str]:
    if report is None:
        return ["⚠️ Заказы в CRM не отправлены: идёт другая выгрузка. Выполненные заказы удаляй "
                "только после следующей выгрузки без ошибок."]
    line = (f"📦 Заказы в CRM: создано {len(report.created)}, обновлено {len(report.updated)}, "
            f"отменено {len(report.cancelled)}.")
    out = [line]
    out.extend(f"  ⚠️ {html.escape(w[:150])}" for w in report.warnings[:10])
    if report.errors:
        out.append(f"  ❌ Ошибки ({len(report.errors)}), выполненные заказы удаляй после повторной выгрузки:")
        out.extend(f"  • {html.escape(e[:150])}" for e in report.errors[:10])
    return out


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

            # Orders too: a completed order deleted from Notion before its `out` reached the CRM
            # would otherwise be read as a deletion of an open order and cancelled there.
            if config.wml_export_apply and redis is None:
                lines.append("⚠️ Заказы в CRM не отправлены: Redis недоступен. Выполненные заказы удаляй "
                             "только после следующей выгрузки без ошибок.")
            elif config.wml_export_apply:
                await safe_edit_message(query, "⏳ Досылаю заказы в CRM…")
                try:
                    orders = await push_orders_now(
                        config, notion, redis, WmlApi(config.wml_username, config.wml_password))
                    lines.extend(_orders_push_lines(orders))
                except Exception as e:
                    LOGGER.exception("Final CRM orders push failed before month close")
                    lines.append(f"⚠️ Заказы в CRM дослать не получилось: {html.escape(str(e))}. "
                                 "Выполненные заказы удаляй только после следующей выгрузки.")

        # 2. Rename + zero, one request per record.
        await safe_edit_message(query, "⏳ Переименовываю и обнуляю записи…")
        plan = await plan_close(config, notion, yyyy_mm)
        done, errors = await apply_close(notion, plan, redis)
        lines.append(f"🗓 Записей обработано: {done} из {len(plan.items)} → {html.escape(month_label(yyyy_mm))}.")
        if errors:
            lines.append(f"⚠️ Ошибки ({len(errors)}):")
            lines.extend(f"• {html.escape(e[:150])}" for e in errors[:15])
        notify_kb = None
        if notify_targets(config):
            notify_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📣 Уведомить менеджеров", callback_data=f"notify_month:{yyyy_mm}"),
            ]])
        await safe_edit_message(query, "✅ Месяц закрыт.\n\n" + "\n".join(lines), parse_mode="HTML",
                                reply_markup=notify_kb)
    except Exception as e:
        LOGGER.exception("Month close failed")
        await safe_edit_message(query, f"⚠️ Не получилось: {html.escape(str(e))}", parse_mode="HTML")
    finally:
        await release_write_lock(redis, lock_key)


TOPIC_MANAGERS = {"robin"}  # served by the CRM topic of the managers group, not by a DM


def notify_targets(config: Config) -> dict[tuple[int, int | None], str]:
    """destination -> label: the CRM topic (Robin's) plus every other manager's DM, one per destination."""
    targets: dict[tuple[int, int | None], str] = {}
    if config.crm_chat_id and config.crm_topic_thread_id:
        targets[(config.crm_chat_id, config.crm_topic_thread_id)] = "CRM-топик"
    for name, target in config.manager_targets.items():
        if name.lower() not in TOPIC_MANAGERS:
            targets.setdefault(target, name)
    return targets


_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")


def month_closed_text(yyyy_mm: str) -> str:
    """Plain English for the managers. `yyyy_mm` is the NEW month."""
    new_month = _MONTHS_EN[int(yyyy_mm[5:7]) - 1]
    old_month = _MONTHS_EN[int(previous_month(yyyy_mm)[5:7]) - 1]
    return (
        f"📊 The {old_month} report has been sent.\n\n"
        f"You can start tracking {new_month} now."
    )


@router.callback_query(F.data.startswith("notify_month:"))
async def cb_notify_month(query: CallbackQuery, config: Config, redis=None) -> None:
    """Owner presses it after finishing the manual Orders cleanup — the bot can't know when that is.

    Robin gets it in the CRM topic, the other managers in their DM (see `notify_targets`).
    """
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Нет доступа", show_alert=True)
        return
    targets = notify_targets(config)
    if not targets:
        await safe_query_answer(query, "Некому слать: нет CRM-топика и менеджеров в личке", show_alert=True)
        return
    yyyy_mm = query.data.split(":", 1)[1]
    if not _YYYY_MM_RE.match(yyyy_mm):
        await safe_query_answer(query, "Неверный месяц", show_alert=True)
        return

    sent_key = f"notify_month:sent:{yyyy_mm}"
    already: set[str] = set()
    if redis is not None:
        try:
            already = {v.decode() if isinstance(v, bytes) else str(v) for v in await redis.smembers(sent_key)}
        except Exception:
            LOGGER.warning("Could not read the notified set", exc_info=True)

    failed: list[str] = []
    delivered = skipped = 0
    for (chat_id, thread_id), name in targets.items():
        dest = f"{chat_id}/{thread_id}"
        if dest in already:
            skipped += 1
            continue
        try:
            await query.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=month_closed_text(yyyy_mm),
                parse_mode="HTML",
            )
            delivered += 1
            if redis is not None:
                try:
                    await redis.sadd(sent_key, dest)
                    await redis.expire(sent_key, 30 * 24 * 3600)
                except Exception:
                    LOGGER.warning("Could not remember the notified destination", exc_info=True)
        except Exception as e:
            LOGGER.exception("Month-closed notification failed for %s", name)
            failed.append(f"{name}: {str(e)[:60]}")
    if failed:
        await safe_query_answer(query, f"Не дошло ({len(failed)} из {len(targets)}): " + "; ".join(failed)[:160],
                                show_alert=True)
        return  # keep the button; a retry would repeat the ones that went through
    await safe_query_answer(query, f"Отправлено: {delivered}" + (f" (ещё {skipped} уже получили)" if skipped else ""))
    if query.message:  # drop the button so a second press can't post it twice
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            LOGGER.debug("Could not remove the notify button", exc_info=True)
