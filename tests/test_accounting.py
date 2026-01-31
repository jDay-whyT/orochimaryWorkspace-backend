import asyncio
from unittest.mock import AsyncMock

from app.handlers.accounting import handle_accounting_callback, handle_text_input, show_accounting_menu
from app.services.accounting import AccountingService
from app.services.models import ModelsService
from tests.fakes import FakeCallbackQuery, FakeMessage
from tests.helpers import assert_any_contains, assert_contains, last_outgoing


def test_accounting_menu_opens(config_admin):
    message = FakeMessage(user_id=111)

    asyncio.run(show_accounting_menu(message, config_admin))

    last = last_outgoing(message)
    assert last is not None
    assert_contains(last["text"], ["Accounting", "Select"])
    assert last["reply_markup"] is not None


def test_accounting_search_flow_calls_models_service(
    config_admin,
    memory_state,
    recent_models,
    monkeypatch,
):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("account|search|start", message, user_id=111)

    search_mock = AsyncMock(return_value=[{"id": "m1", "name": "Alpha"}])
    monkeypatch.setattr(ModelsService, "search_models", search_mock)

    asyncio.run(handle_accounting_callback(query, config_admin, memory_state, recent_models))

    input_message = FakeMessage(text="Alpha", user_id=111, bot=message.bot)
    asyncio.run(handle_text_input(input_message, config_admin, memory_state, recent_models))

    search_mock.assert_awaited()
    assert message.bot.calls
    last_call = message.bot.calls[-1]
    assert_contains(last_call["text"], ["Found", "model"])


def test_accounting_notion_error_alert(config_admin, memory_state, recent_models, monkeypatch):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("account|current|month", message, user_id=111)

    monkeypatch.setattr(
        AccountingService,
        "get_current_month_records",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    asyncio.run(handle_accounting_callback(query, config_admin, memory_state, recent_models))

    assert query.callback_answers
    assert_any_contains(query.callback_answers, ["Error"])
    assert query.callback_answers[0]["show_alert"] is True
