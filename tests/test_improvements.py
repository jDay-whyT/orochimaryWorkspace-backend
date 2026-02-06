"""
Tests for the 5 improvements:
1. SEARCH_MODEL garbage protection (stop-words, looks_like_model_name)
2. TTL cache for build_model_card_text
3. "Close" button hidden when 0 open orders
4. Strict manual files input parsing
5. Menu/Reset always allowed regardless of token/step
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.router.prefilter import STOP_WORDS, is_stop_word, looks_like_model_name
from app.router.entities_v2 import extract_entities_v2, validate_model_name
from app.router.intent_v2 import classify_intent_v2
from app.router.command_filters import CommandIntent
from app.state.memory import MemoryState
from app.state.token import generate_token
from app.keyboards.inline import model_card_keyboard
from app.handlers.nlp_callbacks import _validate_token, _validate_flow_step


# ============================================================================
#  1. SEARCH_MODEL GARBAGE PROTECTION
# ============================================================================

class TestStopWordsNotSearchModel:
    """Stop-words like 'ок', 'да', 'привет' must NOT trigger SEARCH_MODEL."""

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

    @pytest.mark.parametrize("word", GARBAGE_WORDS)
    def test_stop_word_not_search_model_intent(self, word):
        """Stop-word should not produce SEARCH_MODEL intent."""
        entities = extract_entities_v2(word)
        intent = classify_intent_v2(
            word,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent != CommandIntent.SEARCH_MODEL, \
            f"'{word}' triggered SEARCH_MODEL"

    @pytest.mark.parametrize("word", GARBAGE_WORDS)
    def test_stop_word_yields_unknown(self, word):
        """Stop-word should produce UNKNOWN intent."""
        entities = extract_entities_v2(word)
        intent = classify_intent_v2(
            word,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.UNKNOWN, \
            f"'{word}' should be UNKNOWN, got {intent}"

    def test_is_stop_word_function(self):
        """is_stop_word should detect stop-words."""
        assert is_stop_word("ок") is True
        assert is_stop_word("Привет") is True
        assert is_stop_word("мелиса") is False
        assert is_stop_word("клещ") is False

    def test_validate_model_name_rejects_stop_words(self):
        """validate_model_name should reject stop-words."""
        assert validate_model_name("ок") is False
        assert validate_model_name("привет") is False
        assert validate_model_name("мелиса") is True


class TestLooksLikeModelName:
    """Tests for the looks_like_model_name heuristic."""

    def test_valid_model_names(self):
        """Real model names should pass."""
        assert looks_like_model_name("мелиса") is True
        assert looks_like_model_name("polik") is True
        assert looks_like_model_name("anastasia") is True

    def test_stop_words_rejected(self):
        """Stop-words should not look like model names."""
        assert looks_like_model_name("ок") is False
        assert looks_like_model_name("да") is False
        assert looks_like_model_name("привет") is False

    def test_too_short_rejected(self):
        """Very short tokens (< 3 letters) should not pass."""
        assert looks_like_model_name("ab") is False
        assert looks_like_model_name("о") is False

    def test_no_vowels_rejected(self):
        """Tokens with no vowels should not pass."""
        assert looks_like_model_name("бкдфг") is False
        assert looks_like_model_name("bcdfg") is False

    def test_real_model_name_is_still_search_model(self):
        """A real model name like 'мелиса' should still trigger SEARCH_MODEL."""
        entities = extract_entities_v2("мелиса")
        intent = classify_intent_v2(
            "мелиса",
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SEARCH_MODEL


# ============================================================================
#  2. TTL CACHE FOR build_model_card_text
# ============================================================================

class TestModelCardCache:
    """Tests for the in-memory TTL cache on build_model_card_text."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.services.model_card import clear_card_cache
        clear_card_cache()
        yield
        clear_card_cache()

    @pytest.mark.asyncio
    async def test_second_call_uses_cache_no_notion(self):
        """Second call within TTL should NOT call Notion again."""
        from app.services.model_card import build_model_card_text
        from app.services.notion import NotionOrder

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = [
            NotionOrder(page_id="o1", title="t", order_type="custom",
                       in_date="2026-02-01", status="Open"),
        ]
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_accounting_record.return_value = None

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 180
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        # First call — Notion is hit
        text1 = await build_model_card_text("model-x", "TestModel", mock_config, mock_notion)
        assert mock_notion.query_open_orders.call_count == 1

        # Reset call counts
        mock_notion.reset_mock()

        # Second call — should come from cache, no Notion calls
        text2 = await build_model_card_text("model-x", "TestModel", mock_config, mock_notion)
        assert text2 == text1
        assert mock_notion.query_open_orders.call_count == 0
        assert mock_notion.query_upcoming_shoots.call_count == 0
        assert mock_notion.get_accounting_record.call_count == 0

    @pytest.mark.asyncio
    async def test_error_result_cached_shorter(self):
        """Error results should be cached with shorter TTL."""
        from app.services.model_card import (
            build_model_card_text,
            _card_cache,
            CARD_CACHE_ERROR_TTL,
        )

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.side_effect = RuntimeError("down")
        mock_notion.query_upcoming_shoots.side_effect = RuntimeError("down")
        mock_notion.get_accounting_record.side_effect = RuntimeError("down")

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 180
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text("model-err", "ErrModel", mock_config, mock_notion)
        assert "—" in text

        # Check the cache entry is marked as error
        entry = _card_cache.get("model-err")
        assert entry is not None
        _, _, is_error = entry
        assert is_error is True


# ============================================================================
#  3. "CLOSE" BUTTON HIDDEN WHEN 0 OPEN ORDERS
# ============================================================================

