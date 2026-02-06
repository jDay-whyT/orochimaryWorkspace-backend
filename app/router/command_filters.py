"""
Centralized command filter database with support for:
- Synonyms and word variations
- Word forms (declensions)
- Phrase matching
- Priority weights
- Regex patterns

This module provides a single source of truth for all bot command recognition.

Priority levels (from spec):
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

import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Pattern
from enum import Enum


class CommandIntent(Enum):
    """User command intents."""
    # Shoot domain (priority 100)
    SHOOT_CREATE = "shoot_create"
    SHOOT_DONE = "shoot_done"
    SHOOT_RESCHEDULE = "shoot_reschedule"

    # Files domain (priority 90)
    ADD_FILES = "add_files"

    # Orders with type (priority 80)
    CREATE_ORDERS = "create_orders"

    # Orders general (priority 70)
    CREATE_ORDERS_GENERAL = "create_orders_general"

    # Orders close (priority 60)
    CLOSE_ORDERS = "close_orders"

    # Comment (priority 55)
    ADD_COMMENT = "add_comment"

    # Model actions (priority 50)
    GET_REPORT = "get_report"
    SHOW_MODEL_ORDERS = "show_model_orders"

    # Menu (priority 40)
    SHOW_SUMMARY = "show_summary"
    SHOW_ORDERS = "show_orders"
    SHOW_PLANNER = "show_planner"
    SHOW_ACCOUNT = "show_account"

    # Files stats - "мелиса файлы" without number (priority 35)
    FILES_STATS = "files_stats"

    # Ambiguous (priority 30)
    AMBIGUOUS = "ambiguous"

    # Search/Unknown (priority 0)
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

COMMAND_FILTERS = [
    # ========== SHOOT DOMAIN (Priority: 100) ==========
    # "съемка" always takes highest priority, ignoring other markers

    CommandFilter(
        intent=CommandIntent.SHOOT_DONE,
        keywords=[],
        multi_word_phrases=[
            "съемка выполнена", "съемка готова", "съемка готово", "съемка done",
            "съёмка выполнена", "съёмка готова", "съёмка готово", "съёмка done",
            "съемка выполнено", "съёмка выполнено",
            "шут выполнен", "шут готов", "шут done",
        ],
        patterns=[
            re.compile(
                r'\bсъ[её]мк[а-я]*\b.{0,40}\b(выполнен[а-я]*|готов[а-я]*|done)\b',
                re.IGNORECASE,
            ),
            re.compile(
                r'\b(выполнен[а-я]*|готов[а-я]*|done)\b.{0,40}\bсъ[её]мк[а-я]*\b',
                re.IGNORECASE,
            ),
        ],
        priority=102,
    ),

    CommandFilter(
        intent=CommandIntent.SHOOT_RESCHEDULE,
        keywords=["перенос", "перенести"],
        multi_word_phrases=[
            "съемка перенос", "съемка перенести",
            "съёмка перенос", "съёмка перенести",
            "перенести съемку", "перенести съёмку",
        ],
        patterns=[
            re.compile(
                r'\bсъ[её]мк[а-я]*\b.{0,40}\bперенос\b',
                re.IGNORECASE,
            ),
            re.compile(
                r'\bперенос[а-я]*\b.{0,40}\bсъ[её]мк[а-я]*\b',
                re.IGNORECASE,
            ),
            re.compile(
                r'\bперенести\b.{0,40}\bсъ[её]мк[а-я]*\b',
                re.IGNORECASE,
            ),
            re.compile(r'\bперенос[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bперенести\b', re.IGNORECASE),
        ],
        exclude_with=[
            "кастом", "custom", "шорт", "short", "колл", "call",
            "заказ", "order", "файл", "file",
        ],
        priority=101,
    ),

    CommandFilter(
        intent=CommandIntent.SHOOT_CREATE,
        keywords=[
            "съемка", "съемку", "съемки", "съёмка", "съёмку", "съёмки",
            "шут", "шута",
            "заплан", "запланировать", "запланирована",
        ],
        multi_word_phrases=[
            "запланировать съемку",
            "новая съемка",
        ],
        patterns=[
            re.compile(r'\bсъ[её]мк[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bшут[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bзаплан[а-я]*\b', re.IGNORECASE),
        ],
        priority=100,
    ),

    # ========== FILES DOMAIN (Priority: 90) ==========
    # Requires marker ("файлы"/"фото"/"сняла"/"добавить"/"+") + number

    CommandFilter(
        intent=CommandIntent.ADD_FILES,
        keywords=[
            "файл", "файла", "файлов", "файлик", "файлики",
            "фото", "фотки", "фотография",
            "file", "files", "photo", "photos",
            "сняла", "снято",
        ],
        multi_word_phrases=[
            "добавить файлы", "добавить фото",
            "добавить файлов", "добавить фотки",
        ],
        patterns=[
            re.compile(r'\bфайл[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bфото[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bfile[s]?\b', re.IGNORECASE),
            re.compile(r'\bphoto[s]?\b', re.IGNORECASE),
            re.compile(r'\bснял[а-я]*\b', re.IGNORECASE),
            # "+" marker: "мелиса + 30"
            re.compile(r'\+\s*\d+', re.IGNORECASE),
        ],
        requires_number=True,
        priority=90,
    ),

    # ========== ORDERS WITH TYPE (Priority: 80) ==========

    CommandFilter(
        intent=CommandIntent.CREATE_ORDERS,
        keywords=[
            # Кастом
            "кастом", "кастома", "кастомов", "кастомчик",
            "custom", "customs",
            # Шорт
            "шорт", "шорта", "шортов", "шортик", "шортс",
            "short", "shorts",
            # Колл
            "колл", "колла", "коллов", "коллик",
            "call", "calls",
        ],
        multi_word_phrases=[
            "ad request", "ad requests",
            "ад реквест", "ад реквеста", "ад реквестов",
            "адреквест",
        ],
        patterns=[
            re.compile(r'\bка?сто?м[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bcustom[s]?\b', re.IGNORECASE),
            re.compile(r'\bшорт[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bshort[s]?\b', re.IGNORECASE),
            re.compile(r'\bколл?[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bcall[s]?\b', re.IGNORECASE),
            re.compile(r'\b(ad\s*request|ад\s*реквест)[а-я]*\b', re.IGNORECASE),
        ],
        exclude_with=[
            "закрыт", "закрыта", "закрыть",
            "готов", "готова", "выполнен", "выполнена",
        ],
        priority=80,
    ),

    # ========== ORDERS GENERAL (Priority: 70) ==========

    CommandFilter(
        intent=CommandIntent.CREATE_ORDERS_GENERAL,
        keywords=[
            "запрос", "запроса",
        ],
        multi_word_phrases=[
            "новый заказ", "новый запрос",
            "создать заказ", "создать запрос",
        ],
        patterns=[
            re.compile(r'\bзапрос[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bновый\s+заказ\b', re.IGNORECASE),
        ],
        priority=70,
    ),

    # ========== ORDERS CLOSE (Priority: 60) ==========

    CommandFilter(
        intent=CommandIntent.CLOSE_ORDERS,
        keywords=[
            "закрыт", "закрыта", "закрыть", "закрытие",
        ],
        multi_word_phrases=[
            "заказ закрыт", "заказ готов",
            "кастом закрыт", "шорт закрыт", "колл закрыт",
        ],
        patterns=[
            re.compile(r'\bзакрыт[а-я]*\b', re.IGNORECASE),
        ],
        priority=60,
    ),

    # ========== COMMENT (Priority: 55) ==========

    CommandFilter(
        intent=CommandIntent.ADD_COMMENT,
        keywords=[],
        multi_word_phrases=[
            "коммент:", "комментарий:",
            "comment:",
        ],
        patterns=[
            re.compile(r'\bкоммент\s*:', re.IGNORECASE),
            re.compile(r'\bкомментарий\s*:', re.IGNORECASE),
            re.compile(r'\bcomment\s*:', re.IGNORECASE),
        ],
        priority=55,
    ),

    # ========== MODEL ACTIONS (Priority: 50) ==========

    CommandFilter(
        intent=CommandIntent.GET_REPORT,
        keywords=[
            "репорт", "репорта", "репортов",
            "отчет", "отчета", "отчетов",
            "статистика", "статистику", "стат", "стата",
            "report", "reports", "stats", "statistics",
        ],
        patterns=[
            re.compile(r'\b(репорт|отчет)[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bстат[а-я]*\b', re.IGNORECASE),
            re.compile(r'\breport[s]?\b', re.IGNORECASE),
            re.compile(r'\bstats?\b', re.IGNORECASE),
            re.compile(r'\bstatistics?\b', re.IGNORECASE),
        ],
        priority=50,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_MODEL_ORDERS,
        keywords=[
            "заказы", "заказов",
            "orders",
        ],
        patterns=[
            re.compile(r'\bзаказ[а-я]*\b', re.IGNORECASE),
            re.compile(r'\borders?\b', re.IGNORECASE),
        ],
        exclude_with=[
            "кастом", "custom", "шорт", "short", "колл", "call",
            "ad request", "ад реквест",
            "закрыт", "закрыта", "закрыть",
            "запрос", "новый",
        ],
        priority=50,
    ),

    # ========== MENU COMMANDS (Priority: 40) ==========

    CommandFilter(
        intent=CommandIntent.SHOW_SUMMARY,
        keywords=[
            "сводка", "сводку", "сводки",
            "summary",
            "сводк",
        ],
        patterns=[
            re.compile(r'\bсводк[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bsummary\b', re.IGNORECASE),
        ],
        priority=40,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_ORDERS,
        keywords=[
            "заказы", "заказов", "заказ",
            "orders", "order",
        ],
        patterns=[
            re.compile(r'\bзаказ[а-я]*\b', re.IGNORECASE),
            re.compile(r'\borders?\b', re.IGNORECASE),
        ],
        exclude_with=[
            "кастом", "custom", "шорт", "short", "колл", "call",
            "ad request", "ад реквест",
            "закрыт", "закрыта", "закрыть",
            "запрос", "новый",
        ],
        priority=40,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_PLANNER,
        keywords=[
            "планировщик", "планировщика", "планер",
            "план", "плана", "планов",
            "планирование",
            "planner", "schedule", "planning",
        ],
        patterns=[
            re.compile(r'\bплан[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bplann?[a-z]*\b', re.IGNORECASE),
            re.compile(r'\bschedul[a-z]*\b', re.IGNORECASE),
        ],
        exclude_with=[
            "съемка", "съёмка", "шут",
        ],
        priority=40,
    ),

    CommandFilter(
        intent=CommandIntent.SHOW_ACCOUNT,
        keywords=[
            "аккаунт", "аккаунта", "аккаунтов", "акк",
            "бухгалтерия", "бух",
            "account", "accounts", "accounting",
        ],
        patterns=[
            re.compile(r'\bакк[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bбух[а-я]*\b', re.IGNORECASE),
            re.compile(r'\baccount[a-z]*\b', re.IGNORECASE),
        ],
        priority=40,
    ),

    # ========== FILES STATS (Priority: 35) ==========

    CommandFilter(
        intent=CommandIntent.FILES_STATS,
        keywords=[
            "файл", "файла", "файлов", "файлик", "файлы",
            "фото", "фотки",
            "file", "files", "photo", "photos",
        ],
        patterns=[
            re.compile(r'\bфайл[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bфото[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bfile[s]?\b', re.IGNORECASE),
            re.compile(r'\bphoto[s]?\b', re.IGNORECASE),
        ],
        requires_number=False,
        priority=35,
    ),
]


# ============================================================================
#                      IGNORE KEYWORDS (для извлечения имени модели)
# ============================================================================

IGNORE_KEYWORDS = {
    # Ключевые слова команд
    "кастом", "кастома", "кастомов", "custom", "customs",
    "шорт", "шорта", "шортов", "шортс", "short", "shorts",
    "колл", "колла", "коллов", "call", "calls",
    "ад", "ad", "реквест", "request",

    # Файлы
    "файл", "файла", "файлов", "файлик", "файлики", "файлы", "file", "files",
    "фото", "фотки", "photo", "photos",
    "сняла", "снято",

    # Отчеты
    "репорт", "репорта", "репортов", "report", "reports",
    "отчет", "отчета", "отчетов",
    "статистика", "статистику", "стат", "стата", "stats", "statistics",

    # Меню
    "сводка", "сводку", "summary",
    "заказы", "заказов", "заказ", "orders", "order",
    "планировщик", "планер", "план", "planner", "schedule", "planning",
    "аккаунт", "аккаунта", "акк", "account", "accounting", "бухгалтерия", "бух",

    # Shoot keywords
    "съемка", "съемку", "съемки", "съёмка", "съёмку", "съёмки",
    "шут", "шута",
    "заплан", "запланировать", "запланирована",

    # Close/done keywords
    "закрыт", "закрыта", "закрыть", "закрытие",
    "готов", "готова", "выполнен", "выполнена", "done",
    "перенос", "перенести",

    # Comment keywords
    "коммент", "комментарий", "comment",

    # General order keywords
    "запрос", "запроса",

    # Action verbs
    "добавить", "добавь",

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
    "сегодня", "вчера", "завтра", "послезавтра",
    "today", "yesterday", "tomorrow",
    "неделя", "месяц", "год", "week", "month", "year",

    # Глаголы команд (русские)
    "добавить", "добавь", "добавил", "добавила", "добавлю",
    "создай", "создать", "создал", "создала", "создам",
    "сделай", "сделать", "сделал", "сделала", "сделаю",
    "покажи", "показать", "показал", "покажу", "покази",
    "дай", "давай", "дать",
    "открой", "открыть",
    "посмотри", "посмотреть",
    "новый", "новая", "новое", "новые",

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

    # Date-like words
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",

    # Misc
    "штук", "штуки", "штука",
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
    "шортс": "short",
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


# Словарь для конвертации слов-числительных в числа
WORD_TO_NUMBER = {
    # Русские числительные
    "один": 1, "одна": 1, "одно": 1, "одного": 1, "одной": 1,
    "два": 2, "две": 2, "двух": 2,
    "три": 3, "трёх": 3, "тре": 3, "трех": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
    "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
    # Английские числительные
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def word2num(word: str) -> Optional[int]:
    """Convert word-number to integer."""
    return WORD_TO_NUMBER.get(word.lower())


def contains_number(text: str) -> bool:
    """Check if text contains at least one number (digit or word)."""
    if re.search(r'\b\d+\b', text):
        return True
    words = text.lower().split()
    return any(word in WORD_TO_NUMBER for word in words)


def extract_numbers(text: str) -> List[int]:
    """Extract all numbers from text (both digits and word-numbers)."""
    numbers = []
    numbers.extend(int(n) for n in re.findall(r'\b\d+\b', text))
    words = text.lower().split()
    for word in words:
        num = word2num(word)
        if num is not None:
            numbers.append(num)
    return numbers


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
