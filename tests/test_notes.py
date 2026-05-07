"""Tests for Notes feature: create_note and get_recent_notes."""
import pytest
from unittest.mock import AsyncMock
from datetime import date

from app.services.notion import NotionClient, NotionNote


@pytest.fixture
def notion():
    token = "test-token-notes"
    # Use a unique token to avoid singleton collision with other tests
    if token in NotionClient._instances:
        del NotionClient._instances[token]
    client = NotionClient(token)
    client._session = None
    client._session_loop = None
    return client


class TestCreateNote:
    """Tests for NotionClient.create_note."""

    @pytest.mark.asyncio
    async def test_returns_page_id(self, notion):
        notion._request = AsyncMock(return_value={"id": "abc123"})
        result = await notion.create_note("db", "mid", "ШАНЕЛЬ", "не пришла")
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_payload_structure(self, notion):
        notion._request = AsyncMock(return_value={"id": "xyz"})
        await notion.create_note("db_id", "model_page_id", "ТЕСТ", "текст заметки")

        call_args = notion._request.call_args
        assert call_args[0][0] == "POST"
        assert "pages" in call_args[0][1]
        payload = call_args[1]["json"]
        assert payload["parent"]["database_id"] == "db_id"
        props = payload["properties"]
        assert props["model"]["relation"][0]["id"] == "model_page_id"
        assert props["text"]["rich_text"][0]["text"]["content"] == "текст заметки"
        assert "date" in props
        assert "Title" in props

    @pytest.mark.asyncio
    async def test_title_contains_model_name(self, notion):
        notion._request = AsyncMock(return_value={"id": "xyz"})
        await notion.create_note("db", "mid", "КЛЕЩ", "текст")

        payload = notion._request.call_args[1]["json"]
        title_content = payload["properties"]["Title"]["title"][0]["text"]["content"]
        assert "КЛЕЩ" in title_content

    @pytest.mark.asyncio
    async def test_truncates_long_text(self, notion):
        notion._request = AsyncMock(return_value={"id": "xyz"})
        await notion.create_note("db", "mid", "MODEL", "a" * 3000)

        payload = notion._request.call_args[1]["json"]
        content = payload["properties"]["text"]["rich_text"][0]["text"]["content"]
        assert len(content) == 2000


class TestGetRecentNotes:
    """Tests for NotionClient.get_recent_notes."""

    @pytest.mark.asyncio
    async def test_returns_parsed_notes(self, notion):
        notion._request = AsyncMock(return_value={
            "results": [
                {
                    "id": "note1",
                    "properties": {
                        "model": {"type": "relation", "relation": [{"id": "mid"}]},
                        "text": {"type": "rich_text", "rich_text": [{"plain_text": "текст 1"}]},
                        "date": {"type": "date", "date": {"start": "2026-05-07"}},
                    },
                },
                {
                    "id": "note2",
                    "properties": {
                        "model": {"type": "relation", "relation": [{"id": "mid"}]},
                        "text": {"type": "rich_text", "rich_text": [{"plain_text": "текст 2"}]},
                        "date": {"type": "date", "date": {"start": "2026-05-01"}},
                    },
                },
            ]
        })

        notes = await notion.get_recent_notes("db", "mid", limit=3)

        assert len(notes) == 2
        assert notes[0].page_id == "note1"
        assert notes[0].text == "текст 1"
        assert notes[0].date == "2026-05-07"
        assert notes[0].model_id == "mid"
        assert notes[1].page_id == "note2"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_notes(self, notion):
        notion._request = AsyncMock(return_value={"results": []})
        notes = await notion.get_recent_notes("db", "mid")
        assert notes == []

    @pytest.mark.asyncio
    async def test_query_uses_correct_filter_and_sort(self, notion):
        notion._request = AsyncMock(return_value={"results": []})
        await notion.get_recent_notes("test_db", "model_page_id", limit=3)

        payload = notion._request.call_args[1]["json"]
        assert payload["page_size"] == 3
        assert payload["filter"]["property"] == "model"
        assert payload["filter"]["relation"]["contains"] == "model_page_id"
        assert payload["sorts"][0]["property"] == "date"
        assert payload["sorts"][0]["direction"] == "descending"

    @pytest.mark.asyncio
    async def test_respects_limit(self, notion):
        notion._request = AsyncMock(return_value={"results": []})
        await notion.get_recent_notes("db", "mid", limit=5)

        payload = notion._request.call_args[1]["json"]
        assert payload["page_size"] == 5