class TestCloseButtonHiddenZeroOrders:
    """Tests for hiding '✓ Закрыть' when open_orders == 0."""

    def test_close_button_present_by_default(self):
        """When open_orders is None (unknown), Close button should be shown."""
        kb = model_card_keyboard("test1")
        row2_texts = [btn.text for btn in kb.inline_keyboard[1]]
        assert "✓ Закрыть" in row2_texts

    def test_close_button_present_when_orders_exist(self):
        """When open_orders > 0, Close button should be shown."""
        kb = model_card_keyboard("test1", open_orders=3)
        row2_texts = [btn.text for btn in kb.inline_keyboard[1]]
        assert "✓ Закрыть" in row2_texts

    def test_close_button_hidden_when_zero_orders(self):
        """When open_orders == 0, Close button should be hidden."""
        kb = model_card_keyboard("test1", open_orders=0)
        row2_texts = [btn.text for btn in kb.inline_keyboard[1]]
        assert "✓ Закрыть" not in row2_texts
        # Row 2 should have only 2 buttons (Заказы, Репорт)
        assert len(kb.inline_keyboard[1]) == 2

    def test_keyboard_still_has_three_rows_when_zero_orders(self):
        """Keyboard should always have 3 rows."""
        kb = model_card_keyboard("test1", open_orders=0)
        assert len(kb.inline_keyboard) == 3

    def test_other_buttons_present_when_zero_orders(self):
        """All other buttons should still be present when 0 orders."""
        kb = model_card_keyboard("test1", open_orders=0)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "➕ Заказ" in all_texts
        assert "📅 Съёмка" in all_texts
        assert "📁 Файлы" in all_texts
        assert "📋 Заказы" in all_texts
        assert "📊 Репорт" in all_texts
        # Row 3 (service): Меню and Сброс
        row3_texts = [btn.text for btn in kb.inline_keyboard[2]]
        assert any("Меню" in t for t in row3_texts)
        assert any("Сброс" in t for t in row3_texts)

    def test_all_callbacks_under_64_bytes_zero_orders(self):
        """All callback_data still under 64 bytes with 0 orders."""
        kb = model_card_keyboard("zzzzzz", open_orders=0)
        for row in kb.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode("utf-8")) < 64


# ============================================================================
#  4. STRICT MANUAL FILES INPUT PARSING
# ============================================================================

class TestFilesInputParsing:
    """Tests for _parse_files_count strict parsing."""

    def _parse(self, text: str) -> int | None:
        from app.router.dispatcher import _parse_files_count
        return _parse_files_count(text)

    # === Accepted ===

    def test_plain_number(self):
        assert self._parse("30") == 30

    def test_plus_number(self):
        assert self._parse("+30") == 30

    def test_number_with_files_word(self):
        assert self._parse("30 файлов") == 30

    def test_number_with_short_suffix(self):
        assert self._parse("30ф") == 30

    def test_files_word_then_number(self):
        assert self._parse("файлы 30") == 30

    def test_min_value(self):
        assert self._parse("1") == 1

    def test_max_value(self):
        assert self._parse("500") == 500

    def test_number_with_files_suffix_plural(self):
        assert self._parse("15 файлов") == 15

    # === Rejected ===

    def test_zero_rejected(self):
        assert self._parse("0") is None

    def test_negative_rejected(self):
        assert self._parse("-5") is None

    def test_over_limit_rejected(self):
        assert self._parse("99999") is None

    def test_501_rejected(self):
        assert self._parse("501") is None

    def test_text_without_number_rejected(self):
        assert self._parse("много") is None

    def test_empty_rejected(self):
        assert self._parse("") is None

    def test_random_text_rejected(self):
        assert self._parse("привет мир") is None


# ============================================================================
#  5. MENU/RESET ALWAYS ALLOWED
# ============================================================================

class TestMenuResetAlwaysAllowed:
    """Menu (nlp:x:m) and Reset (nlp:x:c) must work regardless of token/step."""

    def test_cancel_valid_with_no_state(self):
        """Cancel should be valid even with no state at all."""
        assert _validate_token(None, ["nlp", "x", "c"], "x") is True

    def test_menu_valid_with_no_state(self):
        """Menu should be valid even with no state at all."""
        assert _validate_token(None, ["nlp", "x", "m"], "x") is True

    def test_cancel_valid_with_wrong_token(self):
        """Cancel should bypass token validation."""
        state = {"flow": "nlp_order", "step": "awaiting_count", "k": "abc123"}
        assert _validate_token(state, ["nlp", "x", "c"], "x") is True

    def test_cancel_bypasses_flow_step_check(self):
        """Cancel action has no flow/step rule, so it always passes."""
        # Invalid flow/step combination
        state = {"flow": "totally_wrong", "step": "bad_step", "k": "xxx"}
        assert _validate_flow_step(state, "x") is True
        assert _validate_flow_step(None, "x") is True

    def test_cancel_clears_state_in_memory(self):
        """Pressing cancel should clear state from memory."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # Set some random state
        memory.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_count",
            "model_id": "page-123",
            "k": "old_token",
        })

        # Simulate cancel: clear state
        memory.clear(user_id)
        assert memory.get(user_id) is None

    def test_cancel_valid_in_stale_session(self):
        """Cancel should work even in completely stale session."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # Set state with token
        k1 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "k": k1,
        })

        # Change state to a new token (old buttons are stale)
        k2 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": "page-456",
            "k": k2,
        })

        state = memory.get(user_id)

        # Old cancel button with no token — should still pass
        assert _validate_token(state, ["nlp", "x", "c"], "x") is True
        assert _validate_flow_step(state, "x") is True

        # Old action button should fail
        assert _validate_token(state, ["nlp", "act", "order", k1], "act") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
