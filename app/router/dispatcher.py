"""
Main routing dispatcher for NLP messages.

Routing pipeline:
1. State Check → есть ли активный flow?
2. Pre-filter → gibberish, длина < 2, bot commands
3. Intent Classification (priority-based)
4. Model Resolution (aliases + fuzzy)
5. Entity Extraction (numbers, dates, types)
6. Validation & Parameter Collection
7. Execute Handler
"""

import asyncio
import html
import logging
import time
from datetime import date, datetime, timedelta

from aiogram.types import Message

from app.config import Config
from app.services import NotionClient
from app.state import MemoryState, RecentModels, generate_token

from app.router.prefilter import prefilter_message
from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import (
    extract_entities_v2,
    validate_model_name,
    get_order_type_display_name,
)
from app.router.command_filters import CommandIntent
from app.router.model_resolver import resolve_model
from app.utils.formatting import format_appended_comment, MAX_COMMENT_LENGTH
from app.utils.accounting import calculate_accounting_progress, format_accounting_progress
from app.utils import PAGE_SIZE


LOGGER = logging.getLogger(__name__)


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


async def _clear_previous_screen_keyboard(message: Message, memory_state: MemoryState) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    prev_id = state.get("screen_message_id")
    if not prev_id:
        return
    await _safe_edit_reply_markup(message.bot, message.chat.id, prev_id)


def _remember_screen_message(
    memory_state: MemoryState,
    chat_id: int,
    user_id: int,
    message_id: int | None,
) -> None:
    if message_id is None:
        return
    memory_state.update(chat_id, user_id, screen_message_id=message_id)


async def _cleanup_prompt_message(message: Message, memory_state: MemoryState) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    prompt_id = state.get("prompt_message_id")
    if not prompt_id:
        return
    await _safe_delete_or_mark_done(message.bot, message.chat.id, prompt_id)
    memory_state.update(chat_id, user_id, prompt_message_id=None)


