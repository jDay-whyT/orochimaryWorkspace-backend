import logging
from datetime import date
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.filters import FlowFilter
from app.filters.topic_access import TopicAccessCallbackFilter, TopicAccessMessageFilter
from app.keyboards import (
    orders_menu_keyboard,
    orders_list_keyboard,
    order_action_keyboard,
    order_types_keyboard,
    order_qty_keyboard,
    order_date_keyboard,
    order_comment_keyboard,
    order_confirm_keyboard,
    order_success_keyboard,
    recent_models_keyboard,
    models_keyboard,
    back_cancel_keyboard,
)
from app.roles import is_authorized, can_edit
from app.services import NotionClient, NotionOrder
from app.services import orders as orders_cache
from app.state import MemoryState, RecentModels
from app.utils import (
    format_date_short,
    days_open,
    today,
    resolve_relative_date,
    escape_html,
    ORDER_TYPES,
    PAGE_SIZE,
    safe_edit_message,
)

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())
router.callback_query.filter(TopicAccessCallbackFilter())

# Tracks (chat_id, user_id) pairs currently executing order creation.
# Prevents duplicate Notion pages when Telegram retries the callback while the
# first Notion API call is still in-flight. asyncio is single-threaded so the
# membership check and add are effectively atomic.
_co_in_progress: set[tuple[int, int]] = set()


def _state_ids_from_message(message: Message) -> tuple[int, int]:
    return message.chat.id, message.from_user.id


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id


# ==================== Menu ====================

async def show_orders_menu(message: Message, config: Config) -> None:
    """Show orders section menu."""
    await message.answer(
        "📦 <b>Orders</b>\n\n"
        "Select an action:",
        reply_markup=orders_menu_keyboard(),
        parse_mode="HTML",
    )


# ==================== Callback Handlers ====================

