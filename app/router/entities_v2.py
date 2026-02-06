"""
Improved entity extraction using centralized command filters.

This version provides:
- Better model name detection
- Order type extraction with synonym support
- Number extraction
- Date parsing (DD.MM, DD/MM, DD месяц, relative dates)
- Comment text extraction
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, List

from app.router.command_filters import (
    ORDER_TYPE_MAP,
    IGNORE_KEYWORDS,
    normalize_text,
    extract_numbers,
)
from app.router.prefilter import STOP_WORDS


LOGGER = logging.getLogger(__name__)

# Russian month names to month number
_MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}


@dataclass
class EntitiesV2:
    """
    Extracted entities from user message.

    Attributes:
        model_name: Model name (first non-keyword, non-number word)
        numbers: All numbers found in text
        order_type: Order type ("custom", "short", "call", "ad request")
        date: Parsed date
        date_str: Raw date string from text
        comment_text: Extracted comment text (after "коммент:")
        comment_target: Comment target ("order"/"shoot"/"account")
        raw_text: Original message text
    """
    model_name: Optional[str] = None
    numbers: List[int] = None
    order_type: Optional[str] = None
    date: Optional[date] = None
    date_str: Optional[str] = None
    comment_text: Optional[str] = None
    comment_target: Optional[str] = None
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
        parts = [f"model={self.model_name!r}"]
        if self.numbers:
            parts.append(f"numbers={self.numbers}")
        if self.order_type:
            parts.append(f"order_type={self.order_type!r}")
        if self.date:
            parts.append(f"date={self.date}")
        if self.comment_text:
            parts.append(f"comment={self.comment_text!r}")
        return f"EntitiesV2({', '.join(parts)})"


def extract_date_str(text: str) -> Optional[str]:
    """
    Extract date string from text.

    Supported formats:
    - DD.MM: "13.02"
    - DD/MM: "13/02"
    - DD месяц: "13 февраля"
    - Relative: "завтра", "послезавтра"
    - "на DD.MM": "на 13.02"

    Returns raw date string or None.
    """
    text_lower = text.lower()

    # Relative dates
    if "послезавтра" in text_lower:
        return "послезавтра"
    if "завтра" in text_lower:
        return "завтра"
    if "сегодня" in text_lower:
        return "сегодня"
    if "вчера" in text_lower:
        return "вчера"

    # DD.MM or DD/MM pattern
    match = re.search(r'\b(\d{1,2})[./](\d{1,2})\b', text)
    if match:
        return match.group(0)

    # DD месяц pattern
    for month_name in _MONTHS_RU:
        pattern = re.compile(rf'\b(\d{{1,2}})\s+{re.escape(month_name)}\b', re.IGNORECASE)
        match = pattern.search(text)
        if match:
            return match.group(0)

    return None


def parse_date_ru(date_str: str, base_date: Optional[date] = None) -> Optional[date]:
    """
    Parse Russian date string to date object.

    Args:
        date_str: Date string from extract_date_str
        base_date: Base date for relative dates (default: today)

    Returns:
        Parsed date or None
    """
    if base_date is None:
        base_date = date.today()

    date_str_lower = date_str.lower().strip()

    # Relative dates
    if date_str_lower == "сегодня":
        return base_date
    if date_str_lower == "вчера":
        return base_date - timedelta(days=1)
    if date_str_lower == "завтра":
        return base_date + timedelta(days=1)
    if date_str_lower == "послезавтра":
        return base_date + timedelta(days=2)

    # DD.MM or DD/MM
    match = re.match(r'^(\d{1,2})[./](\d{1,2})$', date_str_lower)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = base_date.year
        try:
            result = date(year, month, day)
            # If the date is in the past by more than 30 days, assume next year
            if result < base_date - timedelta(days=30):
                result = date(year + 1, month, day)
            return result
        except ValueError:
            return None

    # DD месяц
    for month_name, month_num in _MONTHS_RU.items():
        pattern = re.compile(rf'^(\d{{1,2}})\s+{re.escape(month_name)}$', re.IGNORECASE)
        match = pattern.match(date_str_lower)
        if match:
            day = int(match.group(1))
            year = base_date.year
            try:
                result = date(year, month_num, day)
                if result < base_date - timedelta(days=30):
                    result = date(year + 1, month_num, day)
                return result
            except ValueError:
                return None

    return None


def extract_comment_text(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract comment text and target from message.

    Syntax: "модель [target] коммент: текст"

    Returns:
        (comment_text, comment_target)
        comment_target: "order" | "shoot" | "account" | None
    """
    for marker in ["коммент:", "комментарий:", "comment:"]:
        idx = text.lower().find(marker)
        if idx >= 0:
            comment_text = text[idx + len(marker):].strip()
            prefix = text[:idx].lower()

            target = None
            if any(w in prefix for w in ["заказ", "order", "кастом", "шорт", "колл"]):
                target = "order"
            elif any(w in prefix for w in ["съемк", "съёмк", "шут", "shoot"]):
                target = "shoot"
            elif any(w in prefix for w in ["учет", "аккаунт", "файл", "account"]):
                target = "account"

            return comment_text if comment_text else None, target

    return None, None


