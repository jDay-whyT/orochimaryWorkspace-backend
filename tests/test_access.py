"""Managers approved in the bot: request -> owner button -> access lists."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import access as access_handlers
from app.services import access

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


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)

    async def hset(self, key, field_, value):
        self.hashes.setdefault(key, {})[field_] = value

    async def hdel(self, key, field_):
        self.hashes.get(key, {}).pop(field_, None)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


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
