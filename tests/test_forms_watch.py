"""New Forms entries -> owner notification."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import forms_watch


class FakeRedis:
    def __init__(self, **kv):
        self.kv = dict(kv)
        self.sets = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v):
        self.kv[k] = v

    async def sismember(self, k, v):
        return v in self.sets.get(k, set())

    async def sadd(self, k, v):
        self.sets.setdefault(k, set()).add(v)

    async def expire(self, k, ttl):
        pass


def _page(name, created, lang="eng", platforms=("Reddit",)):
    return {
        "id": f"id-{name}",
        "created_time": created,
        "url": "https://www.notion.so/page",
        "properties": {
            "name": {"type": "title", "title": [{"plain_text": name}]},
            "lang": {"type": "rich_text", "rich_text": [{"plain_text": lang}]},
            "optional": {"type": "multi_select", "multi_select": [{"name": p} for p in platforms]},
        },
    }


CONFIG = SimpleNamespace(owner_telegram_id=111)


@pytest.mark.asyncio
async def test_first_run_only_sets_baseline():
    redis = FakeRedis()
    bot = SimpleNamespace(send_message=AsyncMock())
    notion = AsyncMock()
    assert await forms_watch.check_new_forms(bot, CONFIG, notion, redis) == 0
    assert redis.kv[forms_watch.LAST_SEEN_KEY].endswith("Z")
    notion.query_pages_created_after.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_forms_sent_once_and_cursor_advances():
    redis = FakeRedis(**{forms_watch.LAST_SEEN_KEY: "2026-09-26T10:00:00.000Z"})
    redis.sets[forms_watch.SENT_IDS_KEY] = {"id-OLD"}      # announced on a previous run
    bot = SimpleNamespace(send_message=AsyncMock())
    notion = AsyncMock()
    notion.query_pages_created_after.return_value = [
        _page("OLD", "2026-09-26T10:00:00.000Z"),
        _page("MIA", "2026-09-26T11:30:00.000Z"),
        _page("LUNA", "2026-09-26T11:30:00.000Z", lang="esp", platforms=()),  # same minute as MIA
    ]

    assert await forms_watch.check_new_forms(bot, CONFIG, notion, redis) == 2
    texts = [c.args[1] for c in bot.send_message.await_args_list]
    assert "MIA" in texts[0] and "Reddit" in texts[0] and "eng" in texts[0]
    assert "LUNA" in texts[1] and "Платформы" not in texts[1]
    assert redis.kv[forms_watch.LAST_SEEN_KEY] == "2026-09-26T11:30:00.000Z"


@pytest.mark.asyncio
async def test_no_redis_or_owner_is_noop_and_failures_swallowed():
    bot = SimpleNamespace(send_message=AsyncMock())
    assert await forms_watch.check_new_forms(bot, CONFIG, AsyncMock(), None) == 0

    notion = AsyncMock()
    notion.query_pages_created_after.side_effect = RuntimeError("down")
    redis = FakeRedis(**{forms_watch.LAST_SEEN_KEY: "2026-09-26T10:00:00.000Z"})
    await forms_watch.run_forms_watch(bot, CONFIG, notion, redis)  # must not raise


@pytest.mark.asyncio
async def test_failure_mid_run_does_not_resend_already_sent():
    redis = FakeRedis(**{forms_watch.LAST_SEEN_KEY: "2026-09-26T10:00:00.000Z"})
    notion = AsyncMock()
    notion.query_pages_created_after.return_value = [
        _page("A", "2026-09-26T11:00:00.000Z"), _page("B", "2026-09-26T11:01:00.000Z"),
    ]
    calls = []

    async def send(chat_id, text, **kw):
        calls.append(text)
        if "B" in text and len(calls) == 2:
            raise RuntimeError("telegram hiccup")

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
    await forms_watch.run_forms_watch(bot, CONFIG, notion, redis)   # A sent, B failed
    await forms_watch.run_forms_watch(bot, CONFIG, notion, redis)   # retry: only B again
    assert sum("A" in t.split("</b>")[0] for t in calls) == 1
    assert sum("B" in t.split("</b>")[0] for t in calls) == 2
