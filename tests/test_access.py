"""Managers approved in the bot: request -> owner button -> access lists."""

import asyncio
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.filters.topic_access import TopicAccessCallbackFilter, TopicAccessMessageFilter
from app.handlers import access as access_handlers
from app.handlers import notifications
from app.services import access
from tests.conftest import FakeRedis

OWNER_ID = 1
ROBIN_ID = 2
DI_ID = 3
NEW_ID = 10


@dataclass(frozen=True)
class FakeConfig:
    allowed_editors: set = field(default_factory=lambda: {OWNER_ID, ROBIN_ID, DI_ID})
    manager_targets: dict = field(default_factory=lambda: {"di": (DI_ID, None)})
    digest_user_ids: set = field(default_factory=lambda: {DI_ID})
    owner_telegram_id: int = OWNER_ID
    db_accounting: str = "acc-db"
    mini_app_viewer_ids: set = field(default_factory=lambda: {77})
    mini_app_viewer_handles: set = field(default_factory=lambda: {"@viewer"})


@pytest.fixture
def config():
    return FakeConfig()


@pytest.fixture
def redis():
    return FakeRedis()


# ---------- service ----------

@pytest.mark.asyncio
async def test_approve_adds_editor_target_and_digest_keeping_env(config, redis):
    await access.save_request(redis, NEW_ID, "caramel_mgr", "Caramel")
    info = await access.approve(config, redis, NEW_ID, "caramel")

    assert info["username"] == "caramel_mgr"
    assert config.allowed_editors == {OWNER_ID, ROBIN_ID, DI_ID, NEW_ID}
    assert config.manager_targets == {"di": (DI_ID, None), "caramel": (NEW_ID, None)}
    assert config.digest_user_ids == {DI_ID, NEW_ID}
    assert await access.get_request(redis, NEW_ID) is None


@pytest.mark.asyncio
async def test_revoke_removes_only_approved_user(config, redis):
    await access.approve(config, redis, NEW_ID, "ng")
    await access.revoke(config, redis, NEW_ID)

    assert config.allowed_editors == {OWNER_ID, ROBIN_ID, DI_ID}
    assert config.manager_targets == {"di": (DI_ID, None)}
    assert config.digest_user_ids == {DI_ID}


@pytest.mark.asyncio
async def test_approved_user_cannot_take_over_env_manager_target(config, redis):
    await access.approve(config, redis, NEW_ID, "di")
    assert config.manager_targets["di"] == (DI_ID, None)


@pytest.mark.asyncio
async def test_no_assist_gives_access_without_reminders(config, redis):
    await access.approve(config, redis, NEW_ID, access.NO_ASSIST)
    assert NEW_ID in config.allowed_editors
    assert config.manager_targets == {"di": (DI_ID, None)}


@pytest.mark.asyncio
async def test_request_is_not_repeated_while_pending_or_rejected(redis):
    assert await access.save_request(redis, NEW_ID, "x", "X") is True
    assert await access.save_request(redis, NEW_ID, "x", "X") is False
    await access.reject(redis, NEW_ID)
    assert await access.save_request(redis, NEW_ID, "x", "X") is False
    assert (await access.get_request(redis, NEW_ID))["status"] == "rejected"


@pytest.mark.asyncio
async def test_refresh_is_throttled_but_force_reloads(config, redis):
    await access.refresh(config, redis, force=True)
    await redis.hset(access.MANAGERS_KEY, str(NEW_ID), '{"assist": "ng"}')
    await access.refresh(config, redis)
    assert NEW_ID not in config.allowed_editors
    await access.refresh(config, redis, force=True)
    assert NEW_ID in config.allowed_editors


@pytest.mark.asyncio
async def test_refresh_without_redis_keeps_env(config):
    await access.refresh(config, None, force=True)
    assert config.allowed_editors == {OWNER_ID, ROBIN_ID, DI_ID}


# ---------- handlers ----------

def _message(user_id, username="new_mgr", full_name="New Manager"):
    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username=username, full_name=full_name),
        answer=AsyncMock(),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    return msg


def _query(user_id, data):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        data=data,
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_filter_lets_only_users_without_access(config):
    f = access_handlers.WithoutAccess()
    assert await f(_message(NEW_ID), config) is True
    assert await f(_message(ROBIN_ID), config) is False
    assert await f(_message(OWNER_ID), config) is False


@pytest.mark.asyncio
async def test_start_request_goes_to_owner_with_assist_buttons(config, redis):
    notion = SimpleNamespace(get_select_options=AsyncMock(return_value=["ng", "caramel", "di"]))
    msg = _message(NEW_ID)

    await access_handlers.access_request(msg, config, notion, redis)

    chat_id, text = msg.bot.send_message.await_args.args
    assert chat_id == OWNER_ID and str(NEW_ID) in text and "@new_mgr" in text
    buttons = [b.callback_data for row in msg.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
               for b in row]
    assert buttons == [f"acc:ok:{NEW_ID}:ng", f"acc:ok:{NEW_ID}:caramel", f"acc:ok:{NEW_ID}:di",
                       f"acc:ok:{NEW_ID}:-", f"acc:no:{NEW_ID}"]
    assert "Request sent" in msg.answer.await_args.args[0]

    # second /start does not ping the owner again
    msg2 = _message(NEW_ID)
    await access_handlers.access_request(msg2, config, notion, redis)
    msg2.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_without_redis_just_denies(config):
    msg = _message(NEW_ID)
    await access_handlers.access_request(msg, config, SimpleNamespace(), None)
    msg.bot.send_message.assert_not_awaited()
    assert "No access" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_owner_approves_and_user_is_notified(config, redis):
    await access.save_request(redis, NEW_ID, "new_mgr", "New Manager")
    query = _query(OWNER_ID, f"acc:ok:{NEW_ID}:caramel")

    await access_handlers.access_callback(query, config, redis)

    assert NEW_ID in config.allowed_editors
    assert config.manager_targets["caramel"] == (NEW_ID, None)
    assert "@new_mgr" in query.message.edit_text.await_args.args[0]
    assert query.bot.send_message.await_args.args[0] == NEW_ID