async def route_message(
    message: Message,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """
    Route user message through the full NLP pipeline.

    Steps:
    1. State Check — if user has active flow, skip NLP
    2. Pre-filter — gibberish, length, bot commands
    3. Entity Extraction — model name, numbers, order type, date, comments
    4. Intent Classification — priority-based
    5. Model Resolution — fuzzy matching + disambiguation
    6. Validation — check required params
    7. Execute Handler — route to appropriate handler
    """
    text = message.text.strip()
    user_id = message.from_user.id
    chat_id = message.chat.id
    LOGGER.info("ROUTE_MESSAGE HIT user=%s text=%r", user_id, text[:80])

    # ===== Step 1: State Check =====
    # Only skip NLP for flows that have FlowFilter-equipped handlers.
    # nlp_* flows are handled via callbacks (buttons), not text —
    # if user sends text while in nlp_* flow, we must respond, not stay silent.
    _FLOW_FILTER_FLOWS = {
        "search", "new_order", "view", "comment",
        "summary", "planner", "accounting",
    }

    user_state = memory_state.get(chat_id, user_id)
    if user_state and user_state.get("flow"):
        current_flow = user_state["flow"]

        if current_flow in _FLOW_FILTER_FLOWS:
            LOGGER.info("ROUTE_MESSAGE SKIP: user=%s active flow=%s, deferring to FlowFilter", user_id, current_flow)
            return  # Let FlowFilter-based handlers pick this up

        if current_flow.startswith("nlp_"):
            current_step = user_state.get("step", "")

            # Dispatch to step-specific text handler if one exists.
            # _find_nlp_text_handler is defined at the bottom of this module.
            handler = _find_nlp_text_handler(current_flow, current_step)
            if handler:
                await handler(message, text, user_state, config, notion, memory_state)
                return

            # nlp_* flows expect button presses, not free text.
            # Respond with a prompt instead of silently swallowing the message.
            LOGGER.info("ROUTE_MESSAGE SKIP: user=%s in nlp flow=%s, prompting for button", user_id, current_flow)
            from app.keyboards.inline import nlp_flow_waiting_keyboard
            await message.answer(
                "⏳ Жду нажатия кнопки или сбросьте состояние.",
                reply_markup=nlp_flow_waiting_keyboard(),
                parse_mode="HTML",
            )
            return

        # Unknown flow — clear stale state and continue through NLP pipeline
        LOGGER.warning("User %s has unknown flow=%s, clearing state", user_id, current_flow)
        memory_state.clear(chat_id, user_id)

    # ===== Step 2: Pre-filter =====
    passed, error_msg = prefilter_message(text)
    if not passed:
        LOGGER.info("ROUTE_MESSAGE PREFILTER_REJECT user=%s error=%r text=%r", user_id, error_msg, text[:60])
        if error_msg:
            await message.answer(error_msg)
        return

    # ===== Step 3: Entity Extraction =====
    _t = time.time()
    entities = extract_entities_v2(text)
    LOGGER.info(
        "Stage entities_extraction: %.3fs | model=%s, numbers=%s, type=%s, date=%s",
        time.time() - _t,
        entities.model_name, entities.numbers, entities.order_type, entities.date,
    )

    # ===== Step 4: Intent Classification =====
    _t = time.time()
    intent = classify_intent_v2(
        text,
        has_model=entities.has_model,
        has_numbers=entities.has_numbers,
    )
    LOGGER.info(
        "Stage intent_classification: %.3fs | intent=%s for text=%r",
        time.time() - _t, intent.value, text[:60],
    )

    # ===== Step 5: Model Resolution =====
    model = None
    model_required = _intent_requires_model(intent)

    _t_model = time.time()
    if entities.model_name and validate_model_name(entities.model_name):
        try:
            resolution = await resolve_model(
                query=entities.model_name,
                user_id=user_id,
                db_models=config.db_models,
                notion=notion,
                recent_models=recent_models,
            )
        except asyncio.TimeoutError:
            LOGGER.warning(
                "route_message TIMEOUT in model_resolution user=%s text=%r",
                user_id, text[:80],
            )
            await message.answer("⏱ Сервер перегружен, попробуйте через минуту")
            return

        if resolution["status"] == "found":
            model = resolution["model"]
            recent_models.add(user_id, model["id"], model["name"])

        elif resolution["status"] == "confirm":
            # Fuzzy-only match — ask user to confirm before executing
            from app.keyboards.inline import nlp_confirm_model_keyboard

            m = resolution["model"]
            k = generate_token()
            # Store intent in memory (keyboard only carries model_id)
            memory_state.set(chat_id, user_id, {
                "flow": "nlp_disambiguate",
                "intent": intent.value,
                "entities_raw": text,
                "k": k,
            })
            await message.answer(
                f"🔍 Вы имели в виду <b>{html.escape(m['name'])}</b>?",
                reply_markup=nlp_confirm_model_keyboard(m["id"], m["name"], k),
                parse_mode="HTML",
            )
            return

        elif resolution["status"] == "multiple":
            # Show disambiguation keyboard
            from app.keyboards.inline import nlp_model_selection_keyboard

            k = generate_token()
            # Store intent in memory (keyboard only carries model_id)
            memory_state.set(chat_id, user_id, {
                "flow": "nlp_disambiguate",
                "intent": intent.value,
                "entities_raw": text,
                "k": k,
            })
            await message.answer(
                f"🔍 Уточните модель '{html.escape(entities.model_name)}':",
                reply_markup=nlp_model_selection_keyboard(resolution["models"], k),
                parse_mode="HTML",
            )
            return

        elif resolution["status"] == "not_found":
            if model_required:
                recent = recent_models.get(user_id)
                if recent:
                    from app.keyboards.inline import nlp_not_found_keyboard
                    k = generate_token()
                    # Store intent in memory for when user picks a recent model
                    memory_state.set(chat_id, user_id, {
                        "flow": "nlp_disambiguate",
                        "intent": intent.value,
                        "entities_raw": text,
                        "k": k,
                    })
                    await message.answer(
                        f"❌ Модель '{html.escape(entities.model_name)}' не найдена.\n\n"
                        "Последние модели:",
                        reply_markup=nlp_not_found_keyboard(recent, k),
                        parse_mode="HTML",
                    )
                else:
                    await message.answer(
                        f"❌ Модель '{html.escape(entities.model_name)}' не найдена.",
                        parse_mode="HTML",
                    )
                return

    elif model_required and not entities.model_name:
        # Intent requires model but none detected
        await message.answer("❌ Укажите имя модели.")
        return

    LOGGER.info("Stage model_resolution: %.3fs user=%s", time.time() - _t_model, user_id)

    # ===== Step 6 & 7: Validation & Execute Handler =====
    _t_handler = time.time()
    try:
        await _execute_handler(message, intent, model, entities, config, notion, memory_state, recent_models)
    except asyncio.TimeoutError:
        LOGGER.warning(
            "route_message TIMEOUT in handler_execution user=%s text=%r",
            user_id, text[:80],
        )
        try:
            await message.answer("⏱ Сервер перегружен, попробуйте через минуту")
        except Exception:
            LOGGER.exception("Failed to send timeout fallback to user=%s", user_id)
        return
    LOGGER.info("Stage handler_execution: %.3fs user=%s", time.time() - _t_handler, user_id)


def _intent_requires_model(intent: CommandIntent) -> bool:
    """Check if intent requires a model to be resolved."""
    no_model_intents = {
        CommandIntent.UNKNOWN,
        CommandIntent.SHOW_SUMMARY,
        CommandIntent.SHOW_ORDERS,
        CommandIntent.SHOW_PLANNER,
        CommandIntent.SHOW_ACCOUNT,
    }
    return intent not in no_model_intents


async def _execute_handler(
    message: Message,
    intent: CommandIntent,
    model: dict | None,
    entities,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Execute the appropriate handler based on intent."""

    # ===== MENU COMMANDS (no model) =====

    if intent == CommandIntent.SHOW_SUMMARY:
        from app.handlers.summary import show_summary_menu
        await show_summary_menu(message, config, recent_models)
        return

    if intent == CommandIntent.SHOW_ORDERS:
        from app.handlers.orders import show_orders_menu
        await show_orders_menu(message, config)
        return

    if intent == CommandIntent.SHOW_PLANNER:
        from app.handlers.planner import show_planner_menu
        await show_planner_menu(message, config)
        return

    if intent == CommandIntent.SHOW_ACCOUNT:
        from app.handlers.accounting import show_accounting_menu
        await show_accounting_menu(message, config)
        return

    # ===== SHOOT DOMAIN (priority 100) =====

    if intent == CommandIntent.SHOOT_CREATE:
        await _handle_shoot_create(message, model, entities, config, notion, memory_state, recent_models)
        return

    if intent == CommandIntent.SHOOT_DONE:
        await _handle_shoot_done(message, model, entities, config, notion, memory_state)
        return

    if intent == CommandIntent.SHOOT_RESCHEDULE:
        await _handle_shoot_reschedule(message, model, entities, config, notion, memory_state)
        return

    # ===== FILES DOMAIN (priority 90) =====

    if intent == CommandIntent.ADD_FILES:
        from app.handlers.accounting import handle_add_files_nlp
        await handle_add_files_nlp(message, model, entities, config, notion, recent_models)
        return

    # ===== ORDERS WITH TYPE (priority 80) =====

    if intent == CommandIntent.CREATE_ORDERS:
        from app.handlers.orders import handle_create_orders_nlp
        await handle_create_orders_nlp(message, model, entities, config, notion, memory_state)
        return

    # ===== ORDERS GENERAL (priority 70) =====

    if intent == CommandIntent.CREATE_ORDERS_GENERAL:
        await _handle_create_orders_general(message, model, entities, config, memory_state)
        return

    # ===== ORDERS CLOSE (priority 60) =====

    if intent == CommandIntent.CLOSE_ORDERS:
        await _handle_close_orders(message, model, entities, config, notion, memory_state)
        return

    # ===== COMMENT (priority 55) =====

    if intent == CommandIntent.ADD_COMMENT:
        await _handle_add_comment(message, model, entities, config, notion, memory_state)
        return

    # ===== MODEL ACTIONS (priority 50) =====

    if intent == CommandIntent.GET_REPORT:
        from app.handlers.reports import handle_report_nlp
        await handle_report_nlp(message, model, config, notion, memory_state)
        return

    if intent == CommandIntent.SHOW_MODEL_ORDERS:
        await _handle_show_model_orders(message, model, config, notion)
        return

    # ===== FILES STATS (priority 35) =====

    if intent == CommandIntent.FILES_STATS:
        await _handle_files_stats(message, model, config, notion)
        return

    # ===== AMBIGUOUS (priority 30) =====

    if intent == CommandIntent.AMBIGUOUS:
        await _handle_ambiguous(message, model, entities, config, memory_state)
        return

    # ===== SEARCH MODEL (priority 0) =====

    if intent == CommandIntent.SEARCH_MODEL:
        if model:
            # CRM UX: show universal model card with live data
            from app.keyboards.inline import model_card_keyboard
            from app.services.model_card import build_model_card
            k = generate_token()
            memory_state.set(message.chat.id, message.from_user.id, {
                "flow": "nlp_actions",
                "model_id": model["id"],
                "model_name": model["name"],
                "k": k,
            })
            card_text, _ = await build_model_card(
                model["id"], model["name"], config, notion,
            )
            sent = await message.answer(
                card_text,
                reply_markup=model_card_keyboard(k),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                message.chat.id,
                message.from_user.id,
                sent.message_id if sent else None,
            )
        else:
            await _show_help_message(message)
        return

    # ===== UNKNOWN =====
    await _show_help_message(message)


# ============================================================================
#                         SHOOT HANDLERS
# ============================================================================

async def _handle_shoot_create(message, model, entities, config, notion, memory_state, recent_models):
    """Handle shoot creation via NLP."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав для создания съемок.")
        return

    model_id = model["id"]
    model_name = model["name"]
    chat_id = message.chat.id

    if entities.date:
        # Date provided — create or update shoot
        try:
            # Check for existing shoot on this date
            existing = await notion.query_upcoming_shoots(
                config.db_planner,
                model_page_id=model_id,
            )
            existing_on_date = [
                s for s in existing
                if s.date and s.date == entities.date.isoformat()
            ]

            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            if existing_on_date:
                # Update existing shoot
                shoot = existing_on_date[0]
                await notion.update_shoot_status(shoot.page_id, "scheduled")
                await message.answer(
                    f"✅ Съемка обновлена на {entities.date.strftime('%d.%m')}",
                    reply_markup=_nlp_action_complete_keyboard(model_id),
                    parse_mode="HTML",
                )
            else:
                # Create new shoot
                title = f"{model_name} · {entities.date.strftime('%d.%m')}"
                await notion.create_shoot(
                    database_id=config.db_planner,
                    model_page_id=model_id,
                    shoot_date=entities.date,
                    content=[],
                    location="home",
                    title=title,
                )
                await message.answer(
                    f"✅ Съемка создана на {entities.date.strftime('%d.%m')}",
                    reply_markup=_nlp_action_complete_keyboard(model_id),
                    parse_mode="HTML",
                )

            recent_models.add(message.from_user.id, model_id, model_name)

        except Exception as e:
            LOGGER.exception("Failed to create shoot: %s", e)
            await message.answer("❌ Ошибка при создании съемки.")
    else:
        # No date — ask for date
        from app.keyboards.inline import nlp_shoot_date_keyboard
        k = generate_token()
        memory_state.set(chat_id, message.from_user.id, {
            "flow": "nlp_shoot",
            "step": "awaiting_date",
            "model_id": model_id,
            "model_name": model_name,
            "k": k,
        })
        await _clear_previous_screen_keyboard(message, memory_state)
        sent = await message.answer(
            f"📅 <b>{html.escape(model_name)}</b> · Дата съемки:",
            reply_markup=nlp_shoot_date_keyboard(model_id, k),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            message.from_user.id,
            sent.message_id if sent else None,
        )


async def _handle_shoot_done(message, model, entities, config, notion, memory_state):
    """Handle marking a shoot as done."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав.")
        return

    model_id = model["id"]
    model_name = model["name"]
    chat_id = message.chat.id

    try:
        shoots = await notion.query_upcoming_shoots(
            config.db_planner,
            model_page_id=model_id,
        )

        if not shoots:
            await message.answer(f"✅ Нет запланированных съемок для {html.escape(model_name)}", parse_mode="HTML")
            return

        # If date specified — find that specific shoot
        if entities.date:
            target = [s for s in shoots if s.date == entities.date.isoformat()]
            if target:
                await notion.update_shoot_status(target[0].page_id, "done")
                from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
                await message.answer(
                    f"✅ Съемка на {entities.date.strftime('%d.%m')} выполнена",
                    reply_markup=_nlp_action_complete_keyboard(model_id),
                    parse_mode="HTML",
                )
                return
            await message.answer(
                f"❌ Съемка на {entities.date.strftime('%d.%m')} не найдена",
                parse_mode="HTML",
            )
            return

        # No date — disambiguate
        if len(shoots) == 1:
            from app.keyboards.inline import nlp_shoot_confirm_done_keyboard
            shoot = shoots[0]
            date_str = shoot.date[:10] if shoot.date else "?"
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                f"Отметить '{date_str}' как выполненную?",
                reply_markup=nlp_shoot_confirm_done_keyboard(shoot.page_id),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                f"📅 <b>{html.escape(model_name)}</b> · Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "done", model_id),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )

    except Exception as e:
        LOGGER.exception("Failed to handle shoot done: %s", e)
        await message.answer("❌ Ошибка.")


async def _handle_shoot_reschedule(message, model, entities, config, notion, memory_state):
    """Handle shoot reschedule."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав.")
        return

    model_id = model["id"]
    model_name = model["name"]
    chat_id = message.chat.id

    try:
        shoots = await notion.query_upcoming_shoots(
            config.db_planner,
            model_page_id=model_id,
        )

        if not shoots:
            await message.answer(f"✅ Нет запланированных съемок для {html.escape(model_name)}", parse_mode="HTML")
            return

        # If only one shoot — start reschedule flow
        if len(shoots) == 1:
            shoot = shoots[0]
            from app.keyboards.inline import nlp_shoot_date_keyboard
            k = generate_token()
            memory_state.set(chat_id, message.from_user.id, {
                "flow": "nlp_shoot",
                "step": "awaiting_new_date",
                "shoot_id": shoot.page_id,
                "model_id": model_id,
                "model_name": model_name,
                "old_date": shoot.date,
                "k": k,
            })
            date_str = shoot.date[:10] if shoot.date else "?"
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                f"📅 Перенос съемки {date_str}\n\nНовая дата:",
                reply_markup=nlp_shoot_date_keyboard(model_id, k),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                f"📅 <b>{html.escape(model_name)}</b> · Какую съемку перенести?",
                reply_markup=nlp_shoot_select_keyboard(shoots, "reschedule", model_id),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )

    except Exception as e:
        LOGGER.exception("Failed to handle shoot reschedule: %s", e)
        await message.answer("❌ Ошибка.")


