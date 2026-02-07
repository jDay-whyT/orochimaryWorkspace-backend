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
  af  = add_files       acct = acc_content_toggle  accs = acc_content_save

Anti-stale token: last segment of callback_data (6-char base36 string).
Verified against memory_state["k"] to reject presses on outdated keyboards.

Flow/step validation: each action checks that the current memory_state
flow and step match what the action expects.  On mismatch the user sees
"Сессия устарела" with [Меню][Сброс] buttons.
"""

import html
import logging
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.roles import is_authorized, is_editor
from app.services import NotionClient
from app.state import MemoryState, RecentModels, generate_token
from app.router.command_filters import CommandIntent
from app.keyboards.inline import ORDER_TYPE_CB_MAP
from app.utils.formatting import format_appended_comment


LOGGER = logging.getLogger(__name__)
router = Router()

SESSION_EXPIRED_MSG = "Сессия истекла. Повторите запрос."
STALE_MSG = "Сессия устарела, начните заново"

# Actions that do NOT require token verification (always safe)
_NO_TOKEN_ACTIONS = {"x"}


# ============================================================================
#                        VALIDATION HELPERS
# ============================================================================

def _validate_token(state: dict | None, parts: list[str], action: str) -> bool:
    """Check anti-stale token.  Returns True if valid (or action exempt)."""
    if action in _NO_TOKEN_ACTIONS:
        return True
    if not state:
        return False
    state_k = state.get("k", "")
    if not state_k:
        # Legacy state without token — allow
        return True
    # Token is always the last segment.
    cb_k = parts[-1] if parts else ""
    return cb_k == state_k


# Flow/step rules per action prefix.
# Value: (required_flow, allowed_steps | None).
# None for steps means "any step within that flow".
_FLOW_STEP_RULES: dict[str, tuple[str, set[str] | None]] = {
    "ot": ("nlp_order", {"awaiting_type"}),
    "oq": ("nlp_order", {"awaiting_count"}),
    "od": ("nlp_order", {"awaiting_date"}),
    "oc": ("nlp_order", {"awaiting_date"}),
    "sd": ("nlp_shoot", {"awaiting_date", "awaiting_new_date", "awaiting_custom_date"}),
    "sct": ("nlp_shoot", {"awaiting_content"}),
    "scd": ("nlp_shoot", {"awaiting_content"}),
    "srs": ("nlp_actions", None),
    "scm": ("nlp_actions", None),
    "acct": ("nlp_acc_content", {"selecting"}),
    "accs": ("nlp_acc_content", {"selecting"}),
    "cd": ("nlp_close", {"awaiting_date", "awaiting_custom_date"}),
    "act": ("nlp_actions", None),
}


def _validate_flow_step(state: dict | None, action: str) -> bool:
    """Check that current flow/step allows this action.  Returns True if OK."""
    rule = _FLOW_STEP_RULES.get(action)
    if rule is None:
        # No strict rule for this action — allow
        return True
    if not state:
        return False
    req_flow, allowed_steps = rule
    current_flow = state.get("flow", "")
    if current_flow != req_flow:
        return False
    if action == "act" and not state.get("model_id"):
        return False
    if allowed_steps is not None:
        current_step = state.get("step", "")
        if current_step not in allowed_steps:
            return False
    return True


async def _reject_stale(query: CallbackQuery, reason: str, memory_state: MemoryState) -> None:
    """Reject a callback with a stale/invalid message."""
    user_id = query.from_user.id
    LOGGER.info(
        "NLP callback REJECTED: user=%s reason=%s data=%s",
        user_id, reason, query.data,
    )
    memory_state.clear(user_id)
    from app.keyboards.inline import nlp_stale_keyboard
    try:
        await query.message.edit_text(
            STALE_MSG,
            reply_markup=nlp_stale_keyboard(),
        )
    except Exception:
        pass
    await query.answer(STALE_MSG, show_alert=True)


# ============================================================================
#                          MAIN ROUTER
# ============================================================================

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
    state = memory_state.get(user_id)

    LOGGER.info(
        "NLP callback: user=%s action=%s data=%s flow=%s step=%s model_id=%s order_type=%s",
        user_id, action, query.data,
        state.get("flow") if state else None,
        state.get("step") if state else None,
        state.get("model_id") if state else None,
        state.get("order_type") if state else None,
    )

    try:
        # ===== Cancel (always allowed) =====
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

        # ===== Token validation =====
        if not _validate_token(state, parts, action):
            await _reject_stale(query, "stale_token", memory_state)
            return

        # ===== Flow/step validation =====
        if not _validate_flow_step(state, action):
            await _reject_stale(query, f"flow_step_mismatch(action={action})", memory_state)
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

        # ===== Shoot Content Types =====
        elif action == "sct":
            await _handle_shoot_content_toggle(query, parts, config, memory_state)
        elif action == "scd":
            await _handle_shoot_content_done(query, parts, config, notion, memory_state, recent_models)

        # ===== Accounting Content =====
        elif action == "acct":
            await _handle_accounting_content_toggle(query, parts, config, memory_state)
        elif action == "accs":
            await _handle_accounting_content_save(query, parts, config, notion, memory_state)

        # ===== Shoot Manage (from model card) =====
        elif action == "srs":
            await _handle_shoot_reschedule_cb(query, parts, config, notion, memory_state)
        elif action == "scm":
            await _handle_shoot_comment_cb(query, parts, config, notion, memory_state)

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
    Callback: nlp:sm:{model_id}[:{k}]
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
        from app.keyboards.inline import nlp_order_confirm_keyboard, ORDER_TYPE_CB_REVERSE
        from app.router.entities_v2 import get_order_type_display_name
        type_label = get_order_type_display_name(entities.order_type)
        k = generate_token()
        # Map internal order_type to callback-safe value for storage
        cb_order_type = ORDER_TYPE_CB_REVERSE.get(entities.order_type, entities.order_type)
        memory_state.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_date",
            "model_id": model_id,
            "model_name": model_data.title,
            "order_type": entities.order_type,
            "count": count,
            "k": k,
        })
        await query.message.edit_text(
            f"<b>{html.escape(model_data.title)}</b> · {count}x {type_label}\n\nДата:",
            reply_markup=nlp_order_confirm_keyboard(k),
            parse_mode="HTML",
        )

    elif intent in (CommandIntent.CREATE_ORDERS, CommandIntent.CREATE_ORDERS_GENERAL):
        # Order without type: ask for type
        from app.keyboards.inline import nlp_order_type_keyboard
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_data.title,
            "k": k,
        })
        await query.message.edit_text(
            f"📦 <b>{html.escape(model_data.title)}</b> · Тип заказа:",
            reply_markup=nlp_order_type_keyboard(k),
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
            k = generate_token()
            memory_state.set(user_id, {
                "flow": "nlp_shoot",
                "step": "awaiting_date",
                "model_id": model_id,
                "model_name": model_data.title,
                "k": k,
            })
            await query.message.edit_text(
                f"📅 <b>{html.escape(model_data.title)}</b> · Дата съемки:",
                reply_markup=nlp_shoot_date_keyboard(k),
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
            yyyy_mm = now.strftime("%Y-%m")
            fpm = config.files_per_month
            record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)
            if not record:
                await notion.create_accounting_record(
                    config.db_accounting, model_id, model_data.title, count, yyyy_mm,
                )
                new_files = count
            else:
                new_files = record.files + count
                await notion.update_accounting_files(record.page_id, new_files)
            pct = min(100, round(new_files / fpm * 100)) if fpm > 0 else 0
            over = max(0, new_files - fpm)
            over_str = f" +{over}" if over > 0 else ""
            await query.message.edit_text(
                f"✅ +{count} файлов ({new_files} всего)\n\n"
                f"<b>{html.escape(model_data.title)}</b>\n"
                f"Файлов: {new_files}/{fpm} ({pct}%){over_str}",
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to add files: %s", e)
            await query.message.edit_text("❌ Не смог обновить Notion, попробуй позже.")

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
        k = generate_token()
        if len(orders) == 1:
            from app.keyboards.inline import nlp_close_order_date_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_close",
                "step": "awaiting_date",
                "order_id": orders[0].page_id,
                "k": k,
            })
            await query.message.edit_text(
                f"Закрыть {orders[0].order_type or '?'}?\n\nДата закрытия:",
                reply_markup=nlp_close_order_date_keyboard(k),
                parse_mode="HTML",
            )
        else:
            from app.keyboards.inline import nlp_close_order_select_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_close",
                "k": k,
            })
            await query.message.edit_text(
                f"📦 <b>{html.escape(model_data.title)}</b> · Какой заказ закрыть?",
                reply_markup=nlp_close_order_select_keyboard(orders, k),
                parse_mode="HTML",
            )

    else:
        # Default: show universal model card with live data
        from app.keyboards.inline import model_card_keyboard
        from app.services.model_card import build_model_card
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_actions",
            "model_id": model_id,
            "model_name": model_data.title,
            "k": k,
        })
        card_text, open_orders = await build_model_card(
            model_id, model_data.title, config, notion,
        )
        oo = open_orders if open_orders >= 0 else None
        await query.message.edit_text(
            card_text,
            reply_markup=model_card_keyboard(k, open_orders=oo),
            parse_mode="HTML",
        )


# ============================================================================
#                       MODEL ACTION CARD (CRM UX)
# ============================================================================

async def _handle_model_action(query, parts, config, notion, memory_state, recent_models):
    """
    Handle CRM action card button press.
    Callback: nlp:act:{action}[:{k}]
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
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await query.message.edit_text(
            f"📦 <b>{html.escape(model_name)}</b> · Тип заказа:",
            reply_markup=nlp_order_type_keyboard(k),
            parse_mode="HTML",
        )

    elif action == "files":
        # Show file count selection
        from app.keyboards.inline import nlp_files_qty_keyboard
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_files",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await query.message.edit_text(
            f"📁 <b>{html.escape(model_name)}</b> · Сколько файлов?",
            reply_markup=nlp_files_qty_keyboard(k),
            parse_mode="HTML",
        )

    elif action == "shoot":
        # Check if model has an upcoming shoot → manage it; otherwise → create new
        try:
            shoots = await notion.query_upcoming_shoots(config.db_planner, model_page_id=model_id)
        except Exception:
            shoots = []

        if shoots:
            # Manage nearest shoot
            from app.keyboards.inline import nlp_shoot_manage_keyboard
            shoot = shoots[0]
            s_date = shoot.date[:10] if shoot.date else "?"
            s_status = shoot.status or "planned"
            k = generate_token()
            memory_state.set(user_id, {
                "flow": "nlp_actions",
                "model_id": model_id,
                "model_name": model_name,
                "shoot_id": shoot.page_id,
                "k": k,
            })
            await query.message.edit_text(
                f"📅 <b>{html.escape(model_name)}</b> · Ближайшая: {s_date} ({s_status})\n\n"
                "Что делаем?",
                reply_markup=nlp_shoot_manage_keyboard(shoot.page_id, k),
                parse_mode="HTML",
            )
        else:
            # Create new shoot — start with content type selection
            from app.keyboards.inline import nlp_shoot_content_keyboard
            k = generate_token()
            memory_state.set(user_id, {
                "flow": "nlp_shoot",
                "step": "awaiting_content",
                "model_id": model_id,
                "model_name": model_name,
                "content_types": [],
                "k": k,
            })
            await query.message.edit_text(
                f"📅 <b>{html.escape(model_name)}</b> · Выберите контент:",
                reply_markup=nlp_shoot_content_keyboard([], k),
                parse_mode="HTML",
            )

    elif action == "content":
        # Show accounting content multi-select
        now = datetime.now(tz=config.timezone)
        yyyy_mm = now.strftime("%Y-%m")
        record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)
        existing_content = record.content if record and record.content else []
        accounting_id = record.page_id if record else None

        if not accounting_id:
            await query.answer("Нет записи accounting за этот месяц. Сначала добавьте файлы.", show_alert=True)
            return

        from app.keyboards.inline import nlp_accounting_content_keyboard
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_acc_content",
            "step": "selecting",
            "model_id": model_id,
            "model_name": model_name,
            "accounting_id": accounting_id,
            "selected_content": existing_content,
            "k": k,
        })
        await query.message.edit_text(
            f"🗂 <b>{html.escape(model_name)}</b> · Content\n\n"
            "Выберите типы контента:",
            reply_markup=nlp_accounting_content_keyboard(existing_content, k),
            parse_mode="HTML",
        )

    elif action == "report":
        # Show report inline
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_report",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _show_report(query, model_id, model_name, config, notion, k)

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
        k = generate_token()
        if len(orders) == 1:
            from app.keyboards.inline import nlp_close_order_date_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_close",
                "step": "awaiting_date",
                "order_id": orders[0].page_id,
                "k": k,
            })
            days = _calc_days_open(orders[0].in_date)
            label = f"{orders[0].order_type or '?'} · {_format_date_short(orders[0].in_date)} ({days}d)"
            await query.message.edit_text(
                f"Закрыть '{label}'?\n\nДата закрытия:",
                reply_markup=nlp_close_order_date_keyboard(k),
                parse_mode="HTML",
            )
        else:
            from app.keyboards.inline import nlp_close_order_select_keyboard
            memory_state.set(user_id, {
                "flow": "nlp_close",
                "model_id": model_id,
                "model_name": model_name,
                "k": k,
            })
            await query.message.edit_text(
                f"📦 <b>{html.escape(model_name)}</b> · Какой заказ закрыть?",
                reply_markup=nlp_close_order_select_keyboard(orders, k),
                parse_mode="HTML",
            )


