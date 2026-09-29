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
from app.services import planner as planner_cache
from app.services import accounting as accounting_cache
from app.state import MemoryState, RecentModels, generate_token

from app.router.prefilter import prefilter_message
from app.router.entities_v2 import (
    extract_entities_v2,
    validate_model_name,
)
from app.router.command_filters import CommandIntent
from app.router.model_resolver import resolve_model
from app.utils.formatting import format_appended_comment, MAX_COMMENT_LENGTH
from app.utils.formatting import today as today_in_tz
from app.utils.telegram import safe_answer
from app.utils.locks import get_user_lock


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
            "✅ Done",
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
            "✅ Done",
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
    """Serialize per (chat, user) around the actual routing pipeline.

    Shares the lock with app.handlers.nlp_callbacks — a text message and a
    callback press for the same user must not run concurrently, or one can
    read/overwrite memory_state mid-flow (e.g. an order confirm reading a
    model_id that a racing text search just replaced).
    """
    lock = get_user_lock(message.chat.id, message.from_user.id)
    async with lock:
        await _route_message_impl(message, config, notion, memory_state, recent_models)


async def _route_message_impl(
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
                    await message.answer("⏳ Pick an order from the list or press «Back».")
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
            await message.answer("⏱ Server is busy, try again in a minute")
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
                f"🔍 Did you mean <b>{html.escape(m['name'])}</b>?",
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
                f"🔍 Which model '{html.escape(entities.model_name)}':",
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
                        f"❌ Model '{html.escape(entities.model_name)}' not found.\n\n"
                        "Recent models:",
                        reply_markup=nlp_not_found_keyboard(recent, k),
                        parse_mode="HTML",
                    )
                else:
                    await message.answer(
                        f"❌ Model '{html.escape(entities.model_name)}' not found.",
                        parse_mode="HTML",
                    )
                return

    elif model_required and not entities.model_name:
        # Intent requires model but none detected
        await message.answer("❌ Enter a model name.")
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
            await message.answer("⏱ Server is busy, try again in a minute")
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
            await _clear_previous_screen_keyboard(message, memory_state)
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
        await message.answer("❌ Session expired, try again.")
        return

    comment_text = text.strip()
    if not comment_text:
        await message.answer("❌ Comment can't be empty.")
        return

    if len(comment_text) > MAX_COMMENT_LENGTH:
        await message.answer(
            f"❌ Comment is too long (max {MAX_COMMENT_LENGTH} characters)."
        )
        return

    try:
        shoot = await notion.get_shoot(shoot_id)
        if not shoot:
            LOGGER.warning("SHOOT_COMMENT_INPUT: shoot not found shoot_id=%s user=%s", shoot_id, user_id)
            memory_state.clear(chat_id, user_id)
            await message.answer("❌ Shoot not found. It may have been deleted.")
            return

        existing = shoot.comments or ""
        new_comment = format_appended_comment(existing, comment_text, tz=config.timezone)
        await notion.update_shoot_comment(shoot_id, new_comment)
        planner_cache.clear_cache(user_state.get("model_id", ""))
        await _clear_previous_screen_keyboard(message, memory_state)
        await _cleanup_prompt_message(message, memory_state)
        memory_state.clear(chat_id, user_id)
        LOGGER.info("SHOOT_COMMENT_INPUT OK user=%s shoot_id=%s", user_id, shoot_id)
        from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
        sent = await message.answer(
            f"✅ Comment added for <b>{html.escape(model_name)}</b>",
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
        await message.answer("❌ Failed to save the comment.")


def _day_label(d):
    from app.handlers.nlp_callbacks import _day_label as label
    return label(d)


def _day_label_long(d):
    from app.handlers.nlp_callbacks import _day_label_long as label
    return label(d)


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
        await message.answer("❌ Format: DD.MM (e.g. 13.02)")
        return

    day, month = int(m.group(1)), int(m.group(2))
    try:
        today = today_in_tz(config.timezone)
        year = today.year
        parsed_date = date(year, month, day)
        # Only bump to next year if the date is more than 90 days in the past.
        # This prevents e.g. "10.01" from jumping to next year when today is 06.02.
        if parsed_date < today - timedelta(days=90):
            parsed_date = date(year + 1, month, day)
    except ValueError:
        await message.answer("❌ Invalid date")
        return

    if current_flow == "nlp_shoot":
        step = user_state.get("step", "")
        model_id = user_state.get("model_id", "")
        model_name = user_state.get("model_name", "")

        if step == "awaiting_custom_date" and user_state.get("new_shoot"):
            # New shoot: the day is the first step, content comes next
            from app.keyboards.inline import nlp_shoot_content_keyboard
            k = generate_token()
            memory_state.update(
                chat_id, user_id, step="awaiting_content", date_chosen=True,
                shoot_date=parsed_date.isoformat(), k=k,
            )
            await _clear_previous_screen_keyboard(message, memory_state)
            await _cleanup_prompt_message(message, memory_state)
            sent = await message.answer(
                f"📅 <b>{html.escape(model_name)}</b> · {_day_label_long(parsed_date)}\n\nChoose content:",
                reply_markup=nlp_shoot_content_keyboard(user_state.get("content_types", []), model_id, k),
                parse_mode="HTML",
            )
            _remember_screen_message(memory_state, chat_id, user_id, sent.message_id if sent else None)
        elif step == "awaiting_custom_date" and user_state.get("shoot_id"):
            # Reschedule
            shoot_id = user_state["shoot_id"]
            if not is_editor(user_id, config):
                await message.answer("❌ No permission.")
                memory_state.clear(chat_id, user_id)
                return
            from app.handlers.nlp_callbacks import move_shoot
            moved_text = await move_shoot(notion, shoot_id, user_state.get("old_date"), parsed_date)
            planner_cache.clear_cache(model_id)
            await _clear_previous_screen_keyboard(message, memory_state)
            await _cleanup_prompt_message(message, memory_state)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            await message.answer(
                moved_text,
                reply_markup=_nlp_action_complete_keyboard(model_id),
                parse_mode="HTML",
            )
        else:
            # Proceed to location selection
            if not is_editor(user_id, config):
                await message.answer("❌ No permission.")
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
                f"📍 <b>{html.escape(model_name)}</b> · Location:",
                reply_markup=nlp_shoot_location_keyboard(model_id, k),
                parse_mode="HTML",
            )

    elif current_flow == "nlp_close":
        model_id_for_kb = user_state.get("model_id", "")
        order_id = user_state.get("order_id")
        if not order_id:
            await message.answer("Session expired. Send the request again.")
            memory_state.clear(chat_id, user_id)
            return
        if not is_editor(user_id, config):
            await message.answer("❌ No permission.")
            memory_state.clear(chat_id, user_id)
            return
        try:
            await notion.close_order(order_id, parsed_date)
            orders_cache.clear_cache(model_id_for_kb)
            await _clear_previous_screen_keyboard(message, memory_state)
            await _cleanup_prompt_message(message, memory_state)
            memory_state.clear(chat_id, user_id)
            from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
            await message.answer(
                f"✅ Order closed · {_day_label(parsed_date)}",
                reply_markup=_nlp_action_complete_keyboard(model_id_for_kb),
                parse_mode="HTML",
            )
        except Exception as e:
            LOGGER.exception("Failed to close order: %s", e)
            await message.answer("❌ Failed to close the order.")
            memory_state.clear(chat_id, user_id)
    elif current_flow == "nlp_order":
        if not is_editor(user_id, config):
            await message.answer("❌ No access.")
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
            f"Order date: <b>{_day_label_long(parsed_date)}</b>\n\nCreate the order?",
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
        await message.answer("❌ Unexpected state. Try again.")
        memory_state.clear(chat_id, user_id)


