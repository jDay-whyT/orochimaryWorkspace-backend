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
from unittest.mock import AsyncMock, MagicMock

from app.keyboards.inline import (
    model_card_keyboard,
    nlp_files_qty_keyboard,
)
from app.services.model_card import build_model_card_text
from app.services.notion import NotionNote


# ============================================================================
#              MODEL NAME -> MODEL CARD INTENT TESTS
# ============================================================================

# ============================================================================
#                    MODEL CARD KEYBOARD TESTS
# ============================================================================

class TestModelCardKeyboard:
    """Tests for model_card_keyboard structure and callback_data."""

    def test_row2_has_note_and_done(self):
        """Row 2: note button + done button."""
        kb = model_card_keyboard("test1")
        row2 = kb.inline_keyboard[1]
        assert len(row2) == 2
        texts = [btn.text for btn in row2]
        assert any("Note" in t for t in texts)
        assert any("Done" in t for t in texts)
        done_btn = next(b for b in row2 if "Done" in b.text)
        assert done_btn.callback_data == "nlp:x:c"
        note_btn = next(b for b in row2 if "Note" in b.text)
        assert note_btn.callback_data == "nlp:act:note:test1"

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

# ============================================================================
#                NLP FILES KEYBOARD (UPDATED) TESTS
# ============================================================================

class TestFilesQtyKeyboard:
    """Tests for the updated nlp_files_qty_keyboard (+15/+30/+50/Ввод)."""

    def test_custom_button_callback(self):
        """Ввод button -> nlp:af:custom:{k}."""
        kb = nlp_files_qty_keyboard("model-1", "abc123")
        row1 = kb.inline_keyboard[0]
        custom_btn = [btn for btn in row1 if btn.text == "Enter"][0]
        assert custom_btn.callback_data == "nlp:af:custom:abc123"

    def test_15_button_callback(self):
        """20 button -> nlp:af:20:{k}."""
        kb = nlp_files_qty_keyboard("model-1", "abc123")
        row1 = kb.inline_keyboard[0]
        btn = [b for b in row1 if b.text == "20"][0]
        assert btn.callback_data == "nlp:af:20:abc123"

# ============================================================================
#            MODEL CARD TEXT BUILDER TESTS
# ============================================================================

class TestBuildModelCardText:
    """Tests for build_model_card_text with mocked Notion."""

    @pytest.mark.asyncio
    async def test_card_text_with_data(self, card_config):
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
        ]
        mock_notion.query_last_done_shoot.return_value = NotionPlanner(
            page_id="s2", title="done shoot", date="2026-04-08", status="done", content=["main pack"])
        mock_notion.get_model.return_value = MagicMock(status="work")
        mock_notion.get_monthly_record.return_value = NotionAccounting(
            page_id="a1", title="МЕЛИСА · accounting 2026-04", files=79, of_files=50, reddit_files=29,
        )

        text = await build_model_card_text(
            "model-123", "Мелиса", card_config, mock_notion,
        )

        assert "📌" in text
        assert "МЕЛИСА" in text
        assert "📌 <b>МЕЛИСА</b> · work" in text
        assert "📦 Orders: 2 open · ⚠️ 2 overdue" in text
        assert "📅 Next: <b>25 Apr</b> · reddit, twitter · planned" in text
        assert "    Last: 8 Apr · main pack" in text
        assert "<b>79</b> files" in text and "    OF 50 · Reddit 29" in text
        assert "79/200 (40%)" not in text

    @pytest.mark.asyncio
    async def test_card_text_notion_failure(self, card_config):
        """When Notion fails, card uses '—' placeholders."""
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.side_effect = RuntimeError("Notion down")
        mock_notion.query_upcoming_shoots.side_effect = RuntimeError("Notion down")
        mock_notion.get_monthly_record.side_effect = RuntimeError("Notion down")

        text = await build_model_card_text(
            "model-123", "Мелиса", card_config, mock_notion,
        )

        assert "📌" in text
        assert "МЕЛИСА" in text
        assert "📦 Orders: —" in text
        lines = text.split("\n")
        assert not any("Съёмка" in l for l in lines)
        assert not any("Последняя" in l for l in lines)
        # Files line should be "—"
        files_line = [l for l in lines if l.startswith("📁")][0]
        assert "—" in files_line

    @pytest.mark.asyncio
    async def test_card_text_no_orders_no_shoots(self, card_config):
        """Card text when model has no orders, no shoots, no accounting."""
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = []
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_monthly_record.return_value = None

        text = await build_model_card_text(
            "model-123", "Мелиса", card_config, mock_notion,
        )

        assert "📦 Orders: 0 open" in text
        assert "<b>0</b> files" in text
        assert "📅 Next: —" in text


