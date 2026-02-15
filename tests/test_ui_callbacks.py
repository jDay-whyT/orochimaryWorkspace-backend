import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.handlers.ui_callbacks import handle_ui_callback
from app.state.memory import MemoryState
from app.utils.ui_callbacks import build_ui_callback, parse_ui_callback


def _make_query(data: str) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.from_user.id = 1
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.chat.id = 100
    query.message.message_id = 20
    query.message.edit_text = AsyncMock(return_value=query.message)
    query.bot = AsyncMock()
    return query


def test_ui_callback_build_parse_roundtrip() -> None:
    data = build_ui_callback("model", "orders", token="abc")
    parsed = parse_ui_callback(data)
    assert data == "ui:model:orders|abc"
    assert parsed is not None
    assert parsed.module == "model"
    assert parsed.action == "orders"
    assert parsed.token == "abc"


def test_model_orders_callback_opens_orders_menu() -> None:
    memory_state = MemoryState()
    query = _make_query("ui:model:orders|tok1")
    config = MagicMock()
    config.allowed_users = {1}
    notion = AsyncMock()

    memory_state.set(100, 1, {"model_id": "m1", "model_name": "Triko"})

    asyncio.run(handle_ui_callback(query, config, notion, memory_state))

    query.message.edit_text.assert_called_once()
    text = query.message.edit_text.call_args.args[0]
    assert "📦 Заказы" in text


def test_legacy_unknown_nlp_callback_is_graceful_alert() -> None:
    from app.handlers.nlp_callbacks import handle_nlp_callback

    memory_state = MemoryState()
    query = _make_query("nlp:legacy:broken")
    config = MagicMock()
    config.allowed_users = {1}
    notion = AsyncMock()
    recent_models = MagicMock()

    asyncio.run(handle_nlp_callback(query, config, notion, memory_state, recent_models))

    assert query.answer.call_args_list
    args, kwargs = query.answer.call_args_list[0]
    assert kwargs.get("show_alert") is True
    assert "устарел" in args[0].lower()
