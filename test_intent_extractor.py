#!/usr/bin/env python3
"""Test intent extractor functionality."""

from app.router.extractor import extract


def test_intent_extraction():
    """Test various user inputs for intent extraction."""
    test_cases = [
        # Orders
        ("новый заказ", "orders_new", "orders"),
        ("создать заказ", "orders_new", "orders"),
        ("заказы", "orders_list", "orders"),
        ("открытые заказы", "orders_list", "orders"),
        ("поиск заказа", "orders_search", "orders"),
        ("найти заказ", "orders_search", "orders"),

        # Planner
        ("новый план", "planner_new", "planner"),
        ("планы", "planner_list", "planner"),
        ("стрельба", "planner_list", "planner"),
        ("найти план", "planner_search", "planner"),

        # Accounting
        ("новая запись", "accounting_new", "accounting"),
        ("учет", "accounting_list", "accounting"),
        ("финансы", "accounting_list", "accounting"),
        ("поиск записи", "accounting_search", "accounting"),

        # Summary
        ("сводка", "summary_view", "summary"),
        ("статистика", "summary_view", "summary"),
        ("dashboard", "summary_view", "summary"),
    ]

    print("Testing intent extraction...")
    print("-" * 60)

    passed = 0
    failed = 0

    for user_input, expected_intent, expected_model in test_cases:
        result = extract(user_input)

        if result is None:
            print(f"❌ FAIL: '{user_input}' -> No intent extracted")
            failed += 1
            continue

        intent_ok = result.intent == expected_intent
        model_ok = result.model == expected_model

        if intent_ok and model_ok:
            print(f"✅ PASS: '{user_input}' -> intent={result.intent}, model={result.model}")
            passed += 1
        else:
            print(
                f"❌ FAIL: '{user_input}' -> "
                f"expected ({expected_intent}, {expected_model}), "
                f"got ({result.intent}, {result.model})"
            )
            failed += 1

    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()

    # Test number and date extraction
    print("Testing number and date extraction...")
    print("-" * 60)

    number_tests = [
        ("новый заказ количество 100", [100]),
        ("500 500", [500, 500]),
        ("без чисел", []),
    ]

    for user_input, expected_numbers in number_tests:
        result = extract(user_input)
        if result and result.numbers == expected_numbers:
            print(f"✅ PASS: '{user_input}' -> numbers={result.numbers}")
        else:
            actual = result.numbers if result else []
            print(f"❌ FAIL: '{user_input}' -> expected {expected_numbers}, got {actual}")

    print("-" * 60)
    print()

    # Test complex input
    print("Testing complex inputs with parameters...")
    print("-" * 60)

    complex_tests = [
        "создать новый заказ для модели 'XYZ' на 50 штук на завтра",
        "найти план на этой неделе с датой 25.12",
        "новая запись в учет на 1000 рублей",
    ]

    for user_input in complex_tests:
        result = extract(user_input)
        if result:
            print(f"📝 '{user_input}'")
            print(f"   intent: {result.intent}")
            print(f"   model: {result.model}")
            print(f"   action: {result.action}")
            print(f"   query: '{result.query}'")
            print(f"   numbers: {result.numbers}")
            print(f"   dates: {result.dates}")
            print(f"   confidence: {result.confidence:.2f}")
            print()


if __name__ == "__main__":
    test_intent_extraction()