# ============================================================================
#                      ORDER HANDLERS (General / Close)
# ============================================================================

async def _handle_create_orders_general(message, model, entities, config, memory_state):
    """Handle general order creation (type not specified → ask)."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав.")
        return

    from app.keyboards.inline import nlp_order_type_keyboard
    k = generate_token()
    chat_id = message.chat.id
    memory_state.set(chat_id, message.from_user.id, {
        "flow": "nlp_order",
        "step": "awaiting_type",
        "model_id": model["id"],
        "model_name": model["name"],
        "k": k,
    })
    await _clear_previous_screen_keyboard(message, memory_state)
    sent = await message.answer(
        f"📦 <b>{html.escape(model['name'])}</b> · Тип заказа:",
        reply_markup=nlp_order_type_keyboard(model["id"], k),
        parse_mode="HTML",
    )
    _remember_screen_message(
        memory_state,
        chat_id,
        message.from_user.id,
        sent.message_id if sent else None,
    )


async def _handle_close_orders(message, model, entities, config, notion, memory_state):
    """Handle order closing."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав.")
        return

    model_id = model["id"]
    model_name = model["name"]
    chat_id = message.chat.id

    try:
        # Query open orders, optionally filtered by type
        orders = await notion.query_open_orders(
            config.db_orders,
            model_page_id=model_id,
        )

        # If order type specified, filter
        if entities.order_type:
            orders = [o for o in orders if o.order_type == entities.order_type]

        if not orders:
            type_label = get_order_type_display_name(entities.order_type) if entities.order_type else "заказов"
            from app.keyboards.inline import nlp_back_keyboard
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                f"✅ Нет открытых {type_label} для {html.escape(model_name)}",
                reply_markup=nlp_back_keyboard(model_id),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )
            return

        orders.sort(key=lambda o: o.in_date or "9999-99-99")
        total_pages = max(1, (len(orders) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = 1
        page_orders = orders[:PAGE_SIZE]

        from app.keyboards.inline import nlp_close_order_select_keyboard
        memory_state.set(chat_id, message.from_user.id, {
            "flow": "nlp_close_picker",
            "step": "selecting",
            "model_id": model_id,
            "model_name": model_name,
            "orders": orders,
            "page": page,
        })
        await _clear_previous_screen_keyboard(message, memory_state)
        sent = await message.answer(
            f"📦 <b>{html.escape(model_name)}</b> · Выберите заказ:",
            reply_markup=nlp_close_order_select_keyboard(
                page_orders,
                page,
                total_pages,
                model_id,
            ),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            message.from_user.id,
            sent.message_id if sent else None,
        )

    except Exception as e:
        LOGGER.exception("Failed to handle close orders: %s", e)
        await message.answer("❌ Ошибка при поиске заказов.")


# ============================================================================
#                      COMMENT / FILES STATS / AMBIGUOUS
# ============================================================================

async def _handle_add_comment(message, model, entities, config, notion, memory_state):
    """Handle adding a comment."""
    from app.roles import is_editor

    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет доступа.")
        return

    if not entities.comment_text:
        await message.answer("❌ Укажите текст комментария. Пример: 'мелиса заказ коммент: текст'")
        return

    if entities.comment_target:
        # Target known — handle directly
        if entities.comment_target == "order":
            await _add_comment_to_order(message, model, entities, config, notion, memory_state)
        elif entities.comment_target == "shoot":
            await _add_comment_to_shoot(message, model, entities, config, notion, memory_state)
        else:
            await message.answer("❌ Комментарии к учету пока не поддержаны.")
    else:
        # Target unknown — ask
        from app.keyboards.inline import nlp_comment_target_keyboard
        k = generate_token()
        chat_id = message.chat.id
        memory_state.set(chat_id, message.from_user.id, {
            "flow": "nlp_comment",
            "step": "awaiting_target",
            "model_id": model["id"],
            "model_name": model["name"],
            "comment_text": entities.comment_text,
            "k": k,
        })
        await _clear_previous_screen_keyboard(message, memory_state)
        sent = await message.answer(
            "Что комментировать?",
            reply_markup=nlp_comment_target_keyboard(model["id"], k),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            message.from_user.id,
            sent.message_id if sent else None,
        )


async def _add_comment_to_order(message, model, entities, config, notion, memory_state):
    """Add comment to an order."""
    try:
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model["id"])
        if not orders:
            await message.answer("❌ Нет открытых заказов для этой модели.")
            return

        if len(orders) == 1:
            order = orders[0]
            existing = order.comments or ""
            new_comment = format_appended_comment(existing, entities.comment_text, tz=config.timezone)
            await notion.update_order_comment(order.page_id, new_comment)
            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            await message.answer(
                "✅ Комментарий добавлен",
                reply_markup=_nlp_action_complete_keyboard(model["id"]),
            )
        else:
            from app.keyboards.inline import nlp_comment_order_select_keyboard
            k = generate_token()
            chat_id = message.chat.id
            memory_state.set(chat_id, message.from_user.id, {
                "flow": "nlp_comment",
                "step": "awaiting_order_selection",
                "model_id": model["id"],
                "comment_text": entities.comment_text,
                "k": k,
            })
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                "Выберите заказ:",
                reply_markup=nlp_comment_order_select_keyboard(orders, model["id"], k),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )
    except Exception as e:
        LOGGER.exception("Failed to add comment to order: %s", e)
        await message.answer("❌ Ошибка.")


