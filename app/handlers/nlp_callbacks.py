"""
NLP callback handlers for inline keyboard interactions.

Handles callback_data starting with "nlp:" for:
- Model selection (disambiguation)
- Shoot date selection, done confirm, reschedule
- Order type/qty selection, close date
- Comment target selection
- Ambiguous disambiguation (files vs orders)
- Cancel
"""

import html
import logging
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.roles import is_authorized, is_editor
from app.services import NotionClient
from app.state import MemoryState, RecentModels


LOGGER = logging.getLogger(__name__)
router = Router()


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
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    user_id = query.from_user.id

    LOGGER.info("NLP callback: action=%s, data=%s, user=%s", action, query.data, user_id)

    try:
        # ===== Cancel =====
        if action == "cancel":
            memory_state.clear(user_id)
            await query.message.edit_text("❌ Отменено.")
            await query.answer()
            return

        # ===== Model Selection =====
        if action == "select_model":
            await _handle_select_model(query, parts, config, notion, memory_state, recent_models)

        # ===== Shoot Callbacks =====
        elif action == "shoot_date":
            await _handle_shoot_date(query, parts, config, notion, memory_state, recent_models)
        elif action == "shoot_done_confirm":
            await _handle_shoot_done_confirm(query, parts, config, notion, memory_state)
        elif action == "shoot_select":
            await _handle_shoot_select(query, parts, config, notion, memory_state)

        # ===== Order Callbacks =====
        elif action == "order_type":
            await _handle_order_type(query, parts, config, memory_state)
        elif action == "order_qty":
            await _handle_order_qty(query, parts, config, notion, memory_state)
        elif action == "order_date":
            await _handle_order_date(query, parts, config, notion, memory_state)
        elif action == "order_confirm":
            await _handle_order_confirm(query, parts, config, notion, memory_state, recent_models)

        # ===== Close Order Callbacks =====
        elif action == "close_order":
            await _handle_close_order_select(query, parts, config, memory_state)
        elif action == "close_date":
            await _handle_close_date(query, parts, config, notion, memory_state)

        # ===== Comment Callbacks =====
        elif action == "comment_target":
            await _handle_comment_target(query, parts, config, notion, memory_state)
        elif action == "comment_order":
            await _handle_comment_order(query, parts, config, notion, memory_state)

        # ===== Disambiguation Callbacks =====
        elif action == "disambig_files":
            await _handle_disambig_files(query, parts, config, notion, memory_state, recent_models)
        elif action == "disambig_orders":
            await _handle_disambig_orders(query, parts, config, notion, memory_state)

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
    """Handle model selection from disambiguation."""
    # nlp:select_model:{model_id}:{intent}
    if len(parts) < 4:
        return

    model_id = parts[2]
    intent = parts[3]
    user_id = query.from_user.id

    # Get model info
    model_data = await notion.get_model(model_id)
    if not model_data:
        await query.message.edit_text("❌ Модель не найдена.")
        return

    model = {"id": model_id, "name": model_data.title}
    recent_models.add(user_id, model_id, model_data.title)

    # Get original text from memory state
    state = memory_state.get(user_id)
    memory_state.clear(user_id)

    await query.message.edit_text(
        f"✅ Выбрана: <b>{html.escape(model_data.title)}</b>",
        parse_mode="HTML",
    )


# ============================================================================
#                          SHOOT CALLBACKS
# ============================================================================

async def _handle_shoot_date(query, parts, config, notion, memory_state, recent_models):
    """Handle shoot date selection."""
    # nlp:shoot_date:{model_id}:{date_choice}
    if len(parts) < 4:
        return

    model_id = parts[2]
    date_choice = parts[3]
    user_id = query.from_user.id

    state = memory_state.get(user_id) or {}
    model_name = state.get("model_name", "")
    step = state.get("step", "")

    today = date.today()
    if date_choice == "tomorrow":
        shoot_date = today + timedelta(days=1)
    elif date_choice == "day_after":
        shoot_date = today + timedelta(days=2)
    elif date_choice == "custom":
        # Ask user to type a date
        memory_state.update(user_id, step="awaiting_custom_date")
        await query.message.edit_text(
            "📅 Введите дату (DD.MM):",
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
    """Handle shoot done confirmation."""
    # nlp:shoot_done_confirm:{shoot_id}
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
    """Handle shoot selection from list."""
    # nlp:shoot_select:{action}:{shoot_id}
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
            reply_markup=nlp_shoot_date_keyboard(model_id),
            parse_mode="HTML",
        )

    elif action == "comment":
        state = memory_state.get(user_id) or {}
        comment_text = state.get("comment_text")
        if comment_text:
            shoot = await notion.get_shoot(shoot_id)
            existing = shoot.comments if shoot else ""
            new_comment = f"{existing}\n{comment_text}".strip() if existing else comment_text
            await notion.update_shoot_comment(shoot_id, new_comment)
            memory_state.clear(user_id)
            await query.message.edit_text("✅ Комментарий добавлен")
        else:
            await query.message.edit_text("❌ Текст комментария не найден.")
            memory_state.clear(user_id)


