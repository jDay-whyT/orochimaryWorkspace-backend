"""
Model-name entity extraction using centralized command filters.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, List

from app.router.command_filters import IGNORE_KEYWORDS, normalize_text
from app.router.prefilter import STOP_WORDS


LOGGER = logging.getLogger(__name__)


@dataclass
class EntitiesV2:
    """
    Extracted entities from user message.

    Attributes:
        model_name: Model name (first non-keyword, non-number word)
        raw_text: Original message text
    """
    model_name: Optional[str] = None
    raw_text: str = ""

    @property
    def has_model(self) -> bool:
        """Check if model name was extracted."""
        return bool(self.model_name)

    def __repr__(self) -> str:
        return f"EntitiesV2(model={self.model_name!r})"


def extract_entities_v2(text: str) -> EntitiesV2:
    """
    Extract model name from user message (first word not in IGNORE_KEYWORDS).

    Supports multi-word names like "ке паса", "мона лиза".
    """
    if not text or not text.strip():
        return EntitiesV2(raw_text=text)

    text_normalized = normalize_text(text)
    words = text_normalized.split()

    entities = EntitiesV2(raw_text=text)

    for i, word in enumerate(words):
        # Skip numbers (digits)
        if re.match(r'^\d+$', word):
            continue

        # Skip date-like patterns (DD.MM, DD/MM)
        if re.match(r'^\d{1,2}[./]\d{1,2}$', word):
            continue

        # Skip ignore keywords
        if word in IGNORE_KEYWORDS:
            continue

        # Skip stop-words (greetings, short responses)
        if word in STOP_WORDS:
            continue

        # This is likely the model name — collect this and following non-keyword words
        # to support multi-word names like "ке паса", "мона лиза"
        model_words = [word]
        j = i + 1
        while j < len(words):
            next_word = words[j]
            # Stop collecting at any service/keyword/number token
            if (
                re.match(r'^\d+$', next_word)
                or re.match(r'^\d{1,2}[./]\d{1,2}$', next_word)
                or next_word in IGNORE_KEYWORDS
                or next_word in STOP_WORDS
            ):
                break
            model_words.append(next_word)
            j += 1
        entities.model_name = " ".join(model_words)
        LOGGER.debug("Extracted model name: %r", entities.model_name)
        break

    LOGGER.info("Extracted entities from text=%r: %s", text, entities)
    return entities


def extract_model_names(text: str, max_count: int = 3) -> List[str]:
    """Extract multiple potential model names from text."""
    if not text or not text.strip():
        return []

    text_normalized = normalize_text(text)
    words = text_normalized.split()

    model_names = []

    for word in words:
        if len(model_names) >= max_count:
            break

        if re.match(r'^\d+$', word):
            continue

        if word in IGNORE_KEYWORDS:
            continue

        if word in ("и", "or", "and", ","):
            continue

        model_names.append(word)

    return model_names


def validate_model_name(model_name: Optional[str]) -> bool:
    """Validate if extracted model name looks reasonable."""
    if not model_name:
        return False
    if len(model_name) < 2:
        return False
    if not re.search(r'[a-zа-я]', model_name, re.IGNORECASE):
        return False
    if re.match(r'^\d+$', model_name):
        return False
    if model_name.lower() in IGNORE_KEYWORDS:
        return False
    if model_name.lower() in STOP_WORDS:
        return False
    return True


def get_order_type_display_name(order_type: Optional[str]) -> str:
    """Get display name for order type (used by button-driven order flows)."""
    display_names = {
        "custom": "Кастом",
        "short": "Шорт",
        "verif reddit": "verif reddit",
        "call": "Колл",
        "ad request": "Ad Request",
        "ad_request": "Ad Request",
    }
    return display_names.get(order_type, "Неизвестный тип")