# ============================================================================
#                          SHOOT CALLBACKS
# ============================================================================

async def _handle_shoot_date(query, parts, config, notion, memory_state, recent_models):
    """Handle shoot date selection. Callback: nlp:sd:{choice}[:{k}]"""
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

        content_types = state.get("content_types", [])
        auto_status = _compute_shoot_status(shoot_date.isoformat(), content_types)
        title = f"{model_name} · {shoot_date.strftime('%d.%m')}"
        try:
            await notion.create_shoot(
                database_id=config.db_planner,
                model_page_id=model_id,
                shoot_date=shoot_date,
                content=content_types,
                location="home",
                title=title,
                status=auto_status,
            )
            memory_state.clear(user_id)
            recent_models.add(user_id, model_id, model_name)
            ct_str = ", ".join(content_types) if content_types else "—"
            await query.message.edit_text(
                f"✅ Съемка создана на {shoot_date.strftime('%d.%m')}\n"
                f"Контент: {ct_str}\nСтатус: {auto_status}",
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to create shoot: %s", e)
            await query.message.edit_text("❌ Ошибка при создании съемки.")
            memory_state.clear(user_id)


async def _handle_shoot_done_confirm(query, parts, config, notion, memory_state):
    """Handle shoot done confirmation. Callback: nlp:sdc:{shoot_id}[:{k}]"""
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
    """Handle shoot selection. Callback: nlp:ss:{action}:{shoot_id}[:{k}]"""
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
        k = generate_token()
        memory_state.set(user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_new_date",
            "shoot_id": shoot_id,
            "model_id": model_id,
            "model_name": model_name,
            "old_date": shoot.date if shoot else None,
            "k": k,
        })
        date_str = shoot.date[:10] if shoot and shoot.date else "?"
        await query.message.edit_text(
            f"📅 Перенос съемки {date_str}\n\nНовая дата:",
            reply_markup=nlp_shoot_date_keyboard(k),
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
            new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
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
    """Handle order type selection. Callback: nlp:ot:{type}[:{k}]"""
    if len(parts) < 3:
        return

    cb_order_type = parts[2]
    user_id = query.from_user.id

    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    # Map callback value to internal value (e.g. "ad_request" -> "ad request")
    order_type = ORDER_TYPE_CB_MAP.get(cb_order_type, cb_order_type)

    LOGGER.info(
        "NLP oq/ot: user=%s cb_type=%s -> order_type=%s model=%s",
        user_id, cb_order_type, order_type, state.get("model_name"),
    )

    from app.keyboards.inline import nlp_order_qty_keyboard
    k = generate_token()
    memory_state.update(user_id, step="awaiting_count", order_type=order_type, k=k)
    model_name = state.get("model_name", "")
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {type_label}\n\nСколько?",
        reply_markup=nlp_order_qty_keyboard(k),
        parse_mode="HTML",
    )