async def _add_comment_to_shoot(message, model, entities, config, notion, memory_state):
    """Add comment to a shoot."""
    try:
        shoots = await notion.query_upcoming_shoots(config.db_planner, model_page_id=model["id"])
        if not shoots:
            await message.answer("❌ Нет запланированных съемок для этой модели.")
            return

        if len(shoots) == 1:
            shoot = shoots[0]
            existing = shoot.comments or ""
            new_comment = format_appended_comment(existing, entities.comment_text, tz=config.timezone)
            await notion.update_shoot_comment(shoot.page_id, new_comment)
            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            await message.answer(
                "✅ Комментарий добавлен",
                reply_markup=_nlp_action_complete_keyboard(model["id"]),
            )
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            k = generate_token()
            chat_id = message.chat.id
            memory_state.set(chat_id, message.from_user.id, {
                "flow": "nlp_comment",
                "step": "awaiting_shoot_selection",
                "model_id": model["id"],
                "comment_text": entities.comment_text,
                "k": k,
            })
            await _clear_previous_screen_keyboard(message, memory_state)
            sent = await message.answer(
                "Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "comment", model["id"], k),
                parse_mode="HTML",
            )
            _remember_screen_message(
                memory_state,
                chat_id,
                message.from_user.id,
                sent.message_id if sent else None,
            )
    except Exception as e:
        LOGGER.exception("Failed to add comment to shoot: %s", e)
        await message.answer("❌ Ошибка.")


