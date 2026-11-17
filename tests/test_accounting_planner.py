"""Tests for accounting refactor and planner status logic.

Covers:
  - Accounting: create monthly record when none exists
  - Accounting: update monthly record increments Files
  - Planner statuses: (date+types)->scheduled, (date only)->planned, (types only)->planned
  - Done/reschedule pересчитывают статус
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
#  A) Accounting tests
# ===========================================================================

class TestAccountingSearchFallbacks:
    """query_monthly_records uses 3-step search: primary → fallback1 → fallback2."""

    @pytest.mark.asyncio
    async def test_primary_finds_new_format(self):
        """Step 1 (primary): finds record with '{month_ru} {year}' in title."""
        from app.services.notion import NotionClient

        client = NotionClient("test-token-fb-primary")
        hit = {"id": "p1", "properties": {
            "Title": {"title": [{"plain_text": "КЛЕЩ февраль 2026"}]},
            "model": {"relation": [{"id": "m1"}]},
            "Files": {"number": 10},
            "Comment": {"rich_text": []},
            "status": {"status": {"name": "work"}},
            "Content": {"multi_select": []},
        }, "last_edited_time": "2026-02-05T00:00:00Z"}

        # primary returns hit, other steps should not be called
        client._request = AsyncMock(return_value={"results": [hit]})

        records = await client.query_monthly_records("db-acc", "m1", "2026-02")

        assert len(records) == 1
        assert records[0].page_id == "p1"
        # Only 1 API call (primary step)
        assert client._request.call_count == 1
        payload = client._request.call_args[1].get("json") or client._request.call_args[0][2]
        title_filter = payload["filter"]["and"][1]
        assert title_filter["property"] == "Title"
        assert "февраль 2026" in title_filter["title"]["contains"]

        NotionClient._instances.pop("test-token-fb-primary", None)

    @pytest.mark.asyncio
    async def test_fallback1_finds_old_format_without_year(self):
        """Step 2 (fallback1): finds record with '{month_ru}' only (no year)."""
        from app.services.notion import NotionClient

        client = NotionClient("test-token-fb1")
        hit = {"id": "p2", "properties": {
            "Title": {"title": [{"plain_text": "КЛЕЩ февраль"}]},
            "model": {"relation": [{"id": "m1"}]},
            "Files": {"number": 20},
            "Comment": {"rich_text": []},
            "status": {"status": {"name": "work"}},
            "Content": {"multi_select": []},
        }, "last_edited_time": "2026-02-03T00:00:00Z"}

        # primary returns empty, fallback1 returns hit
        client._request = AsyncMock(side_effect=[
            {"results": []},   # primary — empty
            {"results": [hit]},  # fallback1 — hit
        ])

        records = await client.query_monthly_records("db-acc", "m1", "2026-02")

        assert len(records) == 1
        assert records[0].page_id == "p2"
        assert client._request.call_count == 2

        NotionClient._instances.pop("test-token-fb1", None)

    @pytest.mark.asyncio
    async def test_fallback2_finds_yyyy_mm_format(self):
        """Step 3 (fallback2): finds record with '{yyyy_mm}' in title."""
        from app.services.notion import NotionClient

        client = NotionClient("test-token-fb2")
        hit = {"id": "p3", "properties": {
            "Title": {"title": [{"plain_text": "КЛЕЩ · accounting 2026-02"}]},
            "model": {"relation": [{"id": "m1"}]},
            "Files": {"number": 5},
            "Comment": {"rich_text": []},
            "status": {"status": {"name": "work"}},
            "Content": {"multi_select": []},
        }, "last_edited_time": "2026-02-01T00:00:00Z"}

        # primary and fallback1 return empty, fallback2 returns hit
        client._request = AsyncMock(side_effect=[
            {"results": []},   # primary — empty
            {"results": []},   # fallback1 — empty
            {"results": [hit]},  # fallback2 — hit
        ])

        records = await client.query_monthly_records("db-acc", "m1", "2026-02")

        assert len(records) == 1
        assert records[0].page_id == "p3"
        assert client._request.call_count == 3

        NotionClient._instances.pop("test-token-fb2", None)


# ===========================================================================
#  B) Planner status tests
# ===========================================================================

class TestPlannerAutoStatus:
    """Auto-compute status: date + content_types -> scheduled, else planned."""

    def test_date_and_types_gives_scheduled(self):
        from app.handlers.nlp_callbacks import _compute_shoot_status

        status = _compute_shoot_status("2026-02-15", ["Twitter", "Main"])
        assert status == "scheduled"

    def test_date_only_gives_planned(self):
        from app.handlers.nlp_callbacks import _compute_shoot_status

        status = _compute_shoot_status("2026-02-15", [])
        assert status == "planned"

    def test_types_only_gives_planned(self):
        from app.handlers.nlp_callbacks import _compute_shoot_status

        status = _compute_shoot_status(None, ["Reddit", "SFC"])
        assert status == "planned"

    def test_neither_gives_planned(self):
        from app.handlers.nlp_callbacks import _compute_shoot_status

        status = _compute_shoot_status(None, [])
        assert status == "planned"


class TestShootDoneReschedule:
    """Done and reschedule callbacks change shoot status."""

    @pytest.mark.asyncio
    async def test_done_calls_update_status(self):
        """update_shoot_status builds correct PATCH payload for 'done'."""
        from app.services.notion import NotionClient

        client = NotionClient("test-token-done")
        client._request = AsyncMock(return_value={})

        await client.update_shoot_status("shoot-id-1", "done")

        client._request.assert_called_once()
        call_args = client._request.call_args
        payload = call_args[1].get("json") or call_args[0][2]
        assert payload["properties"]["status"]["select"]["name"] == "done"

        # Cleanup singleton
        NotionClient._instances.pop("test-token-done", None)

    @pytest.mark.asyncio
    async def test_reschedule_calls_reschedule(self):
        """reschedule_shoot builds correct PATCH payload."""
        from datetime import date
        from app.services.notion import NotionClient

        client = NotionClient("test-token-resc")
        client._request = AsyncMock(return_value={})

        await client.reschedule_shoot("shoot-id-2", date(2026, 3, 1))

        client._request.assert_called_once()
        call_args = client._request.call_args
        payload = call_args[1].get("json") or call_args[0][2]
        assert payload["properties"]["status"]["select"]["name"] == "rescheduled"
        assert payload["properties"]["date"]["date"]["start"] == "2026-03-01"

        # Cleanup singleton
        NotionClient._instances.pop("test-token-resc", None)


# ===========================================================================
#  NLP content type keyboard constants
# ===========================================================================

class TestNlpShootContentTypes:
    """Validate that NLP_SHOOT_CONTENT_TYPES is correctly defined."""

    def test_has_expected_types(self):
        from app.utils.constants import NLP_SHOOT_CONTENT_TYPES

        assert "twitter" in NLP_SHOOT_CONTENT_TYPES
        assert "reddit" in NLP_SHOOT_CONTENT_TYPES
        assert "posting" in NLP_SHOOT_CONTENT_TYPES
        assert "fansly" in NLP_SHOOT_CONTENT_TYPES
        # exactly the Planner `content` options, without the "main" duplicate
        assert set(NLP_SHOOT_CONTENT_TYPES) == {
            "of pack", "basic", "event", "twitter", "reddit",
            "fansly", "instagram", "snapchat", "sfs", "posting",
        }


class TestAccountingTitleFormat:
    """Title should be '{MODEL_NAME} {month_ru} {year}'."""

    @pytest.mark.asyncio
    async def test_title_format_on_create(self):
        from app.services.notion import NotionClient

        client = NotionClient("test-token-title")
        client._request = AsyncMock(return_value={"id": "new-id"})

        mock_model = MagicMock()
        mock_model.status = "work"
        mock_model.title = "МЕЛИСА"
        with patch.object(client, "get_model", new_callable=AsyncMock, return_value=mock_model):
            page_id = await client.create_accounting_record(
                database_id="db-acc",
                model_page_id="model-1",
                model_name="МЕЛИСА",
                files=30,
                yyyy_mm="2026-02",
            )

        assert page_id == "new-id"
        call_args = client._request.call_args
        payload = call_args[1].get("json") or call_args[0][2]
        title_content = payload["properties"]["Title"]["title"][0]["text"]["content"]
        assert title_content == "МЕЛИСА февраль 2026"
        assert payload["properties"]["of_files"]["number"] == 30

        # Cleanup singleton
        NotionClient._instances.pop("test-token-title", None)


class TestAccountingSearchByRelationOnly:
    """Step 4: a record found only by the model relation (any title)."""

    @pytest.mark.asyncio
    async def test_untitled_record_found_after_title_steps_miss(self):
        from app.services.notion import NotionClient

        client = NotionClient("test-token-fb-relation")
        hit = {"id": "p4", "properties": {
            "Title": {"title": []},
            "model": {"relation": [{"id": "m1"}]},
            "status": {"status": {"name": "new"}},
            "Content": {"multi_select": []},
        }, "last_edited_time": "2026-09-20T00:00:00Z"}
        client._request = AsyncMock(side_effect=[
            {"results": []}, {"results": []}, {"results": []},  # three title-based steps miss
            {"results": [hit]},                                   # relation-only step hits
        ])

        records = await client.query_monthly_records("db-acc", "m1", "2026-09")

        assert [r.page_id for r in records] == ["p4"]
        last_payload = client._request.call_args[1].get("json") or client._request.call_args[0][2]
        assert last_payload["filter"] == {"and": [
            {"property": "model", "relation": {"contains": "m1"}},
            {"property": "status", "status": {"does_not_equal": "stop"}},  # never write into a dead page
        ]}

        NotionClient._instances.pop("test-token-fb-relation", None)