def extract_entities_v2(text: str) -> EntitiesV2:
    """
    Extract entities from user message using improved logic.

    Extraction process:
    1. Extract all numbers
    2. Extract order type from ORDER_TYPE_MAP
    3. Extract date
    4. Extract comment text
    5. Extract model name (first word not in IGNORE_KEYWORDS)
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
    if "ad request" in text_normalized or "ад реквест" in text_normalized:
        entities.order_type = "ad request"
    else:
        for word in words:
            if word in ORDER_TYPE_MAP:
                entities.order_type = ORDER_TYPE_MAP[word]
                break

    # Step 3: Extract date
    date_str = extract_date_str(text)
    if date_str:
        entities.date_str = date_str
        entities.date = parse_date_ru(date_str)
        LOGGER.debug("Extracted date: %s from %r", entities.date, date_str)

    # Step 4: Extract comment text
    comment_text, comment_target = extract_comment_text(text)
    if comment_text:
        entities.comment_text = comment_text
        entities.comment_target = comment_target

    # Step 5: Extract model name
    date_words = set()
    if date_str:
        date_words = set(date_str.lower().split())

    skip_next = False
    for i, word in enumerate(words):
        if skip_next:
            skip_next = False
            continue

        # Skip numbers (digits)
        if re.match(r'^\d+$', word):
            continue

        # Skip date-like patterns (DD.MM, DD/MM)
        if re.match(r'^\d{1,2}[./]\d{1,2}$', word):
            continue

        # Skip "ad"/"ад" if followed by "request"/"реквест"
        if word in ("ad", "ад") and i + 1 < len(words):
            next_word = words[i + 1]
            if next_word in ("request", "реквест"):
                skip_next = True
                continue

        # Skip ignore keywords
        if word in IGNORE_KEYWORDS:
            continue

        # Skip stop-words (greetings, short responses)
        if word in STOP_WORDS:
            continue

        # Skip date words
        if word in date_words:
            continue

        # Skip "+" (file marker)
        if word == "+":
            continue

        # Skip comment text (everything after "коммент:")
        if word.rstrip(":") in ("коммент", "комментарий", "comment"):
            break

        # This is likely the model name
        entities.model_name = word
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
    skip_next = False

    for i, word in enumerate(words):
        if len(model_names) >= max_count:
            break

        if skip_next:
            skip_next = False
            continue

        if re.match(r'^\d+$', word):
            continue

        if word in ("ad", "ад") and i + 1 < len(words):
            next_word = words[i + 1]
            if next_word in ("request", "реквест"):
                skip_next = True
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
    # Reject stop-words that should never be model names
    from app.router.prefilter import STOP_WORDS
    if model_name.lower() in STOP_WORDS:
        return False
    return True


def get_order_type_display_name(order_type: Optional[str]) -> str:
    """Get display name for order type."""
    display_names = {
        "custom": "Кастом",
        "short": "Шорт",
        "call": "Колл",
        "ad request": "Ad Request",
        "ad_request": "Ad Request",
    }
    return display_names.get(order_type, "Неизвестный тип")
