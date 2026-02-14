"""Accounting handlers — refactored for 1-record-per-model-per-month schema.

Notion fields: Title ("{MODEL} {месяц_ru_lower}"), model (relation),
Files (number), Comment (rich_text), Content (multi_select).
"""
import html
import logging
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.filters import FlowFilter
from app.filters.topic_access import TopicAccessCallbackFilter, TopicAccessMessageFilter
from app.keyboards.inline import (
    accounting_menu_keyboard,
    accounting_quick_files_keyboard,
    recent_models_keyboard,
    models_keyboard,
    back_keyboard,
)
from app.roles import is_authorized, is_editor
from app.services import AccountingService, ModelsService
from app.services.notion import NotionClient
from app.state import MemoryState, RecentModels, generate_token
from app.utils.accounting import format_accounting_progress
from app.utils.exceptions import NotionAPIError

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())
router.callback_query.filter(TopicAccessCallbackFilter())


def _state_ids_from_message(message: Message) -> tuple[int, int]:
    return message.chat.id, message.from_user.id


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id


def _new_token(memory_state: MemoryState, chat_id: int, user_id: int) -> str:
    token = generate_token()
    memory_state.update(chat_id, user_id, k=token)
    return token


def _files_display(files: int, status: str | None) -> str:
    """Format files as 'X/target (Y%) +over'."""
    return format_accounting_progress(files, status)


async def show_accounting_menu(message: Message, config: Config) -> None:
    """Show accounting section menu."""
    await message.answer(
        "💰 <b>Accounting</b>\n\n"
        "Select an action:",
        reply_markup=accounting_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("account|"))
async def handle_accounting_callback(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle accounting callbacks."""
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return

    parts = query.data.split("|")
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    token = parts[-1] if len(parts) >= 4 else ""
    payload = parts[2:-1] if token else parts[2:]
    value = payload[0] if payload else None

    LOGGER.info("Accounting callback: action=%s, value=%s", action, value)

    try:
        if action == "search":
            await _start_model_search(query, memory_state)
        elif action == "current":
            await _show_current_month(query, config, memory_state)
        elif action == "add_files":
            await _start_add_files(query, config, memory_state, recent_models)
        elif action in ("model", "select_model"):
            await _select_model(query, config, memory_state, recent_models, value)
        elif action == "files" and len(payload) >= 2:
            page_id = payload[0]
            count = int(payload[1])
            await _add_files_to_record(query, config, memory_state, page_id, count)
        elif action == "back":
            await _handle_back(query, config, memory_state, value)
        elif action == "cancel":
            await _cancel_flow(query, memory_state)
        else:
            await query.answer("Unknown action", show_alert=True)
    except Exception:
        LOGGER.exception("Error in accounting callback")
        await query.answer("Ошибка. Попробуйте позже.", show_alert=True)

    await query.answer()


@router.message(FlowFilter({"nlp_accounting"}), F.text)
async def handle_text_input(
    message: Message,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle text input for accounting."""
    if not is_authorized(message.from_user.id, config):
        return

    chat_id, user_id = _state_ids_from_message(message)
    data = memory_state.get(chat_id, user_id)
    step = data.get("step")

    try:
        if step == "search_model":
            await _process_model_search(message, config, memory_state)
        elif step == "add_files_custom":
            await _process_custom_files(message, config, memory_state)
        elif step == "add_comment":
            await _process_comment(message, config, memory_state)

        try:
            await message.delete()
        except Exception:
            pass
    except Exception:
        LOGGER.exception("Error processing text input")
        await message.answer("Ошибка. Попробуйте позже.")


# ------------------------------------------------------------------ search
async def _start_model_search(query: CallbackQuery, memory_state: MemoryState) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    token = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_accounting", "step": "search_model",
        "screen_chat_id": query.message.chat.id,
        "screen_message_id": query.message.message_id,
        "k": token,
    })
    await query.message.edit_text(
        "🔍 Send model name to search:",
        reply_markup=back_keyboard("account", token=token),
        parse_mode="HTML",
    )


async def _process_model_search(message: Message, config: Config, memory_state: MemoryState) -> None:
    query_text = message.text.strip()
    chat_id, user_id = _state_ids_from_message(message)
    data = memory_state.get(chat_id, user_id) or {}
    chat_id = data.get("screen_chat_id")
    msg_id = data.get("screen_message_id")

    models_service = ModelsService(config)
    try:
        models = await models_service.search_models(query_text)
    except Exception:
        LOGGER.exception("Failed to search models")
        await message.bot.edit_message_text(
            "❌ <b>Error searching models</b>",
            chat_id=chat_id, message_id=msg_id,
            reply_markup=back_keyboard("account", token=data.get("k", "")), parse_mode="HTML",
        )
        return

    if not models:
        await message.bot.edit_message_text(
            f"🔍 No models found for: {html.escape(query_text)}\n\nTry again:",
            chat_id=chat_id, message_id=msg_id,
            reply_markup=back_keyboard("account", token=data.get("k", "")), parse_mode="HTML",
        )
        return

    model_list = [(m["id"], m["name"]) for m in models]
    await message.bot.edit_message_text(
        f"🔍 Found {len(models)} model(s):\n\nSelect one:",
        chat_id=chat_id, message_id=msg_id,
        reply_markup=models_keyboard("account", model_list, token=data.get("k", "")), parse_mode="HTML",
    )
    memory_state.update(chat_id, user_id, step="select_model", search_results=models)


