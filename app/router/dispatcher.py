"""
Main routing dispatcher for NLP messages.

Routing pipeline:
1. State Check → есть ли активный flow?
2. Pre-filter → gibberish, длина < 2, bot commands
3. Entity Extraction → model name
4. Intent Classification (SEARCH_MODEL / UNKNOWN)
5. Model Resolution (aliases + fuzzy)
6. Execute Handler
"""

import asyncio
import html
import logging
import time
from datetime import date, datetime, timedelta

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.config import Config
from app.services import NotionClient
from app.services import orders as orders_cache
from app.state import MemoryState, RecentModels, generate_token

from app.router.prefilter import prefilter_message
from app.router.entities_v2 import (
    extract_entities_v2,
    validate_model_name,
)
from app.router.command_filters import CommandIntent
from app.router.model_resolver import resolve_model
from app.utils.formatting import format_appended_comment, MAX_COMMENT_LENGTH
from app.utils.telegram import safe_answer


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


async def _mark_screen_done(message: Message, memory_state: MemoryState) -> None:
    """Edit previous screen message to '✅ Готово' and remove its keyboard."""
    chat_id = message.chat.id
    user_id = message.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    prev_id = state.get("screen_message_id")
    if not prev_id:
        return
    try:
        await message.bot.edit_message_text(
            "✅ Готово",
            chat_id=chat_id,
            message_id=prev_id,
            reply_markup=None,
        )
    except Exception as e:
        LOGGER.debug("_mark_screen_done failed msg_id=%s: %s", prev_id, e)


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
    LOGGER.info(
        f"[CLEANUP] chat_id={chat_id}, user_id={user_id}, "
        f"prompt_id={prompt_id}, current_msg_id={message.message_id}"
    )
    if not prompt_id:
        LOGGER.warning("[CLEANUP] No prompt_id in state!")
        return
    LOGGER.info(f"[CLEANUP] Attempting to delete message {prompt_id}")
    await _safe_delete_or_mark_done(message.bot, message.chat.id, prompt_id)
    memory_state.update(chat_id, user_id, prompt_message_id=None)
    LOGGER.info("[CLEANUP] Cleanup complete")


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
    user_state = memory_state.get(chat_id, user_id)
    if user_state and user_state.get("flow"):
        current_flow = user_state["flow"]
        if current_flow.startswith("nlp_"):
            if current_flow == "nlp_disambiguate":
                await _mark_screen_done(message, memory_state)
                memory_state.clear(chat_id, user_id)
                # fall through — обработать текст как новый запрос
            else:
                current_step = user_state.get("step", "")

                # Dispatch to step-specific text handler if one exists.
                # _find_nlp_text_handler is defined at the bottom of this module.
                handler = _find_nlp_text_handler(current_flow, current_step)
                if handler:
                    await handler(message, text, user_state, config, notion, memory_state)
                    return

                # No text handler for this step.
                # nlp_close_picker has no recovery path once state is cleared
                # (callback validation requires flow=nlp_close_picker). Show prompt.
                if current_flow == "nlp_close_picker":
                    LOGGER.info("ROUTE_MESSAGE: user=%s in nlp_close_picker, prompting wait", user_id)
                    await message.answer("⏳ Выберите заказ из списка или нажмите «Назад».")
                    return

                # Other abandoned nlp_ flows — clear and reprocess as fresh request.
                LOGGER.info("ROUTE_MESSAGE: user=%s abandoned nlp flow=%s step=%s, clearing and reprocessing", user_id, current_flow, current_step)
                await _mark_screen_done(message, memory_state)
                memory_state.clear(chat_id, user_id)

        else:
            # Unknown flow — clear stale state and continue through NLP pipeline
            LOGGER.warning("User %s has unknown flow=%s, clearing state", user_id, current_flow)
            await _mark_screen_done(message, memory_state)
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
        "Stage entities_extraction: %.3fs | model=%s",
        time.time() - _t, entities.model_name,
    )

    # ===== Step 4: Intent Classification =====
    intent = CommandIntent.SEARCH_MODEL if entities.has_model else CommandIntent.UNKNOWN
    LOGGER.info("intent=%s for text=%r", intent.value, text[:60])

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
        await _execute_handler(message, text, intent, model, entities, config, notion, memory_state, recent_models)
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
    return intent != CommandIntent.UNKNOWN


