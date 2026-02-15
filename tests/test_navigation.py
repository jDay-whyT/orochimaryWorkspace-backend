from unittest.mock import AsyncMock, MagicMock

import asyncio

from app.handlers.start import cmd_cancel
from app.keyboards.inline import back_cancel_keyboard
from app.state.memory import MemoryState
from app.utils.navigation import build_nav_buttons, format_breadcrumbs


def test_format_breadcrumbs_formats_path():
    assert format_breadcrumbs(["📦 Orders", "Model", "#123"]) == "📦 Orders → Model → #123"


def test_build_nav_buttons_builds_standard_row():
    buttons = build_nav_buttons("orders", "📦 Orders", token="abc")

    assert [b.text for b in buttons] == ["◀️ Назад", "📦 Orders", "🏠 Меню"]
    assert [b.callback_data for b in buttons] == [
        "orders|back|back|abc",
        "orders|back|menu|abc",
        "orders|back|main|abc",
    ]


def test_cancel_command_clears_flow_state():
    message = MagicMock()
    message.chat.id = 100
    message.from_user.id = 55
    message.answer = AsyncMock()

    memory = MemoryState()
    memory.set(100, 55, {"flow": "nlp_new_order", "step": "confirm"})

    asyncio.run(cmd_cancel(message, memory))

    assert memory.get(100, 55) is None
    message.answer.assert_awaited_once()
    assert "Текущий флоу отменен" in message.answer.await_args.args[0]


def test_back_cancel_keyboard_uses_return_to_in_callback_data():
    keyboard = back_cancel_keyboard("files", token="abc")
    rows = keyboard.inline_keyboard

    assert rows[0][0].callback_data == "files|back|files|abc"
    assert rows[0][1].callback_data == "files|cancel|cancel|abc"
