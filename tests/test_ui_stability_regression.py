import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.handlers.files import files_menu_router
from app.handlers.ui_callbacks import handle_ui_callback
from app.keyboards.inline import (
    build_files_menu_keyboard,
    build_orders_menu_keyboard,
    build_planner_menu_keyboard,
    build_planner_shoot_edit_keyboard,
    model_card_keyboard,
)
from app.middlewares.token_validation import TokenValidationMiddleware
from app.state.memory import MemoryState


def _query(data: str, chat_id: int = 1, user_id: int = 7) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.from_user.id = user_id
    query.message = MagicMock()
    query.message.chat.id = chat_id
    query.message.message_id = 11
    query.message.edit_text = AsyncMock()
    query.message.edit_reply_markup = AsyncMock()
    query.answer = AsyncMock()
    return query


def _config() -> MagicMock:
    cfg = MagicMock()
    cfg.allowed_users = {7}
    cfg.allowed_editors = {7}
    return cfg


def test_token_stability_ui_to_files_and_back_to_card():
    memory = MemoryState()
    memory.set(1, 7, {"flow": "nlp_idle", "model_id": "m1", "model_name": "Triko", "k": "abc123"})

    notion = AsyncMock()
    q1 = _query("ui:model:files|abc123")
    asyncio.run(handle_ui_callback(q1, _config(), notion, memory))
    assert memory.get(1, 7)["k"] == "abc123"

    q2 = _query("files|back|card|abc123")
    with patch("app.handlers.files.build_model_card", new=AsyncMock(return_value=("CARD", 0))):
        asyncio.run(files_menu_router(q2, _config(), notion, memory))

    assert memory.get(1, 7)["k"] == "abc123"
    q2.message.edit_text.assert_awaited()


def test_token_validation_accepts_ui_and_legacy_with_same_token():
    middleware = TokenValidationMiddleware()
    memory = MemoryState()
    memory.set(1, 7, {"k": "abc123"})

    async def _ok_handler(event, data):
        return "ok"

    ui_event = _query("ui:model:orders|abc123")
    legacy_event = _query("orders|open|list|abc123")

    ui_result = asyncio.run(middleware(_ok_handler, ui_event, {"memory_state": memory}))
    legacy_result = asyncio.run(middleware(_ok_handler, legacy_event, {"memory_state": memory}))

    assert ui_result == "ok"
    assert legacy_result == "ok"


def test_no_mixed_callback_families_in_key_keyboards():
    keyboards = [
        model_card_keyboard("tok"),
        build_orders_menu_keyboard("tok"),
        build_planner_menu_keyboard("tok"),
        build_files_menu_keyboard("tok"),
        build_planner_shoot_edit_keyboard("shoot-1", "tok"),
    ]

    for kb in keyboards:
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        legacy_callbacks = [c for c in callbacks if c and not c.startswith("ui:")]
        ui_callbacks = [c for c in callbacks if c and c.startswith("ui:")]
        mixed_allowed = set(ui_callbacks).issubset({"ui:model:card|tok"})
        assert not (legacy_callbacks and ui_callbacks and not mixed_allowed), callbacks