# ============================================================================
#          FLOW VALIDATION FOR MODEL CARD ACTIONS
# ============================================================================

# ============================================================================
#          MODEL CARD TEXT HELPER TESTS
# ============================================================================

class TestModelCardHelpers:
    """Tests for model_card.py helper functions."""

    def test_month_ru(self):
        """_month_ru returns correct short month names."""
        from app.services.model_card import _month_ru
        assert _month_ru(1) == "Jan"
        assert _month_ru(2) == "Feb"
        assert _month_ru(12) == "Dec"
        assert _month_ru(0) == "?"
        assert _month_ru(13) == "?"

    def test_format_date_card(self):
        """_format_date_card formats ISO date to 'D mon'."""
        from app.services.model_card import _format_date_card
        assert _format_date_card("2026-02-15") == "15 Feb"
        assert _format_date_card("2026-12-01") == "1 Dec"
        assert _format_date_card(None) == "?"
        assert _format_date_card("invalid") == "?"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
#     CARD AFTER AN ACTION ("+ More"): no stale cache, no Notion query lag
# ============================================================================

class TestCardAfterWrite:
    @staticmethod
    def _order_page(pid, status="Open", out=None, model="model-1"):
        return {
            "object": "page", "id": pid, "parent": {"database_id": "db-orders"},
            "properties": {
                "Title": {"type": "title", "title": [{"plain_text": "M | custom 1/1"}]},
                "model": {"type": "relation", "relation": [{"id": model}]},
                "type": {"type": "select", "select": {"name": "custom"}},
                "in": {"type": "date", "date": {"start": "2099-01-01"}},
                "out": {"type": "date", "date": {"start": out} if out else None},
                "status": {"type": "select", "select": {"name": status}},
                "count": {"type": "number", "number": 1},
            },
        }

    def _notion(self, open_orders):
        from app.services.notion import NotionClient
        notion = object.__new__(NotionClient)
        notion._recent_pages, notion._created_pages, notion._model_writes = {}, set(), {}
        notion.query_open_orders = AsyncMock(return_value=open_orders)
        notion.query_upcoming_shoots = AsyncMock(return_value=[])
        notion.get_monthly_record = AsyncMock(return_value=None)
        notion.get_recent_notes = AsyncMock(return_value=[])
        return notion

    @pytest.fixture(autouse=True)
    def _ids(self, card_config):
        card_config.db_orders, card_config.db_planner, card_config.db_accounting, card_config.db_notes = "db-orders", "db-planner", "db-acc", ""

    @pytest.mark.asyncio
    async def test_new_order_shows_up_although_the_query_lags(self, card_config):
        from app.services.model_card import build_model_card
        notion = self._notion([])
        text, _ = await build_model_card("model-1", "M", card_config, notion)
        assert "📦 Orders: 0 open" in text
        # the bot creates an order; the database query does not return it yet
        notion._remember_write("POST", "https://api.notion.com/v1/pages", self._order_page("o-new"))
        text, count = await build_model_card("model-1", "M", card_config, notion)
        assert count == 1 and "📦 Orders: 1 open" in text   # cache skipped, new order merged in

    @pytest.mark.asyncio
    async def test_closed_order_disappears_although_the_query_lags(self, card_config):
        from app.services.model_card import build_model_card
        from app.services.notion import _parse_order
        page = self._order_page("0a1b-2c3d")
        notion = self._notion([_parse_order(page)])
        notion._remember_write("PATCH", "https://api.notion.com/v1/pages/0a1b-2c3d",
                               self._order_page("0a1b-2c3d", status="Done", out="2099-01-02"))
        _, count = await build_model_card("model-1", "M", card_config, notion)
        assert count == 0

    @pytest.mark.asyncio
    async def test_other_models_writes_do_not_touch_the_card(self, card_config):
        from app.services.model_card import build_model_card
        notion = self._notion([])
        await build_model_card("model-1", "M", card_config, notion)
        notion._remember_write("POST", "https://api.notion.com/v1/pages", self._order_page("o-x", model="model-2"))
        _, count = await build_model_card("model-1", "M", card_config, notion)
        assert count == 0 and notion.query_open_orders.await_count == 1  # still served from cache

    def test_queries_are_not_remembered_as_writes(self):
        notion = self._notion([])
        notion._remember_write("POST", "https://api.notion.com/v1/databases/db-orders/query",
                               {"object": "list", "results": []})
        notion._remember_write("POST", "https://api.notion.com/v1/pages", {"object": "page", "id": "p1",
                               "parent": {"database_id": "db-orders"}, "properties": {}})
        assert [p["id"] for p in notion.recent_pages_in("db-orders", created_only=True)] == ["p1"]


