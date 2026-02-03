"""
Centralized command filter database with support for:
- Synonyms and word variations
- Word forms (declensions)
- Phrase matching
- Priority weights
- Regex patterns

This module provides a single source of truth for all bot command recognition.
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Pattern
from enum import Enum


class CommandIntent(Enum):
    """User command intents."""
    CREATE_ORDERS = "create_orders"
    ADD_FILES = "add_files"
    GET_REPORT = "get_report"
    SHOW_SUMMARY = "show_summary"
    SHOW_ORDERS = "show_orders"
    SHOW_PLANNER = "show_planner"
    SHOW_ACCOUNT = "show_account"
    SEARCH_MODEL = "search_model"
    UNKNOWN = "unknown"


@dataclass
class CommandFilter:
    """
    Command filter with keywords, patterns, and metadata.

    Attributes:
        intent: The command intent this filter detects
        keywords: List of exact keywords (case-insensitive)
        patterns: List of compiled regex patterns
        priority: Priority weight (higher = checked first)
        requires_number: Whether this command requires a number in text
        multi_word_phrases: Multi-word phrases to match as whole
        exclude_with: Keywords that, if present, exclude this intent
    """
    intent: CommandIntent
    keywords: List[str]
    patterns: List[Pattern] = None
    priority: int = 0
    requires_number: bool = False
    multi_word_phrases: List[str] = None
    exclude_with: List[str] = None

    def __post_init__(self):
        if self.patterns is None:
            self.patterns = []
        if self.multi_word_phrases is None:
            self.multi_word_phrases = []
        if self.exclude_with is None:
            self.exclude_with = []


# ============================================================================
#                         COMMAND FILTER DATABASE
# ============================================================================

# Приоритет: чем выше число, тем выше приоритет проверки
# 100 - меню команды (высший приоритет)
# 50 - действия с обязательными параметрами
# 10 - действия без параметров
# 0 - поиск модели (самый низкий)

COMMAND_FILTERS = [
    # ========== МЕНЮ КОМАНДЫ (Priority: 100) ==========

    CommandFilter(
        intent=CommandIntent.SHOW_SUMMARY,
        keywords=[
            # Русские варианты
            "сводка", "сводку", "сводки",
            # Английские варианты
            "summary",
            # Возможные сокращения
            "сводк",
        ],
        patterns=[
            re.compile(r'\bсводк[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bsummary\b', re.IGNORECASE),
        ],
        priority=100,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_ORDERS,
        keywords=[
            # Русские варианты
            "заказы", "заказов", "заказ",
            # Английские варианты
            "orders", "order",
        ],
        patterns=[
            re.compile(r'\bзаказ[а-я]*\b', re.IGNORECASE),
            re.compile(r'\borders?\b', re.IGNORECASE),
        ],
        # Исключаем, если есть тип заказа (тогда это CREATE_ORDERS)
        exclude_with=[
            "кастом", "custom", "шорт", "short", "колл", "call",
            "ad request", "ад реквест",
        ],
        priority=100,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_PLANNER,
        keywords=[
            # Русские варианты
            "планировщик", "планировщика", "планер",
            "план", "плана", "планов",
            "планирование",
            # Английские варианты
            "planner", "schedule", "planning",
        ],
        patterns=[
            re.compile(r'\bплан[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bplann?[a-z]*\b', re.IGNORECASE),
            re.compile(r'\bschedul[a-z]*\b', re.IGNORECASE),
        ],
        priority=100,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_ACCOUNT,
        keywords=[
            # Русские варианты
            "аккаунт", "аккаунта", "аккаунтов", "акк",
            "бухгалтерия", "бух",
            # Английские варианты
            "account", "accounts", "accounting",
        ],
        patterns=[
            re.compile(r'\bакк[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bбух[а-я]*\b', re.IGNORECASE),
            re.compile(r'\baccount[a-z]*\b', re.IGNORECASE),
        ],
        priority=100,
    ),

    # ========== КОМАНДЫ С ПАРАМЕТРАМИ (Priority: 50) ==========

    CommandFilter(
        intent=CommandIntent.CREATE_ORDERS,
        keywords=[
            # Кастом
            "кастом", "кастома", "кастомов", "кастомчик",
            "custom", "customs",
            # Шорт
            "шорт", "шорта", "шортов", "шортик",
            "short", "shorts",
            # Колл
            "колл", "колла", "коллов", "коллик",
            "call", "calls",
        ],
        multi_word_phrases=[
            # Ad request как цельная фраза
            "ad request", "ad requests",
            "ад реквест", "ад реквеста", "ад реквестов",
            "адреквест",
        ],
        patterns=[
            # Кастом (с возможными опечатками)
            re.compile(r'\bка?сто?м[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bcustom[s]?\b', re.IGNORECASE),
            # Шорт
            re.compile(r'\bшорт[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bshort[s]?\b', re.IGNORECASE),
            # Колл
            re.compile(r'\bколл?[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bcall[s]?\b', re.IGNORECASE),
            # Ad request (с пробелом или без)
            re.compile(r'\b(ad\s*request|ад\s*реквест)[а-я]*\b', re.IGNORECASE),
        ],
        priority=50,
    ),

    CommandFilter(
        intent=CommandIntent.ADD_FILES,
        keywords=[
            # Русские варианты
            "файл", "файла", "файлов", "файлик", "файлики",
            "фото", "фотки", "фотография",
            # Английские варианты
            "file", "files", "photo", "photos",
        ],
        patterns=[
            re.compile(r'\bфайл[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bфото[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bfile[s]?\b', re.IGNORECASE),
            re.compile(r'\bphoto[s]?\b', re.IGNORECASE),
        ],
        requires_number=True,  # ОБЯЗАТЕЛЬНО должно быть число
        priority=50,
    ),

    # ========== КОМАНДЫ БЕЗ ПАРАМЕТРОВ (Priority: 10) ==========

    CommandFilter(
        intent=CommandIntent.GET_REPORT,
        keywords=[
            # Русские варианты
            "репорт", "репорта", "репортов",
            "отчет", "отчета", "отчетов",
            "статистика", "статистику", "стат", "стата",
            # Английские варианты
            "report", "reports", "stats", "statistics",
        ],
        patterns=[
            re.compile(r'\b(репорт|отчет)[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bстат[а-я]*\b', re.IGNORECASE),
            re.compile(r'\breport[s]?\b', re.IGNORECASE),
            re.compile(r'\bstats?\b', re.IGNORECASE),
            re.compile(r'\bstatistics?\b', re.IGNORECASE),
        ],
        priority=10,
    ),
]


# ============================================================================
#                      IGNORE KEYWORDS (для извлечения имени модели)
# ============================================================================

IGNORE_KEYWORDS = {
    # Ключевые слова команд
    "кастом", "кастома", "кастомов", "custom", "customs",
    "шорт", "шорта", "шортов", "short", "shorts",
    "колл", "колла", "коллов", "call", "calls",
    "ад", "ad", "реквест", "request",

    # Файлы
    "файл", "файла", "файлов", "файлик", "файлики", "file", "files",
    "фото", "фотки", "photo", "photos",

    # Отчеты
    "репорт", "репорта", "репортов", "report", "reports",
    "отчет", "отчета", "отчетов",
    "статистика", "статистику", "стат", "стата", "stats", "statistics",

    # Меню
    "сводка", "сводку", "summary",
    "заказы", "заказов", "заказ", "orders", "order",
    "планировщик", "планер", "план", "planner", "schedule", "planning",
    "аккаунт", "аккаунта", "акк", "account", "accounting", "бухгалтерия", "бух",

    # Числительные (русские)
    "один", "одна", "одно", "одного", "одной",
    "два", "две", "двух",
    "три", "трёх", "тре", "трех",
    "четыре", "четырёх", "четырех",
    "пять", "пяти",
    "шесть", "шести",
    "семь", "семи",
    "восемь", "восьми",
    "девять", "девяти",
    "десять", "десяти",

    # Числительные (английские)
    "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten",

    # Временные слова
    "сегодня", "вчера", "завтра", "today", "yesterday", "tomorrow",
    "неделя", "месяц", "год", "week", "month", "year",

    # Глаголы команд (русские)
    "добавить", "добавь", "добавил", "добавила", "добавлю",
    "создай", "создать", "создал", "создала", "создам",
    "сделай", "сделать", "сделал", "сделала", "сделаю",
    "покажи", "показать", "показал", "покажу", "покази",
    "дай", "давай", "дать",
    "открой", "открыть", "открой",
    "посмотри", "посмотреть",

    # Глаголы команд (английские)
    "add", "create", "make", "show", "give", "open", "view", "see",

    # Предлоги и союзы
    "на", "в", "с", "по", "для", "из", "к", "о", "у", "за", "от", "до",
    "и", "или", "но", "а",
    "on", "in", "with", "by", "for", "from", "to", "about", "at",
    "and", "or", "but",

    # Местоимения
    "мне", "мой", "моя", "мое", "мои", "меня",
    "я", "ты", "он", "она", "оно", "мы", "вы", "они",
    "me", "my", "mine", "i", "you", "he", "she", "it", "we", "they",
}


# ============================================================================
#                        ORDER TYPE MAPPING
# ============================================================================

ORDER_TYPE_MAP = {
    # Custom
    "кастом": "custom",
    "кастома": "custom",
    "кастомов": "custom",
    "кастомчик": "custom",
    "custom": "custom",
    "customs": "custom",

    # Short
    "шорт": "short",
    "шорта": "short",
    "шортов": "short",
    "шортик": "short",
    "short": "short",
    "shorts": "short",

    # Call
    "колл": "call",
    "колла": "call",
    "коллов": "call",
    "коллик": "call",
    "call": "call",
    "calls": "call",

    # Ad request
    "ad": "ad request",
    "ад": "ad request",
    "request": "ad request",
    "реквест": "ad request",
    "адреквест": "ad request",
    "ad request": "ad request",
    "ad-request": "ad request",
    "ад реквест": "ad request",
    "ад-реквест": "ad request",
}


# ============================================================================
#                              UTILITIES
# ============================================================================

def get_filter_by_intent(intent: CommandIntent) -> Optional[CommandFilter]:
    """Get command filter by intent."""
    for f in COMMAND_FILTERS:
        if f.intent == intent:
            return f
    return None


def get_sorted_filters() -> List[CommandFilter]:
    """Get filters sorted by priority (highest first)."""
    return sorted(COMMAND_FILTERS, key=lambda f: f.priority, reverse=True)


def normalize_text(text: str) -> str:
    """
    Normalize text for matching:
    - lowercase
    - strip whitespace
    - collapse multiple spaces
    """
    return re.sub(r'\s+', ' ', text.lower().strip())


def contains_number(text: str) -> bool:
    """Check if text contains at least one number."""
    return bool(re.search(r'\b\d+\b', text))


def extract_numbers(text: str) -> List[int]:
    """Extract all numbers from text."""
    return [int(n) for n in re.findall(r'\b\d+\b', text)]


def match_multi_word_phrases(text: str, phrases: List[str]) -> bool:
    """Check if any multi-word phrase is present in text."""
    text_normalized = normalize_text(text)
    for phrase in phrases:
        phrase_normalized = normalize_text(phrase)
        if phrase_normalized in text_normalized:
            return True
    return False


def match_keywords(text: str, keywords: List[str]) -> bool:
    """Check if any keyword is present in text (case-insensitive)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def match_patterns(text: str, patterns: List[Pattern]) -> bool:
    """Check if any regex pattern matches text."""
    return any(pattern.search(text) for pattern in patterns)


def match_exclude_keywords(text: str, exclude_keywords: List[str]) -> bool:
    """Check if any exclude keyword is present in text."""
    if not exclude_keywords:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in exclude_keywords)
