"""
Intent classification v2 using centralized filter database.

Priority-based classification:
100: SHOOT domain ("съемка"/"шут"/"заплан")
 90: FILES domain ("файлы"/"фото"/"сняла" + число)
 80: ORDERS with type ("кастом"/"шорт"/"колл"/"ад реквест")
 70: ORDERS general ("запрос"/"новый заказ")
 60: ORDERS close ("закрыт"/"готов")
 55: COMMENT ("коммент:")
 50: MODEL actions ("покажи"/"заказы" + модель)
 40: MENU ("сводка"/"планировщик" без модели)
 35: FILES_STATS ("файлы" без числа)
 30: AMBIGUOUS (модель + число, нет маркера)
  0: UNKNOWN (fallback menu)
"""

import logging
from typing import Optional

from app.router.command_filters import (
    CommandIntent,
    get_sorted_filters,
    normalize_text,
    match_keywords,
    match_patterns,
    match_multi_word_phrases,
    match_exclude_keywords,
    contains_number,
)


LOGGER = logging.getLogger(__name__)


def classify_intent_v2(
    text: str,
    has_model: bool = False,
    has_numbers: bool = False,
) -> CommandIntent:
    """
    Classify user intent using priority-based filter matching.

    Args:
        text: Raw user message text
        has_model: Whether a model name was detected
        has_numbers: Whether numbers were detected

    Returns:
        CommandIntent enum value
    """
    if not text or not text.strip():
        return CommandIntent.UNKNOWN

    text_normalized = normalize_text(text)
    sorted_filters = get_sorted_filters()

    matched_intent: Optional[CommandIntent] = None

    for cmd_filter in sorted_filters:
        # Check exclusions first
        if match_exclude_keywords(text_normalized, cmd_filter.exclude_with):
            continue

        # Check multi-word phrases (highest confidence)
        if cmd_filter.multi_word_phrases:
            if match_multi_word_phrases(text_normalized, cmd_filter.multi_word_phrases):
                if cmd_filter.requires_number and not contains_number(text):
                    continue
                matched_intent = cmd_filter.intent
                break

        # Check patterns (regex)
        if cmd_filter.patterns:
            if match_patterns(text_normalized, cmd_filter.patterns):
                if cmd_filter.requires_number and not contains_number(text):
                    continue
                matched_intent = cmd_filter.intent
                break

        # Check keywords
        if cmd_filter.keywords:
            if match_keywords(text_normalized, cmd_filter.keywords):
                if cmd_filter.requires_number and not contains_number(text):
                    continue
                matched_intent = cmd_filter.intent
                break

    if matched_intent:
        LOGGER.info(
            "Classified intent: %s (text=%r, has_model=%s, has_numbers=%s)",
            matched_intent.value, text[:50], has_model, has_numbers,
        )

        # Disambiguation between SHOW_MODEL_ORDERS (50) and SHOW_ORDERS (40)
        if matched_intent == CommandIntent.SHOW_ORDERS and has_model:
            matched_intent = CommandIntent.SHOW_MODEL_ORDERS

        # Downgrade SHOW_MODEL_ORDERS to SHOW_ORDERS when no model detected
        # Prevents "заказы" (without model) from requiring a model name
        if matched_intent == CommandIntent.SHOW_MODEL_ORDERS and not has_model:
            matched_intent = CommandIntent.SHOW_ORDERS

        return matched_intent

    # No filter matched — check for AMBIGUOUS
    # "модель + число, нет маркера"
    if has_model and has_numbers:
        LOGGER.info(
            "Classified intent: AMBIGUOUS (model + number, no marker) text=%r",
            text[:50],
        )
        return CommandIntent.AMBIGUOUS

    # If there's a model but no command markers → SEARCH_MODEL
    if has_model:
        LOGGER.info("Classified intent: SEARCH_MODEL (has_model, no markers) text=%r", text[:50])
        return CommandIntent.SEARCH_MODEL

    LOGGER.info("Classified intent: UNKNOWN text=%r", text[:50])
    return CommandIntent.UNKNOWN


def get_intent_description(intent: CommandIntent) -> str:
    """Get human-readable description of intent."""
    descriptions = {
        CommandIntent.SHOOT_CREATE: "Создание съемки",
        CommandIntent.SHOOT_DONE: "Завершение съемки",
        CommandIntent.SHOOT_RESCHEDULE: "Перенос съемки",
        CommandIntent.ADD_FILES: "Добавление файлов",
        CommandIntent.CREATE_ORDERS: "Создание заказа (с типом)",
        CommandIntent.CREATE_ORDERS_GENERAL: "Создание заказа (общий)",
        CommandIntent.CLOSE_ORDERS: "Закрытие заказа",
        CommandIntent.ADD_COMMENT: "Добавление комментария",
        CommandIntent.GET_REPORT: "Просмотр отчета",
        CommandIntent.SHOW_MODEL_ORDERS: "Заказы модели",
        CommandIntent.SHOW_SUMMARY: "Сводка",
        CommandIntent.SHOW_ORDERS: "Меню заказов",
        CommandIntent.SHOW_PLANNER: "Планировщик",
        CommandIntent.SHOW_ACCOUNT: "Аккаунтинг",
        CommandIntent.FILES_STATS: "Статистика файлов",
        CommandIntent.AMBIGUOUS: "Неоднозначный запрос",
        CommandIntent.SEARCH_MODEL: "Поиск модели",
        CommandIntent.UNKNOWN: "Неизвестная команда",
    }
    return descriptions.get(intent, "Неизвестно")


def get_intent_priority(intent: CommandIntent) -> int:
    """Get priority level for intent."""
    priorities = {
        CommandIntent.SHOOT_CREATE: 100,
        CommandIntent.SHOOT_DONE: 102,
        CommandIntent.SHOOT_RESCHEDULE: 101,
        CommandIntent.ADD_FILES: 90,
        CommandIntent.CREATE_ORDERS: 80,
        CommandIntent.CREATE_ORDERS_GENERAL: 70,
        CommandIntent.CLOSE_ORDERS: 60,
        CommandIntent.ADD_COMMENT: 55,
        CommandIntent.GET_REPORT: 50,
        CommandIntent.SHOW_MODEL_ORDERS: 50,
        CommandIntent.SHOW_SUMMARY: 40,
        CommandIntent.SHOW_ORDERS: 40,
        CommandIntent.SHOW_PLANNER: 40,
        CommandIntent.SHOW_ACCOUNT: 40,
        CommandIntent.FILES_STATS: 35,
        CommandIntent.AMBIGUOUS: 30,
        CommandIntent.SEARCH_MODEL: 0,
        CommandIntent.UNKNOWN: 0,
    }
    return priorities.get(intent, 0)
