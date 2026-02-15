import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.handlers.files import files_menu_router
from app.handlers.orders import handle_orders_callback
from app.handlers.planner import handle_planner_callback
from app.handlers.ui_callbacks import handle_ui_callback
from app.keyboards.inline import (
    build_files_menu_keyboard,
    build_order_card_keyboard_final,
    build_orders_menu_keyboard,
    build_planner_menu_keyboard,
    build_planner_shoot_edit_keyboard,
)
from app.middlewares.token_validation import TokenValidationMiddleware
from app.state.memory import MemoryState


def _query(data: str) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.from_user.id = 1
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.chat.id = 100
    query.message.message_id = 10
    query.message.edit_text = AsyncMock(return_value=query.message)
    query.message.edit_reply_markup = AsyncMock(return_value=query.message)
    return query


def test_orders_token_stable_on_menu_callback() -> None:
    state = MemoryState()
    state.set(100, 1, {"k": "tok", "model_id": "m1", "model_name": "Model"})
    query = _query("orders|menu|menu|tok")
    config = MagicMock()
    config.allowed_users = {1}

    asyncio.run(handle_orders_callback(query, config, AsyncMock(), state, MagicMock()))

    assert (state.get(100, 1) or {}).get("k") == "tok"


def test_planner_token_stable_on_menu_callback() -> None:
    state = MemoryState()
    state.set(100, 1, {"k": "tok", "model_id": "m1", "model_name": "Model"})
    query = _query("planner|menu|menu|tok")
    config = MagicMock()
    config.allowed_users = {1}

    asyncio.run(handle_planner_callback(query, config, AsyncMock(), state, MagicMock()))

    assert (state.get(100, 1) or {}).get("k") == "tok"


def test_files_token_stable_on_menu_callback() -> None:
    state = MemoryState()
    state.set(100, 1, {"k": "tok", "model_id": "m1", "model_name": "Model"})
    query = _query("files|menu|tok")

    asyncio.run(files_menu_router(query, MagicMock(), AsyncMock(), state))

    assert (state.get(100, 1) or {}).get("k") == "tok"


def test_ui_to_orders_and_back_to_card() -> None:
    state = MemoryState()
    state.set(100, 1, {"k": "tok", "model_id": "m1", "model_name": "Model"})
    config = MagicMock()
    config.allowed_users = {1}
    notion = AsyncMock()

    asyncio.run(handle_ui_callback(_query("ui:model:orders|tok"), config, notion, state))

    import app.handlers.orders as orders_module

    orders_module.build_model_card = AsyncMock(return_value=("card", None))
    asyncio.run(handle_orders_callback(_query("orders|back|card|tok"), config, notion, state, MagicMock()))

    assert (state.get(100, 1) or {}).get("k") == "tok"


def test_ui_to_shoot_and_back_to_card() -> None:
    state = MemoryState()
    state.set(100, 1, {"k": "tok", "model_id": "m1", "model_name": "Model"})
    config = MagicMock()
    config.allowed_users = {1}
    notion = AsyncMock()

    asyncio.run(handle_ui_callback(_query("ui:model:shoot|tok"), config, notion, state))

    import app.handlers.planner as planner_module

    planner_module.build_model_card = AsyncMock(return_value=("card", None))
    asyncio.run(handle_planner_callback(_query("planner|back|card|tok"), config, notion, state, MagicMock()))

    assert (state.get(100, 1) or {}).get("k") == "tok"


def test_ui_to_files_and_back_to_card() -> None:
    state = MemoryState()
    state.set(100, 1, {"k": "tok", "model_id": "m1", "model_name": "Model"})
    config = MagicMock()
    config.allowed_users = {1}
    notion = AsyncMock()

    asyncio.run(handle_ui_callback(_query("ui:model:files|tok"), config, notion, state))

    import app.handlers.files as files_module

    files_module.build_model_card = AsyncMock(return_value=("card", None))
    asyncio.run(files_menu_router(_query("files|back|card|tok"), config, notion, state))

    assert (state.get(100, 1) or {}).get("k") == "tok"


def test_middleware_accepts_ui_token() -> None:
    middleware = TokenValidationMiddleware()
    state = MemoryState()
    state.set(100, 1, {"k": "tok"})

    event = _query("ui:model:orders|tok")
    handler = AsyncMock(return_value="ok")

    result = asyncio.run(middleware(handler, event, {"memory_state": state}))

    assert result == "ok"
    handler.assert_awaited_once()


def _family(callback_data: str) -> str:
    if callback_data.startswith("ui:"):
        return "ui"
    if callback_data.startswith(("planner|", "orders|", "files|", "account|", "nlp:")):
        return "legacy"
    return "other"


def test_no_mixed_callback_families_in_keyboards() -> None:
    keyboards = [
        build_orders_menu_keyboard("tok"),
        build_order_card_keyboard_final("id", "tok"),
        build_planner_menu_keyboard("tok"),
        build_planner_shoot_edit_keyboard("id", "tok"),
        build_files_menu_keyboard("tok"),
    ]
    for kb in keyboards:
        families = {
            _family(button.callback_data or "")
            for row in kb.inline_keyboard
            for button in row
            if button.callback_data
        }
        families.discard("other")
        if families == {"legacy", "ui"}:
            callbacks = [
                button.callback_data or ""
                for row in kb.inline_keyboard
                for button in row
            ]
            assert any(cb.startswith("ui:model:card") for cb in callbacks)
        else:
            assert len(families) <= 1


def test_middleware_rejects_missing_token_as_stale() -> None:
    middleware = TokenValidationMiddleware()
    state = MemoryState()
    state.set(100, 1, {"k": "tok"})

    event = _query("orders|menu")
    handler = AsyncMock(return_value="ok")

    result = asyncio.run(middleware(handler, event, {"memory_state": state}))

    assert result is None
    handler.assert_not_awaited()
    event.answer.assert_awaited_once()
