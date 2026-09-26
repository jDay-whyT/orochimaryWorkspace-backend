"""Morning reminders: overdue orders + low content, routed owner/managers."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services import reminders
from app.services.notion import NotionAccounting, NotionModel, NotionOrder

OWNER = 111
ROBIN = 222
DI = 333


def _config(**kw):
    base = dict(
        timezone=ZoneInfo("Europe/Brussels"),
        db_models="m", db_orders="o", db_accounting="a",
        owner_telegram_id=OWNER,
        manager_telegram_ids={"robin": ROBIN, "di": DI},
        overdue_order_days=3,
        low_content_threshold=30,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _notion():
    notion = AsyncMock()
    notion.query_all_models.return_value = [
        NotionModel(page_id="m-1", title="ROBINS_MODEL", status="work"),
        NotionModel(page_id="m-2", title="DIS_MODEL", status="work"),
        NotionModel(page_id="m-3", title="TANGO_MODEL", status="work"),
        NotionModel(page_id="m-4", title="STOPPED", status="stop"),
        NotionModel(page_id="m-5", title="NO_RECORD", status="work"),
    ]
    notion.query_accounting_for_month.return_value = [
        NotionAccounting(page_id="a1", title="x", model_id="m1", assist="robin", files=5),
        NotionAccounting(page_id="a2", title="y", model_id="m2", assist="di", files=100),
        NotionAccounting(page_id="a3", title="z", model_id="m3", assist="robin", files=0, tango_files=70),
    ]
    notion.query_all_open_orders.return_value = [
        NotionOrder(page_id="o1", title="t", model_id="m1", order_type="custom", in_date="2026-09-10"),
        NotionOrder(page_id="o2", title="t", model_id="m2", order_type="call", in_date="2026-09-20"),
        NotionOrder(page_id="o3", title="t", model_id="m2", order_type="short", in_date="2026-09-25"),  # 1 day
        NotionOrder(page_id="o4", title="t", model_id="m9", order_type="custom", in_date=None),  # no date
    ]
    return notion


TODAY = date(2026, 9, 26)


@pytest.mark.asyncio
async def test_overdue_orders_threshold_and_grouping():
    grouped = await reminders.overdue_orders(_config(), _notion(), TODAY)
    assert grouped["robin"] == ["• ROBINS_MODEL — custom · 16 дн"]
    assert grouped["di"] == ["• DIS_MODEL — call · 6 дн"]
    assert sum(len(v) for v in grouped.values()) == 2  # 1-day and undated orders skipped


@pytest.mark.asyncio
async def test_low_content_counts_tango_and_missing_records():
    grouped = await reminders.low_content(_config(), _notion(), TODAY)
    lines = [line for v in grouped.values() for line in v]
    assert "• ROBINS_MODEL — 5 файлов" in lines
    assert "• NO_RECORD — 0 файлов" in lines          # work model with no record this month
    assert not any("TANGO_MODEL" in l for l in lines)  # 70 Tango files count
    assert not any("DIS_MODEL" in l for l in lines)    # above threshold
    assert not any("STOPPED" in l for l in lines)      # not in work
    assert grouped[None] == ["• NO_RECORD — 0 файлов"]  # unknown manager -> owner only


def test_route_owner_gets_all_managers_get_own():
    routed = reminders._route({"robin": ["r"], "di": ["d"], None: ["x"], "yasha": ["y"]}, _config())
    assert sorted(routed[OWNER]) == ["d", "r", "x", "y"]
    assert routed[ROBIN] == ["r"]
    assert routed[DI] == ["d"]


def test_route_no_duplicate_when_manager_is_owner():
    routed = reminders._route({"robin": ["r"]}, _config(manager_telegram_ids={"robin": OWNER}))
    assert routed == {OWNER: ["r"]}


@pytest.mark.asyncio
async def test_content_only_on_reminder_days_and_silent_when_empty():
    bot = SimpleNamespace(send_message=AsyncMock())
    notion = _notion()
    notion.query_all_open_orders.return_value = []  # nothing overdue -> silent

    with patch.object(reminders, "datetime") as dt:
        dt.now.return_value = SimpleNamespace(date=lambda: date(2026, 9, 26))
        await reminders.run_daily_reminders(bot, _config(), notion)
    bot.send_message.assert_not_awaited()

    with patch.object(reminders, "datetime") as dt:
        dt.now.return_value = SimpleNamespace(date=lambda: date(2026, 9, 27))
        await reminders.run_daily_reminders(bot, _config(), notion)
    recipients = {c.args[0] for c in bot.send_message.await_args_list}
    assert recipients == {OWNER, ROBIN}  # low-content lines belong to robin + unknown


@pytest.mark.asyncio
async def test_undeliverable_manager_does_not_block_owner():
    async def send(chat_id, text, **kw):
        if chat_id == ROBIN:
            raise RuntimeError("Forbidden: bot was blocked by the user")

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
    with patch.object(reminders, "datetime") as dt:
        dt.now.return_value = SimpleNamespace(date=lambda: TODAY)
        await reminders.run_daily_reminders(bot, _config(), _notion())
    recipients = [c.args[0] for c in bot.send_message.await_args_list]
    assert OWNER in recipients and DI in recipients
