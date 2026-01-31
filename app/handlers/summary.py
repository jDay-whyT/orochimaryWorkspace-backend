"""Summary handlers - Phase 5"""
import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.keyboards.inline import (
    summary_menu_keyboard,
    summary_card_keyboard,
    models_keyboard,
    back_keyboard,
)
from app.roles import is_authorized
from app.services import NotionClient, ModelsService, OrdersService, AccountingService
from app.state import MemoryState, RecentModels
from app.utils.formatting import format_percent

LOGGER = logging.getLogger(__name__)
router = Router()


async def show_summary_menu(message: Message, config: Config, recent_models: RecentModels = None) -> None:
    """Show summary section menu."""
    if recent_models is None:
        recent_models = RecentModels()
    
    recent = recent_models.get(message.from_user.id)
    
    if recent:
        text = "📊 <b>Summary</b>\n\n⭐ Recent:\n\nSelect a model:"
        keyboard = summary_menu_keyboard(recent)
    else:
        text = "📊 <b>Summary</b>\n\nSearch for a model:"
        keyboard = back_keyboard("summary")
    
    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("summary|"))
async def handle_summary_callback(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle summary callbacks."""
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return
    
    parts = query.data.split("|")
    if len(parts) < 3:
        await query.answer()
        return
    
    action = parts[1]
    value = parts[2] if len(parts) > 2 else None
    user_id = query.from_user.id
    
    try:
        if action == "back":
            await _handle_back(query, config, memory_state, recent_models, value)
        elif action == "search":
            await _start_search(query, memory_state)
        elif action == "model":
            await _show_model_summary(query, config, memory_state, recent_models, value)
        elif action == "select_model":
            await _show_model_summary(query, config, memory_state, recent_models, value)
        elif action == "debts":
            await _show_debts(query, config, memory_state, value)
        elif action == "orders":
            await _show_all_orders(query, config, memory_state, value)
        elif action == "files":
            await _quick_add_files(query, config, memory_state, recent_models, value)
        elif action == "cancel":
            await _cancel_flow(query, memory_state)
        else:
            await query.answer("Unknown action", show_alert=True)
        
        await query.answer()
    
    except Exception as e:
        LOGGER.exception("Error in summary callback")
        await query.answer(f"Error: {str(e)}", show_alert=True)


@router.message(F.text)
async def handle_text_input(
    message: Message,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle text input for summary search."""
    if not is_authorized(message.from_user.id, config):
        return
    
    data = memory_state.get(message.from_user.id)
    if not data or data.get("flow") != "summary":
        return
    
    step = data.get("step")
    
    try:
        if step == "search_model":
            await _process_model_search(message, config, memory_state, recent_models)
        
        # Delete user message
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        LOGGER.exception("Error processing text input")
        await message.answer(f"Error: {str(e)}")


async def _handle_back(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
    value: str,
) -> None:
    """Handle back button."""
    if value == "main":
        memory_state.clear(query.from_user.id)
        await query.message.delete()
    elif value == "menu":
        recent = recent_models.get(query.from_user.id)
        text = "📊 <b>Summary</b>\n\n⭐ Recent:\n\nSelect a model:"
        await query.message.edit_text(
            text,
            reply_markup=summary_menu_keyboard(recent),
            parse_mode="HTML",
        )
        memory_state.clear(query.from_user.id)


async def _start_search(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Start model search flow."""
    memory_state.set(
        query.from_user.id,
        {
            "flow": "summary",
            "step": "search_model",
            "screen_chat_id": query.message.chat.id,
            "screen_message_id": query.message.message_id,
        },
    )
    
    text = "🔍 Send model name to search:"
    await query.message.edit_text(
        text,
        reply_markup=back_keyboard("summary"),
        parse_mode="HTML",
    )


async def _process_model_search(
    message: Message,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
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
            reply_markup=back_keyboard("summary"),
            parse_mode="HTML",
        )
        return

    if not models:
        text = f"🔍 No models found for: {html.escape(query_text)}\n\nTry again:"
        await message.bot.edit_message_text(
            text,
            chat_id=screen_chat_id,
            message_id=screen_message_id,
            reply_markup=back_keyboard("summary"),
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
        reply_markup=models_keyboard("summary", model_list),
        parse_mode="HTML",
    )
    
    memory_state.update(
        message.from_user.id,
        step="select_model",
        search_results=models,
    )


async def _show_model_summary(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
    model_id: str,
) -> None:
    """Show model summary card with stats."""
    user_id = query.from_user.id
    
    # Get model info
    models_service = ModelsService(config)
    model = await models_service.get_model_by_id(model_id)
    
    if not model:
        await query.answer("Model not found", show_alert=True)
        return
    
    model_name = model.get("name", "Unknown")
    project = model.get("project", "—")
    status = model.get("status", "—")
    winrate = model.get("winrate", "—")
    
    # Add to recent
    recent_models.add(user_id, model_id, model_name)
    
    # Get current month stats
    now = datetime.now(config.timezone)
    month_str = now.strftime("%B")
    
    # Get accounting record
    accounting_service = AccountingService(config)
    record = await accounting_service.get_record_by_model(model_id)
    
    files_amount = record["amount"] if record else 0
    files_percent = record["percent"] if record else 0.0
    
    # Get orders stats
    orders_service = OrdersService(config)
    open_orders = await orders_service.get_open_orders(model_id)
    open_count = len(open_orders)
    
    # Count debts (orders without completion)
    # For simplicity, debts = open orders
    debts_count = open_count
    
    # Build summary text
    text = f"📊 <b>{html.escape(model_name)}</b>\n"
    text += f"{html.escape(project)} · {status} · {winrate}\n\n"
    text += f"📅 {month_str}:\n"
    text += f"Files: {files_amount} ({format_percent(files_percent)})\n"
    text += f"Orders: {open_count} open\n"
    
    if debts_count > 0:
        text += f"Debts: {debts_count} orders\n"
    
    await query.message.edit_text(
        text,
        reply_markup=summary_card_keyboard(model_id),
        parse_mode="HTML",
    )
    
    memory_state.update(
        user_id,
        selected_model_id=model_id,
        selected_model_name=model_name,
    )


async def _show_debts(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    model_id: str,
) -> None:
    """Show debt orders (open orders)."""
    orders_service = OrdersService(config)
    open_orders = await orders_service.get_open_orders(model_id)
    
    if not open_orders:
        text = "📦 <b>Debts</b>\n\nNo open orders ✅"
    else:
        text = f"📦 <b>Debts</b>\n\n{len(open_orders)} open orders:\n\n"
        for order in open_orders[:10]:
            order_type = order.get("type", "order")
            in_date = order.get("in_date", "")
            text += f"• {order_type} · {in_date}\n"
    
    await query.message.edit_text(
        text,
        reply_markup=summary_card_keyboard(model_id),
        parse_mode="HTML",
    )


async def _show_all_orders(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    model_id: str,
) -> None:
    """Redirect to orders section for this model."""
    await query.answer("Opening orders section...", show_alert=True)
    # Could implement redirect to orders handler here


async def _quick_add_files(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
    model_id: str,
) -> None:
    """Quick add files action from summary."""
    await query.answer("Opening accounting to add files...", show_alert=True)
    # Could implement redirect to accounting handler here


async def _cancel_flow(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Cancel current flow."""
    await query.message.edit_text(
        "📊 <b>Summary</b>\n\nCancelled.",
        parse_mode="HTML",
    )
    memory_state.clear(query.from_user.id)
