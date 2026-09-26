"""Models -> Accounting status sync, and the WML project mismatch report."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.services import wml_sync
from app.services.notion import NotionAccounting, NotionModel
from app.services.status_sync import run_status_sync, sync_accounting_status


def _config(apply=True):
    return SimpleNamespace(
        timezone=ZoneInfo("Europe/Brussels"),
        db_models="db_models",
        db_accounting="db_accounting",
        owner_telegram_id=111,
        status_sync_apply=apply,
    )


def _notion(models, records):
    notion = AsyncMock()
    notion.query_all_models.return_value = models
    notion.query_all_accounting.return_value = records
    return notion


class _FakeRedisKV:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v):
        self.kv[k] = v


# ---------- status sync ----------

@pytest.mark.asyncio
async def test_status_copied_from_models_and_looted_becomes_stop():
    models = [
        NotionModel(page_id="aaaa-1", title="ROBIN", status="stop"),
        NotionModel(page_id="bbbb-2", title="EVA", status="looted"),
        NotionModel(page_id="cccc-3", title="MONA", status="work"),
    ]
    records = [
        NotionAccounting(page_id="acc1", title="ROBIN сентябрь 2026", model_id="aaaa1", status="work"),
        NotionAccounting(page_id="acc2", title="EVA сентябрь 2026", model_id="bbbb2", status="work"),
        NotionAccounting(page_id="acc3", title="MONA сентябрь 2026", model_id="cccc3", status="work"),
    ]
    notion = _notion(models, records)

    changes, duplicates = await sync_accounting_status(_config(), notion, apply=True)

    notion.update_accounting_status.assert_any_await("acc1", "stop")
    notion.update_accounting_status.assert_any_await("acc2", "stop")
    assert notion.update_accounting_status.await_count == 2  # MONA already in sync
    assert len(changes) == 2 and duplicates == []


@pytest.mark.asyncio
async def test_untitled_record_is_synced_too():
    models = [NotionModel(page_id="aaaa", title="FAINA", status="inactive")]
    records = [NotionAccounting(page_id="acc1", title="", model_id="aaaa", status="new")]
    notion = _notion(models, records)
    changes, _ = await sync_accounting_status(_config(), notion, apply=True)
    notion.update_accounting_status.assert_awaited_once_with("acc1", "inactive")
    assert changes == ["FAINA: new → inactive"]


@pytest.mark.asyncio
async def test_report_only_mode_writes_nothing():
    models = [NotionModel(page_id="aaaa", title="ROBIN", status="stop")]
    records = [NotionAccounting(page_id="acc1", title="x", model_id="aaaa", status="work")]
    notion = _notion(models, records)
    changes, _ = await sync_accounting_status(_config(), notion, apply=False)
    notion.update_accounting_status.assert_not_awaited()
    assert changes == ["ROBIN: work → stop"]


@pytest.mark.asyncio
async def test_records_without_model_or_status_are_skipped():
    models = [NotionModel(page_id="aaaa", title="ROBIN", status=None)]
    records = [
        NotionAccounting(page_id="acc1", title="x", model_id=None, status="work"),
        NotionAccounting(page_id="acc2", title="y", model_id="aaaa", status="work"),
        NotionAccounting(page_id="acc3", title="z", model_id="unknown", status="work"),
    ]
    notion = _notion(models, records)
    assert await sync_accounting_status(_config(), notion, apply=True) == ([], [])
    notion.update_accounting_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_reports_changes_and_duplicates_once():
    models = [NotionModel(page_id="aaaa", title="TANGO 8", status="stop")]
    records = [
        NotionAccounting(page_id="acc1", title="", model_id="aaaa", status="work", last_edited="2026-09-01"),
        NotionAccounting(page_id="acc2", title="TANGO 8 сентябрь 2026", model_id="aaaa", status="work",
                         last_edited="2026-09-26"),
    ]
    bot = SimpleNamespace(send_message=AsyncMock())
    redis = _FakeRedisKV()
    for _ in range(2):
        await run_status_sync(bot, _config(apply=False), _notion(models, records), redis)
    texts = [c.args[1] for c in bot.send_message.await_args_list]
    assert len(texts) == 2  # status report + duplicates report, not repeated on the 2nd run
    assert any("Дубли" in t and "TANGO 8" in t for t in texts)
    assert any("ничего не меняю" in t for t in texts)


@pytest.mark.asyncio
async def test_run_status_sync_reports_failure_and_never_raises():
    notion = AsyncMock()
    notion.query_all_models.side_effect = RuntimeError("Notion down")
    bot = SimpleNamespace(send_message=AsyncMock())
    await run_status_sync(bot, _config(), notion)
    bot.send_message.assert_awaited_once()


# ---------- WML project report ----------

def _profile(office="", tango_date=None):
    return SimpleNamespace(name="ROBIN", office=office, tango_date=tango_date)


def test_project_diff_detects_office_mismatch_case_insensitive():
    model = NotionModel(page_id="p", title="ROBIN", project="КИЕВ")
    assert wml_sync.project_diff(_profile(office="киев"), model) is None
    diff = wml_sync.project_diff(_profile(office="GRAND"), model)
    assert diff and diff.wml_office == "GRAND" and diff.notion_project == "КИЕВ"


def test_project_diff_tango_only_when_no_office():
    model = NotionModel(page_id="p", title="ROBIN", project="TANGO")
    assert wml_sync.project_diff(_profile(tango_date="01.09.2026"), model) is None
    assert wml_sync.project_diff(_profile(), model) is None  # WML has nothing to say


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v):
        self.kv[k] = v


@pytest.mark.asyncio
async def test_project_report_sent_once_until_list_changes():
    bot = SimpleNamespace(send_message=AsyncMock())
    redis = _FakeRedis()
    diffs = [wml_sync.ProjectDiff("ROBIN", "КИЕВ", "GRAND", False)]

    await wml_sync._report_project_diffs(bot, _config(), redis, diffs)
    await wml_sync._report_project_diffs(bot, _config(), redis, diffs)
    assert bot.send_message.await_count == 1
    assert "ничего не меняю" in bot.send_message.await_args.kwargs["text"]

    diffs.append(wml_sync.ProjectDiff("EVA", None, "TANGO", True))
    await wml_sync._report_project_diffs(bot, _config(), redis, diffs)
    assert bot.send_message.await_count == 2


# ---------- working record selection ----------

def test_working_records_prefers_month_title_then_latest_edit():
    from app.services.accounting import working_records
    records = [
        NotionAccounting(page_id="u", title="", model_id="m-1", last_edited="2026-09-01"),
        NotionAccounting(page_id="s", title="X сентябрь 2026", model_id="m-1", last_edited="2026-08-01"),
        NotionAccounting(page_id="old", title="Y август 2026", model_id="m-2", last_edited="2026-09-02"),
        NotionAccounting(page_id="new", title="", model_id="m-2", last_edited="2026-09-20"),
        NotionAccounting(page_id="solo", title="", model_id="m-3"),
    ]
    working, dups = working_records(records, "2026-09")
    assert working["m1"].page_id == "s"      # month-titled wins over newer untitled
    assert working["m2"].page_id == "new"    # no month title -> latest edit
    assert working["m3"].page_id == "solo"   # untitled single record is found
    assert set(dups) == {"m1", "m2"}
