import asyncio
from unittest.mock import AsyncMock

from app.handlers.planner import handle_planner_callback, show_planner_menu
from app.services.planner import PlannerService
from tests.fakes import FakeCallbackQuery, FakeMessage
from tests.helpers import assert_contains, last_outgoing


def test_planner_menu_opens(config_admin):
    message = FakeMessage(user_id=111)

    asyncio.run(show_planner_menu(message, config_admin))

    last = last_outgoing(message)
    assert last is not None
    assert_contains(last["text"], ["Planner", "Select"])
    assert last["reply_markup"] is not None


def test_planner_upcoming_error_alert(config_admin, memory_state, recent_models, monkeypatch):
    message = FakeMessage(user_id=111)
    query = FakeCallbackQuery("planner|upcoming|list", message, user_id=111)

    monkeypatch.setattr(
        PlannerService,
        "get_upcoming_shoots",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    asyncio.run(handle_planner_callback(query, config_admin, memory_state, recent_models))

    assert query.callback_answers
    last = query.callback_answers[-1]
    assert_contains(last["text"] or "", ["Error"])
    assert last["show_alert"] is True
