# Руководство по системе фильтров команд

## 📋 Содержание

1. [Обзор системы](#обзор-системы)
2. [Архитектура](#архитектура)
3. [Как работают фильтры](#как-работают-фильтры)
4. [Добавление новых команд](#добавление-новых-команд)
5. [Примеры использования](#примеры-использования)
6. [Миграция со старой системы](#миграция-со-старой-системы)
7. [Тестирование](#тестирование)

---

## Обзор системы

Новая система фильтров команд предоставляет:

✅ **Централизованная база данных** - все ключевые слова в одном месте
✅ **Поддержка синонимов** - "кастом", "кастома", "кастомчик" → все работают
✅ **Словоформы** - автоматическое распознавание склонений
✅ **Многословные фразы** - "ad request" распознается как единое целое
✅ **Система приоритетов** - меню-команды имеют приоритет над действиями
✅ **Правила исключения** - "заказы" без типа заказа → меню, с типом → создание
✅ **Regex паттерны** - гибкое распознавание с опечатками

---

## Архитектура

```
app/router/
├── command_filters.py    # Централизованная база фильтров
├── intent_v2.py          # Улучшенная классификация интентов
├── entities_v2.py        # Улучшенное извлечение сущностей
├── intent.py             # Старая версия (для совместимости)
└── entities.py           # Старая версия (для совместимости)
```

### Основные компоненты

#### 1. `CommandFilter` (dataclass)

Описывает один фильтр команды:

```python
@dataclass
class CommandFilter:
    intent: CommandIntent              # Какой интент детектируется
    keywords: List[str]                # Ключевые слова
    patterns: List[Pattern]            # Regex паттерны
    priority: int                      # Приоритет (выше = проверяется раньше)
    requires_number: bool              # Требуется ли число в тексте
    multi_word_phrases: List[str]      # Многословные фразы
    exclude_with: List[str]            # Ключевые слова-исключения
```

#### 2. Система приоритетов

```
100 - Меню-команды (сводка, заказы, планировщик, аккаунт)
 50 - Команды с параметрами (создание заказов, добавление файлов)
 10 - Команды без параметров (репорты)
  0 - Поиск модели (fallback)
```

#### 3. База фильтров `COMMAND_FILTERS`

Список всех фильтров команд, отсортированных по приоритету.

---

## Как работают фильтры

### Процесс классификации

```
1. Нормализация текста
   └─> lowercase, удаление лишних пробелов

2. Проверка фильтров по приоритету
   ├─> Многословные фразы (самая высокая специфичность)
   ├─> Ключевые слова
   └─> Regex паттерны

3. Применение правил исключения
   └─> "заказы" + "кастом" → CREATE_ORDERS, не SHOW_ORDERS

4. Проверка требований
   └─> Если requires_number=True, должно быть число

5. Возврат первого совпадения
   └─> Или SEARCH_MODEL / UNKNOWN
```

### Пример работы

**Входящий текст:** "три кастома мелиса"

```python
1. Нормализация → "три кастома мелиса"
2. Проверка фильтров:
   - SHOW_SUMMARY? ❌ Нет "сводка"
   - SHOW_ORDERS? ❌ Нет "заказы" или есть exclude_with ("кастом")
   - CREATE_ORDERS? ✅ Найдено "кастома" (keyword match)
3. Возврат: CommandIntent.CREATE_ORDERS
```

---

## Добавление новых команд

### Шаг 1: Добавить Intent

В `command_filters.py`:

```python
class CommandIntent(Enum):
    # ... существующие
    NEW_COMMAND = "new_command"  # Ваша новая команда
```

### Шаг 2: Создать CommandFilter

```python
COMMAND_FILTERS = [
    # ... существующие фильтры

    CommandFilter(
        intent=CommandIntent.NEW_COMMAND,
        keywords=[
            # Русские варианты
            "новая", "новую", "новый",
            # Английские варианты
            "new", "create-new",
        ],
        patterns=[
            # Regex для гибкого распознавания
            re.compile(r'\bнов[а-я]*\b', re.IGNORECASE),
            re.compile(r'\bnew\b', re.IGNORECASE),
        ],
        multi_word_phrases=[
            # Многословные фразы
            "новая команда",
            "create new",
        ],
        priority=50,  # Установить приоритет
        requires_number=False,  # Нужно ли число?
        exclude_with=[],  # Ключевые слова-исключения
    ),
]
```

### Шаг 3: Обновить IGNORE_KEYWORDS (если нужно)

Если ключевые слова команды НЕ должны быть именами моделей:

```python
IGNORE_KEYWORDS = {
    # ... существующие
    "новая", "новую", "новый", "new",
}
```

### Шаг 4: Добавить handler

В `app/router/dispatcher.py`:

```python
async def route_message(...):
    # ...

    if intent == Intent.NEW_COMMAND:
        from app.handlers.new_command import handle_new_command
        await handle_new_command(message, entities, ...)
```

---

## Примеры использования

### Пример 1: Базовое использование

```python
from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import extract_entities_v2

# Классификация
text = "три кастома мелиса"
intent = classify_intent_v2(text)
# → CommandIntent.CREATE_ORDERS

# Извлечение сущностей
entities = extract_entities_v2(text)
# → EntitiesV2(model='мелиса', numbers=[3], order_type='custom')
```

### Пример 2: Многословные фразы

```python
text = "ad request софи 2 штуки"
intent = classify_intent_v2(text)
# → CommandIntent.CREATE_ORDERS

entities = extract_entities_v2(text)
# → EntitiesV2(model='софи', numbers=[2], order_type='ad request')
```

### Пример 3: Правила исключения

```python
# Без типа заказа → меню
text = "заказы"
intent = classify_intent_v2(text)
# → CommandIntent.SHOW_ORDERS

# С типом заказа → создание
text = "три кастома заказы мелиса"
intent = classify_intent_v2(text)
# → CommandIntent.CREATE_ORDERS (т.к. есть "кастома")
```

### Пример 4: Требование числа

```python
# С числом → ADD_FILES
text = "мелиса 30 файлов"
intent = classify_intent_v2(text)
# → CommandIntent.ADD_FILES

# Без числа → не ADD_FILES
text = "мелиса файлов"
intent = classify_intent_v2(text)
# → CommandIntent.SEARCH_MODEL (т.к. нет числа)
```

### Пример 5: Извлечение нескольких моделей

```python
from app.router.entities_v2 import extract_model_names

text = "кастом для мелиса софи анна"
models = extract_model_names(text, max_count=3)
# → ['мелиса', 'софи', 'анна']
```

---

## Миграция со старой системы

### Замена в коде

**Старая версия:**
```python
from app.router.intent import classify_intent, Intent
from app.router.entities import extract_entities, Entities

intent = classify_intent(text)  # Intent enum
entities = extract_entities(text)  # Entities dataclass
```

**Новая версия:**
```python
from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import extract_entities_v2
from app.router.command_filters import CommandIntent

intent = classify_intent_v2(text)  # CommandIntent enum
entities = extract_entities_v2(text)  # EntitiesV2 dataclass
```

### Совместимость

Старые файлы (`intent.py`, `entities.py`) сохранены для обратной совместимости.

Можно постепенно мигрировать:

```python
# В dispatcher.py
try:
    from app.router.intent_v2 import classify_intent_v2 as classify_intent
    from app.router.entities_v2 import extract_entities_v2 as extract_entities
    USE_V2 = True
except ImportError:
    from app.router.intent import classify_intent
    from app.router.entities import extract_entities
    USE_V2 = False
```

---

## Тестирование

### Unit-тесты

Создать `tests/test_command_filters.py`:

```python
import pytest
from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import extract_entities_v2
from app.router.command_filters import CommandIntent


class TestIntentClassification:
    """Test intent classification."""

    def test_create_orders_custom(self):
        """Test custom order creation."""
        assert classify_intent_v2("три кастома мелиса") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("кастом для мелисы") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("5 кастомов") == CommandIntent.CREATE_ORDERS

    def test_create_orders_ad_request(self):
        """Test ad request order creation."""
        assert classify_intent_v2("ad request софи") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("ад реквест мелиса") == CommandIntent.CREATE_ORDERS

    def test_show_orders_menu(self):
        """Test showing orders menu."""
        assert classify_intent_v2("заказы") == CommandIntent.SHOW_ORDERS
        assert classify_intent_v2("покажи заказы") == CommandIntent.SHOW_ORDERS

    def test_show_orders_vs_create(self):
        """Test disambiguation between show orders and create orders."""
        # Without order type → show menu
        assert classify_intent_v2("заказы") == CommandIntent.SHOW_ORDERS
        # With order type → create orders
        assert classify_intent_v2("три кастома заказы") == CommandIntent.CREATE_ORDERS

    def test_add_files(self):
        """Test file addition."""
        assert classify_intent_v2("мелиса 30 файлов") == CommandIntent.ADD_FILES
        assert classify_intent_v2("50 фото софи") == CommandIntent.ADD_FILES

    def test_add_files_requires_number(self):
        """Test that file addition requires a number."""
        # With number → ADD_FILES
        assert classify_intent_v2("мелиса 30 файлов") == CommandIntent.ADD_FILES
        # Without number → NOT ADD_FILES
        assert classify_intent_v2("мелиса файлов") != CommandIntent.ADD_FILES


class TestEntityExtraction:
    """Test entity extraction."""

    def test_extract_model_and_number(self):
        """Test extracting model name and number."""
        entities = extract_entities_v2("три кастома мелиса")
        assert entities.model_name == "мелиса"
        assert entities.numbers == [3]
        assert entities.order_type == "custom"

    def test_extract_order_type(self):
        """Test order type extraction."""
        assert extract_entities_v2("кастом мелиса").order_type == "custom"
        assert extract_entities_v2("шорт софи").order_type == "short"
        assert extract_entities_v2("колл анна").order_type == "call"
        assert extract_entities_v2("ad request лиза").order_type == "ad request"

    def test_extract_multiple_numbers(self):
        """Test extracting multiple numbers."""
        entities = extract_entities_v2("3 кастома мелиса 50 файлов")
        assert entities.numbers == [3, 50]
        assert entities.first_number == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### Запуск тестов

```bash
pytest tests/test_command_filters.py -v
```

---

## Преимущества новой системы

### ✅ До vs После

| Аспект | Старая система | Новая система |
|--------|----------------|---------------|
| **Синонимы** | ❌ Жесткий список | ✅ Гибкие паттерны |
| **Склонения** | ❌ Нужно добавлять вручную | ✅ Regex автоматически |
| **Опечатки** | ❌ Не поддерживаются | ✅ Regex с допуском |
| **Многословные фразы** | ❌ Сложная обработка | ✅ Встроенная поддержка |
| **Централизация** | ❌ Разбросано по файлам | ✅ Один файл |
| **Приоритеты** | ❌ Жесткий порядок в коде | ✅ Явная система весов |
| **Расширяемость** | ❌ Сложно добавлять команды | ✅ Просто добавить CommandFilter |

### 🚀 Производительность

- Фильтры сортируются один раз при загрузке
- Regex паттерны компилируются заранее
- Ранний выход при первом совпадении
- O(n) где n = количество фильтров (обычно < 10)

---

## FAQ

**Q: Нужно ли удалять старые файлы?**
A: Нет, они сохранены для обратной совместимости. Можно мигрировать постепенно.

**Q: Как добавить поддержку опечаток?**
A: Использовать regex с optional символами: `r'\bка?сто?м[а-я]*\b'` ловит "касом", "кастм", и т.д.

**Q: Можно ли динамически добавлять фильтры?**
A: Да, `COMMAND_FILTERS.append(CommandFilter(...))` во время runtime.

**Q: Как обрабатывать сложные комбинации?**
A: Использовать `exclude_with` для правил исключения или повысить `priority` более специфичных фильтров.

---

## Контакты и поддержка

При возникновении вопросов или проблем:
- Создайте issue в репозитории
- Обратитесь к команде разработки

---

**Версия документа:** 1.0
**Дата обновления:** 2026-02-03