async def _handle_order_qty(query, parts, config, notion, memory_state):
    """Handle order qty selection. Callback: nlp:oq:{count}[:{k}]"""
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

    LOGGER.info(
        "NLP oq: user=%s count=%s order_type=%s model=%s flow=%s step=%s",
        user_id, count, order_type, model_name,
        state.get("flow"), state.get("step"),
    )

    from app.keyboards.inline import nlp_order_confirm_keyboard
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    k = generate_token()
    memory_state.update(user_id, step="awaiting_date", count=count, k=k)
    await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\nДата заказа:",
        reply_markup=nlp_order_confirm_keyboard(k),
        parse_mode="HTML",
    )


async def _handle_order_date(query, parts, config, notion, memory_state):
    """Handle order date selection. Callback: nlp:od:{date}[:{k}]"""
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
    """Handle order confirm (create with default date=today). Callback: nlp:oc[:{k}]"""
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
    """Handle close order selection. Callback: nlp:co:{order_id}[:{k}]"""
    if len(parts) < 3:
        return

    order_id = parts[2]

    # Store order_id in memory for the date step
    from app.keyboards.inline import nlp_close_order_date_keyboard
    k = generate_token()
    memory_state.set(query.from_user.id, {
        "flow": "nlp_close",
        "step": "awaiting_date",
        "order_id": order_id,
        "k": k,
    })
    await query.message.edit_text(
        "Дата закрытия:",
        reply_markup=nlp_close_order_date_keyboard(k),
        parse_mode="HTML",
    )


