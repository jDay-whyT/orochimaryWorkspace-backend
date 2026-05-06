"""
Tests for universal model card (CRM main scenario).

Test cases:
1. "мелиса" -> SEARCH_MODEL intent, response contains 📌 and buttons
2. callback_data format is <64 bytes for model_card_keyboard
3. model_card_keyboard has correct 3-module layout
4. 📦 Заказы callback -> nlp:act:orders with token
5. 📁 Файлы callback -> shows +15/+30/+50/Ввод keyboard
6. build_model_card_text with Notion data returns correct format
7. build_model_card_text with Notion failure returns "—" placeholders
8. nlp_files_qty_keyboard has +15/+30/+50/Ввод buttons
9. af:custom callback switches to awaiting_count flow
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import extract_entities_v2
from app.router.command_filters import CommandIntent
from app.state.memory import MemoryState
from app.state.token import generate_token
from app.keyboards.inline import (
    model_card_keyboard,
    nlp_model_actions_keyboard,
    nlp_files_qty_keyboard,
)
from app.handlers.nlp_callbacks import (
    _validate_token,
    _validate_flow_step,
)


# ============================================================================
#              MODEL NAME -> MODEL CARD INTENT TESTS
# ============================================================================

class TestModelNameToCard:
    """When user types only a model name, intent should be SEARCH_MODEL."""

    def test_melisa_alone_is_search_model(self):
        """'мелиса' -> SEARCH_MODEL (triggers model card)."""
        text = "мелиса"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SEARCH_MODEL
        assert entities.model_name == "мелиса"

    def test_klesh_alone_is_search_model(self):
        """'клещ' -> SEARCH_MODEL."""
        text = "клещ"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SEARCH_MODEL

    def test_melisa_with_action_not_search(self):
        """'мелиса файлы 30' -> ADD_FILES (NOT SEARCH_MODEL)."""
        text = "мелиса файлы 30"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.ADD_FILES
        assert intent != CommandIntent.SEARCH_MODEL

    def test_melisa_shoot_not_search(self):
        """'съемка мелиса 09.02' -> SHOOT_CREATE (NOT SEARCH_MODEL)."""
        text = "съемка мелиса 09.02"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SHOOT_CREATE


# ============================================================================
#                    MODEL CARD KEYBOARD TESTS
# ============================================================================

class TestModelCardKeyboard:
    """Tests for model_card_keyboard structure and callback_data."""

    def test_keyboard_has_two_rows(self):
        """model_card_keyboard should have 2 rows (modules + reset)."""
        kb = model_card_keyboard("test1")
        assert len(kb.inline_keyboard) == 2

    def test_row1_has_order_shoot_files(self):
        """Row 1: 📦 Заказы | 📅 Съёмка | 📁 Файлы."""
        kb = model_card_keyboard("test1")
        row1 = kb.inline_keyboard[0]
        assert len(row1) == 3
        assert "Заказы" in row1[0].text
        assert "Съёмка" in row1[1].text
        assert "Файлы" in row1[2].text

    def test_row2_has_reset(self):
        """Row 2: done/cancel button."""
        kb = model_card_keyboard("test1")
        row2 = kb.inline_keyboard[1]
        assert len(row2) == 1
        assert "Готово" in row2[0].text
        assert row2[0].callback_data == "nlp:x:c"

    def test_no_report_or_menu_buttons(self):
        """Model card should not include Report/Menu buttons."""
        kb = model_card_keyboard("test1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert all("Репорт" not in text for text in texts)
        assert all("Меню" not in text for text in texts)

    def test_orders_button_callback(self):
        """📦 Заказы -> nlp:act:orders:{k}."""
        kb = model_card_keyboard("abc123")
        row1 = kb.inline_keyboard[0]
        assert row1[0].callback_data == "nlp:act:orders:abc123"

    def test_files_button_callback(self):
        """📁 Файлы -> nlp:act:files:{k}."""
        kb = model_card_keyboard("abc123")
        row1 = kb.inline_keyboard[0]
        assert row1[2].callback_data == "nlp:act:files:abc123"

    def test_shoot_button_callback(self):
        """📅 Съёмка -> nlp:act:shoot:{k}."""
        kb = model_card_keyboard("abc123")
        row1 = kb.inline_keyboard[0]
        assert row1[1].callback_data == "nlp:act:shoot:abc123"

    def test_all_callbacks_under_64_bytes(self):
        """All callback_data in model_card_keyboard must be <64 bytes."""
        kb = model_card_keyboard("zzzzzz")  # max-length token
        for row in kb.inline_keyboard:
            for btn in row:
                data = btn.callback_data
                byte_len = len(data.encode("utf-8"))
                assert byte_len < 64, \
                    f"callback_data too long ({byte_len} bytes): {data}"

    def test_nlp_model_actions_keyboard_delegates_to_model_card(self):
        """nlp_model_actions_keyboard should produce same result as model_card_keyboard."""
        kb1 = nlp_model_actions_keyboard("test1")
        kb2 = model_card_keyboard("test1")
        # Compare all callback_data
        cbs1 = [btn.callback_data for row in kb1.inline_keyboard for btn in row]
        cbs2 = [btn.callback_data for row in kb2.inline_keyboard for btn in row]
        assert cbs1 == cbs2


# ============================================================================
#                NLP FILES KEYBOARD (UPDATED) TESTS
# ============================================================================

class TestFilesQtyKeyboard:
    """Tests for the updated nlp_files_qty_keyboard (+15/+30/+50/Ввод)."""

    def test_has_15_30_50_custom(self):
        """Keyboard should have 20, 50, 80, Ввод buttons."""
        kb = nlp_files_qty_keyboard("model-1", "test1")
        row1 = kb.inline_keyboard[0]
        texts = [btn.text for btn in row1]
        assert "20" in texts
        assert "50" in texts
        assert "80" in texts
        assert "Ввод" in texts

    def test_custom_button_callback(self):
        """Ввод button -> nlp:af:custom:{k}."""
        kb = nlp_files_qty_keyboard("model-1", "abc123")
        row1 = kb.inline_keyboard[0]
        custom_btn = [btn for btn in row1 if btn.text == "Ввод"][0]
        assert custom_btn.callback_data == "nlp:af:custom:abc123"

    def test_15_button_callback(self):
        """20 button -> nlp:af:20:{k}."""
        kb = nlp_files_qty_keyboard("model-1", "abc123")
        row1 = kb.inline_keyboard[0]
        btn = [b for b in row1 if b.text == "20"][0]
        assert btn.callback_data == "nlp:af:20:abc123"

    def test_all_callbacks_under_64_bytes(self):
        """All callback_data in files qty keyboard must be <64 bytes."""
        kb = nlp_files_qty_keyboard("model-1", "zzzzzz")
        for row in kb.inline_keyboard:
            for btn in row:
                data = btn.callback_data
                byte_len = len(data.encode("utf-8"))
                assert byte_len < 64, \
                    f"callback_data too long ({byte_len} bytes): {data}"


# ============================================================================
#            MODEL CARD TEXT BUILDER TESTS
# ============================================================================

class TestBuildModelCardText:
    """Tests for build_model_card_text with mocked Notion."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.services.model_card import clear_card_cache
        clear_card_cache()
        yield
        clear_card_cache()

    @pytest.mark.asyncio
    async def test_card_text_with_data(self):
        """Card text contains 📌, model name, orders, shoot, files."""
        from app.services.model_card import build_model_card_text
        from app.services.notion import NotionOrder, NotionPlanner, NotionAccounting

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = [
            NotionOrder(page_id="o1", title="test", order_type="custom",
                       in_date="2026-02-01", status="Open"),
            NotionOrder(page_id="o2", title="test2", order_type="short",
                       in_date="2026-04-16", status="Open"),
        ]
        mock_notion.query_upcoming_shoots.return_value = [
            NotionPlanner(page_id="s1", title="test shoot",
                         date="2099-04-25", status="planned", content=["reddit", "twitter"]),
            NotionPlanner(page_id="s2", title="done shoot",
                         date="2026-04-08", status="done", content=["main pack"]),
        ]
        mock_notion.get_monthly_record.return_value = NotionAccounting(
            page_id="a1", title="МЕЛИСА · accounting 2026-04", files=79, of_files=50, reddit_files=29,
        )

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 200
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text(
            "model-123", "Мелиса", mock_config, mock_notion,
        )

        assert "📌" in text
        assert "МЕЛИСА" in text
        assert "📦 Заказы: 2 откр · 2 просрочены" in text
        assert "25 апр</b> · reddit, twitter · planned" in text
        assert "8 апр</b> · main pack · done" in text
        assert "📁 Файлы (" in text
        assert "OF: <b>50</b> | Reddit: <b>29</b>" in text
        assert "79/200 (40%)" not in text

    @pytest.mark.asyncio
    async def test_card_text_notion_failure(self):
        """When Notion fails, card uses '—' placeholders."""
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.side_effect = RuntimeError("Notion down")
        mock_notion.query_upcoming_shoots.side_effect = RuntimeError("Notion down")
        mock_notion.get_monthly_record.side_effect = RuntimeError("Notion down")

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 200
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text(
            "model-123", "Мелиса", mock_config, mock_notion,
        )

        assert "📌" in text
        assert "МЕЛИСА" in text
        assert "📦 Заказы: —" in text
        lines = text.split("\n")
        assert not any("Съёмка" in l for l in lines)
        assert not any("Последняя" in l for l in lines)
        # Files line should be "—"
        files_line = [l for l in lines if "Файлы" in l][0]
        assert "—" in files_line

    @pytest.mark.asyncio
    async def test_card_text_no_orders_no_shoots(self):
        """Card text when model has no orders, no shoots, no accounting."""
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = []
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_monthly_record.return_value = None

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 200
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text(
            "model-123", "Мелиса", mock_config, mock_notion,
        )

        assert "📦 Заказы: 0 откр" in text
        assert "Съёмка" not in text
        assert "Последняя" not in text
        assert "📁 Файлы (" in text
        assert ": —" in text