# --------------------------------------------------------- current month
async def _show_current_month(query: CallbackQuery, config: Config, memory_state: MemoryState) -> None:
    try:
        svc = AccountingService(config)
        records = await svc.get_all_month_records()
        now = datetime.now(config.timezone)
        yyyy_mm = now.strftime("%Y-%m")

        if not records:
            text = f"💰 <b>{yyyy_mm} Accounting</b>\n\nNo records yet."
        else:
            text = f"💰 <b>{yyyy_mm} Accounting</b>\n\n"
            for r in records[:10]:
                name = r.get("model_name", "Unknown")
                files = r.get("files", 0)
                line = _files_display(files, r.get("status"))
                text += f"• <b>{html.escape(name)}</b>\n  Files: {line}\n\n"

        await query.message.edit_text(text, reply_markup=accounting_menu_keyboard(token=generate_token()), parse_mode="HTML")
        chat_id, user_id = _state_ids_from_query(query)
        memory_state.clear(chat_id, user_id)
    except Exception:
        LOGGER.exception("Error showing current month accounting")
        try:
            await query.message.edit_text(
                "❌ <b>Error loading accounting data</b>",
                reply_markup=accounting_menu_keyboard(token=generate_token()), parse_mode="HTML",
            )
        except Exception:
            pass


# --------------------------------------------------------- add files flow
async def _start_add_files(query: CallbackQuery, config: Config, memory_state: MemoryState, recent_models: RecentModels) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    recent = recent_models.get(user_id)
    token = generate_token()
    memory_state.set(chat_id, user_id, {
        "flow": "nlp_accounting", "step": "select_model",
        "screen_chat_id": query.message.chat.id,
        "screen_message_id": query.message.message_id,
        "k": token,
    })
    await query.message.edit_text(
        "💰 <b>Add Files</b>\n\nSelect model:",
        reply_markup=recent_models_keyboard(recent, "account", token=token),
        parse_mode="HTML",
    )


async def _select_model(query: CallbackQuery, config: Config, memory_state: MemoryState, recent_models: RecentModels, model_id: str) -> None:
    try:
        models_service = ModelsService(config)
        model = await models_service.get_model_by_id(model_id)
        if not model:
            await query.answer("Model not found", show_alert=True)
            return

        model_name = model.get("name", "Unknown")
        chat_id, user_id = _state_ids_from_query(query)
        recent_models.add(user_id, model_id, model_name)

        svc = AccountingService(config)
        record = await svc.get_monthly_record(model_id)
        current_files = record.files if record else 0
        record_status = record.status if record else None

        text = (
            f"💰 <b>{html.escape(model_name)}</b>\n\n"
            f"Current: {_files_display(current_files, record_status)}\n\n"
            f"Add files:"
        )

        memory_state.update(
            chat_id,
            user_id,
            step="add_files", model_id=model_id,
            model_name=model_name, current_files=current_files,
        )
        await query.message.edit_text(
            text,
            reply_markup=accounting_quick_files_keyboard(model_id, current_files),
            parse_mode="HTML",
        )
    except Exception:
        LOGGER.exception("Error selecting model for accounting")
        await query.answer("Error loading model data", show_alert=True)


async def _add_files_to_record(query: CallbackQuery, config: Config, memory_state: MemoryState, page_id: str, count: int) -> None:
    if not is_editor(query.from_user.id, config):
        await query.answer("Only editors can add files", show_alert=True)
        return

    try:
        chat_id, user_id = _state_ids_from_query(query)
        data = memory_state.get(chat_id, user_id) or {}
        model_id = data.get("model_id") or page_id
        model_name = data.get("model_name", "Unknown")

        svc = AccountingService(config)
        result = await svc.add_files(model_id, model_name, count)

        await query.message.edit_text(
            f"✅ <b>Files added!</b>\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Total: {_files_display(result['files'], result.get('status'))}\n"
            f"Added: +{count}",
            reply_markup=accounting_menu_keyboard(), parse_mode="HTML",
        )
        memory_state.clear(chat_id, user_id)
    except NotionAPIError as e:
        LOGGER.warning("Error adding files to accounting record")
        await query.answer(e.user_message, show_alert=True)
    except Exception:
        LOGGER.exception("Error adding files to accounting record")
        await query.answer("Не смог обновить Notion, попробуй позже", show_alert=True)


