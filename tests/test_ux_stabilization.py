import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.middlewares.token_validation import TokenValidationMiddleware
from app.router.dispatcher import route_message
from app.router.command_filters import CommandIntent
from app.services.notion import NotionClient
from app.state.memory import MemoryState
from app.utils.nlp import normalize_model_name


def _message(text: str = "клещ") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat.id = 10
    msg.from_user.id = 7
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()
    return msg


def _config() -> MagicMock:
    cfg = MagicMock()
    from datetime import timezone
    cfg.allowed_users = {7}
    cfg.db_models = "db"
    cfg.timezone = timezone.utc
    return cfg


def test_model_text_opens_card():
    message = _message("клещ")
    memory = MemoryState()
    recent = MagicMock()

    entities = SimpleNamespace(
        model_name="клещ",
        numbers=[],
        order_type=None,
        date=None,
        has_model=True,
        has_numbers=False,
    )

    with (
        patch("app.router.dispatcher.prefilter_message", return_value=(True, None)),
        patch("app.router.dispatcher.extract_entities_v2", return_value=entities),
        patch("app.router.dispatcher.classify_intent_v2", return_value=CommandIntent.SEARCH_MODEL),
        patch("app.router.dispatcher.validate_model_name", return_value=True),
        patch("app.router.dispatcher.resolve_model", new=AsyncMock(return_value={"status": "found", "model": {"id": "m1", "name": "Клещ"}})),
        patch("app.services.model_card.build_model_card", new=AsyncMock(return_value=("📌 <b>Клещ</b>\nЧто делаем?", 0))),
    ):
        asyncio.run(route_message(message, _config(), AsyncMock(), memory, recent))

    sent_text = message.answer.call_args.args[0]
    assert "📌 <b>Клещ</b>" in sent_text
    assert "Главное меню" not in sent_text


def test_token_stability_card_to_module_back():
    middleware = TokenValidationMiddleware()
    memory = MemoryState()
    memory.set(1, 7, {"k": "abc123", "model_id": "m1", "model_name": "K"})

    query = MagicMock()
    query.data = "ui:model:orders|abc123"
    query.from_user.id = 7
    query.message = MagicMock()
    query.message.chat.id = 1
    query.answer = AsyncMock()

    async def _ok(event, data):
        return "ok"

    assert asyncio.run(middleware(_ok, query, {"memory_state": memory})) == "ok"
    assert memory.get(1, 7)["k"] == "abc123"


def test_no_stacking_in_callbacks():
    callback_files = [
        "app/handlers/orders.py",
        "app/handlers/planner.py",
        "app/handlers/files.py",
        "app/handlers/ui_callbacks.py",
    ]
    forbidden = ("query.message.answer(", "call.message.answer(", "bot.send_message(", ".reply(")
    for path in callback_files:
        content = open(path, encoding="utf-8").read()
        for token in forbidden:
            assert token not in content, f"{path} contains forbidden callback stack call: {token}"


def test_planner_create_shoot_comment_alias():
    client = NotionClient("token")
    client._request = AsyncMock(return_value={"id": "shoot-1"})

    async def _run():
        a = await client.create_shoot(
            database_id="db",
            model_page_id="m1",
            shoot_date=__import__("datetime").date(2026, 1, 1),
            content=["reel"],
            location="studio",
            title="Shoot",
            comments="new",
        )
        b = await client.create_shoot(
            database_id="db",
            model_page_id="m1",
            shoot_date=__import__("datetime").date(2026, 1, 1),
            content=["reel"],
            location="studio",
            title="Shoot",
            comment="old",
        )
        return a, b

    assert asyncio.run(_run()) == ("shoot-1", "shoot-1")


def test_none_safe_normalize():
    assert normalize_model_name(None) == ""