@router.callback_query(F.data.startswith("orders|"))
async def handle_orders_callback(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Main orders callback handler."""
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return
    
    parts = query.data.split("|", 2)
    if len(parts) < 3:
        await query.answer()
        return
    
    _, action, value = parts
    user_id = query.from_user.id
    
    try:
        # Menu navigation
        if action == "back":
            await handle_back(query, value, memory_state, config, notion, recent_models)
        
        elif action == "cancel":
            await handle_cancel(query, memory_state)
        
        # Search/Model selection
        elif action == "search":
            await start_model_search(query, memory_state)
        
        elif action == "model":
            await handle_model_select(query, value, memory_state, config, notion, recent_models)

        elif action == "select_model":
            await handle_model_select(query, value, memory_state, config, notion, recent_models)

        # Open orders list
        elif action == "open":
            await show_open_orders_list(query, memory_state, config, notion)
        
        elif action == "select":
            await show_order_details(query, value, memory_state, config, notion)
        
        elif action == "page":
            await handle_pagination(query, value, memory_state, config, notion)
        
        # Close order
        elif action == "close_today":
            await close_order(query, value, "today", memory_state, config, notion)
        
        elif action == "close_yesterday":
            await close_order(query, value, "yesterday", memory_state, config, notion)
        
        # Comment
        elif action == "comment":
            await start_comment_input(query, value, memory_state)
        
        # New order flow
        elif action == "new":
            await start_new_order(query, memory_state, config, recent_models)
        
        elif action == "type":
            await handle_type_select(query, value, memory_state)
        
        elif action == "qty":
            await handle_qty_select(query, value, memory_state)
        
        elif action == "date":
            await handle_date_select(query, value, memory_state, config)
        
        elif action == "comment_skip":
            await handle_comment_skip(query, memory_state, config)
        
        elif action == "comment_add":
            await start_order_comment_input(query, memory_state)
        
        elif action == "confirm":
            await create_order(query, memory_state, config, notion, recent_models)
        
        else:
            await query.answer()
    
    except Exception as e:
        LOGGER.exception("Error in orders callback: %s", e)
        await query.answer("Error occurred. Please try again.", show_alert=True)


# ==================== Back/Cancel ====================

async def handle_back(
    query: CallbackQuery,
    value: str,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    recent_models: RecentModels,
) -> None:
    """Handle back navigation."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    flow = data.get("flow")
    
    if value == "main":
        memory_state.clear(chat_id, user_id)
        await safe_edit_message(
            query,
            "📦 <b>Orders</b>\n\nSelect an action:",
            reply_markup=orders_menu_keyboard(),
        )

    elif value == "back":
        # Generic back from back_cancel_keyboard - return to menu
        memory_state.clear(chat_id, user_id)
        await safe_edit_message(
            query,
            "📦 <b>Orders</b>\n\nSelect an action:",
            reply_markup=orders_menu_keyboard(),
        )

    elif value == "menu":
        memory_state.clear(chat_id, user_id)
        await safe_edit_message(
            query,
            "📦 <b>Orders</b>\n\nSelect an action:",
            reply_markup=orders_menu_keyboard(),
        )
    
    elif value == "model_select":
        # Back to model selection
        recent = recent_models.get(user_id)
        if recent:
            await safe_edit_message(
                query,
                "Select model:",
                reply_markup=recent_models_keyboard(recent, "orders"),
            )
        else:
            memory_state.update(chat_id, user_id, flow="search", step="waiting_query")
            await safe_edit_message(
                query,
                "🔍 Enter model name to search:",
                reply_markup=back_cancel_keyboard("orders"),
            )
    
    elif value == "list":
        # Back to orders list
        await show_open_orders_list(query, memory_state, config, notion)
    
    elif value == "model":
        # Back to model selection in new order flow
        recent = recent_models.get(user_id)
        memory_state.update(chat_id, user_id, step="select_model")
        if recent:
            await safe_edit_message(
                query,
                "➕ <b>New Order</b>\n\nSelect model:",
                reply_markup=recent_models_keyboard(recent, "orders"),
            )
        else:
            memory_state.update(chat_id, user_id, step="waiting_query")
            await safe_edit_message(
                query,
                "➕ <b>New Order</b>\n\n🔍 Enter model name:",
                reply_markup=back_cancel_keyboard("orders"),
            )
    
    elif value == "type":
        # Back to type selection
        memory_state.update(chat_id, user_id, step="select_type")
        model_title = data.get("model_title", "")
        await safe_edit_message(
            query,
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n\n"
            f"Select order type:",
            reply_markup=order_types_keyboard(),
        )

    elif value == "qty":
        # Back to quantity selection
        memory_state.update(chat_id, user_id, step="select_qty")
        model_title = data.get("model_title", "")
        order_type = data.get("order_type", "")
        await safe_edit_message(
            query,
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b>\n\n"
            f"Select quantity:",
            reply_markup=order_qty_keyboard(),
        )

    elif value == "date":
        # Back to date selection
        memory_state.update(chat_id, user_id, step="select_date")
        model_title = data.get("model_title", "")
        order_type = data.get("order_type", "")
        qty = data.get("qty", 1)
        await safe_edit_message(
            query,
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b> × {qty}\n\n"
            f"Select date:",
            reply_markup=order_date_keyboard(),
        )

    elif value == "comment":
        # Back to comment prompt
        memory_state.update(chat_id, user_id, step="comment_prompt")
        model_title = data.get("model_title", "")
        order_type = data.get("order_type", "")
        qty = data.get("qty", 1)
        in_date = data.get("in_date")
        await safe_edit_message(
            query,
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b> × {qty}\n"
            f"Date: <b>{format_date_short(in_date)}</b>\n\n"
            f"Add comment?",
            reply_markup=order_comment_keyboard(),
        )
    
    await query.answer()


async def handle_cancel(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Handle cancel action."""
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.clear(chat_id, user_id)
    await safe_edit_message(
        query,
        "📦 <b>Orders</b>\n\nCancelled.",
        reply_markup=orders_menu_keyboard(),
    )
    await query.answer()


# ==================== Model Search ====================

async def start_model_search(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Start model search flow."""
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.update(
        chat_id,
        user_id,
        flow="search",
        step="waiting_query",
    )
    await safe_edit_message(
        query,
        "🔍 Enter model name to search:",
        reply_markup=back_cancel_keyboard("orders"),
    )
    await query.answer()


async def handle_model_select(
    query: CallbackQuery,
    model_id: str,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    recent_models: RecentModels,
) -> None:
    """Handle model selection."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    flow = data.get("flow")
    
    # Get model info
    model_options = data.get("model_options", {})
    model_title = model_options.get(model_id)
    
    if not model_title:
        # Try to fetch from Notion
        model = await notion.get_model(model_id)
        if model:
            model_title = model.title
        else:
            await query.answer("Model not found", show_alert=True)
            return
    
    # Add to recent
    recent_models.add(user_id, model_id, model_title)
    
    if flow == "new_order":
        # Continue with new order flow
        memory_state.update(
            chat_id,
            user_id,
            model_id=model_id,
            model_title=model_title,
            step="select_type",
        )
        await safe_edit_message(
            query,
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n\n"
            f"Select order type:",
            reply_markup=order_types_keyboard(),
        )
    else:
        # Show open orders for model
        memory_state.update(
            chat_id,
            user_id,
            flow="view",
            model_id=model_id,
            model_title=model_title,
            page=1,
        )
        await _show_orders_for_model(query, memory_state, config, notion)
    
    await query.answer()


# ==================== Open Orders List ====================

async def show_open_orders_list(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show list of all open orders."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    
    model_id = data.get("model_id")
    
    if not model_id:
        # Need to select model first
        from app.state import RecentModels
        # This is a simplified path - normally we'd inject recent_models
        memory_state.update(chat_id, user_id, flow="view", step="select_model")
        await safe_edit_message(
            query,
            "📋 <b>Open Orders</b>\n\n"
            "🔍 Enter model name to search:",
            reply_markup=back_cancel_keyboard("orders"),
        )
        await query.answer()
        return
    
    await _show_orders_for_model(query, memory_state, config, notion)
    await query.answer()


async def _show_orders_for_model(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    """Internal: show orders for selected model."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    
    model_id = data.get("model_id")
    model_title = data.get("model_title", "")
    page = data.get("page", 1)
    
    # Fetch orders
    orders = await orders_cache.get_cached_orders(notion, config, model_id)
    
    # Sort by in_date
    orders.sort(key=lambda o: o.in_date or "9999-99-99")
    
    # Store in state
    memory_state.update(chat_id, user_id, orders=[_order_to_dict(o) for o in orders])
    
    if not orders:
        await safe_edit_message(
            query,
            f"📋 <b>Open Orders: {escape_html(model_title)}</b>\n\n"
            f"✅ No open orders!",
            reply_markup=orders_menu_keyboard(),
        )
        return
    
    # Pagination
    total_pages = (len(orders) + PAGE_SIZE - 1) // PAGE_SIZE
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    page_orders = orders[start:start + PAGE_SIZE]
    
    memory_state.update(chat_id, user_id, page=page)
    
    # Build list
    today_date = today(config.timezone)
    orders_data = []
    for order in page_orders:
        days = days_open(order.in_date, today_date)
        days_str = f" · {days}d" if days is not None else ""
        label = f"{order.order_type or 'order'} · {format_date_short(order.in_date)}{days_str}"
        orders_data.append({
            "page_id": order.page_id,
            "label": label,
        })
    
    await safe_edit_message(
        query,
        f"📋 <b>Open Orders: {escape_html(model_title)}</b>\n\n"
        f"Total: {len(orders)} (page {page}/{total_pages})",
        reply_markup=orders_list_keyboard(orders_data, page, total_pages),
    )


async def handle_pagination(
    query: CallbackQuery,
    value: str,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    """Handle pagination."""
    try:
        page = int(value)
    except ValueError:
        await query.answer()
        return
    
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.update(chat_id, user_id, page=page)
    await _show_orders_for_model(query, memory_state, config, notion)
    await query.answer()


# ==================== Order Details ====================

async def show_order_details(
    query: CallbackQuery,
    page_id: str,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    """Show details for a specific order."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    
    model_title = data.get("model_title", "")
    orders = data.get("orders", [])
    
    # Find order in cached list
    order = None
    for o in orders:
        if o.get("page_id") == page_id:
            order = o
            break
    
    if not order:
        await query.answer("Order not found", show_alert=True)
        return
    
    memory_state.update(chat_id, user_id, selected_order=page_id)
    
    today_date = today(config.timezone)
    in_date = order.get("in_date")
    days = days_open(in_date, today_date)
    days_str = f"\nDays open: {days}" if days is not None else ""
    
    order_type = order.get("order_type", "order")
    comments = order.get("comments", "")
    comments_str = f"\n💬 {escape_html(comments)}" if comments else ""

    await safe_edit_message(
        query,
        f"📦 <b>{escape_html(order_type)}</b> · {escape_html(model_title)}\n"
        f"In: {format_date_short(in_date)}{days_str}{comments_str}",
        reply_markup=order_action_keyboard(page_id),
    )
    await query.answer()


# ==================== Close Order ====================

async def close_order(
    query: CallbackQuery,
    page_id: str,
    when: str,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    """Close an order."""
    if not can_edit(query.from_user.id, config):
        await query.answer("You don't have permission to close orders", show_alert=True)
        return
    
    out_date = resolve_relative_date(when, config.timezone)
    if not out_date:
        await query.answer("Invalid date", show_alert=True)
        return
    
    try:
        await notion.close_order(page_id, out_date)
    except Exception as e:
        LOGGER.exception("Failed to close order: %s", e)
        await query.answer("Failed to close order", show_alert=True)
        return
    
    # Get order info for message
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    orders = data.get("orders", [])
    order = next((o for o in orders if o.get("page_id") == page_id), None)
    model_id_for_cache = order.get("model_id") if order else data.get("model_id")
    if model_id_for_cache:
        orders_cache.clear_cache(model_id_for_cache)

    in_date = order.get("in_date") if order else None
    if in_date:
        days = (out_date - date.fromisoformat(in_date)).days + 1
        message = f"✅ Order closed in {days} days!"
    else:
        message = "✅ Order closed!"
    
    await query.answer(message, show_alert=True)
    
    # Refresh list
    await _show_orders_for_model(query, memory_state, config, notion)


# ==================== Comment ====================

async def start_comment_input(
    query: CallbackQuery,
    page_id: str,
    memory_state: MemoryState,
) -> None:
    """Start comment input for existing order."""
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.update(
        chat_id,
        user_id,
        flow="comment",
        selected_order=page_id,
        step="waiting_comment",
    )
    await safe_edit_message(
        query,
        "💬 Enter comment for this order:",
        reply_markup=back_cancel_keyboard("orders"),
    )
    await query.answer()


# ==================== New Order Flow ====================

async def start_new_order(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    recent_models: RecentModels,
) -> None:
    """Start new order creation flow."""
    if not can_edit(query.from_user.id, config):
        await query.answer("You don't have permission to create orders", show_alert=True)
        return
    
    chat_id, user_id = _state_ids_from_query(query)
    recent = recent_models.get(user_id)
    
    memory_state.update(
        chat_id,
        user_id,
        flow="new_order",
        step="select_model",
    )
    
    if recent:
        await safe_edit_message(
            query,
            "➕ <b>New Order</b>\n\n"
            "⭐ Recent models:",
            reply_markup=recent_models_keyboard(recent, "orders"),
        )
    else:
        memory_state.update(chat_id, user_id, step="waiting_query")
        await safe_edit_message(
            query,
            "➕ <b>New Order</b>\n\n"
            "🔍 Enter model name to search:",
            reply_markup=back_cancel_keyboard("orders"),
        )
    
    await query.answer()


async def handle_type_select(
    query: CallbackQuery,
    order_type: str,
    memory_state: MemoryState,
) -> None:
    """Handle order type selection."""
    if order_type not in ORDER_TYPES:
        await query.answer("Invalid type", show_alert=True)
        return
    
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    model_title = data.get("model_title", "")
    
    memory_state.update(
        chat_id,
        user_id,
        order_type=order_type,
        step="select_qty",
        qty=1,
    )

    await safe_edit_message(
        query,
        f"➕ <b>New Order</b>\n\n"
        f"Model: <b>{escape_html(model_title)}</b>\n"
        f"Type: <b>{escape_html(order_type)}</b>\n\n"
        f"Select quantity:",
        reply_markup=order_qty_keyboard(),
    )
    await query.answer()


async def handle_qty_select(
    query: CallbackQuery,
    value: str,
    memory_state: MemoryState,
) -> None:
    """Handle quantity selection."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    model_title = data.get("model_title", "")
    order_type = data.get("order_type", "")
    
    if value == "custom":
        memory_state.update(chat_id, user_id, step="waiting_qty")
        await safe_edit_message(
            query,
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b>\n\n"
            f"Enter quantity (1-99):",
            reply_markup=back_cancel_keyboard("orders"),
        )
        await query.answer()
        return
    
    try:
        qty = int(value)
        if qty < 1 or qty > 99:
            raise ValueError()
    except ValueError:
        await query.answer("Invalid quantity", show_alert=True)
        return
    
    memory_state.update(
        chat_id,
        user_id,
        qty=qty,
        step="select_date",
    )

    await safe_edit_message(
        query,
        f"➕ <b>New Order</b>\n\n"
        f"Model: <b>{escape_html(model_title)}</b>\n"
        f"Type: <b>{escape_html(order_type)}</b> × {qty}\n\n"
        f"Select date:",
        reply_markup=order_date_keyboard(),
    )
    await query.answer()


async def handle_date_select(
    query: CallbackQuery,
    value: str,
    memory_state: MemoryState,
    config: Config,
) -> None:
    """Handle date selection."""
    in_date = resolve_relative_date(value, config.timezone)
    if not in_date:
        await query.answer("Invalid date", show_alert=True)
        return
    
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    model_title = data.get("model_title", "")
    order_type = data.get("order_type", "")
    qty = data.get("qty", 1)
    
    memory_state.update(
        chat_id,
        user_id,
        in_date=in_date.isoformat(),
        step="comment_prompt",
    )

    await safe_edit_message(
        query,
        f"➕ <b>New Order</b>\n\n"
        f"Model: <b>{escape_html(model_title)}</b>\n"
        f"Type: <b>{escape_html(order_type)}</b> × {qty}\n"
        f"Date: <b>{format_date_short(in_date)}</b>\n\n"
        f"Add comment?",
        reply_markup=order_comment_keyboard(),
    )
    await query.answer()


async def handle_comment_skip(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
) -> None:
    """Skip comment and show confirmation."""
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.update(chat_id, user_id, comments=None, step="confirm")
    await _show_confirmation(query, memory_state, config)
    await query.answer()


async def start_order_comment_input(
    query: CallbackQuery,
    memory_state: MemoryState,
) -> None:
    """Start comment input for new order."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    model_title = data.get("model_title", "")
    order_type = data.get("order_type", "")
    qty = data.get("qty", 1)
    in_date = data.get("in_date")
    
    memory_state.update(chat_id, user_id, step="waiting_comment")

    await safe_edit_message(
        query,
        f"➕ <b>New Order</b>\n\n"
        f"Model: <b>{escape_html(model_title)}</b>\n"
        f"Type: <b>{escape_html(order_type)}</b> × {qty}\n"
        f"Date: <b>{format_date_short(in_date)}</b>\n\n"
        f"💬 Enter comment:",
        reply_markup=back_cancel_keyboard("orders"),
    )
    await query.answer()


async def _show_confirmation(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
) -> None:
    """Show order confirmation screen."""
    chat_id, user_id = _state_ids_from_query(query)
    data = memory_state.get(chat_id, user_id) or {}
    
    model_title = data.get("model_title", "")
    order_type = data.get("order_type", "")
    qty = data.get("qty", 1)
    in_date = data.get("in_date")
    comments = data.get("comments")
    
    comments_str = f"\n💬 {escape_html(comments)}" if comments else ""

    await safe_edit_message(
        query,
        f"➕ <b>Confirm Order</b>\n\n"
        f"Model: <b>{escape_html(model_title)}</b>\n"
        f"Type: <b>{escape_html(order_type)}</b> × {qty}\n"
        f"Date: <b>{format_date_short(in_date)}</b>{comments_str}\n\n"
        f"Create order?",
        reply_markup=order_confirm_keyboard(),
    )


async def create_order(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    recent_models: RecentModels,
) -> None:
    """Create the order in Notion."""
    if not can_edit(query.from_user.id, config):
        await query.answer("You don't have permission to create orders", show_alert=True)
        return

    chat_id, user_id = _state_ids_from_query(query)

    # Guard against concurrent duplicate callbacks (double-click / Telegram
    # retry while the Notion API call is still in-flight).
    # asyncio is single-threaded so the membership check and add are atomic —
    # no other coroutine can interleave between these two lines.
    _co_key = (chat_id, user_id)
    if _co_key in _co_in_progress:
        await query.answer()
        return
    _co_in_progress.add(_co_key)
    try:
        data = memory_state.get(chat_id, user_id) or {}

        model_id = data.get("model_id")
        model_title = data.get("model_title", "")
        order_type = data.get("order_type")
        qty = data.get("qty", 1)
        in_date_str = data.get("in_date")
        comments = data.get("comments")

        if not all([model_id, order_type, in_date_str]):
            await query.answer("Missing data. Please start over.", show_alert=True)
            memory_state.clear(chat_id, user_id)
            return

        in_date = date.fromisoformat(in_date_str)

        try:
            # Create order(s)
            if order_type in ("short", "ad request"):
                title = f"{order_type} × {qty} — {in_date_str}"
                await notion.create_order(
                    config.db_orders,
                    model_id,
                    order_type,
                    in_date,
                    count=qty,
                    title=title,
                    comments=comments,
                )
            else:
                for i in range(1, qty + 1):
                    title = f"{order_type} {i}/{qty} — {in_date_str}"
                    await notion.create_order(
                        config.db_orders,
                        model_id,
                        order_type,
                        in_date,
                        count=1,
                        title=title,
                        comments=comments,
                    )
        except Exception as e:
            LOGGER.exception("Failed to create order: %s", e)
            await query.answer("Failed to create order", show_alert=True)
            return

        orders_cache.clear_cache(model_id)
        memory_state.clear(chat_id, user_id)

        await safe_edit_message(
            query,
            f"✅ <b>Order Created!</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b> × {qty}\n"
            f"Date: <b>{format_date_short(in_date)}</b>",
            reply_markup=order_success_keyboard(),
        )
        await query.answer("Order created!")
    finally:
        _co_in_progress.discard(_co_key)


# ==================== Text Input Handler ====================

@router.message(FlowFilter({"search", "new_order", "view", "comment"}), F.text)
async def handle_text_input(
    message: Message,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle text input for search and comments."""
    if not is_authorized(message.from_user.id, config):
        return

    chat_id, user_id = _state_ids_from_message(message)
    data = memory_state.get(chat_id, user_id) or {}

    flow = data.get("flow")
    step = data.get("step")

    text = message.text.strip()
    
    # Delete user message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass
    
    # Model search
    if step == "waiting_query":
        if not text:
            return

        try:
            models = await notion.query_models(config.db_models, text)
        except Exception as e:
            LOGGER.exception("Failed to search models (DB: %s): %s", config.db_models, e)
            # Show error to user instead of silently failing
            await message.answer(
                "❌ <b>Error searching models</b>\n\n"
                "Database connection failed. Please contact admin.\n\n"
                f"<code>Error: {escape_html(str(e))[:100]}</code>",
                reply_markup=back_cancel_keyboard(flow or "orders"),
                parse_mode="HTML",
            )
            return

        if not models:
            # Send new message with error
            await message.answer(
                "No models found. Try another search:",
                reply_markup=back_cancel_keyboard(flow or "orders"),
                parse_mode="HTML",
            )
            return
        
        model_options = {m.page_id: m.title for m in models}
        memory_state.update(
            chat_id,
            user_id,
            model_options=model_options,
            step="select_model",
        )
        
        # Send results as new message
        await message.answer(
            f"🔍 Search results for '<b>{escape_html(text)}</b>':",
            reply_markup=models_keyboard(
                "orders",
                [(m.page_id, m.title) for m in models],
            ),
            parse_mode="HTML",
        )
    
    # Custom quantity
    elif step == "waiting_qty":
        try:
            qty = int(text)
            if qty < 1 or qty > 99:
                raise ValueError()
        except ValueError:
            await message.answer(
                "Please enter a number between 1 and 99:",
                reply_markup=back_cancel_keyboard("orders"),
                parse_mode="HTML",
            )
            return
        
        model_title = data.get("model_title", "")
        order_type = data.get("order_type", "")
        
        memory_state.update(
            chat_id,
            user_id,
            qty=qty,
            step="select_date",
        )
        
        await message.answer(
            f"➕ <b>New Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b> × {qty}\n\n"
            f"Select date:",
            reply_markup=order_date_keyboard(),
            parse_mode="HTML",
        )
    
    # Comment input for new order
    elif step == "waiting_comment" and flow == "new_order":
        memory_state.update(
            chat_id,
            user_id,
            comments=text if text else None,
            step="confirm",
        )
        
        data = memory_state.get(chat_id, user_id) or {}
        model_title = data.get("model_title", "")
        order_type = data.get("order_type", "")
        qty = data.get("qty", 1)
        in_date = data.get("in_date")
        
        comments_str = f"\n💬 {escape_html(text)}" if text else ""
        
        await message.answer(
            f"➕ <b>Confirm Order</b>\n\n"
            f"Model: <b>{escape_html(model_title)}</b>\n"
            f"Type: <b>{escape_html(order_type)}</b> × {qty}\n"
            f"Date: <b>{format_date_short(in_date)}</b>{comments_str}\n\n"
            f"Create order?",
            reply_markup=order_confirm_keyboard(),
            parse_mode="HTML",
        )
    
    # Comment input for existing order
    elif step == "waiting_comment" and flow == "comment":
        page_id = data.get("selected_order")
        if not page_id:
            return
        
        try:
            await notion.update_order_comment(page_id, text)
            model_id_for_cache = data.get("model_id")
            if model_id_for_cache:
                orders_cache.clear_cache(model_id_for_cache)
        except Exception as e:
            LOGGER.exception("Failed to update comment: %s", e)
            await message.answer("Failed to save comment", parse_mode="HTML")
            return
        
        memory_state.update(chat_id, user_id, flow="view", step=None)
        
        await message.answer(
            "💬 Comment saved!",
            reply_markup=orders_menu_keyboard(),
            parse_mode="HTML",
        )


# ==================== Helpers ====================

def _order_to_dict(order: NotionOrder) -> dict:
    """Convert NotionOrder to dict for state storage."""
    return {
        "page_id": order.page_id,
        "title": order.title,
        "model_id": order.model_id,
        "order_type": order.order_type,
        "in_date": order.in_date,
        "out_date": order.out_date,
        "status": order.status,
        "count": order.count,
        "comments": order.comments,
    }


# ==================== NLP Handlers ====================

async def handle_create_orders_nlp(
    message: Message,
    model: dict,
    entities: Any,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState | None = None,
) -> None:
    """
    Handle order creation from NLP message.

    Args:
        message: Telegram message
        model: {"id": str, "name": str, "aliases": list}
        entities: Extracted entities with numbers, order_type
        config: Config
        notion: NotionClient
        memory_state: MemoryState for storing flow context
    """
    from app.keyboards.inline import nlp_order_date_keyboard
    from app.router.entities_v2 import get_order_type_display_name

    if not can_edit(message.from_user.id, config):
        await message.answer("❌ У вас нет прав на создание заказов.")
        return

    # Extract count from entities
    count = entities.numbers[0] if entities.numbers else 1

    # Validate count
    if count < 1 or count > 200:
        await message.answer("❌ Количество должно быть положительным (1-200)")
        return

    # Get order type (default to "custom" if not specified)
    order_type = entities.order_type or "custom"
    type_label = get_order_type_display_name(order_type)

    # Store flow context in memory for callback handlers
    if memory_state:
        memory_state.set(message.chat.id, message.from_user.id, {
            "flow": "nlp_order",
            "step": "awaiting_date",
            "model_id": model["id"],
            "model_name": model["name"],
            "order_type": order_type,
            "count": count,
        })

    # Show date selection with short-callback keyboard
    sent = await message.answer(
        f"📦 <b>{escape_html(model['name'])}</b> · {count}x {type_label}\n"
        f"Дата: <b>{format_date_short(today(config.timezone))}</b> (можно изменить)\n",
        reply_markup=nlp_order_date_keyboard(model["id"]),
        parse_mode="HTML",
    )
    if memory_state and sent:
        memory_state.update(message.chat.id, message.from_user.id, screen_message_id=sent.message_id)



# NOTE: All nlp: callbacks (order_type, order_qty, order_confirm, order_date, cancel)
# are handled by nlp_callbacks.router which is registered after this router.
# Do NOT add nlp: callback handlers here — they would intercept callbacks
# before nlp_callbacks.py can process them.
