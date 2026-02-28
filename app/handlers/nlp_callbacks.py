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
  om  = orders_menu     op   = orders_page         cp   = close_page
  fm  = files_menu      smn  = shoot_menu          bk   = back

Anti-stale token: last segment of callback_data (6-char base36 string).
Verified against memory_state["k"] to reject presses on outdated keyboards.

Flow/step validation: each action checks that the current memory_state
flow and step match what the action expects. On mismatch the user sees
"Сессия устарела, откройте модель заново" and (if possible) a stateless Back.
"""

import html
import logging
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.filters.topic_access import TopicAccessCallbackFilter
from app.roles import is_authorized, is_editor
from app.services import NotionClient
from app.services import accounting as accounting_cache
from app.services import orders as orders_cache
from app.services import planner as planner_cache
from app.state import MemoryState, RecentModels, generate_token
from app.router.command_filters import CommandIntent
from app.keyboards.inline import ORDER_TYPE_CB_MAP
from app.utils.formatting import format_appended_comment
from app.utils.accounting import calculate_accounting_progress, format_accounting_progress
from app.utils import PAGE_SIZE
from app.utils.telegram import safe_edit_message


LOGGER = logging.getLogger(__name__)
router = Router()

# Tracks (chat_id, user_id) pairs that are currently executing order creation.
# Prevents duplicate Notion pages from concurrent callbacks (double-click /
# Telegram retry while the first Notion API call is still in-flight).
# asyncio is single-threaded so set membership checks are effectively atomic.
_oc_in_progress: set[tuple[int, int]] = set()
router.callback_query.filter(TopicAccessCallbackFilter())


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id

SESSION_EXPIRED_MSG = "Сессия устарела, откройте модель заново"
STALE_MSG = "Сессия устарела, откройте модель заново"

# Actions that do NOT require token verification (always safe)
_NO_TOKEN_ACTIONS = {"x", "bk", "noop", "om", "op", "cp", "fm", "smn", "sctm",
                     "more_actions", "done"}


async def _safe_edit_reply_markup(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except Exception:
        pass


async def _safe_delete_or_mark_done(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return
    except Exception:
        pass
    try:
        await bot.edit_message_text(
            "✅ Готово",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except Exception:
        pass


async def _clear_previous_screen_keyboard(query: CallbackQuery, memory_state: MemoryState) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id) or {}
    prev_id = state.get("screen_message_id")
    if not prev_id or not query.message:
        return
    if prev_id == query.message.message_id:
        return
    await _safe_edit_reply_markup(query.bot, query.message.chat.id, prev_id)


def _remember_screen_message(
    memory_state: MemoryState,
    chat_id: int,
    user_id: int,
    message_id: int | None,
) -> None:
    if message_id is None:
        return
    memory_state.update(chat_id, user_id, screen_message_id=message_id)


async def _cleanup_prompt_message(query: CallbackQuery, memory_state: MemoryState) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id) or {}
    prompt_id = state.get("prompt_message_id")
    if not prompt_id or not query.message:
        return
    await _safe_delete_or_mark_done(query.bot, query.message.chat.id, prompt_id)
    memory_state.update(chat_id, user_id, prompt_message_id=None)


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
    "oc": ("nlp_order", {"awaiting_confirm"}),
    "sd": ("nlp_shoot", {"awaiting_date", "awaiting_new_date", "awaiting_custom_date"}),
    "sct": ("nlp_shoot", {"awaiting_content", "awaiting_content_update"}),
    "scd": ("nlp_shoot", {"awaiting_content", "awaiting_content_update"}),
    "srs": ("nlp_actions", None),
    "scm": ("nlp_actions", None),
    "acct": ("nlp_acc_content", {"selecting"}),
    "accs": ("nlp_acc_content", {"selecting"}),
    "cd": ("nlp_close", {"awaiting_date", "awaiting_custom_date"}),
    "cp": ("nlp_close_picker", {"selecting"}),
    "op": ("nlp_orders_view", {"viewing"}),
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


async def _reject_stale(
    query: CallbackQuery,
    reason: str,
    memory_state: MemoryState,
    model_id: str | None = None,
) -> None:
    """Reject a callback with a stale/invalid message."""
    chat_id, user_id = _state_ids_from_query(query)
    LOGGER.info(
        "NLP callback REJECTED: user=%s reason=%s data=%s",
        user_id, reason, query.data,
    )
    memory_state.clear(chat_id, user_id)
    reply_markup = None
    if model_id:
        from app.keyboards.inline import nlp_back_keyboard
        reply_markup = nlp_back_keyboard(model_id)
    try:
        await query.message.edit_text(
            STALE_MSG,
            reply_markup=reply_markup,
        )
    except Exception:
        pass
    await query.answer(STALE_MSG, show_alert=True)


async def _session_expired(
    query: CallbackQuery,
    memory_state: MemoryState,
    model_id: str | None = None,
) -> None:
    """Show session expired message with recovery actions."""
    await _reject_stale(query, "session_expired", memory_state, model_id=model_id)


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
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)

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
            memory_state.clear(chat_id, user_id)
            sub = parts[2] if len(parts) >= 3 else "c"
            if sub == "m":
                if query.message:
                    try:
                        await query.message.edit_text(
                            "👋 Главное меню. Напишите запрос текстом или /start",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
            else:
                if query.message:
                    await _safe_edit_reply_markup(
                        query.bot,
                        chat_id=query.message.chat.id,
                        message_id=query.message.message_id,
                    )
                    try:
                        await query.message.edit_text(
                            "✅ Готово, напиши новую модель",
                            reply_markup=None,
                        )
                    except Exception:
                        pass
            await query.answer()
            return
        if action == "bk":
            model_id = parts[2] if len(parts) >= 3 else None
            await _handle_back_to_card(query, config, notion, memory_state, model_id)
            await query.answer()
            return
        if action == "noop":
            await query.answer()
            return

        # ===== Token validation =====
        if not _validate_token(state, parts, action):
            model_id = parts[2] if len(parts) >= 3 and action == "bk" else None
            await _reject_stale(query, "stale_token", memory_state, model_id=model_id)
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
        elif action == "om":
            await _handle_orders_menu_action(query, parts, config, notion, memory_state)
        elif action == "op":
            await _handle_orders_view_page(query, parts, config, notion, memory_state)
        elif action == "cp":
            await _handle_close_picker_page(query, parts, config, notion, memory_state)
        elif action == "fm":
            await _handle_files_menu_action(query, parts, config, notion, memory_state)
        elif action == "smn":
            await _handle_shoot_menu_action(query, parts, config, notion, memory_state, recent_models)

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
        elif action == "sctm":
            await _handle_shoot_content_manage(query, parts, config, notion, memory_state)

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

        # ===== Post-action completion buttons =====
        elif action == "more_actions":
            await _handle_more_actions(query, parts, config, notion, memory_state)
        elif action == "done":
            await _handle_done(query, parts, memory_state)

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
    chat_id, user_id = _state_ids_from_query(query)

    # Get model info
    model_data = await notion.get_model(model_id)
    if not model_data:
        await query.message.edit_text("Модель не найдена.")
        return

    model = {"id": model_id, "name": model_data.title}
    recent_models.add(user_id, model_id, model_data.title)

    # Get original intent + text from memory state
    state = memory_state.get(chat_id, user_id)
    intent_value = state.get("intent", "") if state else ""
    original_text = state.get("entities_raw", "") if state else ""
    memory_state.clear(chat_id, user_id)

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
        from app.keyboards.inline import nlp_order_date_keyboard, ORDER_TYPE_CB_REVERSE
        from app.router.entities_v2 import get_order_type_display_name
        type_label = get_order_type_display_name(entities.order_type)
        k = generate_token()
        # Map internal order_type to callback-safe value for storage
        cb_order_type = ORDER_TYPE_CB_REVERSE.get(entities.order_type, entities.order_type)
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_order",
            "step": "awaiting_date",
            "model_id": model_id,
            "model_name": model_data.title,
            "order_type": entities.order_type,
            "count": count,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        try:
            msg = await query.message.edit_text(
                f"<b>{html.escape(model_data.title)}</b> · {count}x {type_label}\n\nДата заказа:",
                reply_markup=nlp_order_date_keyboard(model_id, k),
                parse_mode="HTML",
            )
        except Exception:
            # Ignore edit errors (e.g., "message is not modified")
            msg = None
        _remember_screen_message(
            memory_state,
            chat_id,
            user_id,
            msg.message_id if msg else query.message.message_id,
            )

    elif intent in (CommandIntent.CREATE_ORDERS, CommandIntent.CREATE_ORDERS_GENERAL):
        # Order without type: ask for type
        from app.keyboards.inline import nlp_order_type_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_data.title,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        try:
            msg = await query.message.edit_text(
                f"📦 <b>{html.escape(model_data.title)}</b> · Тип заказа:",
                reply_markup=nlp_order_type_keyboard(model_id, k),
                parse_mode="HTML",
            )
        except Exception:
            # Ignore edit errors (e.g., "message is not modified")
            msg = None
        _remember_screen_message(
            memory_state,
            chat_id,
            user_id,
            msg.message_id if msg else query.message.message_id,
            )

    elif intent == CommandIntent.SHOOT_CREATE:
        if entities and entities.date:
            # Date known: create shoot directly
            if not is_editor(user_id, config):
                try:
                    await query.message.edit_text("❌ Нет прав.")
                except Exception:
                    # Ignore edit errors (e.g., "message is not modified")
                    pass
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
                from app.keyboards.inline import nlp_action_complete_keyboard
                await query.message.edit_text(
                    f"✅ Съемка создана на {entities.date.strftime('%d.%m')}",
                    reply_markup=nlp_action_complete_keyboard(model_id),
                    parse_mode="HTML",
                )
            except Exception as e:
                LOGGER.exception("Failed to create shoot: %s", e)
                await query.message.edit_text("❌ Ошибка при создании съемки.")
        else:
            # No date: ask for date
            from app.keyboards.inline import nlp_shoot_date_keyboard
            k = generate_token()
            memory_state.set(chat_id, user_id, {
                "flow": "nlp_shoot",
                "step": "awaiting_date",
                "model_id": model_id,
                "model_name": model_data.title,
                "k": k,
            })
            await _clear_previous_screen_keyboard(query, memory_state)
            msg = await query.message.edit_text(
                f"📅 <b>{html.escape(model_data.title)}</b> · Дата съемки:",
                reply_markup=nlp_shoot_date_keyboard(model_id, k),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                user_id,
                msg.message_id if msg else query.message.message_id,
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
            record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)
            if not record:
                await notion.create_accounting_record(
                    config.db_accounting, model_id, model_data.title, count, yyyy_mm,
                )
                new_files = count
                record_status = None
            else:
                new_files = record.files + count
                await notion.update_accounting_files(record.page_id, new_files)
                record_status = record.status
            progress_line = format_accounting_progress(new_files, record_status)
            from app.keyboards.inline import nlp_action_complete_keyboard
            await query.message.edit_text(
                f"✅ +{count} файлов ({new_files} всего)\n\n"
                f"<b>{html.escape(model_data.title)}</b>\n"
                f"Файлов: {progress_line}",
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to add files: %s", e)
            await query.message.edit_text("❌ Не смог обновить Notion, попробуй позже.")

    elif intent == CommandIntent.CLOSE_ORDERS:
        # Close orders flow
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет доступа.")
            return
        await _show_close_picker(
            query=query,
            model_id=model_id,
            model_name=model_data.title,
            config=config,
            notion=notion,
            memory_state=memory_state,
        )

    else:
        # Default: show universal model card with live data
        from app.keyboards.inline import model_card_keyboard
        from app.services.model_card import build_model_card
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_actions",
            "model_id": model_id,
            "model_name": model_data.title,
            "k": k,
        })
        card_text, open_orders = await build_model_card(
            model_id, model_data.title, config, notion,
        )
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            card_text,
            reply_markup=model_card_keyboard(k),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            user_id,
            msg.message_id if msg else query.message.message_id,
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
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state["model_id"]
    model_name = state.get("model_name", "")

    if action == "order":
        # Show order type selection
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет доступа.")
            return
        from app.keyboards.inline import nlp_order_type_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📦 <b>{html.escape(model_name)}</b> · Тип заказа:",
            reply_markup=nlp_order_type_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            user_id,
            msg.message_id if msg else query.message.message_id,
            )

    elif action == "files":
        await _show_files_menu(query, config, notion, memory_state)

    elif action == "shoot":
        await _show_shoot_menu(query, config, notion, memory_state)

    elif action == "content":
        # Show accounting content multi-select
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет доступа.")
            return
        now = datetime.now(tz=config.timezone)
        yyyy_mm = now.strftime("%Y-%m")
        record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)
        existing_content = record.content if record and record.content else []
        accounting_id = record.page_id if record else None

        if not accounting_id:
            await query.answer("Нет записи accounting за этот месяц. Сначала добавьте файлы.", show_alert=True)
            return

        from app.keyboards.inline import nlp_accounting_content_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_acc_content",
            "step": "selecting",
            "model_id": model_id,
            "model_name": model_name,
            "accounting_id": accounting_id,
            "selected_content": existing_content,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"🗂 <b>{html.escape(model_name)}</b> · Content\n\n"
            "Выберите типы контента:",
            reply_markup=nlp_accounting_content_keyboard(existing_content, model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            user_id,
            msg.message_id if msg else query.message.message_id,
        )

    elif action == "report":
        # Show report inline
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_report",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _show_report(query, model_id, model_name, config, notion, memory_state, k)

    elif action == "orders":
        await _show_orders_menu(query, config, notion, memory_state)

    elif action == "close":
        await _show_close_picker(
            query=query,
            model_id=model_id,
            model_name=model_name,
            config=config,
            notion=notion,
            memory_state=memory_state,
        )


async def _handle_back_to_card(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    model_id: str | None,
) -> None:
    await query.answer()  # Instant response to remove loading indicator
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not model_id and state:
        model_id = state.get("model_id")
    if not model_id:
        await _session_expired(query, memory_state)
        return

    model_name = state.get("model_name", "") if state else ""
    if not model_name:
        model_data = await notion.get_model(model_id)
        model_name = model_data.title if model_data else ""
    from app.keyboards.inline import model_card_keyboard
    from app.services.model_card import build_model_card

    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_actions",
        "model_id": model_id,
        "model_name": model_name,
        "k": k,
    })
    card_text, _ = await build_model_card(model_id, model_name, config, notion)
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        card_text,
        reply_markup=model_card_keyboard(k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _show_orders_menu(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")
    orders = await orders_cache.get_cached_orders(notion, config, model_id)
    orders.sort(key=lambda o: o.in_date or "9999-99-99")
    has_orders = bool(orders)
    can_edit = is_editor(user_id, config)

    memory_state.set(chat_id, user_id, {
        "flow": "nlp_orders_menu",
        "step": "menu",
        "model_id": model_id,
        "model_name": model_name,
        "orders": orders,
        "page": 1,
    })

    from app.keyboards.inline import nlp_orders_menu_keyboard
    text = (
        f"📦 <b>{html.escape(model_name)}</b>\n\n"
        f"Открытых заказов: {len(orders)}"
        if has_orders
        else f"📦 <b>{html.escape(model_name)}</b>\n\nНет открытых заказов."
    )
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        text,
        reply_markup=nlp_orders_menu_keyboard(
            can_edit=can_edit,
            has_orders=has_orders,
            model_id=model_id,
        ),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _show_orders_view(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    page: int,
) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")
    orders = state.get("orders")
    if orders is None:
        orders = await orders_cache.get_cached_orders(notion, config, model_id)
        orders.sort(key=lambda o: o.in_date or "9999-99-99")

    if not orders:
        await _show_orders_menu(query, config, notion, memory_state)
        return

    total_pages = max(1, (len(orders) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_orders = orders[start:start + PAGE_SIZE]

    lines = []
    for order in page_orders:
        days = _calc_days_open(order.in_date)
        lines.append(
            f"• {order.order_type or '?'} · {_format_date_short(order.in_date)} ({days}d)"
        )

    text = (
        f"📄 <b>{html.escape(model_name)}</b> · Заказы\n\n"
        + "\n".join(lines)
        + f"\n\nСтраница {page}/{total_pages}"
    )

    from app.keyboards.inline import nlp_orders_view_keyboard
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_orders_view",
        "step": "viewing",
        "model_id": model_id,
        "model_name": model_name,
        "orders": orders,
        "page": page,
    })
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        text,
        reply_markup=nlp_orders_view_keyboard(page, total_pages, model_id),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _show_close_picker(
    query: CallbackQuery,
    model_id: str,
    model_name: str,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    page: int | None = None,
) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "❌ Нет доступа.",
            reply_markup=nlp_back_keyboard(model_id),
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    orders = await orders_cache.get_cached_orders(notion, config, model_id)
    orders.sort(key=lambda o: o.in_date or "9999-99-99")
    if not orders:
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"✅ Нет открытых заказов для {html.escape(model_name)}",
            reply_markup=nlp_back_keyboard(model_id),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    total_pages = max(1, (len(orders) + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = page or 1
    current_page = max(1, min(current_page, total_pages))
    start = (current_page - 1) * PAGE_SIZE
    page_orders = orders[start:start + PAGE_SIZE]

    from app.keyboards.inline import nlp_close_order_select_keyboard
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_close_picker",
        "step": "selecting",
        "model_id": model_id,
        "model_name": model_name,
        "orders": orders,
        "page": current_page,
    })
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · Какой заказ закрыть?",
        reply_markup=nlp_close_order_select_keyboard(
            page_orders,
            current_page,
            total_pages,
            model_id,
        ),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_orders_menu_action(
    query: CallbackQuery,
    parts: list[str],
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    if len(parts) < 3:
        return
    action = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")

    if action == "new":
        if not is_editor(user_id, config):
            from app.keyboards.inline import nlp_back_keyboard
            await _clear_previous_screen_keyboard(query, memory_state)
            msg = await query.message.edit_text(
                "❌ Нет доступа.",
                reply_markup=nlp_back_keyboard(model_id),
            )
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
            return
        from app.keyboards.inline import nlp_order_type_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📦 <b>{html.escape(model_name)}</b> · Тип заказа:",
            reply_markup=nlp_order_type_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if action == "view":
        await _show_orders_view(query, config, notion, memory_state, page=1)
        return

    if action == "close":
        await _show_close_picker(
            query=query,
            model_id=model_id,
            model_name=model_name,
            config=config,
            notion=notion,
            memory_state=memory_state,
        )
        return


async def _handle_orders_view_page(
    query: CallbackQuery,
    parts: list[str],
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    if len(parts) < 3:
        return
    try:
        page = int(parts[2])
    except ValueError:
        return
    await _show_orders_view(query, config, notion, memory_state, page=page)


async def _handle_close_picker_page(
    query: CallbackQuery,
    parts: list[str],
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    if len(parts) < 3:
        return
    try:
        page = int(parts[2])
    except ValueError:
        return
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return
    await _show_close_picker(
        query=query,
        model_id=state.get("model_id"),
        model_name=state.get("model_name", ""),
        config=config,
        notion=notion,
        memory_state=memory_state,
        page=page,
    )


async def _show_files_menu(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")
    can_edit = is_editor(user_id, config)

    from app.keyboards.inline import nlp_files_menu_keyboard
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_files_menu",
        "step": "menu",
        "model_id": model_id,
        "model_name": model_name,
    })
    text = f"📁 <b>{html.escape(model_name)}</b>\n\nВыберите действие:"
    if not can_edit:
        text = f"📁 <b>{html.escape(model_name)}</b>\n\n❌ Нет доступа."
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        text,
        reply_markup=nlp_files_menu_keyboard(can_edit=can_edit, model_id=model_id),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_files_menu_action(
    query: CallbackQuery,
    parts: list[str],
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    if len(parts) < 3:
        return
    action = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")

    if not is_editor(user_id, config):
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "❌ Нет доступа.",
            reply_markup=nlp_back_keyboard(model_id),
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if action == "add":
        from app.keyboards.inline import nlp_files_qty_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_files",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📁 <b>{html.escape(model_name)}</b> · Сколько файлов?",
            reply_markup=nlp_files_qty_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    now = datetime.now(tz=config.timezone)
    yyyy_mm = now.strftime("%Y-%m")
    record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)
    if not record:
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "Нет записи accounting за этот месяц. Сначала добавьте файлы.",
            reply_markup=nlp_back_keyboard(model_id),
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if action == "content":
        from app.keyboards.inline import nlp_accounting_content_keyboard
        existing_content = record.content if record.content else []
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_acc_content",
            "step": "selecting",
            "model_id": model_id,
            "model_name": model_name,
            "accounting_id": record.page_id,
            "selected_content": existing_content,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"🗂 <b>{html.escape(model_name)}</b> · Content\n\n"
            "Выберите типы контента:",
            reply_markup=nlp_accounting_content_keyboard(existing_content, model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if action == "comment":
        from app.keyboards.inline import nlp_back_keyboard
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_accounting_comment",
            "step": "awaiting_accounting_comment",
            "model_id": model_id,
            "model_name": model_name,
            "accounting_id": record.page_id,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"💬 <b>{html.escape(model_name)}</b> · Введите комментарий:",
            parse_mode="HTML",
            reply_markup=nlp_back_keyboard(model_id),
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return


async def _show_shoot_menu(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")
    can_edit = is_editor(user_id, config)

    shoots = []
    try:
        shoots = await planner_cache.get_cached_shoots(notion, config, model_id)
    except Exception:
        shoots = []

    shoot = shoots[0] if shoots else None
    shoot_text = "нет"
    if shoot:
        s_date = shoot.date[:10] if shoot.date else "?"
        s_status = shoot.status or "planned"
        shoot_text = f"{s_date} ({s_status})"

    from app.keyboards.inline import nlp_shoot_menu_keyboard
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_shoot_menu",
        "step": "menu",
        "model_id": model_id,
        "model_name": model_name,
        "shoot_id": shoot.page_id if shoot else None,
    })
    text = f"📅 <b>{html.escape(model_name)}</b>\n\nБлижайшая: {shoot_text}"
    if not can_edit:
        text = f"📅 <b>{html.escape(model_name)}</b>\n\n❌ Нет доступа."
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        text,
        reply_markup=nlp_shoot_menu_keyboard(
            has_shoot=bool(shoot),
            can_edit=can_edit,
            model_id=model_id,
        ),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_shoot_menu_action(
    query: CallbackQuery,
    parts: list[str],
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    if len(parts) < 3:
        return
    action = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state or not state.get("model_id"):
        await _session_expired(query, memory_state)
        return

    if not is_editor(user_id, config):
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "❌ Нет доступа.",
            reply_markup=nlp_back_keyboard(state.get("model_id", "")),
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name", "")
    shoot_id = state.get("shoot_id")

    if action == "new":
        from app.keyboards.inline import nlp_shoot_content_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_content",
            "model_id": model_id,
            "model_name": model_name,
            "content_types": [],
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📅 <b>{html.escape(model_name)}</b> · Выберите контент:",
            reply_markup=nlp_shoot_content_keyboard([], model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if not shoot_id:
        await _show_shoot_menu(query, config, notion, memory_state)
        return

    if action == "reschedule":
        from app.keyboards.inline import nlp_shoot_date_keyboard
        shoot = await notion.get_shoot(shoot_id)
        old_date = shoot.date if shoot else None
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_new_date",
            "shoot_id": shoot_id,
            "model_id": model_id,
            "model_name": model_name,
            "old_date": old_date,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📅 <b>{html.escape(model_name)}</b> · Новая дата:",
            reply_markup=nlp_shoot_date_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if action == "close":
        await notion.update_shoot_status(shoot_id, "done")
        from app.keyboards.inline import nlp_back_keyboard
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_actions",
            "model_id": model_id,
            "model_name": model_name,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        from app.keyboards.inline import nlp_action_complete_keyboard
        msg = await query.message.edit_text(
            "✅ Съемка закрыта",
            reply_markup=nlp_action_complete_keyboard(model_id),
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    if action == "content":
        await _handle_shoot_content_manage(query, ["nlp", "sctm", shoot_id], config, notion, memory_state)
        return

    if action == "comment":
        from app.keyboards.inline import nlp_back_keyboard
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_shoot_comment",
            "shoot_id": shoot_id,
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"💬 <b>{html.escape(model_name)}</b> · Введите комментарий:",
            parse_mode="HTML",
            reply_markup=nlp_back_keyboard(model_id),
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return


# ============================================================================
#                          SHOOT CALLBACKS
# ============================================================================

async def _handle_shoot_date(query, parts, config, notion, memory_state, recent_models):
    """Handle shoot date selection. Callback: nlp:sd:{choice}[:{k}]"""
    if len(parts) < 3:
        return

    date_choice = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
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
        memory_state.update(chat_id, user_id, step="awaiting_custom_date")
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "Введите дату (ДД.ММ):",
            parse_mode="HTML",
            reply_markup=nlp_back_keyboard(model_id),
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
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
            from app.keyboards.inline import nlp_action_complete_keyboard
            await _clear_previous_screen_keyboard(query, memory_state)
            await _cleanup_prompt_message(query, memory_state)
            msg = await query.message.edit_text(
                f"✅ Съемка перенесена с {old_label} на {shoot_date.strftime('%d.%m')}",
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
            memory_state.clear(chat_id, user_id)
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
    else:
        # Create shoot
        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет прав.")
            memory_state.clear(chat_id, user_id)
            return

        content_types = state.get("content_types", [])
        auto_status = _compute_shoot_status(shoot_date.isoformat(), content_types)
        title = f"{model_name} · {shoot_date.strftime('%d.%m')}"
        try:
            shoot_id = await notion.create_shoot(
                database_id=config.db_planner,
                model_page_id=model_id,
                shoot_date=shoot_date,
                content=content_types,
                location="home",
                title=title,
                status=auto_status,
            )
            recent_models.add(user_id, model_id, model_name)
            ct_str = ", ".join(content_types) if content_types else "—"
            from app.keyboards.inline import nlp_action_complete_keyboard
            await _clear_previous_screen_keyboard(query, memory_state)
            await _cleanup_prompt_message(query, memory_state)
            msg = await query.message.edit_text(
                f"✅ Съемка создана на {shoot_date.strftime('%d.%m')}\n"
                f"Контент: {ct_str}\nСтатус: {auto_status}",
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
            memory_state.clear(chat_id, user_id)
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        except Exception as e:
            LOGGER.exception("Failed to create shoot: %s", e)
            await query.message.edit_text("❌ Ошибка при создании съемки.")
            memory_state.clear(chat_id, user_id)


async def _handle_shoot_done_confirm(query, parts, config, notion, memory_state):
    """Handle shoot done confirmation. Callback: nlp:sdc:{shoot_id}[:{k}]"""
    if len(parts) < 3:
        return

    shoot_id = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    try:
        await notion.update_shoot_status(shoot_id, "done")
        from app.keyboards.inline import nlp_action_complete_keyboard
        shoot = await notion.get_shoot(shoot_id)
        model_id = shoot.model_id if shoot else ""
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "✅ Съемка выполнена",
            reply_markup=nlp_action_complete_keyboard(model_id),
        )
        memory_state.clear(chat_id, user_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
    except Exception as e:
        LOGGER.exception("Failed to mark shoot as done: %s", e)
        await query.message.edit_text("❌ Ошибка.")


async def _handle_shoot_select(query, parts, config, notion, memory_state):
    """Handle shoot selection. Callback: nlp:ss:{action}:{shoot_id}[:{k}]"""
    if len(parts) < 4:
        return

    action = parts[2]
    shoot_id = parts[3]
    chat_id, user_id = _state_ids_from_query(query)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    if action == "done":
        await notion.update_shoot_status(shoot_id, "done")
        shoot = await notion.get_shoot(shoot_id)
        model_id = shoot.model_id if shoot else ""
        from app.keyboards.inline import nlp_action_complete_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "✅ Съемка выполнена",
            reply_markup=nlp_action_complete_keyboard(model_id),
        )
        memory_state.clear(chat_id, user_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)

    elif action == "reschedule":
        shoot = await notion.get_shoot(shoot_id)
        model_name = shoot.model_title if shoot else ""
        from app.keyboards.inline import nlp_shoot_date_keyboard
        model_id = shoot.model_id if shoot else ""
        k = generate_token()
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_new_date",
            "shoot_id": shoot_id,
            "model_id": model_id,
            "model_name": model_name,
            "old_date": shoot.date if shoot else None,
            "k": k,
        })
        date_str = shoot.date[:10] if shoot and shoot.date else "?"
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📅 Перенос съемки {date_str}\n\nНовая дата:",
            reply_markup=nlp_shoot_date_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)

    elif action == "comment":
        state = memory_state.get(chat_id, user_id)
        if not state:
            await _session_expired(query, memory_state)
            return
        comment_text = state.get("comment_text")
        if comment_text:
            shoot = await notion.get_shoot(shoot_id)
            existing = shoot.comments if shoot else ""
            new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
            await notion.update_shoot_comment(shoot_id, new_comment)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard
            await _clear_previous_screen_keyboard(query, memory_state)
            msg = await query.message.edit_text(
                "✅ Комментарий добавлен",
                reply_markup=nlp_action_complete_keyboard(state.get("model_id", "")),
            )
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        else:
            await query.message.edit_text("Текст комментария не найден.")
            memory_state.clear(chat_id, user_id)


# ============================================================================
#                          ORDER CALLBACKS
# ============================================================================

async def _handle_order_type(query, parts, config, memory_state):
    """Handle order type selection. Callback: nlp:ot:{type}[:{k}]"""
    if len(parts) < 3:
        return

    cb_order_type = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    # Map callback value to internal value (e.g. "ad_request" -> "ad request")
    order_type = ORDER_TYPE_CB_MAP.get(cb_order_type, cb_order_type)

    LOGGER.info(
        "NLP oq/ot: user=%s cb_type=%s -> order_type=%s model=%s",
        user_id, cb_order_type, order_type, state.get("model_name"),
    )

    from app.keyboards.inline import nlp_order_qty_keyboard
    k = generate_token()
    memory_state.update(chat_id, user_id, step="awaiting_count", order_type=order_type, k=k)
    model_name = state.get("model_name", "")
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {type_label}\n\nСколько?",
        reply_markup=nlp_order_qty_keyboard(state.get("model_id", ""), k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_order_qty(query, parts, config, notion, memory_state):
    """Handle order qty selection. Callback: nlp:oq:{count}[:{k}]"""
    if len(parts) < 3:
        return

    value = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    model_name = state.get("model_name", "")
    order_type = state.get("order_type", "")
    model_id = state.get("model_id", "")

    LOGGER.info(
        "NLP oq: user=%s value=%s order_type=%s model=%s flow=%s step=%s",
        user_id, value, order_type, model_name,
        state.get("flow"), state.get("step"),
    )

    if value == "custom":
        from app.keyboards.inline import nlp_back_keyboard
        from app.router.entities_v2 import get_order_type_display_name

        type_label = get_order_type_display_name(order_type)
        k = generate_token()
        memory_state.update(chat_id, user_id, step="awaiting_custom_count", k=k)

        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📦 <b>{html.escape(model_name)}</b> · {type_label}\n\n"
            f"Введите количество:",
            reply_markup=nlp_back_keyboard(model_id),
            parse_mode="HTML",
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(
            memory_state,
            chat_id,
            user_id,
            msg.message_id if msg else query.message.message_id,
        )
        return

    try:
        count = int(value)
    except ValueError:
        return

    from app.keyboards.inline import nlp_order_date_keyboard
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    k = generate_token()
    memory_state.update(chat_id, user_id, step="awaiting_date", count=count, k=k)
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\nДата заказа:",
        reply_markup=nlp_order_date_keyboard(model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_order_date(query, parts, config, notion, memory_state):
    """Handle order date selection. Callback: nlp:od:{date}[:{k}]"""
    if len(parts) < 3:
        return

    date_choice = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id", "")
    model_name = state.get("model_name", "")
    order_type = state.get("order_type", "")
    count = state.get("count", 1)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        memory_state.clear(chat_id, user_id)
        return

    today_date = date.today()
    if date_choice == "today":
        in_date = today_date
    elif date_choice == "yesterday":
        in_date = today_date - timedelta(days=1)
    elif date_choice == "custom":
        memory_state.update(chat_id, user_id, step="awaiting_custom_date")
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "Введите дату (ДД.ММ):",
            reply_markup=nlp_back_keyboard(model_id),
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return
    else:
        in_date = today_date

    from app.keyboards.inline import nlp_order_confirm_keyboard
    from app.router.entities_v2 import get_order_type_display_name
    type_label = get_order_type_display_name(order_type)
    k = generate_token()
    memory_state.update(chat_id, user_id, step="awaiting_confirm", in_date=in_date.isoformat(), k=k)
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\n"
        f"Дата заказа: <b>{in_date.strftime('%d.%m')}</b>\n\nСоздать заказ?",
        reply_markup=nlp_order_confirm_keyboard(model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_order_confirm(query, parts, config, notion, memory_state, recent_models):
    """Handle order confirm (create with default date=today). Callback: nlp:oc[:{k}]"""
    chat_id, user_id = _state_ids_from_query(query)

    # Guard against concurrent duplicate callbacks (double-click / Telegram
    # retry while the Notion API call is still in-flight).
    # asyncio is single-threaded so the membership check and add are atomic —
    # no other coroutine can interleave between these two lines.
    _oc_key = (chat_id, user_id)
    if _oc_key in _oc_in_progress:
        await query.answer()
        return
    _oc_in_progress.add(_oc_key)
    try:
        state = memory_state.get(chat_id, user_id)
        if not state:
            await _session_expired(query, memory_state)
            return

        model_id = state.get("model_id", "")
        model_name = state.get("model_name", "")
        order_type = state.get("order_type", "")
        count = state.get("count", 1)
        in_date_str = state.get("in_date")
        in_date = date.fromisoformat(in_date_str) if in_date_str else date.today()

        if not is_editor(user_id, config):
            await query.message.edit_text("❌ Нет прав.")
            memory_state.clear(chat_id, user_id)
            return

        try:
            if order_type in ("short", "ad request"):
                title = f"{model_name} | {order_type} × {count}"
                await notion.create_order(
                    database_id=config.db_orders,
                    model_page_id=model_id,
                    order_type=order_type,
                    in_date=in_date,
                    count=count,
                    title=title,
                )
            else:
                for i in range(1, count + 1):
                    title = f"{model_name} | {order_type} {i}/{count}"
                    await notion.create_order(
                        database_id=config.db_orders,
                        model_page_id=model_id,
                        order_type=order_type,
                        in_date=in_date,
                        count=1,
                        title=title,
                    )

            recent_models.add(user_id, model_id, model_name)

            from app.router.entities_v2 import get_order_type_display_name
            from app.keyboards.inline import nlp_action_complete_keyboard
            type_label = get_order_type_display_name(order_type)
            await _clear_previous_screen_keyboard(query, memory_state)
            await _cleanup_prompt_message(query, memory_state)
            await safe_edit_message(
                query,
                f"✅ Создано {count}x {type_label}\n"
                f"<b>{html.escape(model_name)}</b> · {in_date.strftime('%d.%m')}",
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
            msg = query.message
            memory_state.clear(chat_id, user_id)
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)

        except Exception as e:
            LOGGER.exception("Failed to create orders: %s", e)
            await query.message.edit_text("❌ Ошибка при создании заказов.")
            memory_state.clear(chat_id, user_id)

    finally:
        _oc_in_progress.discard(_oc_key)


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
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id) or {}
    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_close",
        "step": "awaiting_date",
        "order_id": order_id,
        "model_id": state.get("model_id"),
        "model_name": state.get("model_name"),
        "k": k,
    })
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        "Дата закрытия:",
        reply_markup=nlp_close_order_date_keyboard(state.get("model_id", ""), k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_close_date(query, parts, config, notion, memory_state):
    """Handle close date selection. Callback: nlp:cd:{choice}[:{k}]"""
    if len(parts) < 3:
        return

    date_choice = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    # Get order_id from memory
    state = memory_state.get(chat_id, user_id)
    order_id = state.get("order_id") if state else None
    if not order_id:
        await _session_expired(query, memory_state)
        return

    today_date = date.today()
    if date_choice == "today":
        out_date = today_date
    elif date_choice == "yesterday":
        out_date = today_date - timedelta(days=1)
    elif date_choice == "custom":
        memory_state.update(chat_id, user_id, step="awaiting_custom_date")
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "Введите дату закрытия (ДД.ММ):",
            reply_markup=nlp_back_keyboard(state.get("model_id", "") if state else ""),
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return
    else:
        out_date = today_date

    model_id_for_kb = state.get("model_id", "") if state else ""
    try:
        await notion.close_order(order_id, out_date)
        await _clear_previous_screen_keyboard(query, memory_state)
        await _cleanup_prompt_message(query, memory_state)
        from app.keyboards.inline import nlp_action_complete_keyboard
        msg = await query.message.edit_text(
            f"✅ Заказ закрыт · {out_date.strftime('%d.%m')}",
            reply_markup=nlp_action_complete_keyboard(model_id_for_kb),
            parse_mode="HTML",
        )
        memory_state.clear(chat_id, user_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
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
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        memory_state.clear(chat_id, user_id)
        return

    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    model_id = state.get("model_id", "")
    comment_text = state.get("comment_text")
    if not comment_text:
        await query.message.edit_text("Текст комментария не найден.")
        memory_state.clear(chat_id, user_id)
        return

    if target == "order":
        orders = await orders_cache.get_cached_orders(notion, config, model_id)
        if not orders:
            await query.message.edit_text("Нет открытых заказов.")
            memory_state.clear(chat_id, user_id)
            return
        if len(orders) == 1:
            existing = orders[0].comments or ""
            new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
            await notion.update_order_comment(orders[0].page_id, new_comment)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard
            await query.message.edit_text(
                "✅ Комментарий добавлен",
                reply_markup=nlp_action_complete_keyboard(model_id),
            )
        else:
            from app.keyboards.inline import nlp_comment_order_select_keyboard
            k = generate_token()
            memory_state.update(chat_id, user_id, step="awaiting_order_selection", k=k)
            await _clear_previous_screen_keyboard(query, memory_state)
            msg = await query.message.edit_text(
                "Выберите заказ:",
                reply_markup=nlp_comment_order_select_keyboard(orders, model_id, k),
                parse_mode="HTML",
            )
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)

    elif target == "shoot":
        shoots = await planner_cache.get_cached_shoots(notion, config, model_id)
        if not shoots:
            await query.message.edit_text("Нет запланированных съемок.")
            memory_state.clear(chat_id, user_id)
            return
        if len(shoots) == 1:
            existing = shoots[0].comments or ""
            new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
            await notion.update_shoot_comment(shoots[0].page_id, new_comment)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard
            await query.message.edit_text(
                "✅ Комментарий добавлен",
                reply_markup=nlp_action_complete_keyboard(model_id),
            )
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            k = generate_token()
            memory_state.update(chat_id, user_id, step="awaiting_shoot_selection", k=k)
            await _clear_previous_screen_keyboard(query, memory_state)
            msg = await query.message.edit_text(
                "Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "comment", model_id, k),
                parse_mode="HTML",
            )
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)

    elif target == "account":
        await query.message.edit_text("Комментарии к учету пока не поддержаны.")
        memory_state.clear(chat_id, user_id)


async def _handle_comment_order(query, parts, config, notion, memory_state):
    """Handle comment order selection. Callback: nlp:cmo:{order_id}[:{k}]"""
    if len(parts) < 3:
        return

    order_id = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        memory_state.clear(chat_id, user_id)
        return

    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    comment_text = state.get("comment_text")
    if not comment_text:
        await query.message.edit_text("Текст комментария не найден.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        from app.services.notion import _extract_rich_text
        url = f"https://api.notion.com/v1/pages/{order_id}"
        page = await notion._request("GET", url)
        existing = _extract_rich_text(page, "comments") or ""

        new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
        await notion.update_order_comment(order_id, new_comment)
        model_id_for_kb = state.get("model_id", "") if state else ""
        memory_state.clear(chat_id, user_id)
        from app.keyboards.inline import nlp_action_complete_keyboard
        await query.message.edit_text(
            "✅ Комментарий добавлен",
            reply_markup=nlp_action_complete_keyboard(model_id_for_kb),
        )
    except Exception as e:
        LOGGER.exception("Failed to add comment: %s", e)
        await query.message.edit_text("❌ Ошибка.")
        memory_state.clear(chat_id, user_id)


# ============================================================================
#                      DISAMBIGUATION CALLBACKS
# ============================================================================

async def _handle_disambig_files(query, parts, config, notion, memory_state, recent_models):
    """Handle disambiguation -> files. Callback: nlp:df:{number}[:{k}]"""
    if len(parts) < 3:
        return

    count = int(parts[2])
    chat_id, user_id = _state_ids_from_query(query)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    # model_id from memory
    state = memory_state.get(chat_id, user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await _session_expired(query, memory_state)
        return

    model_data = await notion.get_model(model_id)
    if not model_data:
        await query.message.edit_text("Модель не найдена.")
        return

    model_name = model_data.title

    try:
        now = datetime.now(tz=config.timezone)
        yyyy_mm = now.strftime("%Y-%m")

        record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)

        if not record:
            await notion.create_accounting_record(
                config.db_accounting, model_id, model_name, count, yyyy_mm,
            )
            new_files = count
            record_status = None
        else:
            new_files = record.files + count
            await notion.update_accounting_files(record.page_id, new_files)
            record_status = record.status

        progress_line = format_accounting_progress(new_files, record_status)
        recent_models.add(user_id, model_id, model_name)
        memory_state.clear(chat_id, user_id)

        from app.keyboards.inline import nlp_action_complete_keyboard
        await query.message.edit_text(
            f"✅ +{count} файлов ({new_files} всего)\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Файлов: {progress_line}",
            reply_markup=nlp_action_complete_keyboard(model_id),
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
    chat_id, user_id = _state_ids_from_query(query)

    state = memory_state.get(chat_id, user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await _session_expired(query, memory_state)
        return

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else ""

    from app.keyboards.inline import nlp_order_type_keyboard
    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_order",
        "step": "awaiting_type",
        "model_id": model_id,
        "model_name": model_name,
        "count": count,
        "k": k,
    })

    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📦 {count}x — Тип заказа:",
        reply_markup=nlp_order_type_keyboard(model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


# ============================================================================
#                        REPORT CALLBACKS
# ============================================================================

async def _handle_report_orders(query, config, notion, memory_state):
    """Handle report orders detail. Callback: nlp:ro[:{k}]"""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await _session_expired(query, memory_state)
        return

    orders = await orders_cache.get_cached_orders(notion, config, model_id)
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
    memory_state.update(chat_id, user_id, k=k)
    from app.keyboards.inline import nlp_report_keyboard
    if query.message:
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📦 <b>Открытые заказы: {html.escape(model_name)}</b>\n\n{orders_text}",
            reply_markup=nlp_report_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_report_accounting(query, config, notion, memory_state):
    """Handle report accounting detail. Callback: nlp:ra[:{k}]"""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    model_id = state.get("model_id") if state else None
    if not model_id:
        await _session_expired(query, memory_state)
        return

    now = datetime.now(tz=config.timezone)
    yyyy_mm = now.strftime("%Y-%m")
    record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)

    model_data = await notion.get_model(model_id)
    model_name = model_data.title if model_data else "модели"

    if not record:
        accounting_text = f"Файлов: {format_accounting_progress(0, None)}"
    else:
        total = record.files
        accounting_text = f"Файлов: {format_accounting_progress(total, record.status)}"

    k = generate_token()
    memory_state.update(chat_id, user_id, k=k)
    from app.keyboards.inline import nlp_report_keyboard
    if query.message:
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"📁 <b>Учет файлов: {html.escape(model_name)}</b>\n\n{accounting_text}",
            reply_markup=nlp_report_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


# ============================================================================
#                          ADD FILES CALLBACK
# ============================================================================

async def _handle_add_files(query, parts, config, notion, memory_state, recent_models):
    """Handle add files from CRM card. Callback: nlp:af:{count|custom}[:{k}]"""
    if len(parts) < 3:
        return

    value = parts[2]
    chat_id, user_id = _state_ids_from_query(query)

    # Custom input: switch to awaiting_count step for free-text entry
    if value == "custom":
        k = generate_token()
        state = memory_state.get(chat_id, user_id)
        model_id = state.get("model_id", "") if state else ""
        model_name = state.get("model_name", "") if state else ""
        memory_state.set(chat_id, user_id, {
            "flow": "nlp_files",
            "step": "awaiting_count",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        from app.keyboards.inline import nlp_back_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            "Введите количество файлов:",
            parse_mode="HTML",
            reply_markup=nlp_back_keyboard(model_id),
        )
        memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        return

    count = int(value)

    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет прав.")
        return

    state = memory_state.get(chat_id, user_id)
    model_id = state.get("model_id") if state else None
    model_name = state.get("model_name", "") if state else ""
    if not model_id:
        await _session_expired(query, memory_state)
        return

    try:
        now = datetime.now(tz=config.timezone)
        yyyy_mm = now.strftime("%Y-%m")

        record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)

        if not record:
            await notion.create_accounting_record(
                config.db_accounting, model_id, model_name, count, yyyy_mm,
            )
            new_files = count
            record_status = None
        else:
            new_files = record.files + count
            await notion.update_accounting_files(record.page_id, new_files)
            record_status = record.status

        progress_line = format_accounting_progress(new_files, record_status)
        recent_models.add(user_id, model_id, model_name)

        await _clear_previous_screen_keyboard(query, memory_state)
        await _cleanup_prompt_message(query, memory_state)
        from app.keyboards.inline import nlp_action_complete_keyboard
        msg = await query.message.edit_text(
            f"✅ +{count} файлов ({new_files} всего)\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Файлов: {progress_line}",
            reply_markup=nlp_action_complete_keyboard(model_id),
            parse_mode="HTML",
        )
        memory_state.clear(chat_id, user_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await query.message.edit_text("❌ Не смог обновить Notion, попробуй позже.")
        memory_state.clear(chat_id, user_id)


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
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        return
    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    selected = list(state.get("content_types", []))
    if ct in selected:
        selected.remove(ct)
    else:
        selected.append(ct)

    k = generate_token()
    memory_state.update(chat_id, user_id, content_types=selected, k=k)
    model_name = state.get("model_name", "")

    from app.keyboards.inline import nlp_shoot_content_keyboard
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Выберите контент:",
        reply_markup=nlp_shoot_content_keyboard(selected, state.get("model_id", ""), k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_shoot_content_done(query, parts, config, notion, memory_state, recent_models):
    """Content selection done → proceed to date. Callback: nlp:scd:done[:{k}]"""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    content_types = state.get("content_types", [])
    model_name = state.get("model_name", "")
    model_id = state.get("model_id", "")
    step = state.get("step", "")

    if step == "awaiting_content" and state.get("shoot_date"):
        shoot_date = state.get("shoot_date")
        if isinstance(shoot_date, str):
            shoot_date = datetime.fromisoformat(shoot_date).date()

        auto_status = _compute_shoot_status(shoot_date.isoformat(), content_types)
        title = f"{model_name} · {shoot_date.strftime('%d.%m')}"
        try:
            shoot_id = await notion.create_shoot(
                database_id=config.db_planner,
                model_page_id=model_id,
                shoot_date=shoot_date,
                content=content_types,
                location="home",
                title=title,
                status=auto_status,
            )
            recent_models.add(user_id, model_id, model_name)
            ct_str = ", ".join(content_types) if content_types else "—"

            from app.keyboards.inline import nlp_action_complete_keyboard
            await _clear_previous_screen_keyboard(query, memory_state)
            await _cleanup_prompt_message(query, memory_state)
            msg = await query.message.edit_text(
                f"✅ Съемка создана на {shoot_date.strftime('%d.%m')}\n"
                f"Контент: {ct_str}\nСтатус: {auto_status}",
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
            memory_state.clear(chat_id, user_id)
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        except Exception as e:
            LOGGER.exception("Failed to create shoot: %s", e)
            await query.message.edit_text("❌ Ошибка при создании съемки.")
            memory_state.clear(chat_id, user_id)
        return

    if step == "awaiting_content_update":
        shoot_id = state.get("shoot_id")
        if not shoot_id:
            await _session_expired(query, memory_state)
            return
        try:
            await notion.update_shoot_content(shoot_id, content_types)
            from app.keyboards.inline import nlp_action_complete_keyboard
            ct_str = ", ".join(content_types) if content_types else "—"
            await _clear_previous_screen_keyboard(query, memory_state)
            msg = await query.message.edit_text(
                f"✅ Content обновлен\n\nКонтент: {ct_str}",
                reply_markup=nlp_action_complete_keyboard(state.get("model_id", "")),
                parse_mode="HTML",
            )
            memory_state.clear(chat_id, user_id)
            _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
        except Exception as e:
            LOGGER.exception("Failed to update shoot content: %s", e)
            await query.message.edit_text("❌ Ошибка при сохранении Content.")
        return

    from app.keyboards.inline import nlp_shoot_date_keyboard
    k = generate_token()
    memory_state.update(chat_id, user_id, step="awaiting_date", k=k)
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Дата съемки:",
        reply_markup=nlp_shoot_date_keyboard(state.get("model_id", ""), k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_shoot_content_manage(query, parts, config, notion, memory_state):
    """Open content multi-select for an existing shoot."""
    if len(parts) < 3:
        return
    shoot_id = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        return

    shoot = await notion.get_shoot(shoot_id)
    if not shoot:
        await _session_expired(query, memory_state)
        return

    selected = shoot.content or []
    model_name = shoot.model_title or ""
    model_id = shoot.model_id or ""

    from app.keyboards.inline import nlp_shoot_content_keyboard
    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_shoot",
        "step": "awaiting_content_update",
        "shoot_id": shoot_id,
        "model_id": model_id,
        "model_name": model_name,
        "content_types": selected,
        "k": k,
    })
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Выберите контент:",
        reply_markup=nlp_shoot_content_keyboard(selected, model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_shoot_reschedule_cb(query, parts, config, notion, memory_state):
    """Reschedule shoot from manage keyboard. Callback: nlp:srs:{shoot_id}[:{k}]"""
    if len(parts) < 3:
        return
    shoot_id = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        return
    state = memory_state.get(chat_id, user_id)
    model_name = state.get("model_name", "") if state else ""
    model_id = state.get("model_id", "") if state else ""

    from app.keyboards.inline import nlp_shoot_date_keyboard
    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_shoot",
        "step": "awaiting_new_date",
        "shoot_id": shoot_id,
        "model_id": model_id,
        "model_name": model_name,
        "k": k,
    })
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📅 <b>{html.escape(model_name)}</b> · Новая дата:",
        reply_markup=nlp_shoot_date_keyboard(model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_shoot_comment_cb(query, parts, config, notion, memory_state):
    """Comment on shoot from manage keyboard. Callback: nlp:scm:{shoot_id}[:{k}]"""
    if len(parts) < 3:
        return
    shoot_id = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        return
    state = memory_state.get(chat_id, user_id)
    model_name = state.get("model_name", "") if state else ""
    model_id = state.get("model_id", "") if state else ""

    LOGGER.info(
        "SHOOT_COMMENT_CB user=%s shoot_id=%s model_id=%s",
        user_id, shoot_id, model_id,
    )

    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_shoot",
        "step": "awaiting_shoot_comment",
        "shoot_id": shoot_id,
        "model_id": model_id,
        "model_name": model_name,
        "k": k,
    })
    from app.keyboards.inline import nlp_back_keyboard
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"💬 <b>{html.escape(model_name)}</b> · Введите комментарий:",
        parse_mode="HTML",
        reply_markup=nlp_back_keyboard(model_id),
    )
    memory_state.update(chat_id, user_id, prompt_message_id=query.message.message_id)
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


# ============================================================================
#                    ACCOUNTING CONTENT CALLBACKS
# ============================================================================

async def _handle_accounting_content_toggle(query, parts, config, memory_state):
    """Toggle an accounting content type. Callback: nlp:acct:{type}[:{k}]"""
    if len(parts) < 3:
        return
    ct = parts[2]
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        return
    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    selected = list(state.get("selected_content", []))
    if ct in selected:
        selected.remove(ct)
    else:
        selected.append(ct)

    k = generate_token()
    memory_state.update(chat_id, user_id, selected_content=selected, k=k)
    model_name = state.get("model_name", "")

    from app.keyboards.inline import nlp_accounting_content_keyboard
    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"🗂 <b>{html.escape(model_name)}</b> · Content\n\n"
        "Выберите типы контента:",
        reply_markup=nlp_accounting_content_keyboard(selected, state.get("model_id", ""), k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


async def _handle_accounting_content_save(query, parts, config, notion, memory_state):
    """Save accounting content. Callback: nlp:accs:save[:{k}]"""
    chat_id, user_id = _state_ids_from_query(query)
    if not is_editor(user_id, config):
        await query.message.edit_text("❌ Нет доступа.")
        return
    state = memory_state.get(chat_id, user_id)
    if not state:
        await _session_expired(query, memory_state)
        return

    accounting_id = state.get("accounting_id")
    selected = state.get("selected_content", [])
    model_name = state.get("model_name", "")
    model_id_for_kb = state.get("model_id", "")

    if not accounting_id:
        await query.message.edit_text("Запись accounting не найдена.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        await notion.update_accounting_content(accounting_id, selected)
        LOGGER.info(
            "Accounting content saved: user=%s accounting_id=%s content=%s",
            user_id, accounting_id, selected,
        )
        content_str = ", ".join(selected) if selected else "—"
        from app.keyboards.inline import nlp_action_complete_keyboard
        await _clear_previous_screen_keyboard(query, memory_state)
        msg = await query.message.edit_text(
            f"✅ Content сохранён\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Content: {html.escape(content_str)}",
            reply_markup=nlp_action_complete_keyboard(model_id_for_kb),
            parse_mode="HTML",
        )
        memory_state.clear(chat_id, user_id)
        _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)
    except Exception as e:
        LOGGER.exception("Failed to save accounting content: %s", e)
        await query.message.edit_text("❌ Ошибка при сохранении Content.")
        memory_state.clear(chat_id, user_id)


# ============================================================================
#                              HELPERS
# ============================================================================

async def _show_report(query, model_id, model_name, config, notion, memory_state, k=""):
    """Show inline report for model."""
    from app.keyboards.inline import nlp_report_keyboard
    from app.utils import escape_html
    chat_id, user_id = _state_ids_from_query(query)

    now = datetime.now(tz=config.timezone)
    yyyy_mm = now.strftime("%Y-%m")

    try:
        record = await accounting_cache.get_cached_monthly_record(notion, config, model_id, yyyy_mm)
    except Exception:
        record = None

    try:
        open_orders = await orders_cache.get_cached_orders(notion, config, model_id)
    except Exception:
        open_orders = []

    if record:
        total = record.files
        files_str = format_accounting_progress(total, record.status)
    else:
        files_str = format_accounting_progress(0, None)

    orders_str = f"{len(open_orders)} открытых"

    await _clear_previous_screen_keyboard(query, memory_state)
    msg = await query.message.edit_text(
        f"📊 <b>{escape_html(model_name)}</b> · {yyyy_mm}\n\n"
        f"📁 Файлов: {files_str}\n"
        f"📦 Заказов: {orders_str}\n",
        reply_markup=nlp_report_keyboard(model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, msg.message_id if msg else query.message.message_id)


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


# ============================================================================
#                    POST-ACTION COMPLETION HANDLERS
# ============================================================================

async def _handle_more_actions(query, parts, config, notion, memory_state):
    """«Еще действие» — send a NEW message with the model card keyboard.

    Callback: nlp:more_actions:{model_id}
    The ✅ success message stays in chat; a fresh model card appears below it.
    """
    model_id = parts[2] if len(parts) >= 3 else None
    if not model_id:
        await query.answer()
        return

    chat_id, user_id = _state_ids_from_query(query)

    try:
        model_data = await notion.get_model(model_id)
        model_name = model_data.title if model_data else ""
    except Exception:
        model_name = ""

    from app.keyboards.inline import model_card_keyboard
    from app.services.model_card import build_model_card

    k = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_actions",
        "model_id": model_id,
        "model_name": model_name,
        "k": k,
    })

    try:
        card_text, _ = await build_model_card(model_id, model_name, config, notion)
    except Exception:
        card_text = f"📊 <b>{html.escape(model_name)}</b>"

    # Remove buttons from the ✅ success message before sending new card
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Send as a NEW message — the ✅ message stays untouched in the chat
    sent = await query.message.answer(
        card_text,
        reply_markup=model_card_keyboard(k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, sent.message_id if sent else None)
    await query.answer()


async def _handle_done(query, parts, memory_state):
    """«Готово» — remove keyboard from the ✅ message and clear state.

    Callback: nlp:done:{model_id}
    The ✅ text stays; only the inline keyboard is removed.
    """
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.clear(chat_id, user_id)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.answer()
