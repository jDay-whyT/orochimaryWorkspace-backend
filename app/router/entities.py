"""Entity extraction from NLP messages."""

from dataclasses import dataclass
from datetime import date
import re
from typing import Optional


@dataclass
class Entities:
    """Extracted entities from user message."""
    model_name: Optional[str] = None       # Имя модели (не ключевое слово)
    numbers: list[int] = None              # Все числа в тексте
    order_type: Optional[str] = None       # "custom" / "short" / "call" / "ad request"
    date: Optional[date] = None            # Дата (если упомянута)

    def __post_init__(self):
        if self.numbers is None:
            self.numbers = []


# Ключевые слова (для фильтрации при поиске имени модели)
ORDER_TYPE_KEYWORDS = {
    "кастом": "custom",
    "custom": "custom",
    "шорт": "short",
    "short": "short",
    "колл": "call",
    "call": "call",
    "ad": "ad request",
    "ад": "ad request",
    "request": "ad request",
    "реквест": "ad request",
}

IGNORE_KEYWORDS = [
    "файл", "file", "файлов", "files",
    "репорт", "report", "статистика", "stats", "стат",
    "три", "два", "пять", "one", "two", "three", "five",
    "сегодня", "вчера", "today", "yesterday",
]


def extract_entities(text: str) -> Entities:
    """
    Extract entities from user message.

    Rules:
    - model_name: First word that is NOT a keyword and NOT a number
    - numbers: All numbers found in text
    - order_type: Mapped from keywords
    - date: Simple date parsing (if needed in future)
    """
    text_lower = text.lower().strip()
    words = text_lower.split()

    entities = Entities()

    # Extract numbers
    numbers = re.findall(r'\b\d+\b', text)
    entities.numbers = [int(n) for n in numbers]

    # Extract order type
    for word in words:
        if word in ORDER_TYPE_KEYWORDS:
            entities.order_type = ORDER_TYPE_KEYWORDS[word]
            break

    # Extract model name: first non-keyword, non-number word
    for word in words:
        # Skip numbers
        if re.match(r'^\d+$', word):
            continue

        # Skip keywords
        if word in ORDER_TYPE_KEYWORDS or word in IGNORE_KEYWORDS:
            continue

        # Skip "ad request" as two words
        if word in ("ad", "ад", "request", "реквест"):
            continue

        # This is likely the model name
        entities.model_name = word
        break

    return entities
