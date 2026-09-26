"""Planner service - Phase 3"""
import logging
import time
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionPlanner

LOGGER = logging.getLogger(__name__)

CACHE_TTL = 60.0
_cache: dict[str, tuple[Any, float]] = {}


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry:
        data, ts = entry
        if time.monotonic() - ts < CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: Any) -> None:
    _cache[key] = (data, time.monotonic())


def clear_cache(model_id: str) -> None:
    """Clear shoots cache for specific model."""
    _cache.pop(model_id, None)


async def get_cached_shoots(
    notion: NotionClient,
    config: Config,
    model_id: str,
) -> list[NotionPlanner]:
    """Get upcoming shoots with in-memory TTL cache."""
    key = model_id
    cached = _get_cached(key)
    if cached is not None:
        return cached

    shoots = await notion.query_upcoming_shoots(
        config.db_planner,
        model_page_id=model_id,
    )
    _set_cached(key, shoots)
    return shoots
