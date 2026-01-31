from unittest.mock import AsyncMock, Mock

import pytest

from app.handlers.orders import handle_orders_callback, handle_text_input
from app.keyboards import back_cancel_keyboard, orders_menu_keyboard, recent_models_keyboard
from app.state import MemoryState, RecentModels
from tests.fakes import FakeCallbackQuery, FakeMessage
from tests.helpers import last_outgoing


def assert_markup_equal(actual, expected) -> None:
    assert actual is not None
    assert actual.model_dump() == expected.model_dump()


@pytest.mark.asyncio
async def test_orders_permission_denied_new_order(config_viewer, notion_mock):
    message = FakeMessage(user_id=222)
    query = FakeCallbackQuery("orders|new|start", message, user_id=222)
    memory_state = MemoryState()
    recent_models = RecentModels()

    await handle_orders_callback(query, config_viewer, notion_mock, memory_state, recent_models)

    assert query.callback_answers
    last = query.callback_answers[-1]
    assert last["text"] == "You don't have permission to create orders"
    assert last["show_alert"] is True
    assert message.edits == []


@pytest.mark.asyncio
async def test_orders_confirm_missing_data_clears_state(config_admin, notion_mock):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("orders|confirm|create", message, user_id=111)
    memory_state = MemoryState()
    recent_models = RecentModels()
    memory_state.set(111, {"model_id": "model-1"})
    clear_mock = Mock(wraps=memory_state.clear)
    memory_state.clear = clear_mock

    await handle_orders_callback(query, config_admin, notion_mock, memory_state, recent_models)

    assert query.callback_answers
    last = query.callback_answers[-1]
    assert last["text"] == "Missing data. Please start over."
    assert last["show_alert"] is True
    clear_mock.assert_called_once_with(111)
    assert memory_state.get(111) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["0", "abc", "100"])
async def test_orders_qty_invalid_shows_prompt(config_admin, notion_mock, recent_models, text):
    memory_state = MemoryState()
    memory_state.set(111, {"flow": "new_order", "step": "waiting_qty"})
    message = FakeMessage(text=text, user_id=111)

    await handle_text_input(message, config_admin, notion_mock, memory_state, recent_models)

    last = last_outgoing(message)
    assert last is not None
    assert last["text"] == "Please enter a number between 1 and 99:"
    assert_markup_equal(last["reply_markup"], back_cancel_keyboard("orders"))


@pytest.mark.asyncio
async def test_orders_create_order_notion_failure_alert(config_admin, notion_mock, recent_models):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("orders|confirm|create", message, user_id=111)
    memory_state = MemoryState()
    memory_state.set(
        111,
        {
            "model_id": "model-123",
            "model_title": "Model Name",
            "order_type": "Test",
            "qty": 1,
            "in_date": "2024-01-15",
            "comments": "note",
        },
    )
    notion_mock.create_order = AsyncMock(side_effect=Exception("boom"))

    await handle_orders_callback(query, config_admin, notion_mock, memory_state, recent_models)

    assert query.callback_answers
    last = query.callback_answers[-1]
    assert last["text"] == "Failed to create order"
    assert last["show_alert"] is True
    assert message.edits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["main", "menu"])
async def test_orders_handle_back_main_menu(config_admin, notion_mock, recent_models, value):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery(f"orders|back|{value}", message, user_id=111)
    memory_state = MemoryState()
    memory_state.set(111, {"flow": "new_order"})
    clear_mock = Mock(wraps=memory_state.clear)
    memory_state.clear = clear_mock

    await handle_orders_callback(query, config_admin, notion_mock, memory_state, recent_models)

    clear_mock.assert_called_once_with(111)
    last = last_outgoing(message)
    assert last is not None
    assert last["text"] == "📦 <b>Orders</b>\n\nSelect an action:"
    assert_markup_equal(last["reply_markup"], orders_menu_keyboard())


@pytest.mark.asyncio
async def test_orders_handle_back_model_select_recent_and_no_recent(config_admin, notion_mock):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("orders|back|model_select", message, user_id=111)
    memory_state = MemoryState()
    recent_models = RecentModels()
    recent_models.add(111, "m1", "Alpha")

    await handle_orders_callback(query, config_admin, notion_mock, memory_state, recent_models)

    last = last_outgoing(message)
    assert last is not None
    assert last["text"] == "Select model:"
    assert_markup_equal(last["reply_markup"], recent_models_keyboard([("m1", "Alpha")], "orders"))

    message_empty = FakeMessage(user_id=111)
    query_empty = FakeCallbackQuery("orders|back|model_select", message_empty, user_id=111)
    memory_state_empty = MemoryState()
    recent_models_empty = RecentModels()

    await handle_orders_callback(
        query_empty,
        config_admin,
        notion_mock,
        memory_state_empty,
        recent_models_empty,
    )

    last_empty = last_outgoing(message_empty)
    assert last_empty is not None
    assert last_empty["text"] == "🔍 Enter model name to search:"
    assert_markup_equal(last_empty["reply_markup"], back_cancel_keyboard("orders"))
    assert memory_state_empty.get(111)["flow"] == "search"
    assert memory_state_empty.get(111)["step"] == "waiting_query"
