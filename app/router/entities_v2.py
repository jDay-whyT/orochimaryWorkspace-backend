"""
Improved entity extraction using centralized command filters.

This version provides:
- Better model name detection
- Order type extraction with synonym support
- Number extraction
- Date parsing (future)
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional, List

from app.router.command_filters import (
    ORDER_TYPE_MAP,
    IGNORE_KEYWORDS,
    normalize_text,
    extract_numbers,
)


LOGGER = logging.getLogger(__name__)


@dataclass
class EntitiesV2:
    """
    Extracted entities from user message.

    Attributes:
        model_name: Model name (first non-keyword, non-number word)
        numbers: All numbers found in text
        order_type: Order type ("custom", "short", "call", "ad request")
        date: Date (for future date parsing)
        raw_text: Original message text
    """
    model_name: Optional[str] = None
    numbers: List[int] = None
    order_type: Optional[str] = None
    date: Optional[date] = None
    raw_text: str = ""

    def __post_init__(self):
        if self.numbers is None:
            self.numbers = []

    @property
    def has_model(self) -> bool:
        """Check if model name was extracted."""
        return bool(self.model_name)

    @property
    def has_numbers(self) -> bool:
        """Check if any numbers were extracted."""
        return bool(self.numbers)

    @property
    def first_number(self) -> Optional[int]:
        """Get first number (most commonly the quantity)."""
        return self.numbers[0] if self.numbers else None

    def __repr__(self) -> str:
        return (
            f"EntitiesV2("
            f"model={self.model_name!r}, "
            f"numbers={self.numbers}, "
            f"order_type={self.order_type!r})"
        )


def extract_entities_v2(text: str) -> EntitiesV2:
    """
    Extract entities from user message using improved logic.

    Extraction process:
    1. Extract all numbers
    2. Extract order type from ORDER_TYPE_MAP
    3. Extract model name (first word not in IGNORE_KEYWORDS)
    4. Future: extract dates

    Args:
        text: User message text

    Returns:
        EntitiesV2: Extracted entities

    Examples:
        >>> extract_entities_v2("три кастома мелиса")
        EntitiesV2(model='мелиса', numbers=[3], order_type='custom')

        >>> extract_entities_v2("мелиса 30 файлов")
        EntitiesV2(model='мелиса', numbers=[30], order_type=None)

        >>> extract_entities_v2("ad request софи 2 штуки")
        EntitiesV2(model='софи', numbers=[2], order_type='ad request')
    """
    if not text or not text.strip():
        return EntitiesV2(raw_text=text)

    text_normalized = normalize_text(text)
    words = text_normalized.split()

    entities = EntitiesV2(raw_text=text)

    # Step 1: Extract numbers
    entities.numbers = extract_numbers(text)
    LOGGER.debug("Extracted numbers: %s", entities.numbers)

    # Step 2: Extract order type
    # Check for multi-word "ad request" first
    if "ad request" in text_normalized or "ад реквест" in text_normalized:
        entities.order_type = "ad request"
        LOGGER.debug("Extracted order type: 'ad request' (multi-word)")
    else:
        # Check single words
        for word in words:
            if word in ORDER_TYPE_MAP:
                entities.order_type = ORDER_TYPE_MAP[word]
                LOGGER.debug("Extracted order type: %r from word %r", entities.order_type, word)
                break

    # Step 3: Extract model name
    # First word that is NOT:
    # - a number
    # - an ignore keyword
    # - part of "ad request" phrase
    skip_next = False
    for i, word in enumerate(words):
        # Skip if this word should be skipped
        if skip_next:
            skip_next = False
            continue

        # Skip numbers
        if re.match(r'^\d+$', word):
            continue

        # Skip "ad" or "ад" if followed by "request"/"реквест"
        if word in ("ad", "ад") and i + 1 < len(words):
            next_word = words[i + 1]
            if next_word in ("request", "реквест"):
                skip_next = True  # Skip "request"/"реквест" too
                continue

        # Skip ignore keywords
        if word in IGNORE_KEYWORDS:
            continue

        # This is likely the model name
        entities.model_name = word
        LOGGER.debug("Extracted model name: %r", entities.model_name)
        break

    # Step 4: Future - date extraction
    # TODO: Add date parsing logic here
    # entities.date = extract_date(text)

    LOGGER.info(
        "Extracted entities from text=%r: %s",
        text, entities
    )

    return entities


def extract_model_names(text: str, max_count: int = 3) -> List[str]:
    """
    Extract multiple potential model names from text.

    Useful when user mentions multiple models in one message.

    Args:
        text: User message text
        max_count: Maximum number of model names to extract

    Returns:
        List[str]: List of potential model names

    Examples:
        >>> extract_model_names("мелиса и софи")
        ['мелиса', 'софи']

        >>> extract_model_names("кастом для мелиса софи анна")
        ['мелиса', 'софи', 'анна']
    """
    if not text or not text.strip():
        return []

    text_normalized = normalize_text(text)
    words = text_normalized.split()

    model_names = []
    skip_next = False

    for i, word in enumerate(words):
        if len(model_names) >= max_count:
            break

        # Skip if this word should be skipped
        if skip_next:
            skip_next = False
            continue

        # Skip numbers
        if re.match(r'^\d+$', word):
            continue

        # Skip "ad" or "ад" if followed by "request"/"реквест"
        if word in ("ad", "ад") and i + 1 < len(words):
            next_word = words[i + 1]
            if next_word in ("request", "реквест"):
                skip_next = True
                continue

        # Skip ignore keywords
        if word in IGNORE_KEYWORDS:
            continue

        # Skip conjunctions
        if word in ("и", "or", "and", ","):
            continue

        # This is likely a model name
        model_names.append(word)

    LOGGER.debug(
        "Extracted %d model names from text=%r: %s",
        len(model_names), text, model_names
    )

    return model_names


def validate_model_name(model_name: Optional[str]) -> bool:
    """
    Validate if extracted model name looks reasonable.

    Args:
        model_name: Extracted model name

    Returns:
        bool: True if valid, False otherwise
    """
    if not model_name:
        return False

    # Must be at least 2 characters
    if len(model_name) < 2:
        return False

    # Must contain at least one letter
    if not re.search(r'[a-zа-я]', model_name, re.IGNORECASE):
        return False

    # Must not be a number
    if re.match(r'^\d+$', model_name):
        return False

    # Must not be an ignore keyword
    if model_name.lower() in IGNORE_KEYWORDS:
        return False

    return True


def get_order_type_display_name(order_type: Optional[str]) -> str:
    """
    Get display name for order type.

    Args:
        order_type: Order type code

    Returns:
        str: Display name in Russian
    """
    display_names = {
        "custom": "Кастом",
        "short": "Шорт",
        "call": "Колл",
        "ad request": "Ad Request",
    }
    return display_names.get(order_type, "Неизвестный тип")
