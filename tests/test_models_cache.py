"""Cached models list used by the NLP model search."""

import asyncio
import json

import pytest

from app.handlers import models as ml


def _page(pid, title, aliases=()):
    return {"id": pid, "properties": {
        "model": {"type": "title", "title": [{"plain_text": title}]},
        "aliases": {"type": "multi_select", "multi_select": [{"name": a} for a in aliases]},
    }}


class FakeNotion:
    def __init__(self, pages):
        self.pages = pages
        self.full_loads = 0
        self.quick = []
        self.urls = []

    async def _request(self, method, url, json=None):
        if method == "GET":
            return {"properties": {"model": {"id": "title"}, "aliases": {"id": "Q0RAUw"}, "status": {"id": "x"}}}
        self.urls.append(url)
        title_filter = (json or {}).get("filter")
        if title_filter:
            needle = title_filter["title"]["contains"].lower()
            self.quick.append(needle)
            return {"results": [p for p in self.pages if needle in p["properties"]["model"]["title"][0]["plain_text"].lower()],
                    "has_more": False}
        self.full_loads += 1
        return {"results": self.pages, "has_more": False}


class FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None):
        self.kv[k] = v

    async def delete(self, k):
        self.kv.pop(k, None)


@pytest.fixture(autouse=True)
def _reset():
    ml._cache.update(at=float("-inf"), models=None)
    ml._prop_ids.clear()
    ml._refresh_task = None
    ml.init(None)
    yield
    ml.init(None)


PAGES = [_page("1", "КЛЕЩ"), _page("2", "КАПРИ", ["kapri"])]


@pytest.mark.asyncio
async def test_only_title_and_aliases_are_requested():
    notion = FakeNotion(PAGES)
    await ml.warm_up("db", notion)
    assert "filter_properties=title" in notion.urls[0] and "filter_properties=Q0RAUw" in notion.urls[0]
    assert "x" not in notion.urls[0].split("?")[1].split("&")  # other properties are not fetched


@pytest.mark.asyncio
async def test_second_call_uses_memory_cache():
    notion = FakeNotion(PAGES)
    await ml.warm_up("db", notion)
    first = await ml.list_models("клещ", "db", notion)
    second = await ml.list_models("kapri", "db", notion)
    assert notion.full_loads == 1 and first == second
    assert second[1] == {"id": "2", "name": "КАПРИ", "aliases": ["kapri"]}


@pytest.mark.asyncio
async def test_cold_instance_uses_redis_copy_and_refreshes_in_background():
    redis = FakeRedis()
    redis.kv[ml.REDIS_KEY] = json.dumps([{"id": "9", "name": "СТАРАЯ", "aliases": []}])
    ml.init(redis)
    notion = FakeNotion(PAGES)
    models = await ml.list_models("клещ", "db", notion)
    assert models[0]["name"] == "СТАРАЯ" and not notion.quick   # answered from Redis, no wait
    await ml._refresh_task
    assert [m["name"] for m in ml._cache["models"]] == ["КЛЕЩ", "КАПРИ"]
    assert json.loads(redis.kv[ml.REDIS_KEY])[0]["name"] == "КЛЕЩ"


@pytest.mark.asyncio
async def test_no_cache_answers_with_quick_title_search():
    notion = FakeNotion(PAGES)
    models = await ml.list_models("клещ", "db", notion)
    assert [m["name"] for m in models] == ["КЛЕЩ"] and notion.quick == ["клещ"]
    await ml._refresh_task  # the full list loads in the background
    assert len(ml._cache["models"]) == 2


@pytest.mark.asyncio
async def test_no_cache_and_no_title_hit_waits_for_full_list():
    notion = FakeNotion(PAGES)
    models = await ml.list_models("kapri", "db", notion)  # alias only -> quick search finds nothing
    assert [m["name"] for m in models] == ["КЛЕЩ", "КАПРИ"]


@pytest.mark.asyncio
async def test_stale_list_is_returned_at_once_and_refreshed():
    notion = FakeNotion(PAGES)
    await ml.warm_up("db", notion)
    ml._cache["at"] -= ml.CACHE_SECONDS + 1
    notion.pages = PAGES + [_page("3", "НОВАЯ")]
    stale = await ml.list_models("клещ", "db", notion)
    assert len(stale) == 2
    await ml._refresh_task
    assert len(await ml.list_models("клещ", "db", notion)) == 3


@pytest.mark.asyncio
async def test_invalidate_forgets_memory_and_redis():
    redis = FakeRedis()
    ml.init(redis)
    notion = FakeNotion(PAGES)
    await ml.warm_up("db", notion)
    assert ml.REDIS_KEY in redis.kv
    await ml.invalidate()
    assert ml._cache["models"] is None and ml.REDIS_KEY not in redis.kv


@pytest.mark.asyncio
async def test_notion_failure_keeps_previous_list():
    notion = FakeNotion(PAGES)
    await ml.warm_up("db", notion)
    ml._cache["at"] -= ml.CACHE_SECONDS + 1

    async def boom(*a, **k):
        raise RuntimeError("Notion down")

    notion._request = boom
    assert len(await ml.list_models("клещ", "db", notion)) == 2
    await asyncio.gather(ml._refresh_task)
    assert len(ml._cache["models"]) == 2


@pytest.mark.asyncio
async def test_cold_title_hit_that_is_not_exact_waits_for_aliases():
    # "клещ" is the alias of КЛЕЩ-2; the title search alone would only see КЛЕЩЕНКО
    notion = FakeNotion([_page("1", "КЛЕЩЕНКО"), _page("2", "КЛЕЩ-2", ["клещ"])])
    models = await ml.list_models("клещ", "db", notion)
    assert {m["name"] for m in models} == {"КЛЕЩЕНКО", "КЛЕЩ-2"}   # full list, alias included


@pytest.mark.asyncio
async def test_failed_refresh_is_not_retried_on_every_message():
    notion = FakeNotion(PAGES)
    await ml.warm_up("db", notion)
    ml._cache["at"] -= ml.CACHE_SECONDS + 1

    async def boom(*a, **k):
        raise RuntimeError("Notion down")

    notion._request = boom
    await ml.list_models("клещ", "db", notion)
    await ml._refresh_task
    task = ml._refresh_task
    await ml.list_models("клещ", "db", notion)
    assert ml._refresh_task is task   # no new refresh right after the failure


@pytest.mark.asyncio
async def test_invalidate_during_refresh_is_not_undone():
    notion = FakeNotion(PAGES)
    started = asyncio.Event()
    original = notion._request

    async def slow(method, url, json=None):
        if method == "POST":
            started.set()
            await asyncio.sleep(0.05)
        return await original(method, url, json=json)

    notion._request = slow
    task = asyncio.create_task(ml._refresh("db", notion))
    await started.wait()
    await ml.invalidate()
    await task
    assert ml._cache["models"] is None   # the old list did not come back
