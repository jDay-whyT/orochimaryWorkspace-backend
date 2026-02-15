import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.handlers.start import cmd_start
from app.router.command_filters import CommandIntent
from app.router.dispatcher import route_message
from app.services.planner import PlannerService
from app.state.memory import MemoryState


def test_start_sends_only_greeting_without_keyboard():
    message = MagicMock()
    message.from_user.id = 1
    message.chat.id = 100
    message.answer = AsyncMock()
    message.text = "/start"

    config = MagicMock()
    config.allowed_users = {1}
    memory_state = MemoryState()

    asyncio.run(cmd_start(message, config, memory_state))

    assert message.answer.call_count == 1
    _, kwargs = message.answer.call_args
    assert "Привет" in message.answer.call_args.args[0]
    assert kwargs.get("reply_markup") is None


def test_model_text_opens_model_card_with_new_ui_callbacks():
    message = MagicMock()
    message.text = "клещ"
    message.from_user.id = 1
    message.chat.id = 100
    message.answer = AsyncMock()

    config = MagicMock()
    config.allowed_users = {1}
    notion = AsyncMock()
    recent_models = MagicMock()
    memory_state = MemoryState()

    with patch("app.router.dispatcher.prefilter_message", return_value=(True, None)), \
         patch("app.router.dispatcher.extract_entities_v2", return_value=SimpleNamespace(has_model=True, has_numbers=False, model_name="клещ", numbers=[], order_type=None, date=None, first_number=None)), \
         patch("app.router.dispatcher.classify_intent_v2", return_value=CommandIntent.SEARCH_MODEL), \
         patch("app.router.dispatcher.resolve_model", new=AsyncMock(return_value={"status": "found", "model": {"id": "m1", "name": "Клещ"}, "models": []})), \
         patch("app.services.model_card.build_model_card", new=AsyncMock(return_value=("card", 0))):
        asyncio.run(route_message(message, config, notion, memory_state, recent_models))

    assert message.answer.call_count == 1
    kwargs = message.answer.call_args.kwargs
    keyboard = kwargs["reply_markup"]
    callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert any(cb.startswith("ui:model:orders") for cb in callbacks)
    assert any(cb.startswith("ui:model:planner") for cb in callbacks)
    assert any(cb.startswith("ui:model:files") for cb in callbacks)


def test_planner_service_create_shoot_uses_supported_notion_signature():
    config = MagicMock()
    config.notion_token = "tok"
    config.db_planner = "db"

    service = PlannerService(config)
    service.notion = AsyncMock()
    service.notion.create_shoot.return_value = "shoot-id"

    result = asyncio.run(
        service.create_shoot(
            model_id="model-1",
            shoot_date="2026-02-12",
            content=["onlyfans"],
            location="Home",
            comment="test comment",
        )
    )

    assert result == "shoot-id"
    _, kwargs = service.notion.create_shoot.call_args
    assert kwargs["comments"] == "test comment"
    assert "comment" not in kwargs
    assert kwargs["shoot_date"] == date(2026, 2, 12)


def test_planner_upcoming_uses_fallback_name_without_unknown():
    config = MagicMock()
    config.notion_token = "tok"
    config.db_planner = "db"
    service = PlannerService(config)
    service.notion = AsyncMock()
    service.notion.query_upcoming_shoots.return_value = [
        SimpleNamespace(
            page_id="s1",
            model_id="m1",
            model_title=None,
            title="Shoot · 2026-02-12",
            date="2026-02-12",
            status="planned",
            content=[],
            location="Studio",
            comments=None,
        )
    ]
    service.notion.get_model.return_value = SimpleNamespace(title="Клещ")

    data = asyncio.run(service.get_upcoming_shoots())

    assert data[0]["model_name"] == "Клещ"


def test_planner_service_create_shoot_accepts_comments_alias():
    config = MagicMock()
    config.notion_token = "tok"
    config.db_planner = "db"

    service = PlannerService(config)
    service.notion = AsyncMock()
    service.notion.create_shoot.return_value = "shoot-id"

    result = asyncio.run(
        service.create_shoot(
            model_id="model-1",
            shoot_date="2026-02-12",
            content=["onlyfans"],
            location="Home",
            comments="alias comment",
        )
    )

    assert result == "shoot-id"
    _, kwargs = service.notion.create_shoot.call_args
    assert kwargs["comments"] == "alias comment"