async def _handle_close_date(query, parts, config, notion, memory_state):
    """Handle close date selection. Callback: nlp:cd:{choice}[:{k}]"""
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
    """Handle comment target selection. Callback: nlp:ct:{target}[:{k}]"""
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
            new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
            await notion.update_order_comment(orders[0].page_id, new_comment)
            memory_state.clear(user_id)
            await query.message.edit_text("✅ Комментарий добавлен")
        else:
            from app.keyboards.inline import nlp_comment_order_select_keyboard
            k = generate_token()
            memory_state.update(user_id, step="awaiting_order_selection", k=k)
            await query.message.edit_text(
                "Выберите заказ:",
                reply_markup=nlp_comment_order_select_keyboard(orders, k),
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
            new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
            await notion.update_shoot_comment(shoots[0].page_id, new_comment)
            memory_state.clear(user_id)
            await query.message.edit_text("✅ Комментарий добавлен")
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            k = generate_token()
            memory_state.update(user_id, step="awaiting_shoot_selection", k=k)
            await query.message.edit_text(
                "Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "comment", k),
                parse_mode="HTML",
            )

    elif target == "account":
        await query.message.edit_text("Комментарии к учету пока не поддержаны.")
        memory_state.clear(user_id)


async def _handle_comment_order(query, parts, config, notion, memory_state):
    """Handle comment order selection. Callback: nlp:cmo:{order_id}[:{k}]"""
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

        new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
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
    """Handle disambiguation -> files. Callback: nlp:df:{number}[:{k}]"""
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
        yyyy_mm = now.strftime("%Y-%m")
        fpm = config.files_per_month

        record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)

        if not record:
            await notion.create_accounting_record(
                config.db_accounting, model_id, model_name, count, yyyy_mm,
            )
            new_files = count
        else:
            new_files = record.files + count
            await notion.update_accounting_files(record.page_id, new_files)

        pct = min(100, round(new_files / fpm * 100)) if fpm > 0 else 0
        over = max(0, new_files - fpm)
        over_str = f" +{over}" if over > 0 else ""
        recent_models.add(user_id, model_id, model_name)
        memory_state.clear(user_id)

        await query.message.edit_text(
            f"✅ +{count} файлов ({new_files} всего)\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Файлов: {new_files}/{fpm} ({pct}%){over_str}",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await query.message.edit_text("❌ Не смог обновить Notion, попробуй позже.")


async def _handle_disambig_orders(query, parts, config, notion, memory_state):
    """Handle disambiguation -> orders. Callback: nlp:do:{number}[:{k}]"""
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
    k = generate_token()
    memory_state.set(user_id, {
        "flow": "nlp_order",
        "step": "awaiting_type",
        "model_id": model_id,
        "model_name": model_name,
        "count": count,
        "k": k,
    })

    await query.message.edit_text(
        f"📦 {count}x — Тип заказа:",
        reply_markup=nlp_order_type_keyboard(k),
        parse_mode="HTML",
    )


# ============================================================================
#                        REPORT CALLBACKS
# ============================================================================

async def _handle_report_orders(query, config, notion, memory_state):
    """Handle report orders detail. Callback: nlp:ro[:{k}]"""
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

    k = generate_token()
    memory_state.update(user_id, k=k)
    from app.keyboards.inline import nlp_report_keyboard
    if query.message:
        await query.message.edit_text(
            f"📦 <b>Открытые заказы: {html.escape(model_name)}</b>\n\n{orders_text}",
            reply_markup=nlp_report_keyboard(k),
            parse_mode="HTML",
        )


async def _handle_report_accounting(query, config, notion, memory_state):
    """Handle report accounting detail. Callback: nlp:ra[:{k}]"""
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    now = datetime.now(tz=config.timezone)
    yyyy_mm = now.strftime("%Y-%m")
    fpm = config.files_per_month
    record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else "модели"

    if not record:
        accounting_text = f"Файлов: 0/{fpm} (0%)"
    else:
        total = record.files
        pct = min(100, round(total / fpm * 100)) if fpm > 0 else 0
        over = max(0, total - fpm)
        over_str = f" +{over}" if over > 0 else ""
        accounting_text = f"Файлов: {total}/{fpm} ({pct}%){over_str}"

    k = generate_token()
    memory_state.update(user_id, k=k)
    from app.keyboards.inline import nlp_report_keyboard
    if query.message:
        await query.message.edit_text(
            f"📁 <b>Учет файлов: {html.escape(model_name)}</b>\n\n{accounting_text}",
            reply_markup=nlp_report_keyboard(k),
            parse_mode="HTML",
        )


# ============================================================================
#                          ADD FILES CALLBACK
# ============================================================================

async def _handle_add_files(query, parts, config, notion, memory_state, recent_models):
    """Handle add files from CRM card. Callback: nlp:af:{count|custom}[:{k}]"""
    if len(parts) < 3:
        return

    value = parts[2]
    user_id = query.from_user.id

    # Custom input: switch to awaiting_count step for free-text entry
    if value == "custom":
        k = generate_token()
        state = memory_state.get(user_id)
        model_id = state.get("model_id", "") if state else ""
        model_name = state.get("model_name", "") if state else ""
        memory_state.set(user_id, {
            "flow": "nlp_files",
            "step": "awaiting_count",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await query.message.edit_text(
            "Введите количество файлов:",
            parse_mode="HTML",
        )
        return

    count = int(value)

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
        yyyy_mm = now.strftime("%Y-%m")
        fpm = config.files_per_month

        record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)

        if not record:
            await notion.create_accounting_record(
                config.db_accounting, model_id, model_name, count, yyyy_mm,
            )
            new_files = count
        else:
            new_files = record.files + count
            await notion.update_accounting_files(record.page_id, new_files)

        pct = min(100, round(new_files / fpm * 100)) if fpm > 0 else 0
        over = max(0, new_files - fpm)
        over_str = f" +{over}" if over > 0 else ""
        recent_models.add(user_id, model_id, model_name)
        memory_state.clear(user_id)

        await query.message.edit_text(
            f"✅ +{count} файлов ({new_files} всего)\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Файлов: {new_files}/{fpm} ({pct}%){over_str}",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await query.message.edit_text("❌ Не смог обновить Notion, попробуй позже.")
        memory_state.clear(user_id)


# ============================================================================
#                    SHOOT CONTENT TYPES + MANAGE
# ============================================================================

def _compute_shoot_status(shoot_date: str | None, content_types: list[str]) -> str:
    """Auto-compute planner status: scheduled if date+types, else planned."""
    if shoot_date and content_types:
        return "scheduled"
    return "planned"


async def _handle_shoot_content_toggle(query, parts, config, memory_state):
    """Toggle a content type. Callback: nlp:sct:{type}[:{k}]"""
    if len(parts) < 3:
        return
    ct = parts[2]
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    selected = list(state.get("content_types", []))
    if ct in selected:
        selected.remove(ct)
    else:
        selected.append(ct)

    k = generate_token()
    memory_state.update(user_id, content_types=selected, k=k)
    model_name = state.get("model_name", "")

    from app.keyboards.inline import nlp_shoot_content_keyboard
    await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Выберите контент:",
        reply_markup=nlp_shoot_content_keyboard(selected, k),
        parse_mode="HTML",
    )


async def _handle_shoot_content_done(query, parts, config, notion, memory_state, recent_models):
    """Content selection done → proceed to date. Callback: nlp:scd:done[:{k}]"""
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    content_types = state.get("content_types", [])
    model_name = state.get("model_name", "")

    from app.keyboards.inline import nlp_shoot_date_keyboard
    k = generate_token()
    memory_state.update(user_id, step="awaiting_date", k=k)
    await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Дата съемки:",
        reply_markup=nlp_shoot_date_keyboard(k),
        parse_mode="HTML",
    )


async def _handle_shoot_reschedule_cb(query, parts, config, notion, memory_state):
    """Reschedule shoot from manage keyboard. Callback: nlp:srs:{shoot_id}[:{k}]"""
    if len(parts) < 3:
        return
    shoot_id = parts[2]
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    model_name = state.get("model_name", "") if state else ""
    model_id = state.get("model_id", "") if state else ""

    from app.keyboards.inline import nlp_shoot_date_keyboard
    k = generate_token()
    memory_state.set(user_id, {
        "flow": "nlp_shoot",
        "step": "awaiting_new_date",
        "shoot_id": shoot_id,
        "model_id": model_id,
        "model_name": model_name,
        "k": k,
    })
    await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Новая дата:",
        reply_markup=nlp_shoot_date_keyboard(k),
        parse_mode="HTML",
    )


