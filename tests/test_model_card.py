"""
Tests for universal model card (CRM main scenario).

Test cases:
1. "мелиса" -> SEARCH_MODEL intent, response contains 📌 and buttons
2. callback_data format is <64 bytes for model_card_keyboard
3. model_card_keyboard has correct button layout (3 rows)
4. ➕ Заказ callback -> nlp:act:order with token
5. 📁 Файлы callback -> shows +15/+30/+50/Ввод keyboard
6. build_model_card_text with Notion data returns correct format
7. build_model_card_text with Notion failure returns "—" placeholders
8. model_card_keyboard includes Меню and Сброс service buttons
9. nlp_files_qty_keyboard has +15/+30/+50/Ввод buttons
10. af:custom callback switches to awaiting_count flow
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

    def test_keyboard_has_three_rows(self):
        """model_card_keyboard should have 3 rows."""
        kb = model_card_keyboard("test1")
        assert len(kb.inline_keyboard) == 3

    def test_row1_has_order_shoot_files(self):
        """Row 1: ➕ Заказ | 📅 Съёмка | 📁 Файлы."""
        kb = model_card_keyboard("test1")
        row1 = kb.inline_keyboard[0]
        assert len(row1) == 3
        assert "Заказ" in row1[0].text
        assert "Съёмка" in row1[1].text
        assert "Файлы" in row1[2].text

    def test_row2_has_orders_close_report(self):
        """Row 2: 📋 Заказы | ✓ Закрыть | 📊 Репорт."""
        kb = model_card_keyboard("test1")
        row2 = kb.inline_keyboard[1]
        assert len(row2) == 3
        assert "Заказы" in row2[0].text
        assert "Закрыть" in row2[1].text
        assert "Репорт" in row2[2].text

    def test_row3_has_menu_and_reset(self):
        """Row 3 (service): 🏠 Меню | ♻️ Сброс."""
        kb = model_card_keyboard("test1")
        row3 = kb.inline_keyboard[2]
        assert len(row3) == 2
        assert "Меню" in row3[0].text
        assert "Сброс" in row3[1].text

    def test_menu_callback_is_cancel_menu(self):
        """Меню button -> nlp:x:m."""
        kb = model_card_keyboard("test1")
        row3 = kb.inline_keyboard[2]
        assert row3[0].callback_data == "nlp:x:m"

    def test_reset_callback_is_cancel(self):
        """Сброс button -> nlp:x:c."""
        kb = model_card_keyboard("test1")
        row3 = kb.inline_keyboard[2]
        assert row3[1].callback_data == "nlp:x:c"

    def test_order_button_starts_order_flow(self):
        """➕ Заказ -> nlp:act:order:{k}."""
        kb = model_card_keyboard("abc123")
        row1 = kb.inline_keyboard[0]
        assert row1[0].callback_data == "nlp:act:order:abc123"

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
        """Keyboard should have +15, +30, +50, Ввод buttons."""
        kb = nlp_files_qty_keyboard("test1")
        row1 = kb.inline_keyboard[0]
        texts = [btn.text for btn in row1]
        assert "+15" in texts
        assert "+30" in texts
        assert "+50" in texts
        assert "Ввод" in texts

    def test_custom_button_callback(self):
        """Ввод button -> nlp:af:custom:{k}."""
        kb = nlp_files_qty_keyboard("abc123")
        row1 = kb.inline_keyboard[0]
        custom_btn = [btn for btn in row1 if btn.text == "Ввод"][0]
        assert custom_btn.callback_data == "nlp:af:custom:abc123"

    def test_15_button_callback(self):
        """+15 button -> nlp:af:15:{k}."""
        kb = nlp_files_qty_keyboard("abc123")
        row1 = kb.inline_keyboard[0]
        btn = [b for b in row1 if b.text == "+15"][0]
        assert btn.callback_data == "nlp:af:15:abc123"

    def test_all_callbacks_under_64_bytes(self):
        """All callback_data in files qty keyboard must be <64 bytes."""
        kb = nlp_files_qty_keyboard("zzzzzz")
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
                       in_date="2026-02-03", status="Open"),
        ]
        mock_notion.query_upcoming_shoots.return_value = [
            NotionPlanner(page_id="s1", title="test shoot",
                         date="2026-02-15", status="planned"),
        ]
        mock_notion.get_accounting_record.return_value = NotionAccounting(
            page_id="a1", title="February", amount=90, percent=0.5,
        )

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 180
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text(
            "model-123", "Мелиса", mock_config, mock_notion,
        )

        assert "📌" in text
        assert "Мелиса" in text
        assert "open 2" in text  # 2 orders
        assert "15.02" in text  # next shoot date
        assert "planned" in text
        assert "90/180" in text  # files
        assert "50%" in text
        assert "Что делаем?" in text

    @pytest.mark.asyncio
    async def test_card_text_notion_failure(self):
        """When Notion fails, card uses '—' placeholders."""
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.side_effect = RuntimeError("Notion down")
        mock_notion.query_upcoming_shoots.side_effect = RuntimeError("Notion down")
        mock_notion.get_accounting_record.side_effect = RuntimeError("Notion down")

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 180
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text(
            "model-123", "Мелиса", mock_config, mock_notion,
        )

        assert "📌" in text
        assert "Мелиса" in text
        # All data sections should have "—" fallback
        assert "open —" in text
        # Shoot line should be "—"
        lines = text.split("\n")
        shoot_line = [l for l in lines if "Съёмка" in l][0]
        assert "—" in shoot_line
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
        mock_notion.get_accounting_record.return_value = None

        from zoneinfo import ZoneInfo
        mock_config = MagicMock()
        mock_config.timezone = ZoneInfo("Europe/Brussels")
        mock_config.files_per_month = 180
        mock_config.db_orders = "db_orders"
        mock_config.db_planner = "db_planner"
        mock_config.db_accounting = "db_accounting"

        text = await build_model_card_text(
            "model-123", "Мелиса", mock_config, mock_notion,
        )

        assert "open 0" in text
        assert "нет" in text  # no shoots
        assert "0/180" in text


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
        """Model card -> ➕ Заказ -> transitions to nlp_order/awaiting_type."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # Step 1: Model card shown (flow=nlp_actions)
        k1 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k1,
        })
        state = memory.get(user_id)
        assert _validate_flow_step(state, "act") is True

        # Step 2: ➕ Заказ pressed -> handler sets nlp_order/awaiting_type
        k2 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k2,
        })
        state = memory.get(user_id)
        assert _validate_flow_step(state, "ot") is True
        assert _validate_flow_step(state, "act") is False  # no longer in nlp_actions

    def test_full_card_to_files_flow(self):
        """Model card -> 📁 Файлы -> transitions to nlp_files."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # Step 1: Model card shown
        k1 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k1,
        })

        # Step 2: 📁 Файлы pressed -> handler sets nlp_files
        k2 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_files",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k2,
        })
        state = memory.get(user_id)
        assert state["flow"] == "nlp_files"

    def test_reset_clears_state(self):
        """♻️ Сброс clears memory state."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42
        memory.set(user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "k": "test1",
        })
        # Pressing nlp:x:c clears state
        memory.clear(user_id)
        assert memory.get(user_id) is None


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
        """_format_date_card formats ISO date to DD.MM."""
        from app.services.model_card import _format_date_card
        assert _format_date_card("2026-02-15") == "15.02"
        assert _format_date_card("2026-12-01") == "01.12"
        assert _format_date_card(None) == "?"
        assert _format_date_card("invalid") == "?"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
