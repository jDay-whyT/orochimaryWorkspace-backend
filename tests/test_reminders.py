"""Morning reminders: overdue orders + low content, routed owner/managers."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services import reminders
from app.services.notion import NotionAccounting, NotionModel, NotionOrder

OWNER = 111
CRM_GROUP, CRM_TOPIC = -100200, 25612
DI = 333
OWNER_T, ROBIN_T, DI_T = (OWNER, None), (CRM_GROUP, CRM_TOPIC), (DI, None)


def _config(**kw):
    base = dict(
        timezone=ZoneInfo("Europe/Brussels"),
        db_models="m", db_orders="o", db_accounting="a",
        owner_telegram_id=OWNER,
        manager_targets={"robin": ROBIN_T, "di": DI_T},
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
        NotionModel(page_id="m-6", title="FRESH", status="new"),
        NotionModel(page_id="m-7", title="PAUSED", status="inactive"),
    ]
    notion.query_all_accounting.return_value = [
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
    assert not any("STOPPED" in l for l in lines)      # not in work/new
    assert not any("PAUSED" in l for l in lines)       # inactive is skipped too
    assert "• FRESH — 0 файлов" in lines               # new models count
    assert grouped[None] == ["• NO_RECORD — 0 файлов", "• FRESH — 0 файлов"]  # unknown manager -> owner only


def test_route_owner_gets_all_managers_get_own():
    routed = reminders._route({"robin": ["r"], "di": ["d"], None: ["x"], "yasha": ["y"]}, _config())
    assert sorted(routed[OWNER_T]) == ["d", "r", "x", "y"]
    assert routed[ROBIN_T] == ["r"]  # CRM group topic
    assert routed[DI_T] == ["d"]      # DM


def test_route_no_duplicate_when_manager_is_owner():
    routed = reminders._route({"robin": ["r"]}, _config(manager_targets={"robin": OWNER_T}))
    assert routed == {OWNER_T: ["r"]}


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
    sent = {(c.args[0], c.kwargs.get("message_thread_id")) for c in bot.send_message.await_args_list}
    assert sent == {OWNER_T, ROBIN_T}  # low-content lines belong to robin + unknown; robin -> CRM topic


@pytest.mark.asyncio
async def test_undeliverable_manager_does_not_block_owner():
    async def send(chat_id, text, **kw):
        if chat_id == CRM_GROUP:
            raise RuntimeError("Forbidden: bot was blocked by the user")

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
    with patch.object(reminders, "datetime") as dt:
        dt.now.return_value = SimpleNamespace(date=lambda: TODAY)
        await reminders.run_daily_reminders(bot, _config(), _notion())
    recipients = [c.args[0] for c in bot.send_message.await_args_list]
    assert OWNER in recipients and DI in recipients


def test_manager_targets_parsing():
    from app.config import _parse_manager_targets
    parsed = _parse_manager_targets("Robin:-1002047661163/25612, di:456, broken:x, :1")
    assert parsed == {"robin": (-1002047661163, 25612), "di": (456, None)}


@pytest.mark.asyncio
async def test_low_content_ignores_numbers_on_a_dead_stop_page():
    notion = _notion()
    notion.query_all_models.return_value = [NotionModel(page_id="m-8", title="REVIVED", status="work")]
    notion.query_all_accounting.return_value = [
        NotionAccounting(page_id="old", title="REVIVED апрель 2026", model_id="m8", status="stop", files=400),
    ]
    grouped = await reminders.low_content(_config(), notion, TODAY)
    assert grouped[None] == ["• REVIVED — 0 файлов"]