async def _handle_shoot_comment_cb(query, parts, config, notion, memory_state):
    """Comment on shoot from manage keyboard. Callback: nlp:scm:{shoot_id}[:{k}]"""
    if len(parts) < 3:
        return
    shoot_id = parts[2]
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    model_name = state.get("model_name", "") if state else ""
    model_id = state.get("model_id", "") if state else ""

    LOGGER.info(
        "SHOOT_COMMENT_CB user=%s shoot_id=%s model_id=%s",
        user_id, shoot_id, model_id,
    )

    k = generate_token()
    memory_state.set(user_id, {
        "flow": "nlp_shoot",
        "step": "awaiting_shoot_comment",
        "shoot_id": shoot_id,
        "model_id": model_id,
        "model_name": model_name,
        "k": k,
    })
    await query.message.edit_text(
        f"💬 <b>{html.escape(model_name)}</b> · Введите комментарий:",
        parse_mode="HTML",
    )


# ============================================================================
#                    ACCOUNTING CONTENT CALLBACKS
# ============================================================================

async def _handle_accounting_content_toggle(query, parts, config, memory_state):
    """Toggle an accounting content type. Callback: nlp:acct:{type}[:{k}]"""
    if len(parts) < 3:
        return
    ct = parts[2]
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    selected = list(state.get("selected_content", []))
    if ct in selected:
        selected.remove(ct)
    else:
        selected.append(ct)

    k = generate_token()
    memory_state.update(user_id, selected_content=selected, k=k)
    model_name = state.get("model_name", "")

    from app.keyboards.inline import nlp_accounting_content_keyboard
    await query.message.edit_text(
        f"🗂 <b>{html.escape(model_name)}</b> · Content\n\n"
        "Выберите типы контента:",
        reply_markup=nlp_accounting_content_keyboard(selected, k),
        parse_mode="HTML",
    )