@pytest.mark.asyncio
async def test_non_owner_cannot_approve(config, redis):
    query = _query(ROBIN_ID, f"acc:ok:{NEW_ID}:caramel")
    await access_handlers.access_callback(query, config, redis)
    assert NEW_ID not in config.allowed_editors
    query.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_revokes_from_access_list(config, redis):
    await access.approve(config, redis, NEW_ID, "ng")
    query = _query(OWNER_ID, f"acc:rm:{NEW_ID}")
    await access_handlers.access_callback(query, config, redis)
    assert NEW_ID not in config.allowed_editors
    assert "ng" not in config.manager_targets


@pytest.mark.asyncio
async def test_mini_app_viewers_are_not_sent_to_the_owner(config):
    f = access_handlers.WithoutAccess()
    assert await f(_message(77), config) is False
    assert await f(_message(88, username="Viewer"), config) is False


@pytest.mark.asyncio
async def test_two_managers_on_one_assist_both_count_as_managers(config, redis):
    await access.approve(config, redis, NEW_ID, "ng")
    await access.approve(config, redis, NEW_ID + 1, "ng")
    assert access.manager_assist(NEW_ID, config) == "ng"
    assert access.manager_assist(NEW_ID + 1, config) == "ng"   # not full mini-app access
    assert config.manager_targets["ng"] == (NEW_ID, None)       # reminders: the first one's DM


# ---------- topic access filter / viewer commands ----------

def test_topic_access_private_only_editor_allowed():
    filt = TopicAccessMessageFilter()
    config = SimpleNamespace(
        allowed_editors={1},
        scouts_chat_id=-1001,
        crm_topic_thread_id=123,
    )
    msg_editor = SimpleNamespace(
        chat=SimpleNamespace(type="private", id=10),
        from_user=SimpleNamespace(id=1),
        message_thread_id=None,
    )
    msg_viewer = SimpleNamespace(
        chat=SimpleNamespace(type="private", id=10),
        from_user=SimpleNamespace(id=2),
        message_thread_id=None,
    )
    assert asyncio.run(filt(msg_editor, config)) is True
    assert asyncio.run(filt(msg_viewer, config)) is False


def test_topic_access_scouts_chat_only_editor_allowed():
    filt = TopicAccessMessageFilter()
    config = SimpleNamespace(
        allowed_editors={1},
        scouts_chat_id=-1001,
        crm_topic_thread_id=123,
    )
    msg_editor = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup", id=-1001),
        from_user=SimpleNamespace(id=1),
        message_thread_id=None,
    )
    msg_stranger = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup", id=-1001),
        from_user=SimpleNamespace(id=2),
        message_thread_id=None,
    )
    assert asyncio.run(filt(msg_editor, config)) is True
    assert asyncio.run(filt(msg_stranger, config)) is False

@pytest.mark.parametrize("user_id, thread_id, expected", [
    (1, 123, True),      # editor in the CRM topic
    (99, 123, False),    # unknown / revoked user in the CRM topic
    (1, 456, False),     # editor in another topic
])
def test_callback_filter_group_chat_needs_crm_topic_and_editor(user_id, thread_id, expected):
    config = SimpleNamespace(allowed_editors={1}, crm_topic_thread_id=123)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(chat=SimpleNamespace(type="supergroup", id=-1001), message_thread_id=thread_id),
    )
    assert asyncio.run(TopicAccessCallbackFilter()(query, config)) is expected


def test_callback_filter_private_chat_is_open():
    config = SimpleNamespace(allowed_editors={1}, crm_topic_thread_id=123)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=99),
        message=SimpleNamespace(chat=SimpleNamespace(type="private", id=10), message_thread_id=None),
    )
    assert asyncio.run(TopicAccessCallbackFilter()(query, config)) is True


@pytest.mark.asyncio
async def test_shoots_ignored_for_non_editor(monkeypatch):
    fetch = AsyncMock(return_value=([], date(2026, 11, 13)))
    board = AsyncMock()
    monkeypatch.setattr(notifications, "_fetch_shoots", fetch)
    monkeypatch.setattr(notifications, "update_board", board)
    message = MagicMock()
    message.from_user.id = 99
    message.answer = AsyncMock()
    config = SimpleNamespace(allowed_editors={1})
    for chat_type in ("private", "group"):
        message.chat.type = chat_type
        await notifications.cmd_upcoming_shoots(message, config, AsyncMock())
    fetch.assert_not_awaited()
    board.assert_not_awaited()
    message.answer.assert_not_awaited()
