"""Accounting handlers - Phase 4"""
import html
import logging
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.keyboards.inline import (
    accounting_menu_keyboard,
    accounting_quick_files_keyboard,
    recent_models_keyboard,
    models_keyboard,
    back_keyboard,
)
from app.roles import is_authorized, is_editor
from app.services import AccountingService, ModelsService
from app.state import MemoryState, RecentModels
from app.utils.constants import FILES_PER_MONTH
from app.utils.formatting import format_percent

LOGGER = logging.getLogger(__name__)
router = Router()


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
    value = parts[2] if len(parts) > 2 else None
    
    LOGGER.info(f"Accounting callback: action={action}, value={value}")
    
    try:
        if action == "search":
            await _start_model_search(query, memory_state)
        elif action == "current":
            await _show_current_month(query, config, memory_state)
        elif action == "add_files":
            await _start_add_files(query, config, memory_state, recent_models)
        elif action == "model":
            await _select_model(query, config, memory_state, recent_models, value)
        elif action == "select_model":
            await _select_model(query, config, memory_state, recent_models, value)
        elif action == "files" and len(parts) >= 4:
            page_id = parts[2]
            count = int(parts[3])
            await _add_files_to_record(query, config, memory_state, page_id, count)
        elif action == "select":
            await _show_record_details(query, config, memory_state, value)
        elif action == "edit_content":
            await _edit_content(query, config, memory_state, value)
        elif action == "comment":
            await _edit_comment(query, config, memory_state, value)
        elif action == "back":
            await _handle_back(query, config, memory_state, value)
        elif action == "cancel":
            await _cancel_flow(query, memory_state)
        else:
            await query.answer("Unknown action", show_alert=True)
    except Exception as e:
        LOGGER.exception("Error in accounting callback")
        await query.answer(f"Error: {str(e)}", show_alert=True)
    
    await query.answer()


