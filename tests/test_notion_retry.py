import asyncio

from app.utils.exceptions import NotionRateLimitError, NotionValidationError
from app.utils.retry import retry_on_notion_error


def test_retry_on_retryable_error():
    state = {"calls": 0}

    @retry_on_notion_error
    async def flaky():
        state["calls"] += 1
        if state["calls"] < 3:
            raise NotionRateLimitError("rate")
        return "ok"

    result = asyncio.run(flaky())
    assert result == "ok"
    assert state["calls"] == 3


def test_no_retry_on_non_retryable_error():
    state = {"calls": 0}

    @retry_on_notion_error
    async def invalid():
        state["calls"] += 1
        raise NotionValidationError("bad payload")

    try:
        asyncio.run(invalid())
    except NotionValidationError:
        pass
    else:
        raise AssertionError("NotionValidationError must be raised")

    assert state["calls"] == 1
