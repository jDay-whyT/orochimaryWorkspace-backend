#!/usr/bin/env python3
"""
Simple integration test for command filter system.
Tests the v2 classification and entity extraction without aiogram dependencies.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Import directly from modules to avoid aiogram dependency
from app.router.command_filters import CommandIntent
from app.router.intent_v2 import classify_intent_v2, get_intent_description
from app.router.entities_v2 import extract_entities_v2


def run_case(text: str, expected_intent: CommandIntent = None):
    """Test a single command and display results."""
    print(f"\n{'='*70}")
    print(f"Текст: '{text}'")
    print('-' * 70)

    # Classify intent
    intent = classify_intent_v2(text)
    description = get_intent_description(intent)

    # Extract entities
    entities = extract_entities_v2(text)

    # Display results
    print(f"Intent:      {intent.value} ({description})")
    print(f"Модель:      {entities.model_name}")
    print(f"Числа:       {entities.numbers}")
    print(f"Тип заказа:  {entities.order_type}")

    # Check if matches expected
    if expected_intent:
        status = "✅" if intent == expected_intent else "❌"
        print(f"Ожидалось:   {expected_intent.value} {status}")

    return intent == expected_intent if expected_intent else True


def main():
    """Run all test cases."""
    print("\n" + "="*70)
    print("ТЕСТИРОВАНИЕ ИНТЕГРАЦИИ СИСТЕМЫ ФИЛЬТРОВ КОМАНД")
    print("="*70)

    test_cases = [
        # Menu commands
        ("сводка", CommandIntent.SHOW_SUMMARY),
        ("заказы", CommandIntent.SHOW_ORDERS),
        ("планировщик", CommandIntent.SHOW_PLANNER),
        ("аккаунт", CommandIntent.SHOW_ACCOUNT),

        # Create orders
        ("три кастома мелиса", CommandIntent.CREATE_ORDERS),
        ("5 шортов софи", CommandIntent.CREATE_ORDERS),
        ("колл анна", CommandIntent.CREATE_ORDERS),
        ("ad request мелиса 2 штуки", CommandIntent.CREATE_ORDERS),

        # Add files (requires number)
        ("мелиса 30 файлов", CommandIntent.ADD_FILES),
        ("50 фото софи", CommandIntent.ADD_FILES),
        ("мелиса файлов", CommandIntent.SEARCH_MODEL),  # No number -> NOT ADD_FILES

        # Reports
        ("репорт мелиса", CommandIntent.GET_REPORT),
        ("статистика софи", CommandIntent.GET_REPORT),

        # Model search
        ("мелиса", CommandIntent.SEARCH_MODEL),
        ("софи", CommandIntent.SEARCH_MODEL),

        # Disambiguation tests
        ("заказы", CommandIntent.SHOW_ORDERS),  # Without order type -> menu
        ("три кастома заказы", CommandIntent.CREATE_ORDERS),  # With order type -> create

        # Word variations
        ("кастом мелиса", CommandIntent.CREATE_ORDERS),
        ("кастома мелиса", CommandIntent.CREATE_ORDERS),
        ("кастомов мелиса", CommandIntent.CREATE_ORDERS),

        # Multi-word phrases
        ("ad request софи", CommandIntent.CREATE_ORDERS),
        ("ад реквест мелиса", CommandIntent.CREATE_ORDERS),
    ]

    passed = 0
    failed = 0

    for text, expected in test_cases:
        if run_case(text, expected):
            passed += 1
        else:
            failed += 1

    # Summary
    print("\n" + "="*70)
    print(f"РЕЗУЛЬТАТЫ: {passed} успешных, {failed} ошибок")
    print("="*70 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
