"""In-memory TTL cache for open orders queries."""
import logging
import time
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionOrder

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
    """Clear orders cache for specific model."""
    _cache.pop(model_id, None)


async def get_cached_orders(
    notion: NotionClient,
    config: Config,
    model_id: str,
) -> list[NotionOrder]:
    """Get open orders with in-memory TTL cache."""
    key = model_id
    cached = _get_cached(key)
    if cached is not None:
        return cached

    orders = await notion.query_open_orders(
        config.db_orders,
        model_page_id=model_id,
    )
    _set_cached(key, orders)
    return orders
