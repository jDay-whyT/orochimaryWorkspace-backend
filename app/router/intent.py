"""Intent classification for NLP messages."""

from enum import Enum
import re


class Intent(Enum):
    """User intent types."""
    CREATE_ORDERS = "create_orders"  # "три кастома мелиса"
    ADD_FILES = "add_files"           # "мелиса 30 файлов"
    GET_REPORT = "get_report"         # "репорт мелиса"
    SHOW_SUMMARY = "show_summary"     # "сводка" / "summary"
    SHOW_ORDERS = "show_orders"       # "заказы" / "orders"
    SHOW_PLANNER = "show_planner"     # "планировщик" / "planner"
    SHOW_ACCOUNT = "show_account"     # "аккаунт" / "account"
    SEARCH_MODEL = "search_model"     # "мелиса" (только имя)
    UNKNOWN = "unknown"               # непонятный текст


# Ключевые слова для классификации (case-insensitive)
ORDER_KEYWORDS = [
    "кастом", "custom",
    "шорт", "short",
    "колл", "call",
    "ad request", "ад реквест"
]

FILE_KEYWORDS = ["файл", "file", "файлов", "files"]

REPORT_KEYWORDS = ["репорт", "report", "статистика", "stats", "стат"]

SUMMARY_KEYWORDS = ["сводка", "summary"]

ORDERS_MENU_KEYWORDS = ["заказы", "orders"]

PLANNER_KEYWORDS = ["планировщик", "planner", "план"]

ACCOUNT_KEYWORDS = ["аккаунт", "account", "accounting"]


def classify_intent(text: str) -> Intent:
    """
    Classify user intent from message text.

    Priority:
    1. SHOW_SUMMARY - if contains "сводка"/"summary"
    2. SHOW_ORDERS - if contains "заказы"/"orders" (without order type)
    3. SHOW_PLANNER - if contains "планировщик"/"planner"
    4. SHOW_ACCOUNT - if contains "аккаунт"/"account"
    5. CREATE_ORDERS - if contains order type keywords
    6. ADD_FILES - if contains "файл"/"file" AND has number
    7. GET_REPORT - if contains "репорт"/"report"/"статистика"
    8. SEARCH_MODEL - if only 1-2 words without keywords
    9. UNKNOWN - otherwise
    """
    text_lower = text.lower().strip()
    words = text_lower.split()

    # Check for menu keywords FIRST (priority)
    if any(kw in text_lower for kw in SUMMARY_KEYWORDS):
        return Intent.SHOW_SUMMARY

    # Check if "заказы"/"orders" without order type keywords
    has_orders_menu_keyword = any(kw in text_lower for kw in ORDERS_MENU_KEYWORDS)
    has_order_type_keyword = any(kw in text_lower for kw in ORDER_KEYWORDS)

    if has_orders_menu_keyword and not has_order_type_keyword:
        return Intent.SHOW_ORDERS

    if any(kw in text_lower for kw in PLANNER_KEYWORDS):
        return Intent.SHOW_PLANNER

    if any(kw in text_lower for kw in ACCOUNT_KEYWORDS):
        return Intent.SHOW_ACCOUNT

    # Check for order keywords
    for keyword in ORDER_KEYWORDS:
        if keyword in text_lower:
            return Intent.CREATE_ORDERS

    # Check for file keywords + number
    has_file_keyword = any(kw in text_lower for kw in FILE_KEYWORDS)
    has_number = bool(re.search(r'\b\d+\b', text))

    if has_file_keyword and has_number:
        return Intent.ADD_FILES

    # Check for report keywords
    if any(kw in text_lower for kw in REPORT_KEYWORDS):
        return Intent.GET_REPORT

    # If only 1-2 words and no keywords → likely model search
    if len(words) <= 2 and not has_file_keyword:
        return Intent.SEARCH_MODEL

    return Intent.UNKNOWN
