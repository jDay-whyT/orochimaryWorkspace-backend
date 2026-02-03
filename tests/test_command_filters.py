"""
Unit tests for command filters system.

Tests intent classification and entity extraction with various inputs.
"""

import pytest

from app.router.intent_v2 import classify_intent_v2, get_intent_description
from app.router.entities_v2 import (
    extract_entities_v2,
    extract_model_names,
    validate_model_name,
    get_order_type_display_name,
)
from app.router.command_filters import CommandIntent


class TestIntentClassification:
    """Test intent classification with various inputs."""

    # ========== CREATE_ORDERS ==========

    def test_create_orders_custom_basic(self):
        """Test basic custom order creation."""
        assert classify_intent_v2("кастом мелиса") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("три кастома мелиса") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("5 кастомов") == CommandIntent.CREATE_ORDERS

    def test_create_orders_custom_variations(self):
        """Test custom order with word variations."""
        assert classify_intent_v2("кастома мелиса") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("кастомов для софи") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("кастомчик") == CommandIntent.CREATE_ORDERS

    def test_create_orders_custom_english(self):
        """Test custom order in English."""
        assert classify_intent_v2("custom melissa") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("3 customs") == CommandIntent.CREATE_ORDERS

    def test_create_orders_short(self):
        """Test short order creation."""
        assert classify_intent_v2("шорт мелиса") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("два шорта") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("short melissa") == CommandIntent.CREATE_ORDERS

    def test_create_orders_call(self):
        """Test call order creation."""
        assert classify_intent_v2("колл софи") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("три колла") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("call sophia") == CommandIntent.CREATE_ORDERS

    def test_create_orders_ad_request(self):
        """Test ad request order creation (multi-word phrase)."""
        assert classify_intent_v2("ad request софи") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("ад реквест мелиса") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("ad request melissa 2 штуки") == CommandIntent.CREATE_ORDERS

    # ========== ADD_FILES ==========

    def test_add_files_basic(self):
        """Test file addition with number."""
        assert classify_intent_v2("мелиса 30 файлов") == CommandIntent.ADD_FILES
        assert classify_intent_v2("50 фото софи") == CommandIntent.ADD_FILES
        assert classify_intent_v2("добавь 100 файлов мелиса") == CommandIntent.ADD_FILES

    def test_add_files_variations(self):
        """Test file addition with word variations."""
        assert classify_intent_v2("мелиса 20 файла") == CommandIntent.ADD_FILES
        assert classify_intent_v2("30 файлов для софи") == CommandIntent.ADD_FILES
        assert classify_intent_v2("файлики 50 мелиса") == CommandIntent.ADD_FILES

    def test_add_files_requires_number(self):
        """Test that file addition requires a number."""
        # With number → ADD_FILES
        assert classify_intent_v2("мелиса 30 файлов") == CommandIntent.ADD_FILES
        # Without number → NOT ADD_FILES
        assert classify_intent_v2("мелиса файлов") != CommandIntent.ADD_FILES
        assert classify_intent_v2("файлы для мелисы") != CommandIntent.ADD_FILES

    def test_add_files_english(self):
        """Test file addition in English."""
        assert classify_intent_v2("melissa 50 files") == CommandIntent.ADD_FILES
        assert classify_intent_v2("30 photos sophia") == CommandIntent.ADD_FILES

    # ========== GET_REPORT ==========

    def test_get_report_basic(self):
        """Test report generation."""
        assert classify_intent_v2("репорт мелиса") == CommandIntent.GET_REPORT
        assert classify_intent_v2("отчет софи") == CommandIntent.GET_REPORT
        assert classify_intent_v2("статистика мелиса") == CommandIntent.GET_REPORT

    def test_get_report_variations(self):
        """Test report with word variations."""
        assert classify_intent_v2("репорта мелиса") == CommandIntent.GET_REPORT
        assert classify_intent_v2("стат для софи") == CommandIntent.GET_REPORT
        assert classify_intent_v2("статистику покажи") == CommandIntent.GET_REPORT

    def test_get_report_english(self):
        """Test report in English."""
        assert classify_intent_v2("report melissa") == CommandIntent.GET_REPORT
        assert classify_intent_v2("stats sophia") == CommandIntent.GET_REPORT

    # ========== SHOW_SUMMARY ==========

    def test_show_summary_basic(self):
        """Test summary menu."""
        assert classify_intent_v2("сводка") == CommandIntent.SHOW_SUMMARY
        assert classify_intent_v2("покажи сводку") == CommandIntent.SHOW_SUMMARY
        assert classify_intent_v2("summary") == CommandIntent.SHOW_SUMMARY

    def test_show_summary_variations(self):
        """Test summary with variations."""
        assert classify_intent_v2("сводки") == CommandIntent.SHOW_SUMMARY
        assert classify_intent_v2("сводк") == CommandIntent.SHOW_SUMMARY

    # ========== SHOW_ORDERS ==========

    def test_show_orders_basic(self):
        """Test orders menu."""
        assert classify_intent_v2("заказы") == CommandIntent.SHOW_ORDERS
        assert classify_intent_v2("покажи заказы") == CommandIntent.SHOW_ORDERS
        assert classify_intent_v2("orders") == CommandIntent.SHOW_ORDERS

    def test_show_orders_vs_create_orders(self):
        """Test disambiguation between show orders and create orders."""
        # Without order type → SHOW_ORDERS
        assert classify_intent_v2("заказы") == CommandIntent.SHOW_ORDERS
        assert classify_intent_v2("покажи заказы") == CommandIntent.SHOW_ORDERS

        # With order type → CREATE_ORDERS (exclude rule)
        assert classify_intent_v2("три кастома заказы") == CommandIntent.CREATE_ORDERS
        assert classify_intent_v2("заказы шорт мелиса") == CommandIntent.CREATE_ORDERS

    # ========== SHOW_PLANNER ==========

    def test_show_planner_basic(self):
        """Test planner menu."""
        assert classify_intent_v2("планировщик") == CommandIntent.SHOW_PLANNER
        assert classify_intent_v2("план") == CommandIntent.SHOW_PLANNER
        assert classify_intent_v2("planner") == CommandIntent.SHOW_PLANNER

    def test_show_planner_variations(self):
        """Test planner with variations."""
        assert classify_intent_v2("планировщика") == CommandIntent.SHOW_PLANNER
        assert classify_intent_v2("планер") == CommandIntent.SHOW_PLANNER
        assert classify_intent_v2("planning") == CommandIntent.SHOW_PLANNER

    # ========== SHOW_ACCOUNT ==========

    def test_show_account_basic(self):
        """Test account menu."""
        assert classify_intent_v2("аккаунт") == CommandIntent.SHOW_ACCOUNT
        assert classify_intent_v2("бухгалтерия") == CommandIntent.SHOW_ACCOUNT
        assert classify_intent_v2("account") == CommandIntent.SHOW_ACCOUNT

    def test_show_account_variations(self):
        """Test account with variations."""
        assert classify_intent_v2("аккаунта") == CommandIntent.SHOW_ACCOUNT
        assert classify_intent_v2("акк") == CommandIntent.SHOW_ACCOUNT
        assert classify_intent_v2("бух") == CommandIntent.SHOW_ACCOUNT
        assert classify_intent_v2("accounting") == CommandIntent.SHOW_ACCOUNT

    # ========== SEARCH_MODEL ==========

    def test_search_model_single_word(self):
        """Test model search with single word."""
        assert classify_intent_v2("мелиса") == CommandIntent.SEARCH_MODEL
        assert classify_intent_v2("софи") == CommandIntent.SEARCH_MODEL

    def test_search_model_two_words(self):
        """Test model search with two words."""
        assert classify_intent_v2("melissa smith") == CommandIntent.SEARCH_MODEL

    # ========== UNKNOWN ==========

    def test_unknown_empty(self):
        """Test unknown intent for empty text."""
        assert classify_intent_v2("") == CommandIntent.UNKNOWN
        assert classify_intent_v2("   ") == CommandIntent.UNKNOWN

    def test_unknown_gibberish(self):
        """Test unknown intent for gibberish."""
        assert classify_intent_v2("asdfghjkl") == CommandIntent.UNKNOWN
        assert classify_intent_v2("123 456 789") == CommandIntent.UNKNOWN