@router.message(F.text)
async def handle_text_input(
    message: Message,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle text input for accounting."""
    if not is_authorized(message.from_user.id, config):
        return
    
    data = memory_state.get(message.from_user.id)
    if not data or data.get("flow") != "accounting":
        return
    
    step = data.get("step")
    
    try:
        if step == "search_model":
            await _process_model_search(message, config, memory_state)
        elif step == "add_files_custom":
            await _process_custom_files(message, config, memory_state)
        elif step == "add_comment":
            await _process_comment(message, config, memory_state)
        
        # Delete user message
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        LOGGER.exception("Error processing text input")
        await message.answer(f"Error: {str(e)}")


async def _start_model_search(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Start model search flow."""
    memory_state.set(
        query.from_user.id,
        {
            "flow": "accounting",
            "step": "search_model",
            "screen_chat_id": query.message.chat.id,
            "screen_message_id": query.message.message_id,
        },
    )
    
    text = "🔍 Send model name to search:"
    await query.message.edit_text(
        text,
        reply_markup=back_keyboard("account"),
        parse_mode="HTML",
    )


async def _process_model_search(
    message: Message,
    config: Config,
    memory_state: MemoryState,
) -> None:
    """Process model search query."""
    query_text = message.text.strip()

    data = memory_state.get(message.from_user.id) or {}
    screen_chat_id = data.get("screen_chat_id")
    screen_message_id = data.get("screen_message_id")

    models_service = ModelsService(config)
    try:
        models = await models_service.search_models(query_text)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to search models: %s", e)
        text = f"❌ <b>Error searching models</b>\n\nDatabase connection failed. Please contact admin."
        await message.bot.edit_message_text(
            text,
            chat_id=screen_chat_id,
            message_id=screen_message_id,
            reply_markup=back_keyboard("account"),
            parse_mode="HTML",
        )
        return

    if not models:
        text = f"🔍 No models found for: {html.escape(query_text)}\n\nTry again:"
        await message.bot.edit_message_text(
            text,
            chat_id=screen_chat_id,
            message_id=screen_message_id,
            reply_markup=back_keyboard("account"),
            parse_mode="HTML",
        )
        return
    
    # Convert to list of tuples
    model_list = [(m["id"], m["name"]) for m in models]
    
    text = f"🔍 Found {len(models)} model(s):\n\nSelect one:"
    await message.bot.edit_message_text(
        text,
        chat_id=screen_chat_id,
        message_id=screen_message_id,
        reply_markup=models_keyboard("account", model_list),
        parse_mode="HTML",
    )
    
    memory_state.update(
        message.from_user.id,
        step="select_model",
        search_results=models,
    )


async def _show_current_month(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
) -> None:
    """Show current month accounting records."""
    accounting_service = AccountingService(config)
    records = await accounting_service.get_current_month_records()
    
    now = datetime.now(config.timezone)
    month_str = now.strftime("%B")
    
    if not records:
        text = f"💰 <b>{month_str} Accounting</b>\n\nNo records yet."
    else:
        text = f"💰 <b>{month_str} Accounting</b>\n\n"
        for record in records[:10]:  # Limit to 10
            name = record.get("model_name", "Unknown")
            amount = record.get("amount", 0)
            percent = record.get("percent", 0.0)
            text += f"• <b>{html.escape(name)}</b>\n"
            text += f"  Files: {amount} ({format_percent(percent)})\n\n"
    
    await query.message.edit_text(
        text,
        reply_markup=accounting_menu_keyboard(),
        parse_mode="HTML",
    )
    
    memory_state.clear(query.from_user.id)


async def _start_add_files(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Start add files flow."""
    recent = recent_models.get(query.from_user.id)
    
    memory_state.set(
        query.from_user.id,
        {
            "flow": "accounting",
            "step": "select_model",
            "screen_chat_id": query.message.chat.id,
            "screen_message_id": query.message.message_id,
        },
    )
    
    text = "💰 <b>Add Files</b>\n\nSelect model:"
    await query.message.edit_text(
        text,
        reply_markup=recent_models_keyboard(recent, "account"),
        parse_mode="HTML",
    )


async def _select_model(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
    model_id: str,
) -> None:
    """Model selected for adding files."""
    models_service = ModelsService(config)
    model = await models_service.get_model_by_id(model_id)
    
    if not model:
        await query.answer("Model not found", show_alert=True)
        return
    
    model_name = model.get("name", "Unknown")
    recent_models.add(query.from_user.id, model_id, model_name)
    
    # Get current record
    accounting_service = AccountingService(config)
    record = await accounting_service.get_record_by_model(model_id)
    
    now = datetime.now(config.timezone)
    month_str = now.strftime("%B")
    
    current_amount = record["amount"] if record else 0
    current_percent = record["percent"] if record else 0.0
    
    text = f"💰 <b>{html.escape(model_name)} · {month_str}</b>\n\n"
    text += f"Current: {current_amount} ({format_percent(current_percent)})\n\n"
    text += "Add files (quick select):"
    
    # Create dummy page_id for quick files keyboard
    # We'll store model info in memory state
    memory_state.update(
        query.from_user.id,
        step="add_files",
        model_id=model_id,
        model_name=model_name,
        current_amount=current_amount,
    )
    
    # Use model_id as page_id placeholder in keyboard
    await query.message.edit_text(
        text,
        reply_markup=accounting_quick_files_keyboard(model_id, current_amount),
        parse_mode="HTML",
    )


async def _add_files_to_record(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    page_id: str,  # Actually model_id in this case
    count: int,
) -> None:
    """Add files to accounting record."""
    if not is_editor(query.from_user.id, config):
        await query.answer("Only editors can add files", show_alert=True)
        return
    
    data = memory_state.get(query.from_user.id) or {}
    model_id = data.get("model_id") or page_id
    model_name = data.get("model_name", "Unknown")
    
    accounting_service = AccountingService(config)
    result = await accounting_service.add_files(
        model_id=model_id,
        model_name=model_name,
        files_to_add=count,
    )
    
    now = datetime.now(config.timezone)
    month_str = now.strftime("%B")
    
    text = f"✅ <b>Files added!</b>\n\n"
    text += f"<b>{html.escape(model_name)} · {month_str}</b>\n"
    text += f"Total: {result['amount']} ({format_percent(result['percent'])})\n"
    text += f"Added: +{count}"
    
    await query.message.edit_text(
        text,
        reply_markup=accounting_menu_keyboard(),
        parse_mode="HTML",
    )
    
    memory_state.clear(query.from_user.id)


async def _show_record_details(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    record_id: str,
) -> None:
    """Show accounting record details."""
    # This would require fetching record by ID
    # For now, just go back to menu
    await query.message.edit_text(
        "💰 <b>Accounting</b>\n\nRecord details coming soon...",
        reply_markup=accounting_menu_keyboard(),
        parse_mode="HTML",
    )


async def _edit_content(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    record_id: str,
) -> None:
    """Edit content for record."""
    await query.answer("Content editing coming soon", show_alert=True)


async def _edit_comment(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    record_id: str,
) -> None:
    """Edit comment for record."""
    await query.answer("Comment editing coming soon", show_alert=True)


async def _handle_back(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    value: str,
) -> None:
    """Handle back button."""
    if value == "main":
        await query.message.delete()
        memory_state.clear(query.from_user.id)
    elif value == "back":
        # Generic back from back_keyboard - return to menu
        await query.message.edit_text(
            "💰 <b>Accounting</b>\n\nSelect an action:",
            reply_markup=accounting_menu_keyboard(),
            parse_mode="HTML",
        )
        memory_state.clear(query.from_user.id)
    else:
        await query.message.edit_text(
            "💰 <b>Accounting</b>\n\nSelect an action:",
            reply_markup=accounting_menu_keyboard(),
            parse_mode="HTML",
        )
        memory_state.clear(query.from_user.id)


async def _cancel_flow(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Cancel current flow."""
    await query.message.edit_text(
        "💰 <b>Accounting</b>\n\nCancelled.",
        reply_markup=accounting_menu_keyboard(),
        parse_mode="HTML",
    )
    memory_state.clear(query.from_user.id)


async def _process_custom_files(
    message: Message,
    config: Config,
    memory_state: MemoryState,
) -> None:
    """Process custom file count input."""
    try:
        count = int(message.text.strip())
        if count < 1 or count > 1000:
            raise ValueError("Invalid count")
    except ValueError:
        data = memory_state.get(message.from_user.id) or {}
        screen_chat_id = data.get("screen_chat_id")
        screen_message_id = data.get("screen_message_id")
        
        await message.bot.edit_message_text(
            "Invalid number. Please enter a number between 1 and 1000:",
            chat_id=screen_chat_id,
            message_id=screen_message_id,
            parse_mode="HTML",
        )
        return
    
    # Add files with custom count
    data = memory_state.get(message.from_user.id) or {}
    model_id = data.get("model_id")
    
    if not model_id:
        return
    
    # Call add files function
    # (implementation omitted for brevity)


async def _process_comment(
    message: Message,
    config: Config,
    memory_state: MemoryState,
) -> None:
    """Process comment input."""
    comment_text = message.text.strip()
    
    data = memory_state.get(message.from_user.id) or {}
    record_id = data.get("record_id")
    
    if not record_id:
        return
    
    accounting_service = AccountingService(config)
    await accounting_service.update_comment(record_id, comment_text)
    
    # Show success
    screen_chat_id = data.get("screen_chat_id")
    screen_message_id = data.get("screen_message_id")
    
    await message.bot.edit_message_text(
        "✅ Comment updated!",
        chat_id=screen_chat_id,
        message_id=screen_message_id,
        reply_markup=accounting_menu_keyboard(),
        parse_mode="HTML",
    )

    memory_state.clear(message.from_user.id)


# ==================== NLP Handlers ====================

async def handle_add_files_nlp(
    message: Message,
    model: dict,
    entities: Any,
    config: Config,
    notion: Any,
    recent_models: RecentModels,
) -> None:
    """
    Handle adding files from NLP message.

    Args:
        message: Telegram message
        model: {"id": str, "name": str, "aliases": list}
        entities: Extracted entities with numbers
        config: Config
        notion: NotionClient
        recent_models: RecentModels
    """
    from app.services import NotionClient

    if not is_editor(message.from_user.id, config):
        await message.answer("❌ У вас нет прав на добавление файлов.")
        return

    # Extract count from entities
    if not entities.numbers:
        await message.answer("❌ Укажите количество файлов. Пример: 'мелиса 30 файлов'")
        return

    count = entities.numbers[0]

    # Validate count
    if count < 1 or count > 1000:
        await message.answer("❌ Количество должно быть положительным (1-1000)")
        return

    model_id = model["id"]
    model_name = model["name"]

    # Get current month name
    now = datetime.now(tz=config.timezone)
    month_str = now.strftime("%B %Y")  # e.g., "February 2026"

    # Get or create accounting record for current month
    try:
        # Query for existing record
        record = await notion.get_accounting_record(
            config.db_accounting, model_id, month_str
        )

        if not record:
            # Create new record
            LOGGER.info(
                "Creating new accounting record for model %s, month %s",
                model_id,
                month_str,
            )
            await notion.create_accounting_record(
                config.db_accounting, model_id, count, month_str, config.files_per_month
            )
            new_amount = count
        else:
            # Update existing record
            LOGGER.info(
                "Updating existing accounting record %s, adding %d files",
                record.page_id,
                count,
            )
            current_amount = record.amount or 0
            new_amount = current_amount + count
            new_percent = new_amount / float(config.files_per_month)

            await notion.update_accounting_files(
                record.page_id, new_amount, new_percent
            )

        # Calculate percentage
        percent = new_amount / float(config.files_per_month)

        # Show success message
        await message.answer(
            f"✅ Добавлено {count} файлов!\n\n"
            f"<b>{html.escape(model_name)}</b> | {month_str}\n"
            f"Файлов: {new_amount} ({int(percent * 100)}%)",
            parse_mode="HTML",
        )

        # Add to recent models
        recent_models.add(message.from_user.id, model_id, model_name)

    except Exception as e:
        LOGGER.exception("Failed to add files: %s", e)
        await message.answer("❌ Ошибка при добавлении файлов. Попробуйте позже.")
