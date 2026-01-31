from unittest.mock import Mock

import pytest

from app.handlers.summary import handle_summary_callback
from app.keyboards import summary_menu_keyboard
from app.state import MemoryState, RecentModels
from tests.fakes import FakeCallbackQuery, FakeMessage
from tests.helpers import last_outgoing


def assert_markup_equal(actual, expected) -> None:
    assert actual is not None
    assert actual.model_dump() == expected.model_dump()


@pytest.mark.asyncio
async def test_summary_back_main_deletes_and_clears(config_admin):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("summary|back|main", message, user_id=111)
    memory_state = MemoryState()
    recent_models = RecentModels()
    memory_state.set(111, {"flow": "summary"})
    clear_mock = Mock(wraps=memory_state.clear)
    memory_state.clear = clear_mock

    await handle_summary_callback(query, config_admin, memory_state, recent_models)

    clear_mock.assert_called_once_with(111)
    assert message.deleted is True


@pytest.mark.asyncio
async def test_summary_back_menu_shows_recent_keyboard_and_clears(config_admin):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("summary|back|menu", message, user_id=111)
    memory_state = MemoryState()
    recent_models = RecentModels()
    recent_models.add(111, "m1", "Alpha")
    memory_state.set(111, {"flow": "summary"})
    clear_mock = Mock(wraps=memory_state.clear)
    memory_state.clear = clear_mock

    await handle_summary_callback(query, config_admin, memory_state, recent_models)

    clear_mock.assert_called_once_with(111)
    last = last_outgoing(message)
    assert last is not None
    assert last["text"] == "📊 <b>Summary</b>\n\n⭐ Recent:\n\nSelect a model:"
    assert_markup_equal(last["reply_markup"], summary_menu_keyboard([("m1", "Alpha")]))
