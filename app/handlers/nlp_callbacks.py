"""
NLP callback handlers for inline keyboard interactions.

All callbacks use SHORT callback_data to stay within Telegram's 64-byte limit.
Flow context (model_id, order_type, count …) is stored in memory_state.

Callback prefix mapping:
  x   = cancel          sm  = select_model     act = model_action
  ot  = order_type      oq  = order_qty        od  = order_date
  oc  = order_confirm   sd  = shoot_date       sdc = shoot_done_confirm
  ss  = shoot_select    co  = close_order      cd  = close_date
  ct  = comment_target  cmo = comment_order    df  = disambig_files
  do  = disambig_orders ro  = report_orders    ra  = report_accounting
  af  = add_files
"""

import html
import logging
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.roles import is_authorized, is_editor
from app.services import NotionClient
from app.state import MemoryState, RecentModels
from app.router.command_filters import CommandIntent


LOGGER = logging.getLogger(__name__)
router = Router()

SESSION_EXPIRED_MSG = "Сессия истекла. Повторите запрос."


@router.callback_query(F.data.startswith("nlp:"))
async def handle_nlp_callback(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle all NLP-related callbacks."""
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return

    parts = query.data.split(":")
    if len(parts) < 2:
        await query.answer()
        return

    action = parts[1]
    user_id = query.from_user.id

    LOGGER.info("NLP callback: action=%s, data=%s, user=%s", action, query.data, user_id)

    try:
        # ===== Cancel =====
        if action == "x":
            memory_state.clear(user_id)
            sub = parts[2] if len(parts) >= 3 else "c"
            if sub == "m":
                await query.message.edit_text(
                    "👋 Главное меню. Напишите запрос текстом или /start",
                    parse_mode="HTML",
                )
            else:
                await query.message.edit_text("Отменено.")
            await query.answer()
            return

        # ===== Model Selection =====
        if action == "sm":
            await _handle_select_model(query, parts, config, notion, memory_state, recent_models)

        # ===== Model Action Card (CRM) =====
        elif action == "act":
            await _handle_model_action(query, parts, config, notion, memory_state, recent_models)

        # ===== Shoot Callbacks =====
        elif action == "sd":
            await _handle_shoot_date(query, parts, config, notion, memory_state, recent_models)
        elif action == "sdc":
            await _handle_shoot_done_confirm(query, parts, config, notion, memory_state)
        elif action == "ss":
            await _handle_shoot_select(query, parts, config, notion, memory_state)

        # ===== Order Callbacks =====
        elif action == "ot":
            await _handle_order_type(query, parts, config, memory_state)
        elif action == "oq":
            await _handle_order_qty(query, parts, config, notion, memory_state)
        elif action == "od":
            await _handle_order_date(query, parts, config, notion, memory_state)
        elif action == "oc":
            await _handle_order_confirm(query, parts, config, notion, memory_state, recent_models)

        # ===== Close Order Callbacks =====
        elif action == "co":
            await _handle_close_order_select(query, parts, config, memory_state)
        elif action == "cd":
            await _handle_close_date(query, parts, config, notion, memory_state)

        # ===== Comment Callbacks =====
        elif action == "ct":
            await _handle_comment_target(query, parts, config, notion, memory_state)
        elif action == "cmo":
            await _handle_comment_order(query, parts, config, notion, memory_state)

        # ===== Disambiguation Callbacks =====
        elif action == "df":
            await _handle_disambig_files(query, parts, config, notion, memory_state, recent_models)
        elif action == "do":
            await _handle_disambig_orders(query, parts, config, notion, memory_state)

        # ===== Report Callbacks =====
        elif action == "ro":
            await _handle_report_orders(query, config, notion, memory_state)
        elif action == "ra":
            await _handle_report_accounting(query, config, notion, memory_state)

        # ===== Add Files Callback =====
        elif action == "af":
            await _handle_add_files(query, parts, config, notion, memory_state, recent_models)

        else:
            LOGGER.warning("Unknown NLP callback action: %s", action)
            await query.answer("Unknown action", show_alert=True)

    except Exception as e:
        LOGGER.exception("Error in NLP callback: %s", e)
        await query.answer(f"Error: {str(e)[:100]}", show_alert=True)

    await query.answer()


# ============================================================================
#                          MODEL SELECTION
# ============================================================================

async def _handle_select_model(query, parts, config, notion, memory_state, recent_models):
    """
    Handle model selection from disambiguation or fuzzy confirmation.
    Callback: nlp:sm:{model_id}
    Intent is read from memory_state (set by dispatcher before showing keyboard).
    """
    if len(parts) < 3:
        return

    model_id = parts[2]
    user_id = query.from_user.id

    # Get model info
    model_data = await notion.get_model(model_id)
    if not model_data:
        await query.message.edit_text("Модель не найдена.")
        return

    model = {"id": model_id, "name": model_data.title}
    recent_models.add(user_id, model_id, model_data.title)

    # Get original intent + text from memory state
    state = memory_state.get(user_id)
    intent_value = state.get("intent", "") if state else ""
    original_text = state.get("entities_raw", "") if state else ""
    memory_state.clear(user_id)

    # Parse intent
    try:
        intent = CommandIntent(intent_value)
    except ValueError:
        intent = None

    # Re-extract entities from the original text
    from app.router.entities_v2 import extract_entities_v2
    entities = extract_entities_v2(original_text) if original_text else None

    # ---- Route to intent-specific follow-up ----

    if intent == CommandIntent.CREATE_ORDERS and entities and entities.order_type:
        # Order with known type: proceed to date selection
        count = entities.first_number or 1
        from app.keyboards.inline import nlp_order_confirm_keyboard
        from app.router.entities_v2 import get_order_type_display_name
        type_label = get_order_type_display_name(entities.order_type)
        memory_state.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_date",
            "model_id": model_id,
            "model_name": model_data.title,
            "order_type": entities.order_type,
            "count": count,
        })
        await query.message.edit_text(
            f"<b>{html.escape(model_data.title)}</b> · {count}x {type_label}\n\nДата:",
            reply_markup=nlp_order_confirm_keyboard(),
            parse_mode="HTML",
        )

    elif intent in (CommandIntent.CREATE_ORDERS, CommandIntent.CREATE_ORDERS_GENERAL):
        # Order without type: ask for type
        from app.keyboards.inline import nlp_order_type_keyboard
        memory_state.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_data.title,
        })
        await query.message.edit_text(
            f"📦 <b>{html.escape(model_data.title)}</b> · Тип заказа:",
            reply_markup=nlp_order_type_keyboard(),
            parse_mode="HTML",
        )

    elif intent == CommandIntent.SHOOT_CREATE:
        if entities and entities.date:
            # Date known: create shoot directly
            if not is_editor(user_id, config):
                await query.message.edit_text("❌ Нет прав.")
                return
            title = f"{model_data.title} · {entities.date.strftime('%d.%m')}"
            try:
                await notion.create_shoot(
                    database_id=config.db_planner,
                    model_page_id=model_id,
                    shoot_date=entities.date,
                    content=[],
                    location="home",
                    title=title,
                )
                await query.message.edit_text(
                    f"✅ Съемка создана на {entities.date.strftime('%d.%m')}",
                    parse_mode="HTML",
                )
            except Exception as e:
                LOGGER.exception("Failed to create shoot: %s", e)
                await query.message.edit_text("❌ Ошибка при создании съемки.")
        else:
            # No date: ask for date
            from app.keyboards.inline import nlp_shoot_date_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_shoot",
                "step": "awaiting_date",
                "model_id": model_id,
                "model_name": model_data.title,
            })
            await query.message.edit_text(
                f"📅 <b>{html.escape(model_data.title)}</b> · Дата съемки:",
                reply_markup=nlp_shoot_date_keyboard(),
                parse_mode="HTML",
            )

    elif intent == CommandIntent.ADD_FILES and entities and entities.numbers:
        # Add files directly
        count = entities.first_number
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет прав.")
            return
        try:
            now = datetime.now(tz=config.timezone)
            month_str = now.strftime("%B")
            record = await notion.get_accounting_record(config.db_accounting, model_id, month_str)
            if not record:
                await notion.create_accounting_record(
                    config.db_accounting, model_id, count, month_str, config.files_per_month
                )
                new_amount = count
            else:
                current_amount = record.amount or 0
                new_amount = current_amount + count
                new_percent = new_amount / float(config.files_per_month)
                await notion.update_accounting_files(record.page_id, new_amount, new_percent)
            percent = int((new_amount / config.files_per_month) * 100)
            await query.message.edit_text(
                f"✅ +{count} файлов ({new_amount} всего)\n\n"
                f"<b>{html.escape(model_data.title)}</b> · {month_str}\n"
                f"Файлов: {new_amount} ({percent}%)",
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to add files: %s", e)
            await query.message.edit_text("❌ Ошибка при добавлении файлов.")

    elif intent == CommandIntent.CLOSE_ORDERS:
        # Close orders flow
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет прав.")
            return
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model_id)
        if not orders:
            await query.message.edit_text(
                f"✅ Нет открытых заказов для {html.escape(model_data.title)}",
                parse_mode="HTML",
            )
            return
        if len(orders) == 1:
            from app.keyboards.inline import nlp_close_order_date_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_close",
                "order_id": orders[0].page_id,
            })
            await query.message.edit_text(
                f"Закрыть {orders[0].order_type or '?'}?\n\nДата закрытия:",
                reply_markup=nlp_close_order_date_keyboard(),
                parse_mode="HTML",
            )
        else:
            from app.keyboards.inline import nlp_close_order_select_keyboard
            await query.message.edit_text(
                f"📦 <b>{html.escape(model_data.title)}</b> · Какой заказ закрыть?",
                reply_markup=nlp_close_order_select_keyboard(orders),
                parse_mode="HTML",
            )

    else:
        # Default: show CRM action card
        from app.keyboards.inline import nlp_model_actions_keyboard
        memory_state.set(user_id, {
            "flow": "nlp_actions",
            "model_id": model_id,
            "model_name": model_data.title,
        })
        await query.message.edit_text(
            f"✅ <b>{html.escape(model_data.title)}</b>\n\nЧто сделать?",
            reply_markup=nlp_model_actions_keyboard(),
            parse_mode="HTML",
        )


# ============================================================================
#                       MODEL ACTION CARD (CRM UX)
# ============================================================================

async def _handle_model_action(query, parts, config, notion, memory_state, recent_models):
    """
    Handle CRM action card button press.
    Callback: nlp:act:{action}
    model_id/model_name read from memory_state.
    """
    if len(parts) < 3:
        return

    action = parts[2]
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    if not state or not state.get("model_id"):
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_id = state["model_id"]
    model_name = state.get("model_name", "")

    if action == "order":
        # Show order type selection
        from app.keyboards.inline import nlp_order_type_keyboard
        memory_state.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_name,
        })
        await query.message.edit_text(
            f"📦 <b>{html.escape(model_name)}</b> · Тип заказа:",
            reply_markup=nlp_order_type_keyboard(),
            parse_mode="HTML",
        )

    elif action == "files":
        # Show file count selection
        from app.keyboards.inline import nlp_files_qty_keyboard
        memory_state.set(user_id, {
            "flow": "nlp_files",
            "model_id": model_id,
            "model_name": model_name,
        })
        await query.message.edit_text(
            f"📁 <b>{html.escape(model_name)}</b> · Сколько файлов?",
            reply_markup=nlp_files_qty_keyboard(),
            parse_mode="HTML",
        )

    elif action == "shoot":
        # Show shoot date selection
        from app.keyboards.inline import nlp_shoot_date_keyboard
        memory_state.set(user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_date",
            "model_id": model_id,
            "model_name": model_name,
        })
        await query.message.edit_text(
            f"📅 <b>{html.escape(model_name)}</b> · Дата съемки:",
            reply_markup=nlp_shoot_date_keyboard(),
            parse_mode="HTML",
        )

    elif action == "report":
        # Show report inline
        memory_state.set(user_id, {
            "flow": "nlp_report",
            "model_id": model_id,
            "model_name": model_name,
        })
        await _show_report(query, model_id, model_name, config, notion)

    elif action == "orders":
        # Show open orders list
        memory_state.clear(user_id)
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model_id)
        if not orders:
            await query.message.edit_text(
                f"📋 <b>{html.escape(model_name)}</b>\n\n✅ Нет открытых заказов.",
                parse_mode="HTML",
            )
            return
        text = f"📋 <b>{html.escape(model_name)}</b> · Открытые заказы:\n\n"
        for order in orders[:10]:
            days = _calc_days_open(order.in_date)
            text += f"• {order.order_type or '?'} · {_format_date_short(order.in_date)} ({days}d)\n"
        if len(orders) > 10:
            text += f"\n...и ещё {len(orders) - 10}"
        await query.message.edit_text(text, parse_mode="HTML")

    elif action == "close":
        # Close orders flow
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет прав.")
            return
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model_id)
        if not orders:
            memory_state.clear(user_id)
            await query.message.edit_text(
                f"✅ Нет открытых заказов для {html.escape(model_name)}",
                parse_mode="HTML",
            )
            return
        if len(orders) == 1:
            from app.keyboards.inline import nlp_close_order_date_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_close",
                "order_id": orders[0].page_id,
            })
            days = _calc_days_open(orders[0].in_date)
            label = f"{orders[0].order_type or '?'} · {_format_date_short(orders[0].in_date)} ({days}d)"
            await query.message.edit_text(
                f"Закрыть '{label}'?\n\nДата закрытия:",
                reply_markup=nlp_close_order_date_keyboard(),
                parse_mode="HTML",
            )
        else:
            from app.keyboards.inline import nlp_close_order_select_keyboard
            memory_state.clear(user_id)
            await query.message.edit_text(
                f"📦 <b>{html.escape(model_name)}</b> · Какой заказ закрыть?",
                reply_markup=nlp_close_order_select_keyboard(orders),
                parse_mode="HTML",
            )


# ============================================================================
#                          SHOOT CALLBACKS
# ============================================================================

async def _handle_shoot_date(query, parts, config, notion, memory_state, recent_models):
    """Handle shoot date selection. Callback: nlp:sd:{choice}"""
    if len(parts) < 3:
        return

    date_choice = parts[2]
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_id = state.get("model_id", "")
    model_name = state.get("model_name", "")
    step = state.get("step", "")

    today = date.today()
    if date_choice == "tomorrow":
        shoot_date = today + timedelta(days=1)
    elif date_choice == "day_after":
        shoot_date = today + timedelta(days=2)
    elif date_choice == "custom":
        memory_state.update(user_id, step="awaiting_custom_date")
        await query.message.edit_text(
            "Введите дату (ДД.ММ):",
            parse_mode="HTML",
        )
        return
    else:
        return

    if step == "awaiting_new_date":
        # Reschedule
        shoot_id = state.get("shoot_id")
        if shoot_id:
            old_date = state.get("old_date", "?")
            await notion.reschedule_shoot(shoot_id, shoot_date)
            old_label = old_date[:10] if old_date else "?"
            memory_state.clear(user_id)
            await query.message.edit_text(
                f"✅ Съемка перенесена с {old_label} на {shoot_date.strftime('%d.%m')}",
                parse_mode="HTML",
            )
    else:
        # Create shoot
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет прав.")
            memory_state.clear(user_id)
            return

        title = f"{model_name} · {shoot_date.strftime('%d.%m')}"
        try:
            await notion.create_shoot(
                database_id=config.db_planner,
                model_page_id=model_id,
                shoot_date=shoot_date,
                content=[],
                location="home",
                title=title,
            )
            memory_state.clear(user_id)
            recent_models.add(user_id, model_id, model_name)
            await query.message.edit_text(
                f"✅ Съемка создана на {shoot_date.strftime('%d.%m')}",
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to create shoot: %s", e)
            await query.message.edit_text("❌ Ошибка при создании съемки.")
            memory_state.clear(user_id)


async def _handle_shoot_done_confirm(query, parts, config, notion, memory_state):
    """Handle shoot done confirmation. Callback: nlp:sdc:{shoot_id}"""
    if len(parts) < 3:
        return

    shoot_id = parts[2]
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    try:
        await notion.update_shoot_status(shoot_id, "done")
        memory_state.clear(user_id)
        await query.message.edit_text("✅ Съемка выполнена")
    except Exception as e:
        LOGGER.exception("Failed to mark shoot as done: %s", e)
        await query.message.edit_text("❌ Ошибка.")


async def _handle_shoot_select(query, parts, config, notion, memory_state):
    """Handle shoot selection. Callback: nlp:ss:{action}:{shoot_id}"""
    if len(parts) < 4:
        return

    action = parts[2]
    shoot_id = parts[3]
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    if action == "done":
        await notion.update_shoot_status(shoot_id, "done")
        memory_state.clear(user_id)
        await query.message.edit_text("✅ Съемка выполнена")

    elif action == "reschedule":
        shoot = await notion.get_shoot(shoot_id)
        model_name = shoot.model_title if shoot else ""
        from app.keyboards.inline import nlp_shoot_date_keyboard
        model_id = shoot.model_id if shoot else ""
        memory_state.set(user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_new_date",
            "shoot_id": shoot_id,
            "model_id": model_id,
            "model_name": model_name,
            "old_date": shoot.date if shoot else None,
        })
        date_str = shoot.date[:10] if shoot and shoot.date else "?"
        await query.message.edit_text(
            f"📅 Перенос съемки {date_str}\n\nНовая дата:",
            reply_markup=nlp_shoot_date_keyboard(),
            parse_mode="HTML",
        )

    elif action == "comment":
        state = memory_state.get(user_id)
        if not state:
            await query.message.edit_text(SESSION_EXPIRED_MSG)
            return
        comment_text = state.get("comment_text")
        if comment_text:
            shoot = await notion.get_shoot(shoot_id)
            existing = shoot.comments if shoot else ""
            new_comment = f"{existing}\n{comment_text}".strip() if existing else comment_text
            await notion.update_shoot_comment(shoot_id, new_comment)
            memory_state.clear(user_id)
            await query.message.edit_text("✅ Комментарий добавлен")
        else:
            await query.message.edit_text("Текст комментария не найден.")
            memory_state.clear(user_id)


# ============================================================================
#                          ORDER CALLBACKS
# ============================================================================

async def _handle_order_type(query, parts, config, memory_state):
    """Handle order type selection. Callback: nlp:ot:{type}"""
    if len(parts) < 3:
        return

    order_type = parts[2]
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    from app.keyboards.inline import nlp_order_qty_keyboard
    memory_state.update(user_id, step="awaiting_count", order_type=order_type)
    model_name = state.get("model_name", "")
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {type_label}\n\nСколько?",
        reply_markup=nlp_order_qty_keyboard(),
        parse_mode="HTML",
    )


async def _handle_order_qty(query, parts, config, notion, memory_state):
    """Handle order qty selection. Callback: nlp:oq:{count}"""
    if len(parts) < 3:
        return

    count = int(parts[2])
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_name = state.get("model_name", "")
    order_type = state.get("order_type", "")

    from app.keyboards.inline import nlp_order_confirm_keyboard
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    memory_state.update(user_id, step="awaiting_date", count=count)
    await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\nДата заказа:",
        reply_markup=nlp_order_confirm_keyboard(),
        parse_mode="HTML",
    )


async def _handle_order_date(query, parts, config, notion, memory_state):
    """Handle order date selection. Callback: nlp:od:{date}"""
    if len(parts) < 3:
        return

    date_choice = parts[2]
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_id = state.get("model_id", "")
    model_name = state.get("model_name", "")
    order_type = state.get("order_type", "")
    count = state.get("count", 1)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        memory_state.clear(user_id)
        return

    today_date = date.today()
    if date_choice == "today":
        in_date = today_date
    elif date_choice == "yesterday":
        in_date = today_date - timedelta(days=1)
    else:
        in_date = today_date

    try:
        for _ in range(count):
            title = f"{model_name} | {order_type}"
            await notion.create_order(
                database_id=config.db_orders,
                model_page_id=model_id,
                order_type=order_type,
                in_date=in_date,
                count=1,
                title=title,
            )

        memory_state.clear(user_id)
        from app.router.entities_v2 import get_order_type_display_name
        type_label = get_order_type_display_name(order_type)
        await query.message.edit_text(
            f"✅ Создано {count}x {type_label}\n"
            f"<b>{html.escape(model_name)}</b> · {in_date.strftime('%d.%m')}",
            parse_mode="HTML",
        )

    except Exception as e:
        LOGGER.exception("Failed to create orders: %s", e)
        await query.message.edit_text("❌ Ошибка при создании заказов.")
        memory_state.clear(user_id)


async def _handle_order_confirm(query, parts, config, notion, memory_state, recent_models):
    """Handle order confirm (create with default date=today). Callback: nlp:oc"""
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_id = state.get("model_id", "")
    model_name = state.get("model_name", "")
    order_type = state.get("order_type", "")
    count = state.get("count", 1)
    # Default: today
    in_date = date.today()

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        memory_state.clear(user_id)
        return

    try:
        for _ in range(count):
            title = f"{model_name} | {order_type}"
            await notion.create_order(
                database_id=config.db_orders,
                model_page_id=model_id,
                order_type=order_type,
                in_date=in_date,
                count=1,
                title=title,
            )

        recent_models.add(user_id, model_id, model_name)
        memory_state.clear(user_id)

        from app.router.entities_v2 import get_order_type_display_name
        type_label = get_order_type_display_name(order_type)
        await query.message.edit_text(
            f"✅ Создано {count}x {type_label}\n"
            f"<b>{html.escape(model_name)}</b> · {in_date.strftime('%d.%m')}",
            parse_mode="HTML",
        )

    except Exception as e:
        LOGGER.exception("Failed to create orders: %s", e)
        await query.message.edit_text("❌ Ошибка при создании заказов.")
        memory_state.clear(user_id)


# ============================================================================
#                       CLOSE ORDER CALLBACKS
# ============================================================================

async def _handle_close_order_select(query, parts, config, memory_state):
    """Handle close order selection. Callback: nlp:co:{order_id}"""
    if len(parts) < 3:
        return

    order_id = parts[2]

    # Store order_id in memory for the date step
    from app.keyboards.inline import nlp_close_order_date_keyboard
    memory_state.set(query.from_user.id, {
        "flow": "nlp_close",
        "order_id": order_id,
    })
    await query.message.edit_text(
        "Дата закрытия:",
        reply_markup=nlp_close_order_date_keyboard(),
        parse_mode="HTML",
    )


async def _handle_close_date(query, parts, config, notion, memory_state):
    """Handle close date selection. Callback: nlp:cd:{choice}"""
    if len(parts) < 3:
        return

    date_choice = parts[2]
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    # Get order_id from memory
    state = memory_state.get(user_id)
    order_id = state.get("order_id") if state else None
    if not order_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    today_date = date.today()
    if date_choice == "today":
        out_date = today_date
    elif date_choice == "yesterday":
        out_date = today_date - timedelta(days=1)
    elif date_choice == "custom":
        memory_state.update(user_id, step="awaiting_custom_date")
        await query.message.edit_text("Введите дату закрытия (ДД.ММ):")
        return
    else:
        out_date = today_date

    try:
        await notion.close_order(order_id, out_date)
        memory_state.clear(user_id)
        await query.message.edit_text(
            f"✅ Заказ закрыт · {out_date.strftime('%d.%m')}",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to close order: %s", e)
        await query.message.edit_text("❌ Ошибка при закрытии заказа.")


# ============================================================================
#                        COMMENT CALLBACKS
# ============================================================================

async def _handle_comment_target(query, parts, config, notion, memory_state):
    """Handle comment target selection. Callback: nlp:ct:{target}"""
    if len(parts) < 3:
        return

    target = parts[2]
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_id = state.get("model_id", "")
    comment_text = state.get("comment_text")
    if not comment_text:
        await query.message.edit_text("Текст комментария не найден.")
        memory_state.clear(user_id)
        return

    if target == "order":
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model_id)
        if not orders:
            await query.message.edit_text("Нет открытых заказов.")
            memory_state.clear(user_id)
            return
        if len(orders) == 1:
            existing = orders[0].comments or ""
            new_comment = f"{existing}\n{comment_text}".strip() if existing else comment_text
            await notion.update_order_comment(orders[0].page_id, new_comment)
            memory_state.clear(user_id)
            await query.message.edit_text("✅ Комментарий добавлен")
        else:
            from app.keyboards.inline import nlp_comment_order_select_keyboard
            memory_state.update(user_id, step="awaiting_order_selection")
            await query.message.edit_text(
                "Выберите заказ:",
                reply_markup=nlp_comment_order_select_keyboard(orders),
                parse_mode="HTML",
            )

    elif target == "shoot":
        shoots = await notion.query_upcoming_shoots(config.db_planner, model_page_id=model_id)
        if not shoots:
            await query.message.edit_text("Нет запланированных съемок.")
            memory_state.clear(user_id)
            return
        if len(shoots) == 1:
            existing = shoots[0].comments or ""
            new_comment = f"{existing}\n{comment_text}".strip() if existing else comment_text
            await notion.update_shoot_comment(shoots[0].page_id, new_comment)
            memory_state.clear(user_id)
            await query.message.edit_text("✅ Комментарий добавлен")
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            memory_state.update(user_id, step="awaiting_shoot_selection")
            await query.message.edit_text(
                "Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "comment"),
                parse_mode="HTML",
            )

    elif target == "account":
        await query.message.edit_text("Комментарии к учету пока не поддержаны.")
        memory_state.clear(user_id)


async def _handle_comment_order(query, parts, config, notion, memory_state):
    """Handle comment order selection. Callback: nlp:cmo:{order_id}"""
    if len(parts) < 3:
        return

    order_id = parts[2]
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    comment_text = state.get("comment_text")
    if not comment_text:
        await query.message.edit_text("Текст комментария не найден.")
        memory_state.clear(user_id)
        return

    try:
        from app.services.notion import _extract_rich_text
        url = f"https://api.notion.com/v1/pages/{order_id}"
        page = await notion._request("GET", url)
        existing = _extract_rich_text(page, "comments") or ""

        new_comment = f"{existing}\n{comment_text}".strip() if existing else comment_text
        await notion.update_order_comment(order_id, new_comment)
        memory_state.clear(user_id)
        await query.message.edit_text("✅ Комментарий добавлен")
    except Exception as e:
        LOGGER.exception("Failed to add comment: %s", e)
        await query.message.edit_text("❌ Ошибка.")
        memory_state.clear(user_id)


# ============================================================================
#                      DISAMBIGUATION CALLBACKS
# ============================================================================

async def _handle_disambig_files(query, parts, config, notion, memory_state, recent_models):
    """Handle disambiguation → files. Callback: nlp:df:{number}"""
    if len(parts) < 3:
        return

    count = int(parts[2])
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    # model_id from memory
    state = memory_state.get(user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_data = await notion.get_model(model_id)
    if not model_data:
        await query.message.edit_text("Модель не найдена.")
        return

    model_name = model_data.title

    try:
        now = datetime.now(tz=config.timezone)
        month_str = now.strftime("%B")

        record = await notion.get_accounting_record(config.db_accounting, model_id, month_str)

        if not record:
            await notion.create_accounting_record(
                config.db_accounting, model_id, count, month_str, config.files_per_month
            )
            new_amount = count
        else:
            current_amount = record.amount or 0
            new_amount = current_amount + count
            new_percent = new_amount / float(config.files_per_month)
            await notion.update_accounting_files(record.page_id, new_amount, new_percent)

        percent = int((new_amount / config.files_per_month) * 100)
        recent_models.add(user_id, model_id, model_name)
        memory_state.clear(user_id)

        await query.message.edit_text(
            f"✅ +{count} файлов ({new_amount} всего)\n\n"
            f"<b>{html.escape(model_name)}</b> · {month_str}\n"
            f"Файлов: {new_amount} ({percent}%)",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await query.message.edit_text("❌ Ошибка при добавлении файлов.")


async def _handle_disambig_orders(query, parts, config, notion, memory_state):
    """Handle disambiguation → orders. Callback: nlp:do:{number}"""
    if len(parts) < 3:
        return

    count = int(parts[2])
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else ""

    from app.keyboards.inline import nlp_order_type_keyboard
    memory_state.set(user_id, {
        "flow": "nlp_order",
        "step": "awaiting_type",
        "model_id": model_id,
        "model_name": model_name,
        "count": count,
    })

    await query.message.edit_text(
        f"📦 {count}x — Тип заказа:",
        reply_markup=nlp_order_type_keyboard(),
        parse_mode="HTML",
    )


# ============================================================================
#                        REPORT CALLBACKS
# ============================================================================

async def _handle_report_orders(query, config, notion, memory_state):
    """Handle report orders detail. Callback: nlp:ro"""
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    orders = await notion.query_open_orders(config.db_orders, model_id)
    if not orders:
        await query.answer("Нет открытых заказов", show_alert=True)
        return

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else "модели"

    orders_text = "\n".join(
        f"• {o.order_type or 'order'} · {_format_date_short(o.in_date)}"
        for o in orders[:10]
    )
    if len(orders) > 10:
        orders_text += f"\n\n...и ещё {len(orders) - 10}"

    from app.keyboards.inline import nlp_report_keyboard
    if query.message:
        await query.message.edit_text(
            f"📦 <b>Открытые заказы: {html.escape(model_name)}</b>\n\n{orders_text}",
            reply_markup=nlp_report_keyboard(),
            parse_mode="HTML",
        )


async def _handle_report_accounting(query, config, notion, memory_state):
    """Handle report accounting detail. Callback: nlp:ra"""
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    records = await notion.query_accounting_current_month(config.db_accounting, model_id)
    if not records:
        await query.answer("Нет данных по учету", show_alert=True)
        return

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else "модели"

    accounting_text = "\n".join(
        f"• {rec.title}: {rec.amount or 0} файлов ({int((rec.percent or 0) * 100)}%)"
        for rec in records[:5]
    )

    from app.keyboards.inline import nlp_report_keyboard
    if query.message:
        await query.message.edit_text(
            f"📁 <b>Учет файлов: {html.escape(model_name)}</b>\n\n{accounting_text}",
            reply_markup=nlp_report_keyboard(),
            parse_mode="HTML",
        )


# ============================================================================
#                          ADD FILES CALLBACK
# ============================================================================

async def _handle_add_files(query, parts, config, notion, memory_state, recent_models):
    """Handle add files from CRM card. Callback: nlp:af:{count}"""
    if len(parts) < 3:
        return

    count = int(parts[2])
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    state = memory_state.get(user_id)
    model_id = state.get("model_id") if state else None
    model_name = state.get("model_name", "") if state else ""
    if not model_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    try:
        now = datetime.now(tz=config.timezone)
        month_str = now.strftime("%B")

        record = await notion.get_accounting_record(config.db_accounting, model_id, month_str)

        if not record:
            await notion.create_accounting_record(
                config.db_accounting, model_id, count, month_str, config.files_per_month
            )
            new_amount = count
        else:
            current_amount = record.amount or 0
            new_amount = current_amount + count
            new_percent = new_amount / float(config.files_per_month)
            await notion.update_accounting_files(record.page_id, new_amount, new_percent)

        percent = int((new_amount / config.files_per_month) * 100)
        recent_models.add(user_id, model_id, model_name)
        memory_state.clear(user_id)

        await query.message.edit_text(
            f"✅ +{count} файлов ({new_amount} всего)\n\n"
            f"<b>{html.escape(model_name)}</b> · {month_str}\n"
            f"Файлов: {new_amount} ({percent}%)",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await query.message.edit_text("❌ Ошибка при добавлении файлов.")
        memory_state.clear(user_id)


# ============================================================================
#                              HELPERS
# ============================================================================

async def _show_report(query, model_id, model_name, config, notion):
    """Show inline report for model."""
    from app.keyboards.inline import nlp_report_keyboard
    from app.utils import escape_html

    now = datetime.now(tz=config.timezone)
    month_str = now.strftime("%B")

    try:
        accounting_records = await notion.query_accounting_current_month(
            config.db_accounting, model_id
        )
    except Exception:
        accounting_records = []

    try:
        open_orders = await notion.query_open_orders(config.db_orders, model_id)
    except Exception:
        open_orders = []

    total_files = sum(
        rec.amount for rec in accounting_records if rec.amount is not None
    )
    avg_percent = (
        sum(rec.percent for rec in accounting_records if rec.percent is not None)
        / len(accounting_records)
        if accounting_records
        else 0
    )

    files_str = f"{total_files} ({int(avg_percent * 100)}%)"
    orders_str = f"{len(open_orders)} открытых"

    await query.message.edit_text(
        f"📊 <b>{escape_html(model_name)}</b> · {month_str}\n\n"
        f"📁 Файлов: {files_str}\n"
        f"📦 Заказов: {orders_str}\n",
        reply_markup=nlp_report_keyboard(),
        parse_mode="HTML",
    )


def _calc_days_open(in_date_str: str | None) -> int:
    if not in_date_str:
        return 0
    try:
        in_date = date.fromisoformat(in_date_str[:10])
        return (date.today() - in_date).days
    except (ValueError, TypeError):
        return 0


def _format_date_short(date_str: str | None) -> str:
    if not date_str:
        return "?"
    try:
        d = date.fromisoformat(date_str[:10])
        return d.strftime("%d.%m")
    except (ValueError, TypeError):
        return "?"