# ============================================================================
#                          ORDER CALLBACKS
# ============================================================================

async def _handle_order_type(query, parts, config, memory_state):
    """Handle order type selection."""
    # nlp:order_type:{model_id}:{type}
    if len(parts) < 4:
        return

    model_id = parts[2]
    order_type = parts[3]
    user_id = query.from_user.id

    from app.keyboards.inline import nlp_order_qty_keyboard
    memory_state.update(user_id, step="awaiting_count", order_type=order_type)
    await query.message.edit_text(
        f"📦 Сколько?",
        reply_markup=nlp_order_qty_keyboard(model_id, order_type),
        parse_mode="HTML",
    )


async def _handle_order_qty(query, parts, config, notion, memory_state):
    """Handle order quantity selection."""
    # nlp:order_qty:{model_id}:{type}:{count}
    if len(parts) < 5:
        return

    model_id = parts[2]
    order_type = parts[3]
    count = int(parts[4])
    user_id = query.from_user.id

    from app.keyboards.inline import nlp_order_confirm_keyboard
    memory_state.update(user_id, step="awaiting_date", count=count)
    await query.message.edit_text(
        f"📦 {count}x {order_type}\n\nДата заказа:",
        reply_markup=nlp_order_confirm_keyboard(model_id, order_type, count, "today"),
        parse_mode="HTML",
    )


async def _handle_order_date(query, parts, config, notion, memory_state):
    """Handle order date selection and create order."""
    # nlp:order_date:{model_id}:{type}:{count}:{date}
    if len(parts) < 6:
        return

    model_id = parts[2]
    order_type = parts[3]
    count = int(parts[4])
    date_choice = parts[5]
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        memory_state.clear(user_id)
        return

    today = date.today()
    if date_choice == "today":
        in_date = today
    elif date_choice == "yesterday":
        in_date = today - timedelta(days=1)
    else:
        in_date = today

    state = memory_state.get(user_id) or {}
    model_name = state.get("model_name", "")

    try:
        for _ in range(count):
            title = f"{model_name} · {order_type}"
            await notion.create_order(
                database_id=config.db_orders,
                model_page_id=model_id,
                order_type=order_type,
                in_date=in_date,
                count=1,
                title=title,
            )

        memory_state.clear(user_id)

        if count == 1:
            await query.message.edit_text(f"✅ Создан 1 {order_type}")
        else:
            await query.message.edit_text(f"✅ Создано {count} {order_type}")

    except Exception as e:
        LOGGER.exception("Failed to create orders: %s", e)
        await query.message.edit_text("❌ Ошибка при создании заказов.")
        memory_state.clear(user_id)


async def _handle_order_confirm(query, parts, config, notion, memory_state, recent_models):
    """Handle order creation confirmation."""
    # nlp:order_confirm:{model_id}:{type}:{count}:{date_iso}
    if len(parts) < 6:
        return

    model_id = parts[2]
    order_type = parts[3]
    count = int(parts[4])
    date_iso = parts[5]
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        memory_state.clear(user_id)
        return

    try:
        in_date = date.fromisoformat(date_iso)
    except ValueError:
        in_date = date.today()

    state = memory_state.get(user_id) or {}
    model_name = state.get("model_name", "")

    try:
        for _ in range(count):
            title = f"{model_name} · {order_type}"
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

        if count == 1:
            await query.message.edit_text(f"✅ Создан 1 {order_type}")
        else:
            await query.message.edit_text(f"✅ Создано {count} {order_type}")

    except Exception as e:
        LOGGER.exception("Failed to create orders: %s", e)
        await query.message.edit_text("❌ Ошибка при создании заказов.")
        memory_state.clear(user_id)


