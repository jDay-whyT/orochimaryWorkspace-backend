"""
Improved intent classification using centralized command filters.

This version provides:
- Better synonym support
- Word form matching (declensions)
- Multi-word phrase detection
- Priority-based classification
- Exclude rules for disambiguation
"""

import logging
from typing import Optional

from app.router.command_filters import (
    CommandIntent,
    CommandFilter,
    get_sorted_filters,
    normalize_text,
    contains_number,
    match_multi_word_phrases,
    match_keywords,
    match_patterns,
    match_exclude_keywords,
)


LOGGER = logging.getLogger(__name__)


def classify_intent_v2(text: str) -> CommandIntent:
    """
    Classify user intent from message text using improved filter system.

    Process:
    1. Normalize text
    2. Iterate through filters sorted by priority
    3. Check multi-word phrases first
    4. Check keywords and patterns
    5. Apply exclude rules
    6. Check number requirement if needed
    7. Return first match or fallback to SEARCH_MODEL/UNKNOWN

    Args:
        text: User message text

    Returns:
        CommandIntent: Detected intent

    Examples:
        >>> classify_intent_v2("три кастома мелиса")
        CommandIntent.CREATE_ORDERS

        >>> classify_intent_v2("мелиса 30 файлов")
        CommandIntent.ADD_FILES

        >>> classify_intent_v2("репорт мелиса")
        CommandIntent.GET_REPORT

        >>> classify_intent_v2("сводка")
        CommandIntent.SHOW_SUMMARY

        >>> classify_intent_v2("заказы")
        CommandIntent.SHOW_ORDERS

        >>> classify_intent_v2("мелиса")
        CommandIntent.SEARCH_MODEL
    """
    if not text or not text.strip():
        return CommandIntent.UNKNOWN

    text_normalized = normalize_text(text)
    words = text_normalized.split()
    has_number = contains_number(text)

    LOGGER.debug(
        "Classifying intent for text=%r (normalized=%r, words=%d, has_number=%s)",
        text, text_normalized, len(words), has_number
    )

    # Iterate through filters sorted by priority (highest first)
    for cmd_filter in get_sorted_filters():
        matched = False

        # Step 1: Check multi-word phrases FIRST (highest specificity)
        if cmd_filter.multi_word_phrases:
            if match_multi_word_phrases(text, cmd_filter.multi_word_phrases):
                matched = True
                LOGGER.debug(
                    "Matched multi-word phrase for intent=%s",
                    cmd_filter.intent.value
                )

        # Step 2: Check keywords
        if not matched and cmd_filter.keywords:
            if match_keywords(text, cmd_filter.keywords):
                matched = True
                LOGGER.debug(
                    "Matched keyword for intent=%s",
                    cmd_filter.intent.value
                )

        # Step 3: Check regex patterns
        if not matched and cmd_filter.patterns:
            if match_patterns(text, cmd_filter.patterns):
                matched = True
                LOGGER.debug(
                    "Matched pattern for intent=%s",
                    cmd_filter.intent.value
                )

        # Step 4: Apply exclude rules (disambiguation)
        if matched and cmd_filter.exclude_with:
            if match_exclude_keywords(text, cmd_filter.exclude_with):
                LOGGER.debug(
                    "Excluded intent=%s due to exclude keywords",
                    cmd_filter.intent.value
                )
                matched = False

        # Step 5: Check number requirement
        if matched and cmd_filter.requires_number:
            if not has_number:
                LOGGER.debug(
                    "Excluded intent=%s due to missing number",
                    cmd_filter.intent.value
                )
                matched = False

        # If matched all conditions, return this intent
        if matched:
            LOGGER.info(
                "Classified intent=%s for text=%r",
                cmd_filter.intent.value, text
            )
            return cmd_filter.intent

    # No filter matched - check if it's a simple model search
    # Model search: 1-2 words, no numbers, no command keywords
    if len(words) <= 2 and not has_number:
        LOGGER.info("Classified as SEARCH_MODEL for text=%r", text)
        return CommandIntent.SEARCH_MODEL

    # Fallback to unknown
    LOGGER.info("Classified as UNKNOWN for text=%r", text)
    return CommandIntent.UNKNOWN


def get_intent_description(intent: CommandIntent) -> str:
    """
    Get human-readable description of intent.

    Args:
        intent: Command intent

    Returns:
        str: Description in Russian
    """
    descriptions = {
        CommandIntent.CREATE_ORDERS: "Создание заказов",
        CommandIntent.ADD_FILES: "Добавление файлов",
        CommandIntent.GET_REPORT: "Получение отчета",
        CommandIntent.SHOW_SUMMARY: "Показ сводки",
        CommandIntent.SHOW_ORDERS: "Показ заказов",
        CommandIntent.SHOW_PLANNER: "Открытие планировщика",
        CommandIntent.SHOW_ACCOUNT: "Открытие аккаунта",
        CommandIntent.SEARCH_MODEL: "Поиск модели",
        CommandIntent.UNKNOWN: "Неизвестная команда",
    }
    return descriptions.get(intent, "Неизвестная команда")


def get_intent_examples(intent: CommandIntent) -> list[str]:
    """
    Get example messages for an intent.

    Args:
        intent: Command intent

    Returns:
        list[str]: List of example messages
    """
    examples = {
        CommandIntent.CREATE_ORDERS: [
            "три кастома мелиса",
            "5 шортов для мелисы",
            "колл мелиса",
            "ad request мелиса 2 штуки",
        ],
        CommandIntent.ADD_FILES: [
            "мелиса 30 файлов",
            "добавь 50 фото для мелисы",
            "мелиса 100 файлов",
        ],
        CommandIntent.GET_REPORT: [
            "репорт мелиса",
            "статистика мелиса",
            "отчет для мелисы",
        ],
        CommandIntent.SHOW_SUMMARY: [
            "сводка",
            "покажи сводку",
            "summary",
        ],
        CommandIntent.SHOW_ORDERS: [
            "заказы",
            "покажи заказы",
            "orders",
        ],
        CommandIntent.SHOW_PLANNER: [
            "планировщик",
            "открой план",
            "planner",
        ],
        CommandIntent.SHOW_ACCOUNT: [
            "аккаунт",
            "бухгалтерия",
            "accounting",
        ],
        CommandIntent.SEARCH_MODEL: [
            "мелиса",
            "найди софи",
        ],
    }
    return examples.get(intent, [])