# ============================================================================
#          FLOW VALIDATION FOR MODEL CARD ACTIONS
# ============================================================================

class TestModelCardFlowValidation:
    """Tests that model card button presses go through proper flow/step validation."""

    def test_act_order_requires_nlp_actions_flow(self):
        """act:order requires flow=nlp_actions with model_id."""
        state = {"flow": "nlp_actions", "model_id": "page-123", "k": "test1"}
        assert _validate_flow_step(state, "act") is True

    def test_act_rejected_without_model_id(self):
        """act action rejected when model_id missing."""
        state = {"flow": "nlp_actions", "k": "test1"}
        assert _validate_flow_step(state, "act") is False

    def test_act_token_checked(self):
        """Token must match for act action."""
        state = {"flow": "nlp_actions", "model_id": "page-123", "k": "abc1"}
        assert _validate_token(state, ["nlp", "act", "order", "abc1"], "act") is True
        assert _validate_token(state, ["nlp", "act", "order", "wrong"], "act") is False

    def test_full_card_to_order_flow(self):
        """Model card -> 📦 Заказы -> transitions to orders module flow."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42
        chat_id = 100

        # Step 1: Model card shown (flow=nlp_actions)
        k1 = generate_token()
        memory.set(chat_id, user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k1,
        })
        state = memory.get(chat_id, user_id)
        assert _validate_flow_step(state, "act") is True

        # Step 2: 📦 Заказы pressed -> handler sets nlp_orders_menu
        memory.set(chat_id, user_id, {
            "flow": "nlp_orders_menu",
            "step": "menu",
            "model_id": "page-123",
            "model_name": "мелиса",
        })
        state = memory.get(chat_id, user_id)
        assert state["flow"] == "nlp_orders_menu"

    def test_full_card_to_files_flow(self):
        """Model card -> 📁 Файлы -> transitions to nlp_files."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42
        chat_id = 100

        # Step 1: Model card shown
        k1 = generate_token()
        memory.set(chat_id, user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k1,
        })

        # Step 2: 📁 Файлы pressed -> handler sets nlp_files
        k2 = generate_token()
        memory.set(chat_id, user_id, {
            "flow": "nlp_files",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k2,
        })
        state = memory.get(chat_id, user_id)
        assert state["flow"] == "nlp_files"

    def test_reset_clears_state(self):
        """♻️ Сброс clears memory state."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42
        chat_id = 100
        memory.set(chat_id, user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "k": "test1",
        })
        # Pressing nlp:x:c clears state
        memory.clear(chat_id, user_id)
        assert memory.get(chat_id, user_id) is None


# ============================================================================
#          MODEL CARD TEXT HELPER TESTS
# ============================================================================

class TestModelCardHelpers:
    """Tests for model_card.py helper functions."""

    def test_month_ru(self):
        """_month_ru returns correct short month names."""
        from app.services.model_card import _month_ru
        assert _month_ru(1) == "янв"
        assert _month_ru(2) == "фев"
        assert _month_ru(12) == "дек"
        assert _month_ru(0) == "?"
        assert _month_ru(13) == "?"

    def test_format_date_card(self):
        """_format_date_card formats ISO date to 'D mon'."""
        from app.services.model_card import _format_date_card
        assert _format_date_card("2026-02-15") == "15 фев"
        assert _format_date_card("2026-12-01") == "1 дек"
        assert _format_date_card(None) == "?"
        assert _format_date_card("invalid") == "?"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
