"""
Practical examples of using the new command filter system.

This file demonstrates:
- How to use the classifier and extractor
- Common use cases
- Integration patterns
- Edge cases handling
"""

import sys
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.router.intent_v2 import classify_intent_v2, get_intent_description
from app.router.entities_v2 import (
    extract_entities_v2,
    extract_model_names,
    validate_model_name,
)
from app.router.command_filters import CommandIntent


# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def example_1_basic_classification():
    """Example 1: Basic intent classification."""
    logger.info("\n" + "="*60)
    logger.info("Example 1: Basic Intent Classification")
    logger.info("="*60)

    test_cases = [
        "три кастома мелиса",
        "мелиса 30 файлов",
        "репорт мелиса",
        "сводка",
        "заказы",
        "планировщик",
        "аккаунт",
        "мелиса",
    ]

    for text in test_cases:
        intent = classify_intent_v2(text)
        description = get_intent_description(intent)
        logger.info(f"  '{text}' → {intent.value} ({description})")


def example_2_entity_extraction():
    """Example 2: Entity extraction from messages."""
    logger.info("\n" + "="*60)
    logger.info("Example 2: Entity Extraction")
    logger.info("="*60)

    test_cases = [
        "три кастома мелиса",
        "мелиса 30 файлов",
        "ad request софи 2 штуки",
        "50 фото для мелисы",
        "репорт мелиса за месяц",
    ]

    for text in test_cases:
        entities = extract_entities_v2(text)
        logger.info(f"\n  Текст: '{text}'")
        logger.info(f"    Модель: {entities.model_name}")
        logger.info(f"    Числа: {entities.numbers}")
        logger.info(f"    Тип заказа: {entities.order_type}")


def example_3_word_variations():
    """Example 3: Word variations and declensions."""
    logger.info("\n" + "="*60)
    logger.info("Example 3: Word Variations (Склонения)")
    logger.info("="*60)

    # Все эти варианты должны распознаваться как CREATE_ORDERS
    variations = [
        "кастом мелиса",       # nominative
        "кастома мелиса",      # genitive
        "кастомов мелиса",     # genitive plural
        "кастомчик мелиса",    # diminutive
        "три кастома",
        "пять кастомов",
    ]

    logger.info("\n  Все варианты слова 'кастом':")
    for text in variations:
        intent = classify_intent_v2(text)
        entities = extract_entities_v2(text)
        status = "✓" if intent == CommandIntent.CREATE_ORDERS else "✗"
        logger.info(
            f"    {status} '{text}' → {intent.value} "
            f"(order_type={entities.order_type})"
        )


def example_4_multi_word_phrases():
    """Example 4: Multi-word phrase detection."""
    logger.info("\n" + "="*60)
    logger.info("Example 4: Multi-word Phrases")
    logger.info("="*60)

    # "ad request" должен распознаваться как единое целое
    test_cases = [
        "ad request софи",
        "ад реквест мелиса",
        "ad request melissa 2 штуки",
        "три ad request для софи",
    ]

    logger.info("\n  'ad request' как единая фраза:")
    for text in test_cases:
        entities = extract_entities_v2(text)
        logger.info(
            f"    '{text}'\n"
            f"      → order_type='{entities.order_type}', model='{entities.model_name}'"
        )


def example_5_disambiguation():
    """Example 5: Disambiguation with exclude rules."""
    logger.info("\n" + "="*60)
    logger.info("Example 5: Disambiguation (Правила исключения)")
    logger.info("="*60)

    # "заказы" без типа → SHOW_ORDERS
    # "заказы" с типом → CREATE_ORDERS
    test_cases = [
        ("заказы", CommandIntent.SHOW_ORDERS),
        ("покажи заказы", CommandIntent.SHOW_ORDERS),
        ("три кастома заказы", CommandIntent.CREATE_ORDERS),
        ("заказы шорт мелиса", CommandIntent.CREATE_ORDERS),
    ]

    logger.info("\n  Различие между SHOW_ORDERS и CREATE_ORDERS:")
    for text, expected in test_cases:
        intent = classify_intent_v2(text)
        status = "✓" if intent == expected else "✗"
        logger.info(f"    {status} '{text}' → {intent.value} (ожидалось: {expected.value})")


def example_6_number_requirement():
    """Example 6: Commands that require numbers."""
    logger.info("\n" + "="*60)
    logger.info("Example 6: Number Requirement (requires_number)")
    logger.info("="*60)

    # ADD_FILES требует число
    test_cases = [
        ("мелиса 30 файлов", CommandIntent.ADD_FILES, True),
        ("50 фото софи", CommandIntent.ADD_FILES, True),
        ("мелиса файлов", CommandIntent.ADD_FILES, False),  # НЕТ числа
        ("файлы для мелисы", CommandIntent.ADD_FILES, False),  # НЕТ числа
    ]

    logger.info("\n  ADD_FILES требует число:")
    for text, expected_intent, should_match in test_cases:
        intent = classify_intent_v2(text)
        is_add_files = intent == CommandIntent.ADD_FILES
        status = "✓" if is_add_files == should_match else "✗"
        logger.info(
            f"    {status} '{text}' → {intent.value} "
            f"(ADD_FILES={is_add_files}, ожидалось={should_match})"
        )