MAX_FILES_INPUT = 1500  # configurable upper limit for manual file count


async def _handle_custom_files_input(message, text, user_state, config, notion, memory_state):
    """Typed amount in the nlp_files flow (the type was chosen before): save right away."""
    from app.roles import is_editor

    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_editor(user_id, config):
        await message.answer("❌ No permission.")
        memory_state.clear(chat_id, user_id)
        return

    count = _parse_files_count(text.strip())
    if count is None:
        await message.answer(f"❌ Enter a number (1–{MAX_FILES_INPUT})")
        return

    model_id = user_state.get("model_id", "")
    model_name = user_state.get("model_name", "")
    content_type = user_state.get("content_type")
    if not model_id or not content_type:
        await message.answer("❌ Session expired, try again.")
        memory_state.clear(chat_id, user_id)
        return

    from app.handlers.nlp_callbacks import save_files
    from app.keyboards.inline import nlp_action_complete_keyboard

    try:
        confirm = await save_files(config, notion, message.from_user, model_id, model_name, count, content_type)
    except Exception:
        LOGGER.exception("Failed to add files")
        await message.answer("❌ Notion error — try later")
        memory_state.clear(chat_id, user_id)
        return

    await _clear_previous_screen_keyboard(message, memory_state)
    await _cleanup_prompt_message(message, memory_state)
    await message.answer(confirm, reply_markup=nlp_action_complete_keyboard(model_id), parse_mode="HTML")
    memory_state.clear(chat_id, user_id)


async def _handle_new_shoot_comment_input(message, text, user_state, config, notion, memory_state):
    """Comment typed for a new shoot: create it."""
    from app.roles import is_editor

    user_id = message.from_user.id
    chat_id = message.chat.id
    if not is_editor(user_id, config):
        await message.answer("❌ No permission.")
        memory_state.clear(chat_id, user_id)
        return
    comment = (text or "").strip()
    if len(comment) > MAX_COMMENT_LENGTH:
        await message.answer(f"❌ Comment is too long (max {MAX_COMMENT_LENGTH} characters).")
        return

    from app.handlers.nlp_callbacks import create_new_shoot
    from app.keyboards.inline import nlp_action_complete_keyboard

    try:
        confirm = await create_new_shoot(config, notion, message.from_user, user_state, comment)
    except Exception:
        LOGGER.exception("Failed to create shoot")
        await message.answer("❌ Notion error — try later")
        memory_state.clear(chat_id, user_id)
        return
    await _clear_previous_screen_keyboard(message, memory_state)
    await _cleanup_prompt_message(message, memory_state)
    await message.answer(confirm, reply_markup=nlp_action_complete_keyboard(user_state.get("model_id", "")),
                         parse_mode="HTML")
    memory_state.clear(chat_id, user_id)


