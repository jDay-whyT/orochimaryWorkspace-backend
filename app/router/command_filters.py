"""
Model-name extraction support: stop-word list and text-normalization
utilities used by app.router.entities_v2.

The bot used to run a full keyword-based intent classifier here (shoot/order/
files/comment commands). Usage data showed 99% of real traffic is a bare
model name, so the keyword classifier was removed — only the pieces
entities_v2 still needs for model-name extraction remain.
"""

import re
from enum import Enum


class CommandIntent(Enum):
    """User message intent — either a model name was found, or it wasn't."""
    SEARCH_MODEL = "search_model"
    UNKNOWN = "unknown"


# ============================================================================
#                      IGNORE KEYWORDS (для извлечения имени модели)
# ============================================================================

IGNORE_KEYWORDS = {
    # Ключевые слова команд
    "кастом", "кастома", "кастомов", "custom", "customs",
    "шорт", "шорта", "шортов", "шортс", "short", "shorts",
    "вериф", "верифреддит", "вериф-реддит", "verif", "reddit", "реддит",
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
    "скаут",
}


# ============================================================================
#                              UTILITIES
# ============================================================================

def normalize_text(text: str) -> str:
    """
    Normalize text for matching:
    - lowercase
    - strip whitespace
    - collapse multiple spaces
    """
    return re.sub(r'\s+', ' ', text.lower().strip())

