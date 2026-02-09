import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from app.keyboards.inline import (
    nlp_orders_menu_keyboard,
    nlp_files_menu_keyboard,
    nlp_shoot_menu_keyboard,
    nlp_shoot_post_create_keyboard,
    nlp_order_date_keyboard,
    nlp_order_confirm_keyboard,
)
from app.handlers import nlp_callbacks
from app.router.dispatcher import _handle_shoot_comment_input
from app.state.memory import MemoryState
from app.services.notion import NotionOrder, NotionPlanner
from app.utils import PAGE_SIZE


def _make_config(allowed_editors=None):
    cfg = MagicMock()
    cfg.allowed_editors = allowed_editors or set()
    cfg.db_orders = "db_orders"
    cfg.db_planner = "db_planner"
    cfg.db_accounting = "db_accounting"
    cfg.files_per_month = 200
    cfg.timezone = ZoneInfo("Europe/Brussels")
    return cfg


class TestAccessAndBackButtons:
    def test_orders_menu_hides_write_buttons_for_viewer(self):
        kb = nlp_orders_menu_keyboard(can_edit=False, has_orders=True, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "➕ Заказ" not in texts
        assert "✅ Закрыть" not in texts
        assert any("Назад" in t for t in texts)

    def test_files_menu_only_actions_and_back(self):
        kb = nlp_files_menu_keyboard(can_edit=True, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "➕ добавить файлы" in texts
        assert "🗂 тип (контент)" in texts
        assert "💬 обновить коммент" in texts
        assert any("Назад" in t for t in texts)

    def test_files_menu_viewer_only_back(self):
        kb = nlp_files_menu_keyboard(can_edit=False, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert texts == ["⬅ Назад"]

    def test_shoot_menu_has_content_comment_back(self):
        kb = nlp_shoot_menu_keyboard(has_shoot=True, can_edit=True, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "🗂 Content" in texts
        assert "💬 Коммент" in texts
        assert any("Назад" in t for t in texts)


class TestOrderCreationDateFlow:
    def test_date_keyboard_before_confirm(self):
        kb = nlp_order_date_keyboard("m1", "t1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "✅ Создать" not in texts
        assert "📅 Другая дата" in texts

    def test_confirm_keyboard_has_create(self):
        kb = nlp_order_confirm_keyboard("m1", "t2")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "✅ Создать" in texts


class TestOrdersAggregationAndPagination:
    @pytest.mark.asyncio
    async def test_short_order_aggregated(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        memory = MemoryState()
        memory.set(1, {
            "flow": "nlp_order",
            "step": "awaiting_confirm",
            "model_id": "m1",
            "model_name": "Модель",
            "order_type": "short",
            "count": 3,
            "in_date": date(2026, 2, 1).isoformat(),
        })
        recent_models = MagicMock()

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.answer = AsyncMock()

        await nlp_callbacks._handle_order_confirm(
            query, ["nlp", "oc"], config, notion, memory, recent_models,
        )

        assert notion.create_order.call_count == 1
        call_kwargs = notion.create_order.call_args.kwargs
        assert call_kwargs["count"] == 3

    @pytest.mark.asyncio
    async def test_non_short_orders_create_multiple(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        memory = MemoryState()
        memory.set(1, {
            "flow": "nlp_order",
            "step": "awaiting_confirm",
            "model_id": "m1",
            "model_name": "Модель",
            "order_type": "custom",
            "count": 2,
            "in_date": date(2026, 2, 1).isoformat(),
        })
        recent_models = MagicMock()

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.answer = AsyncMock()

        await nlp_callbacks._handle_order_confirm(
            query, ["nlp", "oc"], config, notion, memory, recent_models,
        )

        assert notion.create_order.call_count == 2
        for call in notion.create_order.call_args_list:
            assert call.kwargs["count"] == 1

    @pytest.mark.asyncio
    async def test_orders_view_pagination(self):
        config = _make_config()
        memory = MemoryState()
        orders = [
            NotionOrder(page_id=f"o{i}", title="t", order_type="custom", in_date="2026-02-01")
            for i in range(PAGE_SIZE + 2)
        ]
        memory.set(1, {
            "flow": "nlp_orders_menu",
            "step": "menu",
            "model_id": "m1",
            "model_name": "Модель",
            "orders": orders,
        })
        notion = AsyncMock()

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.answer = AsyncMock()

        await nlp_callbacks._show_orders_view(query, config, notion, memory, page=1)

        _, kwargs = query.message.edit_text.call_args
        reply_markup = kwargs["reply_markup"]
        buttons = [btn.text for row in reply_markup.inline_keyboard for btn in row]
        assert "➡️" in buttons

    @pytest.mark.asyncio
    async def test_close_picker_pagination(self):
        config = _make_config(allowed_editors={1})
        memory = MemoryState()
        orders = [
            NotionOrder(page_id=f"o{i}", title="t", order_type="custom", in_date="2026-02-01")
            for i in range(PAGE_SIZE + 1)
        ]
        notion = AsyncMock()
        notion.query_open_orders.return_value = orders

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.answer = AsyncMock()

        await nlp_callbacks._show_close_picker(
            query, "m1", "Модель", config, notion, memory,
        )

        _, kwargs = query.message.edit_text.call_args
        reply_markup = kwargs["reply_markup"]
        buttons = [btn.text for row in reply_markup.inline_keyboard for btn in row]
        assert "➡️" in buttons


class TestShootContentAndComment:
    @pytest.mark.asyncio
    async def test_shoot_content_updates_notion(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        memory = MemoryState()
        memory.set(1, {
            "flow": "nlp_shoot",
            "step": "awaiting_content_update",
            "shoot_id": "s1",
            "model_id": "m1",
            "model_name": "Модель",
            "content_types": ["Twitter"],
        })
        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.answer = AsyncMock()

        await nlp_callbacks._handle_shoot_content_done(
            query, ["nlp", "scd", "done"], config, notion, memory, MagicMock(),
        )

        notion.update_shoot_content.assert_called_once_with("s1", ["Twitter"])

    @pytest.mark.asyncio
    async def test_shoot_comment_updates_notion(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        notion.get_shoot.return_value = NotionPlanner(
            page_id="s1", title="Shoot", comments="old",
        )
        memory = MemoryState()
        user_state = {
            "flow": "nlp_shoot",
            "step": "awaiting_shoot_comment",
            "shoot_id": "s1",
            "model_name": "Модель",
        }

        message = MagicMock()
        message.from_user.id = 1
        message.answer = AsyncMock()

        await _handle_shoot_comment_input(
            message, "new comment", user_state, config, notion, memory,
        )

        assert notion.update_shoot_comment.called


class TestShootPostCreateKeyboard:
    def test_post_create_has_content_comment_back(self):
        kb = nlp_shoot_post_create_keyboard("s1", "m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "🗂 Content" in texts
        assert "💬 Коммент" in texts
        assert any("Назад" in t for t in texts)
