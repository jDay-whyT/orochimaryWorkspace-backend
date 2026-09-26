"""Accounting service — one record per model per month.

Title format: "{MODEL_NAME} {месяц_ru_lower}" e.g. "КЛЕЩ февраль"
Fields used: Title, model (relation), Files (number), Comment (rich_text), Content (multi_select).
"""
import logging
import time
from typing import Any

from app.config import Config
from app.services.notion import NotionClient, NotionAccounting


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


def clear_cache(model_id: str, yyyy_mm: str) -> None:
    """Clear accounting cache for specific model and month."""
    key = f"{model_id}:{yyyy_mm}"
    _cache.pop(key, None)


async def get_cached_monthly_record(
    notion: NotionClient,
    config: Config,
    model_id: str,
    yyyy_mm: str,
) -> NotionAccounting | None:
    """Get monthly accounting record with in-memory TTL cache."""
    key = f"{model_id}:{yyyy_mm}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    record = await notion.get_monthly_record(config.db_accounting, model_id, yyyy_mm)
    _set_cached(key, record)
    return record
