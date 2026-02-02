"""Main routing dispatcher for NLP messages."""

import logging
from aiogram.types import Message

from app.config import Config
from app.services import NotionClient
from app.state import MemoryState, RecentModels
from app.router.intent import Intent, classify_intent
from app.router.entities import extract_entities


LOGGER = logging.getLogger(__name__)


async def route_message(
    message: Message,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """
    Route user message to appropriate handler based on intent.

    Flow:
    1. Classify intent
    2. Extract entities
    3. Search for model (if model_name exists)
    4. Route to handler based on intent
    """
    text = message.text.strip()

    # 1. Classify intent
    intent = classify_intent(text)
    LOGGER.info("Classified intent: %s for text: %s", intent.value, text)

    # 2. Extract entities
    entities = extract_entities(text)
    LOGGER.info(
        "Extracted entities - model: %s, numbers: %s, type: %s",
        entities.model_name,
        entities.numbers,
        entities.order_type,
    )

    # 3. Search for model (if needed)
    model = None
    if entities.model_name:
        from app.handlers.models import search_model_by_name_or_alias

        models = await search_model_by_name_or_alias(
            entities.model_name, config.db_models, notion
        )

        if len(models) == 0:
            await message.answer(
                f"❌ Модель '{entities.model_name}' не найдена. Проверьте имя."
            )
            return

        if len(models) > 1:
            # Show model selection keyboard
            from app.keyboards.inline import nlp_model_selection_keyboard

            await message.answer(
                f"🔍 Найдено несколько моделей '{entities.model_name}':\n\nВыберите нужную:",
                reply_markup=nlp_model_selection_keyboard(models, intent.value, entities),
            )
            return

        # Found exactly 1 model
        model = models[0]
        # Add to recent
        recent_models.add(message.from_user.id, model["id"], model["name"])
    else:
        # Check if intent requires model
        if intent not in (
            Intent.UNKNOWN,
            Intent.SHOW_SUMMARY,
            Intent.SHOW_ORDERS,
            Intent.SHOW_PLANNER,
            Intent.SHOW_ACCOUNT,
        ):
            await message.answer("❌ Не указано имя модели.")
            return

    # 4. Route to handler
    if intent == Intent.SHOW_SUMMARY:
        from app.handlers.summary import show_summary_menu

        await show_summary_menu(message, config, recent_models)

    elif intent == Intent.SHOW_ORDERS:
        from app.handlers.orders import show_orders_menu

        await show_orders_menu(message, config)

    elif intent == Intent.SHOW_PLANNER:
        from app.handlers.planner import show_planner_menu

        await show_planner_menu(message, config)

    elif intent == Intent.SHOW_ACCOUNT:
        from app.handlers.accounting import show_accounting_menu

        await show_accounting_menu(message, config)

    elif intent == Intent.CREATE_ORDERS:
        from app.handlers.orders import handle_create_orders_nlp

        await handle_create_orders_nlp(message, model, entities, config, notion)

    elif intent == Intent.ADD_FILES:
        from app.handlers.accounting import handle_add_files_nlp

        await handle_add_files_nlp(message, model, entities, config, notion, recent_models)

    elif intent == Intent.GET_REPORT:
        from app.handlers.reports import handle_report_nlp

        await handle_report_nlp(message, model, config, notion)

    elif intent == Intent.SEARCH_MODEL:
        # Simple model search
        if not entities.model_name:
            await _show_help_message(message)
            return

        await message.answer(
            f"✅ Найдена модель: <b>{model['name']}</b>\n\n"
            f"Что вы хотите сделать?\n\n"
            f"Примеры:\n"
            f"• три кастома {model['name']}\n"
            f"• {model['name']} 30 файлов\n"
            f"• репорт {model['name']}",
            parse_mode="HTML",
        )

    elif intent == Intent.UNKNOWN:
        await _show_help_message(message)


async def _show_help_message(message: Message) -> None:
    """Show help message when intent is unknown."""
    await message.answer(
        "🤔 Не понял запрос. Примеры:\n"
        "• три кастома мелиса\n"
        "• мелиса 30 файлов\n"
        "• репорт мелиса\n\n"
        "Или используй /start для помощи."
    )
