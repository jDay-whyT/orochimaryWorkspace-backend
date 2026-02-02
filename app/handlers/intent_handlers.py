"""Intent-based handler adapters for different models."""

import logging
from typing import Optional

from aiogram.types import Message

from app.config import Config
from app.roles import is_authorized
from app.services import NotionClient
from app.state import MemoryState, RecentModels
from app.router.extractor import ExtractedData
from app.keyboards import (
    orders_menu_keyboard,
    planner_menu_keyboard,
    accounting_menu_keyboard,
    recent_models_keyboard,
    back_cancel_keyboard,
)
from app.utils import safe_edit_message

LOGGER = logging.getLogger(__name__)


async def handle_orders_intent(
    message: Message,
    extracted: ExtractedData,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle orders-related intents."""
    user_id = message.from_user.id
    intent = extracted.intent
    action = extracted.action
    query = extracted.query

    # Import handlers
    from app.handlers.orders import (
        show_orders_menu,
        start_new_order,
        show_open_orders_list,
        start_model_search,
    )

    if intent == "orders_new":
        # Create new order
        await message.answer(
            "📦 <b>New Order</b>\n\n"
            "Select a model:",
            reply_markup=orders_menu_keyboard(),
            parse_mode="HTML",
        )
        # Initialize state for new order flow
        memory_state.set(user_id, {
            "flow": "orders",
            "step": "model_select",
            "action": "new_order",
        })

    elif intent == "orders_list":
        # Show open orders
        await show_open_orders_list(
            message=message,
            config=config,
            notion=notion,
            memory_state=memory_state,
        )

    elif intent == "orders_search":
        # Search for orders
        if query:
            # Direct search with provided query
            memory_state.set(user_id, {
                "flow": "orders",
                "step": "search_results",
                "query": query,
            })
            await message.answer(
                f"🔍 Searching for: {query}",
                reply_markup=back_cancel_keyboard("orders"),
            )
        else:
            # Ask for search query
            memory_state.set(user_id, {
                "flow": "orders",
                "step": "waiting_query",
                "action": "search",
            })
            await message.answer(
                "🔍 Enter model name to search:",
                reply_markup=back_cancel_keyboard("orders"),
            )

    elif intent == "orders_view":
        # View orders - same as list
        await show_open_orders_list(
            message=message,
            config=config,
            notion=notion,
            memory_state=memory_state,
        )

    else:
        # Default: show menu
        await show_orders_menu(message, config)


async def handle_planner_intent(
    message: Message,
    extracted: ExtractedData,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle planner-related intents."""
    user_id = message.from_user.id
    intent = extracted.intent
    action = extracted.action
    query = extracted.query
    dates = extracted.dates

    # Import handlers
    from app.handlers.planner import show_planner_menu

    if intent == "planner_new":
        # Create new planner item
        await message.answer(
            "📅 <b>New Plan</b>\n\n"
            "Select a model:",
            reply_markup=planner_menu_keyboard(),
            parse_mode="HTML",
        )
        memory_state.set(user_id, {
            "flow": "planner",
            "step": "model_select",
            "action": "new_planner",
            "suggested_date": dates[0]["date"] if dates else None,
        })

    elif intent == "planner_list":
        # Show planner items
        await message.answer(
            "📅 <b>Planner</b>\n\n"
            "Loading planner items...",
            reply_markup=planner_menu_keyboard(),
            parse_mode="HTML",
        )
        memory_state.set(user_id, {
            "flow": "planner",
            "step": "list",
        })

    elif intent == "planner_search":
        # Search planner
        if query:
            memory_state.set(user_id, {
                "flow": "planner",
                "step": "search_results",
                "query": query,
            })
            await message.answer(
                f"🔍 Searching in planner: {query}",
                reply_markup=back_cancel_keyboard("planner"),
            )
        else:
            memory_state.set(user_id, {
                "flow": "planner",
                "step": "waiting_query",
            })
            await message.answer(
                "🔍 Enter search text:",
                reply_markup=back_cancel_keyboard("planner"),
            )

    else:
        # Show menu
        await show_planner_menu(message, config)


async def handle_accounting_intent(
    message: Message,
    extracted: ExtractedData,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle accounting-related intents."""
    user_id = message.from_user.id
    intent = extracted.intent
    action = extracted.action
    query = extracted.query
    numbers = extracted.numbers

    # Import handlers
    from app.handlers.accounting import show_accounting_menu

    if intent == "accounting_new":
        # Create new record
        await message.answer(
            "💰 <b>New Record</b>\n\n"
            "Select a model:",
            reply_markup=accounting_menu_keyboard(),
            parse_mode="HTML",
        )
        memory_state.set(user_id, {
            "flow": "accounting",
            "step": "model_select",
            "action": "new_accounting",
            "suggested_amount": numbers[0] if numbers else None,
        })

    elif intent == "accounting_list":
        # Show accounting records
        await message.answer(
            "💰 <b>Accounting</b>\n\n"
            "Loading records...",
            reply_markup=accounting_menu_keyboard(),
            parse_mode="HTML",
        )
        memory_state.set(user_id, {
            "flow": "accounting",
            "step": "list",
        })

    elif intent == "accounting_search":
        # Search accounting
        if query:
            memory_state.set(user_id, {
                "flow": "accounting",
                "step": "search_results",
                "query": query,
            })
            await message.answer(
                f"🔍 Searching: {query}",
                reply_markup=back_cancel_keyboard("accounting"),
            )
        else:
            memory_state.set(user_id, {
                "flow": "accounting",
                "step": "waiting_query",
            })
            await message.answer(
                "🔍 Enter search text:",
                reply_markup=back_cancel_keyboard("accounting"),
            )

    else:
        # Show menu
        await show_accounting_menu(message, config)


async def handle_summary_intent(
    message: Message,
    extracted: ExtractedData,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle summary intent."""
    # Import handlers
    from app.handlers.summary import show_summary_menu

    await show_summary_menu(message, config, recent_models)