async def _execute_handler(
    message: Message,
    text: str,
    intent: CommandIntent,
    model: dict | None,
    entities,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Execute the appropriate handler based on intent."""

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
            sent = await safe_answer(
                message,
                card_text,
                reply_markup=model_card_keyboard(k),
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
#                    SHOOT COMMENT INPUT (button-driven nlp_shoot flow)
# ============================================================================

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


async def _handle_custom_date_input(message, text, user_state, config, notion, memory_state):
    """Handle free-text date input (DD.MM) in nlp_shoot / nlp_close flows."""
    import re
    from app.roles import is_editor
    from app.state import generate_token

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
            # Proceed to location selection
            if not is_editor(user_id, config):
                await message.answer("❌ Нет прав.")
                memory_state.clear(chat_id, user_id)
                return

            content_types = user_state.get("content_types", [])
            k = generate_token()
            memory_state.set(chat_id, user_id, {
                "flow": "nlp_shoot",
                "step": "awaiting_location",
                "model_id": model_id,
                "model_name": model_name,
                "shoot_date": parsed_date.isoformat(),
                "content_types": content_types,
                "k": k,
            })
            from app.keyboards.inline import nlp_shoot_location_keyboard
            await _clear_previous_screen_keyboard(message, memory_state)
            await _cleanup_prompt_message(message, memory_state)
            await message.answer(
                f"📍 <b>{html.escape(model_name)}</b> · Локация:",
                reply_markup=nlp_shoot_location_keyboard(model_id, k),
                parse_mode="HTML",
            )

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
    memory_state.update(
        chat_id,
        user_id,
        flow="nlp_files",
        step="awaiting_content_type",
        count=count,
    )

    await _clear_previous_screen_keyboard(message, memory_state)
    await _cleanup_prompt_message(message, memory_state)
    from app.keyboards.inline import nlp_files_content_type_keyboard
    sent = await message.answer(
        f"📁 <b>{html.escape(model_name)}</b> · {count} файлов\n\nВыберите тип контента:",
        reply_markup=nlp_files_content_type_keyboard(model_id),
        parse_mode="HTML",
    )
    _remember_screen_message(
        memory_state,
        chat_id,
        message.from_user.id,
        sent.message_id if sent else None,
    )


async def _handle_note_input(message, text, user_state, config, notion, memory_state):
    """Handle note text input for nlp_note flow."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    note_text = text.strip()
    if not note_text:
        await message.answer("❌ Заметка не может быть пустой.")
        return

    model_id = user_state.get("model_id")
    model_name = user_state.get("model_name", "")
    screen_message_id = user_state.get("screen_message_id")

    if not model_id or not config.db_notes:
        await message.answer("❌ Сессия устарела, попробуйте заново.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        await notion.create_note(config.db_notes, model_id, model_name, note_text)
    except Exception:
        LOGGER.exception("Failed to create note model=%s", model_id)
        await message.answer("❌ Ошибка при сохранении заметки.")
        memory_state.clear(chat_id, user_id)
        return

    if config.owner_telegram_id:
        try:
            await message.bot.send_message(
                config.owner_telegram_id,
                f"📝 {html.escape(model_name)}\n{html.escape(note_text)}",
                parse_mode="HTML",
            )
        except Exception:
            LOGGER.warning("Failed to send owner note notification user=%s", user_id)

    from app.keyboards.inline import model_card_keyboard
    from app.services.model_card import build_model_card, clear_card_cache
    clear_card_cache()

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
        LOGGER.exception("Failed to rebuild model card after note")
        card_text = f"📌 <b>{html.escape(model_name.upper())}</b>\n\n✅ Заметка сохранена"

    keyboard = model_card_keyboard(k)

    if screen_message_id:
        try:
            await message.bot.edit_message_text(
                card_text,
                chat_id=chat_id,
                message_id=screen_message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            _remember_screen_message(memory_state, chat_id, user_id, screen_message_id)
            return
        except Exception:
            pass

    sent = await message.answer(card_text, reply_markup=keyboard, parse_mode="HTML")
    _remember_screen_message(memory_state, chat_id, user_id, sent.message_id if sent else None)


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
    """Show help message when no model was recognized in the message."""
    await message.answer(
        "🤔 Не нашёл модель в сообщении.\n\n"
        "Просто напишите имя модели, например: <b>мелиса</b>\n\n"
        "Или /start",
        parse_mode="HTML",
    )


async def _handle_custom_order_count_input(message, text, user_state, config, notion, memory_state):
    """Handle custom order count input."""
    from app.roles import is_editor
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_editor(user_id, config):
        await message.answer("❌ Нет прав.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        count = int(text.strip())
        if count < 1 or count > 99:
            await message.answer("❌ Введите число от 1 до 99")
            return
    except ValueError:
        await message.answer("❌ Введите число от 1 до 99")
        return

    from app.keyboards.inline import nlp_order_date_keyboard
    from app.router.entities_v2 import get_order_type_display_name

    model_name = user_state.get("model_name", "")
    order_type = user_state.get("order_type", "")
    model_id = user_state.get("model_id", "")
    type_label = get_order_type_display_name(order_type)

    k = generate_token()
    memory_state.update(chat_id, user_id, step="awaiting_date", count=count, k=k)

    await _clear_previous_screen_keyboard(message, memory_state)
    await _cleanup_prompt_message(message, memory_state)
    sent = await message.answer(
        f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\nДата заказа:",
        reply_markup=nlp_order_date_keyboard(model_id, k),
        parse_mode="HTML",
    )
    _remember_screen_message(memory_state, chat_id, user_id, sent.message_id if sent else None)


async def _handle_received_input(message, text, user_state, config, notion, memory_state):
    """Handle free-text received count input for nlp_received flow.

    Adds the entered number to current_received.  Auto-closes when total >= count.
    """
    from app.roles import is_editor
    chat_id, user_id = message.chat.id, message.from_user.id

    if not is_editor(user_id, config):
        memory_state.clear(chat_id, user_id)
        return

    try:
        added = int(text.strip())
        if added <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число больше 0")
        return

    order_id = user_state.get("order_id", "")
    count = int(user_state.get("count") or 0)
    current_received = int(user_state.get("current_received") or 0)
    model_name = user_state.get("model_name", "")
    model_id = user_state.get("model_id", "")
    screen_message_id = user_state.get("screen_message_id")

    new_received = current_received + added

    from app.keyboards.inline import nlp_action_complete_keyboard

    if new_received >= count:
        today_date = datetime.now(tz=config.timezone).date()
        await notion.close_order_with_received(order_id, today_date, new_received)
        orders_cache.clear_cache(model_id)
        try:
            await message.delete()
        except Exception:
            pass
        memory_state.clear(chat_id, user_id)
        success_text = (
            f"✅ Заказ закрыт — <b>{html.escape(model_name)}</b>\n"
            f"📥 {new_received}/{count} · все получено"
        )
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id,
                message_id=screen_message_id,
                text=success_text,
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            await message.answer(
                success_text,
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
    else:
        await notion.update_order_received(order_id, new_received)
        orders_cache.clear_cache(model_id)
        try:
            await message.delete()
        except Exception:
            pass
        memory_state.clear(chat_id, user_id)
        partial_text = (
            f"🔄 Обновлено — <b>{html.escape(model_name)}</b>\n"
            f"Получено: <b>{new_received}/{count}</b>"
        )
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id,
                message_id=screen_message_id,
                text=partial_text,
                reply_markup=nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            await message.answer(
                partial_text,
                reply_markup=nlp_action_complete_keyboard(model_id),
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
    ("nlp_note", "awaiting_text"): _handle_note_input,
    ("nlp_order", "awaiting_custom_count"): _handle_custom_order_count_input,
    ("nlp_received", "awaiting_received"): _handle_received_input,
}


def _find_nlp_text_handler(flow: str, step: str):
    """Look up handler for free-text input during an nlp_* flow.

    Tries exact (flow, step) first, then wildcard (None, step).
    Returns the handler callable or None.
    """
    return _NLP_TEXT_HANDLERS.get((flow, step)) or _NLP_TEXT_HANDLERS.get((None, step))
