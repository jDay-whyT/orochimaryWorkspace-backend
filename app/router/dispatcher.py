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

import html
import logging
from datetime import date, datetime

from aiogram.types import Message

from app.config import Config
from app.services import NotionClient
from app.state import MemoryState, RecentModels

from app.router.prefilter import prefilter_message
from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import (
    extract_entities_v2,
    validate_model_name,
    get_order_type_display_name,
)
from app.router.command_filters import CommandIntent
from app.router.model_resolver import resolve_model


LOGGER = logging.getLogger(__name__)


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

    # ===== Step 1: State Check =====
    # Only skip NLP for flows that have FlowFilter-equipped handlers.
    # nlp_* flows are handled via callbacks (buttons), not text —
    # if user sends text while in nlp_* flow, we must respond, not stay silent.
    _FLOW_FILTER_FLOWS = {
        "search", "new_order", "view", "comment",
        "summary", "planner", "accounting",
    }

    user_state = memory_state.get(user_id)
    if user_state and user_state.get("flow"):
        current_flow = user_state["flow"]

        if current_flow in _FLOW_FILTER_FLOWS:
            LOGGER.debug("User %s has active flow=%s, skipping NLP", user_id, current_flow)
            return  # Let FlowFilter-based handlers pick this up

        if current_flow.startswith("nlp_"):
            # nlp_* flows expect button presses, not free text.
            # Respond with a prompt instead of silently swallowing the message.
            LOGGER.debug("User %s in nlp flow=%s, prompting for button", user_id, current_flow)
            from app.keyboards.inline import nlp_flow_waiting_keyboard
            await message.answer(
                "⏳ Жду нажатия кнопки или сбросьте состояние.",
                reply_markup=nlp_flow_waiting_keyboard(),
                parse_mode="HTML",
            )
            return

        # Unknown flow — clear stale state and continue through NLP pipeline
        LOGGER.warning("User %s has unknown flow=%s, clearing state", user_id, current_flow)
        memory_state.clear(user_id)

    # ===== Step 2: Pre-filter =====
    passed, error_msg = prefilter_message(text)
    if not passed:
        if error_msg:
            await message.answer(error_msg)
        return

    # ===== Step 3: Entity Extraction =====
    entities = extract_entities_v2(text)
    LOGGER.info(
        "Entities: model=%s, numbers=%s, type=%s, date=%s",
        entities.model_name, entities.numbers, entities.order_type, entities.date,
    )

    # ===== Step 4: Intent Classification =====
    intent = classify_intent_v2(
        text,
        has_model=entities.has_model,
        has_numbers=entities.has_numbers,
    )
    LOGGER.info("Intent: %s for text=%r", intent.value, text[:60])

    # ===== Step 5: Model Resolution =====
    model = None
    model_required = _intent_requires_model(intent)

    if entities.model_name and validate_model_name(entities.model_name):
        resolution = await resolve_model(
            query=entities.model_name,
            user_id=user_id,
            db_models=config.db_models,
            notion=notion,
            recent_models=recent_models,
        )

        if resolution["status"] == "found":
            model = resolution["model"]
            recent_models.add(user_id, model["id"], model["name"])

        elif resolution["status"] == "confirm":
            # Fuzzy-only match — ask user to confirm before executing
            from app.keyboards.inline import nlp_confirm_model_keyboard

            m = resolution["model"]
            await message.answer(
                f"🔍 Вы имели в виду <b>{html.escape(m['name'])}</b>?",
                reply_markup=nlp_confirm_model_keyboard(m["id"], m["name"], intent.value),
                parse_mode="HTML",
            )
            memory_state.set(user_id, {
                "flow": "nlp_disambiguate",
                "intent": intent.value,
                "entities_raw": text,
            })
            return

        elif resolution["status"] == "multiple":
            # Show disambiguation keyboard
            from app.keyboards.inline import nlp_model_selection_keyboard

            await message.answer(
                f"🔍 Уточните модель '{html.escape(entities.model_name)}':",
                reply_markup=nlp_model_selection_keyboard(
                    resolution["models"], intent.value, entities,
                ),
                parse_mode="HTML",
            )
            # Save state for after selection
            memory_state.set(user_id, {
                "flow": "nlp_disambiguate",
                "intent": intent.value,
                "entities_raw": text,
            })
            return

        elif resolution["status"] == "not_found":
            if model_required:
                recent = recent_models.get(user_id)
                if recent:
                    from app.keyboards.inline import nlp_not_found_keyboard
                    await message.answer(
                        f"❌ Модель '{html.escape(entities.model_name)}' не найдена.\n\n"
                        "Последние модели:",
                        reply_markup=nlp_not_found_keyboard(recent, intent.value),
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

    # ===== Step 6 & 7: Validation & Execute Handler =====
    await _execute_handler(message, intent, model, entities, config, notion, memory_state, recent_models)


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
        await handle_create_orders_nlp(message, model, entities, config, notion)
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
        await handle_report_nlp(message, model, config, notion)
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
            await message.answer(
                f"✅ <b>{html.escape(model['name'])}</b>\n\n"
                f"Примеры:\n"
                f"• {model['name']} кастом\n"
                f"• {model['name']} 30 файлов\n"
                f"• {model['name']} съемка на 13.02\n"
                f"• репорт {model['name']}",
                parse_mode="HTML",
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

            if existing_on_date:
                # Update existing shoot
                shoot = existing_on_date[0]
                await notion.update_shoot_status(shoot.page_id, "scheduled")
                await message.answer(
                    f"✅ Съемка обновлена на {entities.date.strftime('%d.%m')}",
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
                    parse_mode="HTML",
                )

            recent_models.add(message.from_user.id, model_id, model_name)

        except Exception as e:
            LOGGER.exception("Failed to create shoot: %s", e)
            await message.answer("❌ Ошибка при создании съемки.")
    else:
        # No date — ask for date
        from app.keyboards.inline import nlp_shoot_date_keyboard
        memory_state.set(message.from_user.id, {
            "flow": "nlp_shoot",
            "step": "awaiting_date",
            "model_id": model_id,
            "model_name": model_name,
        })
        await message.answer(
            f"📅 <b>{html.escape(model_name)}</b> · Дата съемки:",
            reply_markup=nlp_shoot_date_keyboard(model_id),
            parse_mode="HTML",
        )


async def _handle_shoot_done(message, model, entities, config, notion, memory_state):
    """Handle marking a shoot as done."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав.")
        return

    model_id = model["id"]
    model_name = model["name"]

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
                await message.answer(
                    f"✅ Съемка на {entities.date.strftime('%d.%m')} выполнена",
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
            await message.answer(
                f"Отметить '{date_str}' как выполненную?",
                reply_markup=nlp_shoot_confirm_done_keyboard(shoot.page_id),
                parse_mode="HTML",
            )
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            await message.answer(
                f"📅 <b>{html.escape(model_name)}</b> · Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "done"),
                parse_mode="HTML",
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
            memory_state.set(message.from_user.id, {
                "flow": "nlp_shoot",
                "step": "awaiting_new_date",
                "shoot_id": shoot.page_id,
                "model_id": model_id,
                "model_name": model_name,
                "old_date": shoot.date,
            })
            date_str = shoot.date[:10] if shoot.date else "?"
            await message.answer(
                f"📅 Перенос съемки {date_str}\n\nНовая дата:",
                reply_markup=nlp_shoot_date_keyboard(model_id),
                parse_mode="HTML",
            )
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            await message.answer(
                f"📅 <b>{html.escape(model_name)}</b> · Какую съемку перенести?",
                reply_markup=nlp_shoot_select_keyboard(shoots, "reschedule"),
                parse_mode="HTML",
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
    memory_state.set(message.from_user.id, {
        "flow": "nlp_order",
        "step": "awaiting_type",
        "model_id": model["id"],
        "model_name": model["name"],
    })
    await message.answer(
        f"📦 <b>{html.escape(model['name'])}</b> · Тип заказа:",
        reply_markup=nlp_order_type_keyboard(model["id"]),
        parse_mode="HTML",
    )


async def _handle_close_orders(message, model, entities, config, notion, memory_state):
    """Handle order closing."""
    from app.roles import is_editor
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ Нет прав.")
        return

    model_id = model["id"]
    model_name = model["name"]

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
            await message.answer(
                f"✅ Нет открытых {type_label} для {html.escape(model_name)}",
                parse_mode="HTML",
            )
            return

        if len(orders) == 1:
            # Single order — ask for close date
            order = orders[0]
            from app.keyboards.inline import nlp_close_order_date_keyboard
            days = _calc_days_open(order.in_date)
            label = f"{order.order_type or '?'} · {_format_date_short(order.in_date)} ({days}d)"
            await message.answer(
                f"Закрыть '{label}'?\n\nДата закрытия:",
                reply_markup=nlp_close_order_date_keyboard(order.page_id),
                parse_mode="HTML",
            )
        else:
            # Multiple orders — show selection
            from app.keyboards.inline import nlp_close_order_select_keyboard
            await message.answer(
                f"📦 <b>{html.escape(model_name)}</b> · Выберите заказ:",
                reply_markup=nlp_close_order_select_keyboard(orders),
                parse_mode="HTML",
            )

    except Exception as e:
        LOGGER.exception("Failed to handle close orders: %s", e)
        await message.answer("❌ Ошибка при поиске заказов.")


# ============================================================================
#                      COMMENT / FILES STATS / AMBIGUOUS
# ============================================================================

async def _handle_add_comment(message, model, entities, config, notion, memory_state):
    """Handle adding a comment."""
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
        memory_state.set(message.from_user.id, {
            "flow": "nlp_comment",
            "step": "awaiting_target",
            "model_id": model["id"],
            "model_name": model["name"],
            "comment_text": entities.comment_text,
        })
        await message.answer(
            "Что комментировать?",
            reply_markup=nlp_comment_target_keyboard(model["id"]),
            parse_mode="HTML",
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
            new_comment = f"{existing}\n{entities.comment_text}".strip() if existing else entities.comment_text
            await notion.update_order_comment(order.page_id, new_comment)
            await message.answer("✅ Комментарий добавлен")
        else:
            from app.keyboards.inline import nlp_comment_order_select_keyboard
            memory_state.set(message.from_user.id, {
                "flow": "nlp_comment",
                "step": "awaiting_order_selection",
                "model_id": model["id"],
                "comment_text": entities.comment_text,
            })
            await message.answer(
                "Выберите заказ:",
                reply_markup=nlp_comment_order_select_keyboard(orders),
                parse_mode="HTML",
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
            new_comment = f"{existing}\n{entities.comment_text}".strip() if existing else entities.comment_text
            await notion.update_shoot_comment(shoot.page_id, new_comment)
            await message.answer("✅ Комментарий добавлен")
        else:
            from app.keyboards.inline import nlp_shoot_select_keyboard
            memory_state.set(message.from_user.id, {
                "flow": "nlp_comment",
                "step": "awaiting_shoot_selection",
                "model_id": model["id"],
                "comment_text": entities.comment_text,
            })
            await message.answer(
                "Выберите съемку:",
                reply_markup=nlp_shoot_select_keyboard(shoots, "comment"),
                parse_mode="HTML",
            )
    except Exception as e:
        LOGGER.exception("Failed to add comment to shoot: %s", e)
        await message.answer("❌ Ошибка.")


async def _handle_files_stats(message, model, config, notion):
    """Handle files stats view (no number, just show stats)."""
    if not model:
        await message.answer("❌ Укажите модель. Пример: 'мелиса файлы'")
        return

    model_name = model["name"]
    model_id = model["id"]

    try:
        now = datetime.now(tz=config.timezone)
        month_str = now.strftime("%B")

        record = await notion.get_accounting_record(config.db_accounting, model_id, month_str)

        if record:
            current = record.amount or 0
            target = config.files_per_month
            percent = int((current / target) * 100) if target > 0 else 0
            remaining = max(0, target - current)

            await message.answer(
                f"📊 <b>{html.escape(model_name)}</b> | {month_str}\n\n"
                f"Файлов: {current} ({percent}%)\n"
                f"До {target}: {remaining} файлов",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"📊 <b>{html.escape(model_name)}</b> | {month_str}\n\n"
                f"Файлов: 0 (0%)\n"
                f"До {config.files_per_month}: {config.files_per_month} файлов",
                parse_mode="HTML",
            )

    except Exception as e:
        LOGGER.exception("Failed to get files stats: %s", e)
        await message.answer("❌ Ошибка при загрузке статистики.")


async def _handle_ambiguous(message, model, entities, config, memory_state):
    """Handle ambiguous intent (model + number, no marker)."""
    if not model or not entities.numbers:
        await _show_help_message(message)
        return

    number = entities.first_number
    from app.keyboards.inline import nlp_disambiguate_keyboard

    await message.answer(
        f"Что сделать с {number}?",
        reply_markup=nlp_disambiguate_keyboard(model["id"], number),
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
