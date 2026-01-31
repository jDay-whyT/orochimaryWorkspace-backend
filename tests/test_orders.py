import asyncio
from datetime import date
from unittest.mock import AsyncMock

from app.handlers.orders import handle_orders_callback, show_orders_menu
from app.state import MemoryState
from tests.fakes import FakeCallbackQuery, FakeMessage
from tests.helpers import assert_called_with, assert_contains, extract_last_text, last_outgoing


def test_orders_menu_opens(config_admin):
    message = FakeMessage(user_id=111)

    asyncio.run(show_orders_menu(message, config_admin))

    last = last_outgoing(message)
    assert last is not None
    assert_contains(last["text"], ["Orders", "Select"])
    assert last["reply_markup"] is not None


def test_orders_open_error_alert(config_admin, notion_mock, recent_models):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("orders|open|noop", message, user_id=111)
    memory_state = MemoryState()
    memory_state.set(111, {"model_id": "model-1", "model_title": "Test Model"})

    notion_mock.query_open_orders = AsyncMock(side_effect=RuntimeError("boom"))

    asyncio.run(handle_orders_callback(query, config_admin, notion_mock, memory_state, recent_models))

    assert query.callback_answers
    last = query.callback_answers[-1]
    assert_contains(last["text"] or "", ["Error", "try"])
    assert last["show_alert"] is True


def test_orders_create_calls_notion(config_admin, notion_mock, recent_models):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("orders|confirm|ok", message, user_id=111)
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

    asyncio.run(handle_orders_callback(query, config_admin, notion_mock, memory_state, recent_models))

    expected_date = date(2024, 1, 15)
    assert_called_with(
        notion_mock.create_order,
        config_admin.db_orders,
        "model-123",
        "Test",
        expected_date,
        count=1,
        comments="note",
    )

    last = last_outgoing(message)
    assert last is not None
    assert_contains(last["text"], ["Order", "Created"])