async def _handle_note_input(message, text, user_state, config, notion, memory_state):
    """Handle note text input for nlp_note flow."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    note_text = text.strip()
    if not note_text:
        await message.answer("❌ Note can't be empty.")
        return

    model_id = user_state.get("model_id")
    model_name = user_state.get("model_name", "")
    screen_message_id = user_state.get("screen_message_id")

    if not model_id or not config.db_notes:
        await message.answer("❌ Session expired, try again.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        await notion.create_note(
            config.db_notes, model_id, model_name, note_text,
            note_date=today_in_tz(config.timezone),
        )
    except Exception:
        LOGGER.exception("Failed to create note model=%s", model_id)
        await message.answer("❌ Failed to save the note.")
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
        card_text = f"📌 <b>{html.escape(model_name.upper())}</b>\n\n✅ Note saved"

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
        await message.answer("❌ No access.")
        memory_state.clear(chat_id, user_id)
        return

    comment_text = text.strip()
    if not comment_text:
        await message.answer("❌ Comment can't be empty.")
        return

    record_id = user_state.get("accounting_id")
    model_name = user_state.get("model_name", "")
    if not record_id:
        await message.answer("❌ Session expired, try again.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        await notion.update_accounting_comment(record_id, comment_text)
        yyyy_mm = datetime.now(tz=config.timezone).strftime("%Y-%m")
        accounting_cache.clear_cache(user_state.get("model_id", ""), yyyy_mm)
        await _clear_previous_screen_keyboard(message, memory_state)
        await _cleanup_prompt_message(message, memory_state)
        memory_state.clear(chat_id, user_id)
        from app.keyboards.inline import nlp_action_complete_keyboard as _nlp_action_complete_keyboard
        sent = await message.answer(
            f"✅ Comment updated for <b>{html.escape(model_name)}</b>",
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
        await message.answer("❌ Failed to save the comment.")
        memory_state.clear(chat_id, user_id)


def _parse_files_count(text: str) -> int | None:
    """Parse a positive file count (1..MAX_FILES_INPUT) from text like "30", "+30", "30 файлов", "файлы 30"."""
    import re
    t = text.strip().lower()

    # Pattern 1: optional '+', digits, optional suffix (ф/файл*)
    m = re.match(r'^[+]?\s*(\d+)\s*(?:ф[а-я]*|files?)?\s*$', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= MAX_FILES_INPUT:
            return n
        return None

    # Pattern 2: "файлы 30", "файлов 30"
    m = re.match(r'^(?:файл[а-я]*|files?)\s+[+]?\s*(\d+)\s*$', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= MAX_FILES_INPUT:
            return n
        return None

    return None


async def _show_help_message(message: Message) -> None:
    """Show help message when no model was recognized in the message."""
    await message.answer(
        "🤔 No model found in the message.\n\n"
        "Just type the model name.\n\n"
        "Or /start",
        parse_mode="HTML",
    )


async def _handle_custom_order_count_input(message, text, user_state, config, notion, memory_state):
    """Handle custom order count input."""
    from app.roles import is_editor
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_editor(user_id, config):
        await message.answer("❌ No permission.")
        memory_state.clear(chat_id, user_id)
        return

    try:
        count = int(text.strip())
        if count < 1 or count > 99:
            await message.answer("❌ Enter a number from 1 to 99")
            return
    except ValueError:
        await message.answer("❌ Enter a number from 1 to 99")
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
        f"📦 <b>{html.escape(model_name)}</b> · {count}x {type_label}\n\nOrder date:",
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
        await message.answer("❌ Enter a whole number above 0")
        return

    model_id = user_state.get("model_id", "")
    screen_message_id = user_state.get("screen_message_id")

    from app.handlers.nlp_callbacks import apply_received
    from app.keyboards.inline import nlp_action_complete_keyboard

    try:
        result_text = await apply_received(config, notion, user_state, added)
    except Exception:
        LOGGER.exception("Failed to update received")
        await message.answer("❌ Notion error — try later")
        memory_state.clear(chat_id, user_id)
        return
    try:
        await message.delete()
    except Exception:
        pass
    memory_state.clear(chat_id, user_id)
    try:
        await message.bot.edit_message_text(
            chat_id=chat_id,
            message_id=screen_message_id,
            text=result_text,
            reply_markup=nlp_action_complete_keyboard(model_id),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await message.answer(
            result_text,
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
    ("nlp_shoot", "awaiting_new_shoot_comment"): _handle_new_shoot_comment_input,
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
