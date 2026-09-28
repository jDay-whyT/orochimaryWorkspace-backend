"""The models list the NLP router matches names against: [{"id", "name", "aliases"}, ...].

Loading every Models page on each message was slow, so the list is cached:
- only the title and aliases are fetched (filter_properties), not every property;
- in memory for CACHE_SECONDS, refreshed in the background once stale (the
  caller gets the slightly stale list right away);
- in Redis too, so a fresh Cloud Run instance does not wait for Notion;
- with no cache at all, a single title-contains query answers first, and the
  full list (needed for typos and aliases) loads in the background.

multi_select "contains" only matches registered options, so aliases can't be
searched server-side - hence the full list and client-side matching.
"""

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

from app.services import NotionClient
from app.services.notion import _extract_multi_select, _extract_title

LOGGER = logging.getLogger(__name__)

CACHE_SECONDS = 300
RETRY_AFTER_FAILURE_SECONDS = 30
REDIS_KEY = "models:list"
REDIS_TTL_SECONDS = 24 * 60 * 60

_redis: Any = None
_cache: dict[str, Any] = {"at": float("-inf"), "models": None, "generation": 0}
_prop_ids: dict[str, str] = {}
_refresh_task: asyncio.Task | None = None
_lock = asyncio.Lock()


def init(redis: Any) -> None:
    """Set the async Redis client for the shared copy (None = memory only)."""
    global _redis
    _redis = redis


async def invalidate() -> None:
    """Forget the list (a model was added); the next call reloads it."""
    _cache.update(at=float("-inf"), models=None, generation=_cache["generation"] + 1)
    if _redis is not None:
        try:
            await _redis.delete(REDIS_KEY)
        except Exception:
            LOGGER.warning("models cache: Redis delete failed", exc_info=True)


async def _query_url(db_id: str, notion: NotionClient) -> str:
    """Query URL that returns only the title and aliases properties."""
    if not _prop_ids:
        schema = await notion._request("GET", f"https://api.notion.com/v1/databases/{db_id}")
        props = schema.get("properties") or {}
        for name in ("model", "aliases"):
            if name in props and props[name].get("id"):
                _prop_ids[name] = props[name]["id"]
    params = urlencode([("filter_properties", pid) for pid in _prop_ids.values()])
    base = f"https://api.notion.com/v1/databases/{db_id}/query"
    return f"{base}?{params}" if params else base


async def _fetch(db_id: str, notion: NotionClient, title_contains: str | None = None) -> list[dict[str, Any]]:
    url = await _query_url(db_id, notion)
    models: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if title_contains:
            payload["filter"] = {"property": "model", "title": {"contains": title_contains}}
        if cursor:
            payload["start_cursor"] = cursor
        response = await notion._request("POST", url, json=payload)
        for item in response.get("results", []):
            title = _extract_title(item, "model")
            if not title:
                LOGGER.warning("Skipping model %s - no title found", item.get("id"))
                continue
            models.append({"id": item["id"], "name": title, "aliases": _extract_multi_select(item, "aliases")})
        if not response.get("has_more"):
            return models
        cursor = response.get("next_cursor")


async def _refresh(db_id: str, notion: NotionClient) -> list[dict[str, Any]] | None:
    async with _lock:
        if _cache["models"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["models"]  # another caller just refreshed it
        started = time.monotonic()
        generation = _cache["generation"]
        try:
            models = await _fetch(db_id, notion)
        except Exception:
            LOGGER.exception("models cache: loading from Notion failed")
            if _cache["models"] is not None:  # retry in a while, not on every message
                _cache["at"] = time.monotonic() - CACHE_SECONDS + RETRY_AFTER_FAILURE_SECONDS
            return _cache["models"]
        if generation != _cache["generation"]:
            return models  # invalidated meanwhile (a model was added): this list may miss it
        _cache.update(at=time.monotonic(), models=models)
        LOGGER.info("models cache: loaded %d models in %.1fs", len(models), time.monotonic() - started)
        if _redis is not None:
            try:
                await _redis.set(REDIS_KEY, json.dumps(models, ensure_ascii=False), ex=REDIS_TTL_SECONDS)
            except Exception:
                LOGGER.warning("models cache: Redis write failed", exc_info=True)
        return models


def _refresh_in_background(db_id: str, notion: NotionClient) -> asyncio.Task:
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh(db_id, notion))
    return _refresh_task


async def warm_up(db_id: str, notion: NotionClient) -> None:
    """Load the list at startup so the first message doesn't wait. Never raises."""
    if _redis is not None:
        try:
            raw = await _redis.get(REDIS_KEY)
            if raw:
                _cache.update(at=float("-inf"), models=json.loads(raw))  # usable now, refreshed below
        except Exception:
            LOGGER.warning("models cache: Redis read failed", exc_info=True)
    await _refresh(db_id, notion)


async def list_models(name: str, db_id: str, notion: NotionClient) -> list[dict[str, Any]]:
    """Models to match `name` against (see module docstring)."""
    if _cache["models"] is not None:
        if time.monotonic() - _cache["at"] >= CACHE_SECONDS:
            _refresh_in_background(db_id, notion)
        return _cache["models"]

    if _redis is not None:
        try:
            raw = await _redis.get(REDIS_KEY)
        except Exception:
            raw = None
            LOGGER.warning("models cache: Redis read failed", exc_info=True)
        if raw:
            _cache.update(at=float("-inf"), models=json.loads(raw))
            _refresh_in_background(db_id, notion)
            return _cache["models"]

    task = _refresh_in_background(db_id, notion)
    try:
        quick = await _fetch(db_id, notion, title_contains=name)
    except Exception:
        LOGGER.warning("models cache: quick title search failed", exc_info=True)
        quick = []
    wanted = name.strip().lower()
    if any(m["name"].strip().lower() == wanted for m in quick):
        return quick  # exact title hit: safe to answer before the full list (aliases) is in
    return await task or quick
