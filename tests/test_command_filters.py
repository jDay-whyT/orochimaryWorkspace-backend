"""
Unit tests for model-name entity extraction (app.router.entities_v2).
"""

import pytest

from app.router.entities_v2 import (
    extract_entities_v2,
    extract_model_names,
    validate_model_name,
    get_order_type_display_name,
)


class TestEntityExtraction:
    """Test model-name extraction from messages."""

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

    def test_extract_multi_word_model(self):
        """Test multi-word model name extraction."""
        entities = extract_entities_v2("мона лиза")
        assert entities.model_name == "мона лиза"


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


class TestOrderTypeDisplayName:
    """Test order type display name (still used by button-driven order flows)."""

    def test_get_order_type_display_name(self):
        """Test order type display name."""
        assert get_order_type_display_name("custom") == "Кастом"
        assert get_order_type_display_name("short") == "Шорт"
        assert get_order_type_display_name("verif reddit") == "verif reddit"
        assert get_order_type_display_name("call") == "Колл"
        assert get_order_type_display_name("ad request") == "Ad Request"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