class TestEntityExtraction:
    """Test entity extraction from messages."""

    # ========== Model Name Extraction ==========

    def test_extract_model_basic(self):
        """Test basic model name extraction."""
        entities = extract_entities_v2("мелиса")
        assert entities.model_name == "мелиса"

        entities = extract_entities_v2("три кастома мелиса")
        assert entities.model_name == "мелиса"

    def test_extract_model_with_noise(self):
        """Test model extraction with command keywords."""
        entities = extract_entities_v2("добавь кастом для мелиса")
        assert entities.model_name == "мелиса"

        entities = extract_entities_v2("покажи репорт софи")
        assert entities.model_name == "софи"

    def test_extract_model_ignores_keywords(self):
        """Test that command keywords are not extracted as model names."""
        entities = extract_entities_v2("кастом заказ")
        # "кастом" and "заказ" are both keywords, so no model name
        assert entities.model_name is None

    # ========== Number Extraction ==========

    def test_extract_single_number(self):
        """Test single number extraction."""
        entities = extract_entities_v2("три кастома мелиса")
        assert entities.numbers == [3]

        entities = extract_entities_v2("50 файлов софи")
        assert entities.numbers == [50]

    def test_extract_multiple_numbers(self):
        """Test multiple numbers extraction."""
        entities = extract_entities_v2("3 кастома мелиса 50 файлов")
        assert entities.numbers == [3, 50]

        entities = extract_entities_v2("100 200 300")
        assert entities.numbers == [100, 200, 300]

    def test_extract_no_numbers(self):
        """Test extraction when no numbers present."""
        entities = extract_entities_v2("мелиса кастом")
        assert entities.numbers == []

    def test_first_number_property(self):
        """Test first_number property."""
        entities = extract_entities_v2("3 кастома 50 файлов")
        assert entities.first_number == 3

        entities = extract_entities_v2("мелиса")
        assert entities.first_number is None

    # ========== Order Type Extraction ==========

    def test_extract_order_type_custom(self):
        """Test custom order type extraction."""
        entities = extract_entities_v2("кастом мелиса")
        assert entities.order_type == "custom"

        entities = extract_entities_v2("три кастома")
        assert entities.order_type == "custom"

    def test_extract_order_type_short(self):
        """Test short order type extraction."""
        entities = extract_entities_v2("шорт софи")
        assert entities.order_type == "short"

    def test_extract_order_type_call(self):
        """Test call order type extraction."""
        entities = extract_entities_v2("колл мелиса")
        assert entities.order_type == "call"

    def test_extract_order_type_ad_request(self):
        """Test ad request order type extraction (multi-word)."""
        entities = extract_entities_v2("ad request софи")
        assert entities.order_type == "ad request"

        entities = extract_entities_v2("ад реквест мелиса 2 штуки")
        assert entities.order_type == "ad request"

    def test_extract_no_order_type(self):
        """Test when no order type present."""
        entities = extract_entities_v2("мелиса 30 файлов")
        assert entities.order_type is None

    # ========== Full Entity Extraction ==========

    def test_extract_full_create_orders(self):
        """Test full entity extraction for create orders."""
        entities = extract_entities_v2("три кастома мелиса")
        assert entities.model_name == "мелиса"
        assert entities.numbers == [3]
        assert entities.order_type == "custom"

    def test_extract_full_add_files(self):
        """Test full entity extraction for add files."""
        entities = extract_entities_v2("мелиса 30 файлов")
        assert entities.model_name == "мелиса"
        assert entities.numbers == [30]
        assert entities.order_type is None

    def test_extract_full_ad_request(self):
        """Test full entity extraction for ad request."""
        entities = extract_entities_v2("ad request софи 2 штуки")
        assert entities.model_name == "софи"
        assert entities.numbers == [2]
        assert entities.order_type == "ad request"