# ============================================================================
#                       CLOSE ORDER CALLBACKS
# ============================================================================

async def _handle_close_order_select(query, parts, config, memory_state):
    """Handle close order selection."""
    # nlp:close_order:{order_id}
    if len(parts) < 3:
        return

    order_id = parts[2]

    from app.keyboards.inline import nlp_close_order_date_keyboard
    await query.message.edit_text(
        "Дата закрытия:",
        reply_markup=nlp_close_order_date_keyboard(order_id),
        parse_mode="HTML",
    )


async def _handle_close_date(query, parts, config, notion, memory_state):
    """Handle close date selection."""
    # nlp:close_date:{date_choice}:{order_id}
    if len(parts) < 4:
        return

    date_choice = parts[2]
    order_id = parts[3]
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    today = date.today()
    if date_choice == "today":
        out_date = today
    elif date_choice == "yesterday":
        out_date = today - timedelta(days=1)
    elif date_choice == "custom":
        memory_state.set(user_id, {
            "flow": "nlp_close",
            "step": "awaiting_custom_date",
            "order_id": order_id,
        })
        await query.message.edit_text("📅 Введите дату закрытия (DD.MM):")
        return
    else:
        out_date = today

    try:
        await notion.close_order(order_id, out_date)
        memory_state.clear(user_id)
        await query.message.edit_text(
            f"✅ Заказ закрыт",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to close order: %s", e)
        await query.message.edit_text("❌ Ошибка при закрытии заказа.")


# ============================================================================
#                        COMMENT CALLBACKS
# ============================================================================

async def _handle_comment_target(query, parts, config, notion, memory_state):
    """Handle comment target selection."""
    # nlp:comment_target:{model_id}:{target}
    if len(parts) < 4:
        return

    model_id = parts[2]
    target = parts[3]
    user_id = query.from_user.id

    state = memory_state.get(user_id) or {}
    comment_text = state.get("comment_text")

    if not comment_text:
        await query.message.edit_text("❌ Текст комментария не найден.")
        memory_state.clear(user_id)
        return

    if target == "order":
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model_id)
        if not orders:
            await query.message.edit_text("❌ Нет открытых заказов.")
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
            await query.message.edit_text("❌ Нет запланированных съемок.")
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
        await query.message.edit_text("❌ Комментарии к учету пока не поддержаны.")
        memory_state.clear(user_id)


async def _handle_comment_order(query, parts, config, notion, memory_state):
    """Handle comment order selection."""
    # nlp:comment_order:{order_id}
    if len(parts) < 3:
        return

    order_id = parts[2]
    user_id = query.from_user.id
    state = memory_state.get(user_id) or {}
    comment_text = state.get("comment_text")

    if not comment_text:
        await query.message.edit_text("❌ Текст комментария не найден.")
        memory_state.clear(user_id)
        return

    try:
        # Get existing comments
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
    """Handle disambiguation: user chose 'add files'."""
    # nlp:disambig_files:{model_id}:{number}
    if len(parts) < 4:
        return

    model_id = parts[2]
    count = int(parts[3])
    user_id = query.from_user.id

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    model_data = await notion.get_model(model_id)
    if not model_data:
        await query.message.edit_text("❌ Модель не найдена.")
        return

    model_name = model_data.title

    try:
        from datetime import datetime
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
            f"✅ Добавлено {count} файлов ({new_amount} всего)\n\n"
            f"<b>{html.escape(model_name)}</b> | {month_str}\n"
            f"Файлов: {new_amount} ({percent}%)",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await query.message.edit_text("❌ Ошибка при добавлении файлов.")


async def _handle_disambig_orders(query, parts, config, notion, memory_state):
    """Handle disambiguation: user chose 'create orders'."""
    # nlp:disambig_orders:{model_id}:{number}
    if len(parts) < 4:
        return

    model_id = parts[2]
    count = int(parts[3])

    # Ask for order type
    from app.keyboards.inline import nlp_order_type_keyboard

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else ""

    memory_state.set(query.from_user.id, {
        "flow": "nlp_order",
        "step": "awaiting_type",
        "model_id": model_id,
        "model_name": model_name,
        "count": count,
    })

    await query.message.edit_text(
        f"📦 {count}x — Тип заказа:",
        reply_markup=nlp_order_type_keyboard(model_id),
        parse_mode="HTML",
    )
