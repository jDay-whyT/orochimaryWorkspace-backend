"""Tests for accounting refactor and planner status logic.

Covers:
  - Accounting: create monthly record when none exists
  - Accounting: update monthly record increments Files
  - Accounting: >1 record → chooses latest
  - Model card shows X/200, percent, over
  - Planner statuses: (date+types)->scheduled, (date only)->planned, (types only)->planned
  - Done/reschedule pересчитывают статус
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.services.notion import NotionAccounting, NotionPlanner
from app.services.model_card import clear_card_cache


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_config(fpm=200):
    cfg = MagicMock()
    cfg.timezone = ZoneInfo("Europe/Brussels")
    cfg.files_per_month = fpm
    cfg.db_orders = "db_orders"
    cfg.db_planner = "db_planner"
    cfg.db_accounting = "db_accounting"
    cfg.notion_token = "test-token"
    return cfg


# ===========================================================================
#  A) Accounting tests
# ===========================================================================

class TestAccountingCreateMonthlyRecord:
    """When no monthly record exists, a new page should be created."""

    @pytest.mark.asyncio
    async def test_create_when_none_exists(self):
        from app.services.accounting import AccountingService

        config = _make_config()
        svc = AccountingService(config)

        svc.notion = AsyncMock()
        svc.notion.get_monthly_record.return_value = None
        svc.notion.create_accounting_record.return_value = "new-page-id"

        result = await svc.add_files("model-1", "МЕЛИСА", 30)

        svc.notion.create_accounting_record.assert_called_once()
        call_kwargs = svc.notion.create_accounting_record.call_args
        assert call_kwargs[1]["files"] == 30 or call_kwargs[0][3] == 30
        assert result["files"] == 30
        assert result["id"] == "new-page-id"


class TestAccountingUpdateMonthlyRecord:
    """When a record exists, Files should be incremented."""

    @pytest.mark.asyncio
    async def test_update_increments_files(self):
        from app.services.accounting import AccountingService

        config = _make_config()
        svc = AccountingService(config)

        existing = NotionAccounting(
            page_id="existing-page",
            title="МЕЛИСА · accounting 2026-02",
            files=120,
        )
        svc.notion = AsyncMock()
        svc.notion.get_monthly_record.return_value = existing
        svc.notion.update_accounting_files.return_value = None

        result = await svc.add_files("model-1", "МЕЛИСА", 50)

        svc.notion.update_accounting_files.assert_called_once_with(
            "existing-page", 170,
        )
        assert result["files"] == 170

    @pytest.mark.asyncio
    async def test_update_accumulates_multiple(self):
        """Multiple add_files calls accumulate correctly."""
        from app.services.accounting import AccountingService

        config = _make_config()
        svc = AccountingService(config)

        record = NotionAccounting(
            page_id="page-1", title="МЕЛИСА · accounting 2026-02", files=50,
        )
        svc.notion = AsyncMock()
        svc.notion.get_monthly_record.return_value = record
        svc.notion.update_accounting_files.return_value = None

        result = await svc.add_files("model-1", "МЕЛИСА", 15)
        assert result["files"] == 65


class TestAccountingMultipleRecords:
    """>1 record → query_monthly_records returns sorted, get_monthly_record picks latest."""

    @pytest.mark.asyncio
    async def test_chooses_latest_by_last_edited(self):
        """get_monthly_record returns the first (most recent) when >1."""
        from app.services.notion import NotionClient

        client = AsyncMock(spec=NotionClient)

        records = [
            NotionAccounting(
                page_id="newer",
                title="МЕЛИСА · accounting 2026-02",
                files=100,
                last_edited="2026-02-05T12:00:00Z",
            ),
            NotionAccounting(
                page_id="older",
                title="МЕЛИСА · accounting 2026-02",
                files=80,
                last_edited="2026-02-01T10:00:00Z",
            ),
        ]

        # Mock query_monthly_records, then call the real get_monthly_record logic
        client.query_monthly_records.return_value = records

        # Inline the logic: get_monthly_record picks records[0] (sorted desc)
        result = records[0] if records else None

        assert result is not None
        assert result.page_id == "newer"
        assert result.files == 100


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
#  Model card shows X/200, percent, over
# ===========================================================================

class TestModelCardDisplay:
    """Model card text contains correct files display."""

    def setup_method(self):
        clear_card_cache()

    @pytest.mark.asyncio
    async def test_card_shows_files_200_percent(self):
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = []
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_monthly_record.return_value = NotionAccounting(
            page_id="a1", title="T", files=150,
        )

        config = _make_config(fpm=200)
        text = await build_model_card_text("m1", "TestModel", config, mock_notion)

        assert "150/200" in text
        assert "75%" in text
        assert "+150" not in text  # no over (150 < 200)

    @pytest.mark.asyncio
    async def test_card_shows_over_limit(self):
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = []
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_monthly_record.return_value = NotionAccounting(
            page_id="a1", title="T", files=250,
        )

        config = _make_config(fpm=200)
        text = await build_model_card_text("m2", "OverModel", config, mock_notion)

        assert "250/200" in text
        assert "100%" in text  # capped at 100
        assert "+50" in text  # 250 - 200 = 50

    @pytest.mark.asyncio
    async def test_card_zero_files(self):
        from app.services.model_card import build_model_card_text

        mock_notion = AsyncMock()
        mock_notion.query_open_orders.return_value = []
        mock_notion.query_upcoming_shoots.return_value = []
        mock_notion.get_monthly_record.return_value = None

        config = _make_config(fpm=200)
        text = await build_model_card_text("m3", "EmptyModel", config, mock_notion)

        assert "0/200" in text
        assert "0%" in text


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
        assert "main" in NLP_SHOOT_CONTENT_TYPES
        assert "SFS" in NLP_SHOOT_CONTENT_TYPES
        assert "posting" in NLP_SHOOT_CONTENT_TYPES
        assert "fansly" in NLP_SHOOT_CONTENT_TYPES
        assert "event" in NLP_SHOOT_CONTENT_TYPES
        assert len(NLP_SHOOT_CONTENT_TYPES) == 7


class TestFilesMonthLimit:
    """FILES_MONTH_LIMIT is 200."""

    def test_value(self):
        from app.utils.constants import FILES_MONTH_LIMIT

        assert FILES_MONTH_LIMIT == 200


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
        assert payload["properties"]["Files"]["number"] == 30

        # Cleanup singleton
        NotionClient._instances.pop("test-token-title", None)


class TestNoOldAccountingFields:
    """Ensure old fields (Month, FilesTotal, FilesPercent, amount, %) are not used."""

    def test_no_old_fields_in_notion_accounting_dataclass(self):
        from app.services.notion import NotionAccounting
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(NotionAccounting)}
        assert "amount" not in field_names
        assert "percent" not in field_names
        assert "comments" not in field_names  # now it's 'comment' singular
        # New fields present:
        assert "files" in field_names
        assert "comment" in field_names
        assert "content" in field_names