class TestExtractMultipleModels:
    """Test extracting multiple model names."""

    def test_extract_two_models(self):
        """Test extracting two model names."""
        models = extract_model_names("мелиса и софи")
        assert models == ["мелиса", "софи"]

    def test_extract_three_models(self):
        """Test extracting three model names."""
        models = extract_model_names("кастом для мелиса софи анна")
        assert models == ["мелиса", "софи", "анна"]

    def test_extract_with_max_count(self):
        """Test max_count limit."""
        models = extract_model_names("мелиса софи анна лиза", max_count=2)
        assert len(models) == 2
        assert models == ["мелиса", "софи"]

    def test_extract_with_conjunctions(self):
        """Test that conjunctions are skipped."""
        models = extract_model_names("мелиса и софи or анна")
        # "и" and "or" should be skipped
        assert "и" not in models
        assert "or" not in models


class TestValidateModelName:
    """Test model name validation."""

    def test_valid_model_names(self):
        """Test valid model names."""
        assert validate_model_name("мелиса") is True
        assert validate_model_name("софи") is True
        assert validate_model_name("melissa") is True

    def test_invalid_too_short(self):
        """Test invalid: too short."""
        assert validate_model_name("м") is False
        assert validate_model_name("a") is False

    def test_invalid_only_numbers(self):
        """Test invalid: only numbers."""
        assert validate_model_name("123") is False
        assert validate_model_name("50") is False

    def test_invalid_keywords(self):
        """Test invalid: ignore keywords."""
        assert validate_model_name("кастом") is False
        assert validate_model_name("файл") is False
        assert validate_model_name("заказы") is False

    def test_invalid_none_or_empty(self):
        """Test invalid: None or empty."""
        assert validate_model_name(None) is False
        assert validate_model_name("") is False


class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_intent_description(self):
        """Test intent description."""
        assert "Создание заказов" in get_intent_description(CommandIntent.CREATE_ORDERS)
        assert "Добавление файлов" in get_intent_description(CommandIntent.ADD_FILES)

    def test_get_order_type_display_name(self):
        """Test order type display name."""
        assert get_order_type_display_name("custom") == "Кастом"
        assert get_order_type_display_name("short") == "Шорт"
        assert get_order_type_display_name("call") == "Колл"
        assert get_order_type_display_name("ad request") == "Ad Request"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
