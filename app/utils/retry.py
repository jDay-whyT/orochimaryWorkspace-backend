"""Retry utilities for transient Notion failures."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from app.utils.exceptions import NotionAPIError

LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def retry_on_notion_error(func: F) -> F:
    """Retry Notion operations for retryable custom errors using exponential backoff."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        max_attempts = 3
        delay = 0.5

        for attempt in range(1, max_attempts + 1):
            try:
                return await func(*args, **kwargs)
            except NotionAPIError as exc:
                is_last = attempt == max_attempts
                if not exc.retryable or is_last:
                    raise

                LOGGER.warning(
                    "Retrying in %.1fs after Notion error in %s (attempt %d/%d): %s",
                    delay,
                    func.__name__,
                    attempt,
                    max_attempts,
                    exc,
                )
                await asyncio.sleep(delay)
                delay *= 2

        return None

    return wrapper  # type: ignore[return-value]
