"""Tests for the editor activity log and the owner's daily digest."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.services import activity_log

OWNER_ID = 111
MANAGER = SimpleNamespace(id=222, username="manager", full_name="Man Ager")


class FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def expire(self, key, ttl):
        pass

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))


@pytest.fixture
def config():
    return SimpleNamespace(
        owner_telegram_id=OWNER_ID,
        timezone=ZoneInfo("Europe/Brussels"),
        digest_user_ids={MANAGER.id},
    )


@pytest.fixture
def redis():
    fake = FakeRedis()
    activity_log.init(fake)
    yield fake
    activity_log.init(None)


def test_author_label_prefers_username():
    assert activity_log.author_label(MANAGER) == "@manager"
    assert activity_log.author_label(SimpleNamespace(id=5, username=None, full_name="Anna")) == "Anna"
    assert activity_log.author_label(SimpleNamespace(id=5, username=None, full_name=None)) == "5"


@pytest.mark.asyncio
async def test_record_skips_owner(config, redis):
    owner = SimpleNamespace(id=OWNER_ID, username="owner", full_name="Owner")
    await activity_log.record(config, owner, "order", "Robin", "custom × 1")
    assert redis.lists == {}


@pytest.mark.asyncio
async def test_record_and_digest(config, redis):
    await activity_log.record(config, MANAGER, "order", "Robin", "custom × 2")
    await activity_log.record(config, MANAGER, "files", "Robin", "12 · instagram")
    (entries,) = redis.lists.values()
    assert json.loads(entries[0])["author"] == "@manager"

    bot = SimpleNamespace(send_message=AsyncMock())
    await activity_log.send_daily_digest(bot, config)
    bot.send_message.assert_awaited_once()
    chat_id, text = bot.send_message.await_args.args
    assert chat_id == OWNER_ID
    assert "@manager" in text and "custom × 2" in text and "12 · instagram" in text


@pytest.mark.asyncio
async def test_digest_silent_without_activity(config, redis):
    bot = SimpleNamespace(send_message=AsyncMock())
    await activity_log.send_daily_digest(bot, config)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_noop_without_redis(config):
    activity_log.init(None)
    await activity_log.record(config, MANAGER, "order", "Robin", "x")  # must not raise


@pytest.mark.asyncio
async def test_record_skips_users_not_in_digest_list(config, redis):
    robin = SimpleNamespace(id=999, username="robin", full_name="Robin")
    await activity_log.record(config, robin, "order", "X", "custom × 1")
    assert redis.lists == {}
