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


def working_records(
    records: list[NotionAccounting],
    yyyy_mm: str,
) -> tuple[dict[str, NotionAccounting], dict[str, list[NotionAccounting]]]:
    """Pick each model's working record from the whole Accounting database.

    A model normally has exactly one record (renamed and zeroed at month close),
    whatever its title says. With duplicates, the one titled for `yyyy_mm` wins,
    else the most recently edited. Keys are model ids without dashes.
    Returns (working record per model, duplicates per model).
    """
    from app.utils.formatting import MONTHS_RU_LOWER

    year, month = yyyy_mm.split("-")
    month_label = f"{MONTHS_RU_LOWER[int(month) - 1]} {year}"

    by_model: dict[str, list[NotionAccounting]] = {}
    for record in records:
        if record.model_id:
            by_model.setdefault(record.model_id.replace("-", ""), []).append(record)

    working: dict[str, NotionAccounting] = {}
    duplicates: dict[str, list[NotionAccounting]] = {}
    for model_key, group in by_model.items():
        group = sorted(group, key=lambda r: r.last_edited or "", reverse=True)
        titled = [r for r in group if month_label in (r.title or "").lower()]
        working[model_key] = (titled or group)[0]
        if len(group) > 1:
            duplicates[model_key] = group
    return working, duplicates