@pytest.mark.asyncio
async def test_card_next_shoot_without_date_and_overdue(card_config):
    from app.services.model_card import build_model_card_text
    from app.services.notion import NotionPlanner

    notion = AsyncMock()
    notion.query_open_orders.return_value = []
    notion.get_monthly_record.return_value = None
    notion.query_last_done_shoot.return_value = None
    notion.get_model.return_value = None
    config = card_config
    config.db_notes = ""

    notion.query_upcoming_shoots.return_value = [
        NotionPlanner(page_id="s1", title="s", date=None, status="planned", content=["reddit"])]
    text = await build_model_card_text("m-a", "A", config, notion)
    assert "📅 Next: no date yet · reddit · planned" in text and "Last:" not in text

    notion.query_upcoming_shoots.return_value = [
        NotionPlanner(page_id="s2", title="s", date="2020-01-02", status="scheduled", content=[])]
    text = await build_model_card_text("m-b", "B", config, notion)
    assert "📅 Next: ⚠️ <b>2 Jan</b> · — · scheduled" in text


# ============================================================================
#          CARD CACHE / NOTE PREVIEW
# ============================================================================

class TestModelCardCache:
    """Tests for the in-memory TTL cache on build_model_card_text."""

    @pytest.mark.asyncio
    async def test_second_call_uses_cache_no_notion(self, card_config):
        """Second call within TTL should NOT call Notion again."""
        from app.services.model_card import build_model_card_text
        from app.services.notion import NotionOrder

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = [
            NotionOrder(page_id="o1", title="t", order_type="custom",
                       in_date="2026-02-01", status="Open"),
        ]
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_monthly_record.return_value = None

        # First call — Notion is hit
        text1 = await build_model_card_text("model-x", "TestModel", card_config, mock_notion)
        assert mock_notion.query_open_orders.call_count == 1

        # Reset call counts
        mock_notion.reset_mock()

        # Second call — should come from cache, no Notion calls
        text2 = await build_model_card_text("model-x", "TestModel", card_config, mock_notion)
        assert text2 == text1
        assert mock_notion.query_open_orders.call_count == 0
        assert mock_notion.query_upcoming_shoots.call_count == 0
        assert mock_notion.get_monthly_record.call_count == 0

    @pytest.mark.asyncio
    async def test_error_result_cached_shorter(self, card_config):
        """Error results should be cached with shorter TTL."""
        from app.services.model_card import (
            build_model_card_text,
            _card_cache,
            CARD_CACHE_ERROR_TTL,
        )

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.side_effect = RuntimeError("down")
        mock_notion.query_upcoming_shoots.side_effect = RuntimeError("down")
        mock_notion.get_monthly_record.side_effect = RuntimeError("down")

        text = await build_model_card_text("model-err", "ErrModel", card_config, mock_notion)
        assert "—" in text

        # Check the cache entry is marked as error
        entry = _card_cache.get("model-err")
        assert entry is not None
        _, _, is_error = entry
        assert is_error is True


async def _card_with_note(text: str, card_config) -> tuple[str, AsyncMock]:
    notion = AsyncMock()
    notion.query_open_orders.return_value = []
    notion.query_upcoming_shoots.return_value = []
    notion.get_monthly_record.return_value = None
    notion.get_recent_notes.return_value = [NotionNote(page_id="n1", text=text, date="2026-09-20")]

    card_config.db_notes = "db_notes"

    card = await build_model_card_text("model-1", "Robin", card_config, notion)
    return card, notion


@pytest.mark.asyncio
async def test_only_latest_note_is_requested(card_config):
    _, notion = await _card_with_note("коротко", card_config)
    assert notion.get_recent_notes.await_args.kwargs["limit"] == 1


@pytest.mark.asyncio
async def test_multiline_note_shows_first_line_only(card_config):
    card, _ = await _card_with_note("первая строка\nвторая строка\nтретья", card_config)
    assert "первая строка …" in card
    assert "вторая строка" not in card
    assert "📝 Заметки" not in card


@pytest.mark.asyncio
async def test_long_note_is_truncated(card_config):
    card, _ = await _card_with_note("а" * 300, card_config)
    assert "а" * 100 + "…" in card
    assert "а" * 101 not in card