async def _handle_accounting_content_save(query, parts, config, notion, memory_state):
    """Save accounting content. Callback: nlp:accs:save[:{k}]"""
    user_id = query.from_user.id
    state = memory_state.get(user_id)
    if not state:
        await query.message.edit_text(SESSION_EXPIRED_MSG)
        return

    accounting_id = state.get("accounting_id")
    selected = state.get("selected_content", [])
    model_name = state.get("model_name", "")

    if not accounting_id:
        await query.message.edit_text("Запись accounting не найдена.")
        memory_state.clear(user_id)
        return

    try:
        await notion.update_accounting_content(accounting_id, selected)
        LOGGER.info(
            "Accounting content saved: user=%s accounting_id=%s content=%s",
            user_id, accounting_id, selected,
        )
        content_str = ", ".join(selected) if selected else "—"
        memory_state.clear(user_id)
        await query.message.edit_text(
            f"✅ Content сохранён\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Content: {html.escape(content_str)}",
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to save accounting content: %s", e)
        await query.message.edit_text("❌ Ошибка при сохранении Content.")
        memory_state.clear(user_id)


# ============================================================================
#                              HELPERS
# ============================================================================

async def _show_report(query, model_id, model_name, config, notion, k=""):
    """Show inline report for model."""
    from app.keyboards.inline import nlp_report_keyboard
    from app.utils import escape_html

    now = datetime.now(tz=config.timezone)
    yyyy_mm = now.strftime("%Y-%m")
    fpm = config.files_per_month

    try:
        record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)
    except Exception:
        record = None

    try:
        open_orders = await notion.query_open_orders(config.db_orders, model_id)
    except Exception:
        open_orders = []

    if record:
        total = record.files
        pct = min(100, round(total / fpm * 100)) if fpm > 0 else 0
        over = max(0, total - fpm)
        over_str = f" +{over}" if over > 0 else ""
        files_str = f"{total}/{fpm} ({pct}%){over_str}"
    else:
        files_str = f"0/{fpm} (0%)"

    orders_str = f"{len(open_orders)} открытых"

    await query.message.edit_text(
        f"📊 <b>{escape_html(model_name)}</b> · {yyyy_mm}\n\n"
        f"📁 Файлов: {files_str}\n"
        f"📦 Заказов: {orders_str}\n",
        reply_markup=nlp_report_keyboard(k),
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