# --------------------------------------------------------- custom input
async def _process_custom_files(message: Message, config: Config, memory_state: MemoryState) -> None:
    chat_id, user_id = _state_ids_from_message(message)
    data = memory_state.get(chat_id, user_id) or {}
    chat_id = data.get("screen_chat_id")
    msg_id = data.get("screen_message_id")

    try:
        count = int(message.text.strip())
        if count < 1 or count > 500:
            raise ValueError
    except ValueError:
        if chat_id and msg_id:
            await message.bot.edit_message_text(
                "❌ Введите число от 1 до 500:",
                chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
            )
        return

    model_id = data.get("model_id")
    model_name = data.get("model_name", "Unknown")
    if not model_id:
        return

    try:
        svc = AccountingService(config)
        result = await svc.add_files(model_id, model_name, count)

        if chat_id and msg_id:
            await message.bot.edit_message_text(
                f"✅ <b>Files added!</b>\n\n"
                f"<b>{html.escape(model_name)}</b>\n"
                f"Total: {_files_display(result['files'], result.get('status'))}\n"
                f"Added: +{count}",
                chat_id=chat_id, message_id=msg_id,
                reply_markup=accounting_menu_keyboard(token=generate_token()), parse_mode="HTML",
            )
        memory_state.clear(chat_id, user_id)
    except NotionAPIError as e:
        LOGGER.warning("Error adding custom files")
        if chat_id and msg_id:
            await message.bot.edit_message_text(
                e.user_message,
                chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
            )
    except Exception:
        LOGGER.exception("Error adding custom files")
        if chat_id and msg_id:
            await message.bot.edit_message_text(
                "❌ Не смог обновить Notion, попробуй позже",
                chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
            )


async def _process_comment(message: Message, config: Config, memory_state: MemoryState) -> None:
    comment_text = message.text.strip()
    chat_id, user_id = _state_ids_from_message(message)
    data = memory_state.get(chat_id, user_id) or {}
    record_id = data.get("record_id")
    if not record_id:
        return

    svc = AccountingService(config)
    await svc.update_comment(record_id, comment_text)

    chat_id = data.get("screen_chat_id")
    msg_id = data.get("screen_message_id")
    if chat_id and msg_id:
        await message.bot.edit_message_text(
            "✅ Comment updated!",
            chat_id=chat_id, message_id=msg_id,
            reply_markup=accounting_menu_keyboard(), parse_mode="HTML",
        )
    memory_state.clear(chat_id, user_id)


# --------------------------------------------------------- nav
async def _handle_back(query: CallbackQuery, config: Config, memory_state: MemoryState, value: str) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.clear(chat_id, user_id)
    if value == "main":
        await query.message.delete()
    else:
        await query.message.edit_text(
            "💰 <b>Accounting</b>\n\nSelect an action:",
            reply_markup=accounting_menu_keyboard(), parse_mode="HTML",
        )


async def _cancel_flow(query: CallbackQuery, memory_state: MemoryState) -> None:
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.clear(chat_id, user_id)
    await query.message.edit_text(
        "💰 <b>Accounting</b>\n\nCancelled.",
        reply_markup=accounting_menu_keyboard(), parse_mode="HTML",
    )


# ==================== NLP Handler ====================

async def handle_add_files_nlp(
    message: Message,
    model: dict,
    entities: Any,
    config: Config,
    notion: NotionClient,
    recent_models: RecentModels,
) -> None:
    """Handle adding files from NLP message."""
    if not is_editor(message.from_user.id, config):
        await message.answer("❌ У вас нет прав на добавление файлов.")
        return

    if not entities.numbers:
        await message.answer("❌ Укажите количество файлов. Пример: 'мелиса 30 файлов'")
        return

    count = entities.numbers[0]
    if count < 1 or count > 500:
        await message.answer("❌ Количество должно быть от 1 до 500")
        return

    model_id = model["id"]
    model_name = model["name"]
    yyyy_mm = datetime.now(tz=config.timezone).strftime("%Y-%m")

    try:
        record = await notion.get_monthly_record(
            config.db_accounting, model_id, yyyy_mm,
        )
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

        await message.answer(
            f"✅ +{count} файлов\n\n"
            f"<b>{html.escape(model_name)}</b>\n"
            f"Файлов: {_files_display(new_files, record_status)}",
            parse_mode="HTML",
        )
        recent_models.add(message.from_user.id, model_id, model_name)
    except NotionAPIError as e:
        LOGGER.warning("Failed to add files: %s", e)
        await message.answer(e.user_message)
    except Exception:
        LOGGER.exception("Failed to add files")
        await message.answer("❌ Не смог обновить Notion, попробуй позже.")