def example_7_priority_system():
    """Example 7: Priority-based classification."""
    logger.info("\n" + "="*60)
    logger.info("Example 7: Priority System (Система приоритетов)")
    logger.info("="*60)

    # Приоритет: SHOW_SUMMARY (100) > CREATE_ORDERS (50)
    # Если в тексте и "сводка" и "кастом", должна распознаться "сводка"
    test_cases = [
        ("сводка", CommandIntent.SHOW_SUMMARY),
        ("сводка кастом мелиса", CommandIntent.SHOW_SUMMARY),  # приоритет выше
        ("кастом для сводки", CommandIntent.CREATE_ORDERS),  # "сводки" в родительном падеже - менее точное совпадение
    ]

    logger.info("\n  Меню-команды (priority=100) > Действия (priority=50):")
    for text, expected in test_cases:
        intent = classify_intent_v2(text)
        status = "✓" if intent == expected else "✗"
        logger.info(f"    {status} '{text}' → {intent.value}")


def example_8_multiple_models():
    """Example 8: Extracting multiple model names."""
    logger.info("\n" + "="*60)
    logger.info("Example 8: Multiple Model Names")
    logger.info("="*60)

    test_cases = [
        "мелиса и софи",
        "кастом для мелиса софи анна",
        "три кастома мелиса софи",
    ]

    logger.info("\n  Извлечение нескольких моделей:")
    for text in test_cases:
        models = extract_model_names(text, max_count=5)
        logger.info(f"    '{text}' → {models}")


def example_9_model_name_validation():
    """Example 9: Model name validation."""
    logger.info("\n" + "="*60)
    logger.info("Example 9: Model Name Validation")
    logger.info("="*60)

    test_cases = [
        ("мелиса", True),
        ("софи", True),
        ("melissa", True),
        ("м", False),  # too short
        ("123", False),  # only numbers
        ("кастом", False),  # keyword
        ("файл", False),  # keyword
        ("", False),  # empty
    ]

    logger.info("\n  Проверка корректности имени модели:")
    for name, expected in test_cases:
        is_valid = validate_model_name(name)
        status = "✓" if is_valid == expected else "✗"
        logger.info(f"    {status} '{name}' → valid={is_valid} (ожидалось: {expected})")


def example_10_real_world_cases():
    """Example 10: Real-world test cases."""
    logger.info("\n" + "="*60)
    logger.info("Example 10: Real-World Cases (Реальные сценарии)")
    logger.info("="*60)

    test_cases = [
        # Создание заказов
        "три кастома мелиса",
        "5 шортов для софи",
        "колл мелиса на завтра",
        "ad request софи 2 штуки",

        # Добавление файлов
        "мелиса 30 файлов",
        "добавь 50 фото для мелисы",
        "софи 100 файлов новых",

        # Отчеты
        "репорт мелиса",
        "статистика софи за месяц",
        "покажи стат мелиса",

        # Меню
        "сводка",
        "заказы",
        "планировщик",
        "аккаунт",

        # Поиск модели
        "мелиса",
        "найди софи",
    ]

    logger.info("\n  Реальные примеры использования:")
    for text in test_cases:
        intent = classify_intent_v2(text)
        entities = extract_entities_v2(text)
        logger.info(
            f"\n    Текст: '{text}'\n"
            f"      Intent: {intent.value}\n"
            f"      Модель: {entities.model_name}\n"
            f"      Числа: {entities.numbers}\n"
            f"      Тип: {entities.order_type}"
        )


def example_11_integration_pattern():
    """Example 11: Integration pattern in message handler."""
    logger.info("\n" + "="*60)
    logger.info("Example 11: Integration Pattern (Паттерн интеграции)")
    logger.info("="*60)

    logger.info("\n  Пример использования в обработчике сообщений:\n")

    example_code = '''
async def handle_message(message: Message, ...):
    """Handle incoming text message."""
    text = message.text

    # Step 1: Classify intent
    intent = classify_intent_v2(text)

    # Step 2: Extract entities
    entities = extract_entities_v2(text)

    # Step 3: Route to appropriate handler
    if intent == CommandIntent.CREATE_ORDERS:
        if not entities.has_model:
            await message.answer("❌ Укажите имя модели")
            return

        await handle_create_orders(
            message,
            model_name=entities.model_name,
            quantity=entities.first_number or 1,
            order_type=entities.order_type,
        )

    elif intent == CommandIntent.ADD_FILES:
        if not entities.has_model or not entities.has_numbers:
            await message.answer("❌ Укажите модель и количество файлов")
            return

        await handle_add_files(
            message,
            model_name=entities.model_name,
            file_count=entities.first_number,
        )

    elif intent == CommandIntent.SHOW_SUMMARY:
        await show_summary_menu(message)

    # ... и так далее
    '''

    logger.info(example_code)


def main():
    """Run all examples."""
    logger.info("\n" + "="*60)
    logger.info("COMMAND FILTER SYSTEM - PRACTICAL EXAMPLES")
    logger.info("="*60)

    examples = [
        example_1_basic_classification,
        example_2_entity_extraction,
        example_3_word_variations,
        example_4_multi_word_phrases,
        example_5_disambiguation,
        example_6_number_requirement,
        example_7_priority_system,
        example_8_multiple_models,
        example_9_model_name_validation,
        example_10_real_world_cases,
        example_11_integration_pattern,
    ]

    for example in examples:
        try:
            example()
        except Exception as e:
            logger.error(f"\n  ❌ Error in {example.__name__}: {e}")

    logger.info("\n" + "="*60)
    logger.info("All examples completed!")
    logger.info("="*60 + "\n")


if __name__ == "__main__":
    main()
