"""Intent-based message router for the bot."""

import logging
from typing import Callable, Optional, Any

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import StateFilter

from app.config import Config
from app.roles import is_authorized
from app.services import NotionClient
from app.state import MemoryState, RecentModels
from app.router.extractor import extract, ExtractedData
from app.utils import safe_edit_message

LOGGER = logging.getLogger(__name__)

# Router registry for different model handlers
_HANDLERS = {}


def _register_default_handlers() -> None:
    """Register default handlers for all models."""
    from app.handlers.intent_handlers import (
        handle_orders_intent,
        handle_planner_intent,
        handle_accounting_intent,
        handle_summary_intent,
    )

    _HANDLERS["orders"] = handle_orders_intent
    _HANDLERS["planner"] = handle_planner_intent
    _HANDLERS["accounting"] = handle_accounting_intent
    _HANDLERS["summary"] = handle_summary_intent


def register_model_handler(model: str, handler_fn: Callable) -> None:
    """Register a handler function for a model."""
    _HANDLERS[model] = handler_fn


async def route_message(
    message: Message,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Main entry point for all text messages. Routes based on intent."""
    user_id = message.from_user.id

    # Authorization check
    if not is_authorized(user_id, config):
        await message.answer(
            "⛔ Access denied.\n\n"
            "You are not authorized to use this bot."
        )
        LOGGER.warning("Unauthorized message from user %s: %s", user_id, message.text)
        return

    # Check if user is already in a flow (being handled by existing handlers)
    data = memory_state.get(user_id) or {}
    flow = data.get("flow")
    if flow:
        # User is already in a flow, let existing handlers handle it
        LOGGER.debug("User %s is in flow '%s', skipping intent routing", user_id, flow)
        return

    # Extract intent and parameters
    extracted = extract(message.text)

    if not extracted:
        # No recognized intent
        await message.answer(
            "❓ Sorry, I didn't understand that.\n\n"
            "Try: 'new order', 'show orders', 'planner list', etc."
        )
        return

    LOGGER.info(
        "User %s: intent=%s, model=%s, action=%s, confidence=%.2f, query='%s'",
        user_id,
        extracted.intent,
        extracted.model,
        extracted.action,
        extracted.confidence,
        extracted.query,
    )

    # Delete user's message to keep chat clean
    try:
        await message.delete()
    except Exception as e:
        LOGGER.warning("Could not delete message %s: %s", message.message_id, e)

    # Route to appropriate handler based on model
    handler = _HANDLERS.get(extracted.model)

    if handler:
        try:
            await handler(
                message=message,
                extracted=extracted,
                config=config,
                notion=notion,
                memory_state=memory_state,
                recent_models=recent_models,
            )
        except Exception as e:
            LOGGER.exception("Error handling intent %s: %s", extracted.intent, e)
            await message.answer(f"❌ Error: {str(e)}")
    else:
        # No handler registered for this model
        await message.answer(
            f"⚠️ No handler available for {extracted.model}."
        )
        LOGGER.warning("No handler registered for model: %s", extracted.model)


def create_intent_router() -> Router:
    """Create and configure the intent-based message router."""
    # Register default handlers if not already registered
    if not _HANDLERS:
        _register_default_handlers()

    router = Router()

    # Main message handler - catches all text messages
    @router.message(F.text)
    async def handle_text_message(
        message: Message,
        config: Config,
        notion: NotionClient,
        memory_state: MemoryState,
        recent_models: RecentModels,
    ) -> None:
        await route_message(message, config, notion, memory_state, recent_models)

    return router
