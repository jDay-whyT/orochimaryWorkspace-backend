"""
Unit tests for model-name entity extraction (app.router.entities_v2).
"""

import pytest

from app.router.entities_v2 import (
    extract_entities_v2,
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
        assert get_order_type_display_name("custom") == "Custom"
        assert get_order_type_display_name("short") == "Short"
        assert get_order_type_display_name("verif reddit") == "verif reddit"
        assert get_order_type_display_name("call") == "Call"
        assert get_order_type_display_name("ad request") == "Ad Request"


class TestStopWordsNotSearchModel:
    """Stop-words like 'ок', 'да', 'привет' must NOT be taken as a model name."""

    GARBAGE_WORDS = [
        "ок", "да", "нет", "привет", "спс", "хз", "ага",
        "угу", "ладно", "ясно", "понял", "хорошо", "спасибо",
        "окей", "hi", "hello", "bye", "пока", "норм",
    ]

    @pytest.mark.parametrize("word", GARBAGE_WORDS)
    def test_stop_word_not_model_name(self, word):
        """Stop-word should not be extracted as model name."""
        entities = extract_entities_v2(word)
        assert entities.model_name is None, \
            f"'{word}' was extracted as model name"

    def test_validate_model_name_rejects_stop_words(self):
        """validate_model_name should reject stop-words."""
        assert validate_model_name("ок") is False
        assert validate_model_name("привет") is False
        assert validate_model_name("мелиса") is True


class TestModelNameToCard:
    """When user types only a model name, it should resolve (triggers model card)."""

    def test_klesh_alone_is_search_model(self):
        """'клещ' -> resolves as model."""
        entities = extract_entities_v2("клещ")
        assert entities.has_model is True

    def test_melisa_with_old_keyword_still_resolves(self):
        """'мелиса файлы 30' -> still resolves model 'мелиса' (keyword is a no-op now)."""
        entities = extract_entities_v2("мелиса файлы 30")
        assert entities.model_name == "мелиса"

    def test_melisa_shoot_still_resolves(self):
        """'съемка мелиса 09.02' -> still resolves model 'мелиса' (keyword is a no-op now)."""
        entities = extract_entities_v2("съемка мелиса 09.02")
        assert entities.model_name == "мелиса"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
