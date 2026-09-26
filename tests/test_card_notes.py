"""Model card shows only a one-line preview of the latest note."""

from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.services.model_card import build_model_card_text, clear_card_cache
from app.services.notion import NotionNote


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_card_cache()
    yield
    clear_card_cache()


async def _card_with_note(text: str) -> tuple[str, AsyncMock]:
    notion = AsyncMock()
    notion.query_open_orders.return_value = []
    notion.query_upcoming_shoots.return_value = []
    notion.get_monthly_record.return_value = None
    notion.get_recent_notes.return_value = [NotionNote(page_id="n1", text=text, date="2026-09-20")]

    config = MagicMock()
    config.timezone = ZoneInfo("Europe/Brussels")
    config.files_per_month = 200
    config.db_notes = "db_notes"

    card = await build_model_card_text("model-1", "Robin", config, notion)
    return card, notion


@pytest.mark.asyncio
async def test_only_latest_note_is_requested():
    _, notion = await _card_with_note("коротко")
    assert notion.get_recent_notes.await_args.kwargs["limit"] == 1


@pytest.mark.asyncio
async def test_multiline_note_shows_first_line_only():
    card, _ = await _card_with_note("первая строка\nвторая строка\nтретья")
    assert "первая строка …" in card
    assert "вторая строка" not in card
    assert "📝 Заметки" not in card


@pytest.mark.asyncio
async def test_long_note_is_truncated():
    card, _ = await _card_with_note("а" * 300)
    assert "а" * 100 + "…" in card
    assert "а" * 101 not in card