async def _handle_shoot_comment_input(message, text, user_state, config, notion, memory_state):
    """Handle free-text comment input for a shoot (step: awaiting_shoot_comment)."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    shoot_id = user_state.get("shoot_id")
    model_name = user_state.get("model_name", "")

    LOGGER.info(
        "SHOOT_COMMENT_INPUT user=%s shoot_id=%s flow=%s step=%s",
        user_id, shoot_id,
        user_state.get("flow"), user_state.get("step"),
    )

    if not shoot_id:
        LOGGER.warning("SHOOT_COMMENT_INPUT ABORT: missing shoot_id user=%s", user_id)
        memory_state.clear(chat_id, user_id)
        await message.answer("❌ Сессия устарела, попробуйте заново.")
        return

    comment_text = text.strip()
    if not comment_text:
        await message.answer("❌ Комментарий не может быть пустым.")
        return

    if len(comment_text) > MAX_COMMENT_LENGTH:
        await message.answer(
            f"❌ Комментарий слишком длинный (макс. {MAX_COMMENT_LENGTH} символов)."
        )
        return

    try:
        shoot = await notion.get_shoot(shoot_id)
        if not shoot:
            LOGGER.warning("SHOOT_COMMENT_INPUT: shoot not found shoot_id=%s user=%s", shoot_id, user_id)
            memory_state.clear(chat_id, user_id)
            await message.answer("❌ Съемка не найдена. Возможно, она была удалена.")
            return

        existing = shoot.comments or ""
        new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
        await notion.update_shoot_comment(shoot_id, new_comment)
        await _clear_previous_screen_keyboard(message, memory_state)
        await _cleanup_prompt_message(message, memory_state)
        memory_state.clear(chat_id, user_id)
        LOGGER.info("SHOOT_COMMENT_INPUT OK user=%s shoot_id=%s", user_id, shoot_id)
        from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
        sent = await message.answer(
            f"✅ Комментарий добавлен для <b>{html.escape(model_name)}</b>",
            parse_mode="HTML",
            reply_markup=_nlp_action_complete_keyboard(user_state.get("model_id", "")),
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            message.from_user.id,
            sent.message_id if sent else None,
        )
    except Exception as e:
        LOGGER.exception("SHOOT_COMMENT_INPUT FAIL user=%s shoot_id=%s: %s", user_id, shoot_id, e)
        memory_state.clear(chat_id, user_id)
        await message.answer("❌ Ошибка при сохранении комментария.")


async def _handle_files_stats(message, model, config, notion):
    """Handle files stats view (no number, just show stats)."""
    if not model:
        await message.answer("❌ Укажите модель. Пример: 'мелиса файлы'")
        return

    model_name = model["name"]
    model_id = model["id"]

    try:
        yyyy_mm = datetime.now(tz=config.timezone).strftime("%Y-%m")
        record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)

        if record:
            current = record.files
            target, pct, over = calculate_accounting_progress(current, record.status)
            remaining = max(0, target - current)
            over_str = f"\nСверх лимита: +{over}" if over > 0 else ""

            await message.answer(
                f"📊 <b>{html.escape(model_name)}</b> | {yyyy_mm}\n\n"
                f"Файлов: {current}/{target} ({pct}%)\n"
                f"До {target}: {remaining} файлов{over_str}",
                parse_mode="HTML",
            )
        else:
            target, pct, _ = calculate_accounting_progress(0, None)
            await message.answer(
                f"📊 <b>{html.escape(model_name)}</b> | {yyyy_mm}\n\n"
                f"Файлов: 0/{target} ({pct}%)\n"
                f"До {target}: {target} файлов",
                parse_mode="HTML",
            )

    except Exception as e:
        LOGGER.exception("Failed to get files stats: %s", e)
        await message.answer("❌ Не смог обновить Notion, попробуй позже.")


async def _handle_ambiguous(message, model, entities, config, memory_state):
    """Handle ambiguous intent (model + number, no marker)."""
    if not model or not entities.numbers:
        await _show_help_message(message)
        return

    number = entities.first_number
    from app.keyboards.inline import nlp_disambiguate_keyboard

    k = generate_token()
    # Store model_id in memory for disambiguation callbacks
    memory_state.set(message.chat.id, message.from_user.id, {
        "flow": "nlp_disambiguate",
        "model_id": model["id"],
        "model_name": model["name"],
        "k": k,
    })

    await message.answer(
        f"Что сделать с {number}?",
        reply_markup=nlp_disambiguate_keyboard(number, k),
        parse_mode="HTML",
    )


async def _handle_show_model_orders(message, model, config, notion):
    """Show open orders for a specific model."""
    if not model:
        from app.handlers.orders import show_orders_menu
        await show_orders_menu(message, config)
        return

    try:
        orders = await notion.query_open_orders(config.db_orders, model_page_id=model["id"])

        if not orders:
            await message.answer(
                f"📋 <b>{html.escape(model['name'])}</b>\n\nНет открытых заказов.",
                parse_mode="HTML",
            )
            return

        text = f"📋 <b>{html.escape(model['name'])}</b> · Открытые заказы:\n\n"
        for order in orders[:10]:
            days = _calc_days_open(order.in_date)
            text += f"• {order.order_type or '?'} · {_format_date_short(order.in_date)} ({days}d)\n"

        if len(orders) > 10:
            text += f"\n...и ещё {len(orders) - 10}"

        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        LOGGER.exception("Failed to show model orders: %s", e)
        await message.answer("❌ Ошибка при загрузке заказов.")


# ============================================================================
#                              HELPERS
# ============================================================================

def _calc_days_open(in_date_str: str | None) -> int:
    """Calculate number of days since order was opened."""
    if not in_date_str:
        return 0
    try:
        in_date = date.fromisoformat(in_date_str[:10])
        return (date.today() - in_date).days
    except (ValueError, TypeError):
        return 0


def _format_date_short(date_str: str | None) -> str:
    """Format date string to DD.MM."""
    if not date_str:
        return "?"
    try:
        d = date.fromisoformat(date_str[:10])
        return d.strftime("%d.%m")
    except (ValueError, TypeError):
        return "?"


async def _handle_custom_date_input(message, text, user_state, config, notion, memory_state):
    """Handle free-text date input (DD.MM) in nlp_shoot / nlp_close flows."""
    import re
    from app.roles import is_editor

    user_id = message.from_user.id
    chat_id = message.chat.id
    current_flow = user_state.get("flow", "")

    # Parse DD.MM or DD/MM
    m = re.match(r'^(\d{1,2})[./](\d{1,2})$', text.strip())
    if not m:
        await message.answer("❌ Формат: ДД.ММ (например 13.02)")
        return

    day, month = int(m.group(1)), int(m.group(2))
    try:
        today = date.today()
        year = today.year
        parsed_date = date(year, month, day)
        # Only bump to next year if the date is more than 90 days in the past.
        # This prevents e.g. "10.01" from jumping to next year when today is 06.02.
        if parsed_date < today - timedelta(days=90):
            parsed_date = date(year + 1, month, day)
    except ValueError:
        await message.answer("❌ Неверная дата")
        return

    if current_flow == "nlp_shoot":
        step = user_state.get("step", "")
        model_id = user_state.get("model_id", "")
        model_name = user_state.get("model_name", "")

        if step == "awaiting_custom_date" and user_state.get("shoot_id"):
            # Reschedule
            shoot_id = user_state["shoot_id"]
            old_date = user_state.get("old_date", "?")
            if not is_editor(user_id, config):
                await message.answer("❌ Нет прав.")
                memory_state.clear(chat_id, user_id)
                return
            await notion.reschedule_shoot(shoot_id, parsed_date)
            old_label = old_date[:10] if old_date else "?"
            await _clear_previous_screen_keyboard(message, memory_state)
            await _cleanup_prompt_message(message, memory_state)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            await message.answer(
                f"✅ Съемка перенесена с {old_label} на {parsed_date.strftime('%d.%m')}",
                reply_markup=_nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
        else:
            # Create shoot
            if not is_editor(user_id, config):
                await message.answer("❌ Нет прав.")
                memory_state.clear(chat_id, user_id)
                return
            content_types = user_state.get("content_types", [])
            auto_status = "scheduled" if content_types else "planned"
            title = f"{model_name} · {parsed_date.strftime('%d.%m')}"
            try:
                await notion.create_shoot(
                    database_id=config.db_planner,
                    model_page_id=model_id,
                    shoot_date=parsed_date,
                    content=content_types,
                    location="home",
                    title=title,
                    status=auto_status,
                )
                await _clear_previous_screen_keyboard(message, memory_state)
                await _cleanup_prompt_message(message, memory_state)
                memory_state.clear(chat_id, user_id)
                from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
                await message.answer(
                    f"✅ Съемка создана на {parsed_date.strftime('%d.%m')}",
                    reply_markup=_nlp_action_complete_keyboard(model_id),
                    parse_mode="HTML",
                )
            except Exception as e:
                LOGGER.exception("Failed to create shoot: %s", e)
                await message.answer("❌ Ошибка при создании съемки.")
                memory_state.clear(chat_id, user_id)

    elif current_flow == "nlp_close":
        model_id_for_kb = user_state.get("model_id", "")
        order_id = user_state.get("order_id")
        if not order_id:
            await message.answer("Сессия истекла. Повторите запрос.")
            memory_state.clear(chat_id, user_id)
            return
        if not is_editor(user_id, config):
            await message.answer("❌ Нет прав.")
            memory_state.clear(chat_id, user_id)
            return
        try:
            await notion.close_order(order_id, parsed_date)
            await _clear_previous_screen_keyboard(message, memory_state)
            await _cleanup_prompt_message(message, memory_state)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            await message.answer(
                f"✅ Заказ закрыт · {parsed_date.strftime('%d.%m')}",
                reply_markup=_nlp_action_complete_keyboard(model_id_for_kb),
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to close order: %s", e)
            await message.answer("❌ Ошибка при закрытии заказа.")
            memory_state.clear(chat_id, user_id)
    elif current_flow == "nlp_order":
        if not is_editor(user_id, config):
            await message.answer("❌ Нет доступа.")
            memory_state.clear(chat_id, user_id)
            return
        from app.keyboards.inline import nlp_order_confirm_keyboard
        from app.router.entities_v2 import get_order_type_display_name

        model_name = user_state.get("model_name", "")
        order_type = user_state.get("order_type", "")
        count = user_state.get("count", 1)
        type_label = get_order_type_display_name(order_type)

        k = generate_token()
        memory_state.update(
            chat_id,
            user_id,
            step="awaiting_confirm",
            in_date=parsed_date.isoformat(),
            k=k,
        )
        await _clear_previous_screen_keyboard(message, memory_state)
        await _cleanup_prompt_message(message, memory_state)
        sent = await message.answer(
            f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\n"
            f"Дата заказа: <b>{parsed_date.strftime('%d.%m')}</b>\n\nСоздать заказ?",
            reply_markup=nlp_order_confirm_keyboard(user_state.get("model_id", ""), k),
            parse_mode="HTML",
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            message.from_user.id,
            sent.message_id if sent else None,
        )
    else:
        await message.answer("❌ Неожиданное состояние. Попробуйте заново.")
        memory_state.clear(chat_id, user_id)


MAX_FILES_INPUT = 500  # configurable upper limit for manual file count


async def _handle_custom_files_input(message, text, user_state, config, notion, memory_state):
    """Handle free-text number input for nlp_files flow (awaiting_count)."""
    from app.roles import is_editor

    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_editor(user_id, config):
        await message.answer("❌ Нет прав.")
        memory_state.clear(chat_id, user_id)
        return

    count = _parse_files_count(text.strip())
    if count is None:
        await message.answer(f"❌ Введите число (1–{MAX_FILES_INPUT})")
        return

    model_id = user_state.get("model_id", "")
    model_name = user_state.get("model_name", "")
    yyyy_mm = datetime.now(tz=config.timezone).strftime("%Y-%m")

    try:
        record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)

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
        await _clear_previous_screen_keyboard(message, memory_state)
        await _cleanup_prompt_message(message, memory_state)
        memory_state.clear(chat_id, user_id)

        from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
        await message.answer(
            f"✅ +{count} файлов ({new_files} всего)\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Файлов: {progress_line}",
            reply_markup=_nlp_action_complete_keyboard(model_id),
            parse_mode="HTML",
        )
    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await message.answer("❌ Не смог обновить Notion, попробуй позже.")
        memory_state.clear(chat_id, user_id)


async def _handle_accounting_comment_input(message, text, user_state, config, notion, memory_state):
    """Handle accounting comment input for nlp_accounting_comment flow."""
    from app.roles import is_editor

    user_id = message.from_user.id
    chat_id = message.chat.id
    if not is_editor(user_id, config):
        await message.answer("❌ Нет доступа.")
        memory_state.clear(chat_id, user_id)
        return

    comment_text = text.strip()
    if not comment_text:
        await message.answer("❌ Комментарий не может быть пустым.")
        return

    record_id = user_state.get("accounting_id")
    model_name = user_state.get("model_name", "")
    if not record_id:
        await message.answer("❌ Сессия устарела, попробуйте заново.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        await notion.update_accounting_comment(record_id, comment_text)
        await _clear_previous_screen_keyboard(message, memory_state)
        await _cleanup_prompt_message(message, memory_state)
        memory_state.clear(chat_id, user_id)
        from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
        sent = await message.answer(
            f"✅ Комментарий обновлён для <b>{html.escape(model_name)}</b>",
            parse_mode="HTML",
            reply_markup=_nlp_action_complete_keyboard(user_state.get("model_id", "")),
        )
        _remember_screen_message(
            memory_state,
            chat_id,
            message.from_user.id,
            sent.message_id if sent else None,
        )
    except Exception:
        LOGGER.exception("Failed to update accounting comment")
        await message.answer("❌ Ошибка при сохранении комментария.")
        memory_state.clear(chat_id, user_id)


def _parse_files_count(text: str) -> int | None:
    """
    Parse a positive integer file count from free-text input.

    Accepted: "30", "+30", "30 файлов", "30ф", "файлы 30"
    Rejected: "0", "-5", "99999", text without number
    Returns: int 1..MAX_FILES_INPUT or None on invalid input.
    """
    import re
    t = text.strip().lower()

    # Pattern 1: optional '+', digits, optional suffix (ф/файл*)
    m = re.match(r'^[+]?\s*(\d+)\s*(?:ф[а-я]*)?\s*$', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= MAX_FILES_INPUT:
            return n
        return None

    # Pattern 2: "файлы 30", "файлов 30"
    m = re.match(r'^(?:файл[а-я]*)\s+[+]?\s*(\d+)\s*$', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= MAX_FILES_INPUT:
            return n
        return None

    return None


async def _show_help_message(message: Message) -> None:
    """Show help message when intent is unknown."""
    await message.answer(
        "🤔 Не понял запрос. Примеры:\n\n"
        "📦 <b>Заказы:</b>\n"
        "• мелиса кастом\n"
        "• мелиса 3 шорта\n"
        "• мелиса кастом закрыт\n\n"
        "📅 <b>Съемки:</b>\n"
        "• мелиса съемка на 13.02\n"
        "• мелиса съемка выполнена\n\n"
        "📁 <b>Файлы:</b>\n"
        "• мелиса 30 файлов\n"
        "• мелиса + 20\n\n"
        "📊 <b>Отчеты:</b>\n"
        "• репорт мелиса\n"
        "• сводка\n\n"
        "Или /start",
        parse_mode="HTML",
    )


# ============================================================================
#               NLP TEXT STEP HANDLER MAP
# ============================================================================
# Map (flow | None, step) → handler for free-text input in nlp_* flows.
# None as flow means "match any nlp_* flow".
# All handlers share the signature:
#   (message, text, user_state, config, notion, memory_state) → None
#
# To add a new text-input step:
#   1. Define the handler function above.
#   2. Add an entry here.
#   3. Done — no need to touch route_message().

_NLP_TEXT_HANDLERS: dict[tuple[str | None, str], object] = {
    (None, "awaiting_custom_date"): _handle_custom_date_input,
    ("nlp_files", "awaiting_count"): _handle_custom_files_input,
    (None, "awaiting_shoot_comment"): _handle_shoot_comment_input,
    ("nlp_accounting_comment", "awaiting_accounting_comment"): _handle_accounting_comment_input,
}


def _find_nlp_text_handler(flow: str, step: str):
    """Look up handler for free-text input during an nlp_* flow.

    Tries exact (flow, step) first, then wildcard (None, step).
    Returns the handler callable or None.
    """
    return _NLP_TEXT_HANDLERS.get((flow, step)) or _NLP_TEXT_HANDLERS.get((None, step))
