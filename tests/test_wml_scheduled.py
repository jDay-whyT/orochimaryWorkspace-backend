"""Scheduled Notion -> WML CRM export."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.services import wml_scheduled as ws
from app.services.month_close import CLOSE_IN_PROGRESS_KEY
from app.services.notion import NotionAccounting, NotionModel, NotionOrder
from app.services.wml_api import WmlApiError

MODEL = NotionModel(page_id="m-1", title="ТВИКСИ", project="КИЕВ")


class FakeRedis:
    def __init__(self):
        self.kv, self.h = {}, {}

    async def get(self, k):
        return self.kv.get(k)

    async def hget(self, k, f):
        return self.h.get(k, {}).get(f)

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))

    async def hset(self, k, f, v):
        self.h.setdefault(k, {})[f] = v

    async def hdel(self, k, f):
        self.h.get(k, {}).pop(f, None)


def _config(apply=True):
    return SimpleNamespace(db_orders="o", db_models="m", db_accounting="a", wml_export_apply=apply,
                           wml_export_from="2026-09-01", timezone=ZoneInfo("Europe/Brussels"),
                           wml_username="u", wml_password="p", owner_telegram_id=111)


def _order(pid, **kw):
    base = dict(page_id=pid, title=f"ТВИКСИ | {pid}", model_id="m1", order_type="custom",
                in_date="2026-09-20", status="Open", count=1)
    base.update(kw)
    return NotionOrder(**base)


def _notion(orders, accounting=()):
    notion = AsyncMock()
    notion.query_all_orders.return_value = list(orders)
    notion.query_all_models.return_value = [MODEL]
    notion.query_all_accounting.return_value = list(accounting)
    return notion


def _api():
    api = MagicMock()
    api.create_order.side_effect = lambda payload: {"id": 500 + len(api.create_order.mock_calls)}
    api.update_order.return_value = {"success": True}
    api.upsert_files.return_value = {"success": True}
    return api


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ws, "_SEND_INTERVAL_SECONDS", 0)


# ---------- orders ----------

@pytest.mark.asyncio
async def test_report_mode_sends_and_stores_nothing():
    redis, api, report = FakeRedis(), _api(), ws.ExportReport()
    notion = _notion([_order("new"), _order("gone", status="Canceled"), _order("old", in_date="2026-08-20")])
    await ws.export_orders(_config(apply=False), notion, redis, api, False, report)
    assert report.created == ["ТВИКСИ | new"]          # canceled and pre-September orders are not created
    api.create_order.assert_not_called()
    notion.set_order_wml_id.assert_not_awaited()
    assert redis.h == {}


@pytest.mark.asyncio
async def test_create_then_second_run_is_a_noop():
    redis, api = FakeRedis(), _api()
    order = _order("new", out_date="2026-09-25", received=1)
    notion = _notion([order])
    await ws.export_orders(_config(), notion, redis, api, True, ws.ExportReport())
    wml_id = notion.set_order_wml_id.await_args.args[1]
    assert json.loads(redis.h[ws.ORDER_STATE_KEY]["new"])["closed"] is True

    order.wml_id = wml_id  # Notion now has the id
    report = ws.ExportReport()
    await ws.export_orders(_config(), _notion([order]), redis, api, True, report)
    assert report.empty() and api.update_order.call_count == 0


@pytest.mark.asyncio
async def test_changed_fields_are_updated_and_cancel_sent_once():
    redis, api = FakeRedis(), _api()
    redis.h[ws.ORDER_STATE_KEY] = {
        "a": ws._state(11, {"count": 1}, "active", False),
        "b": ws._state(12, {"count": 1}, "active", False),
    }
    orders = [_order("a", wml_id=11, out_date="2026-09-26", received=1), _order("b", wml_id=12, status="Canceled")]
    report = ws.ExportReport()
    await ws.export_orders(_config(), _notion(orders), redis, api, True, report)
    api.update_order.assert_any_call(11, {"count": 1, "out": "2026-09-26", "received": 1, "status": "active"})
    api.update_order.assert_any_call(12, {"status": "cancelled"})
    assert report.updated == ["ТВИКСИ | a"] and report.cancelled == ["ТВИКСИ | b"]

    api.update_order.reset_mock()
    await ws.export_orders(_config(), _notion(orders), redis, api, True, ws.ExportReport())
    api.update_order.assert_not_called()


@pytest.mark.asyncio
async def test_first_sight_of_test_sent_order_resyncs_silently():
    redis, api, report = FakeRedis(), _api(), ws.ExportReport()
    await ws.export_orders(_config(), _notion([_order("t", wml_id=7)]), redis, api, True, report)
    api.update_order.assert_called_once()
    assert report.updated == []  # not reported: the CRM already had it


@pytest.mark.asyncio
async def test_vanished_closed_is_archive_open_is_cancelled():
    redis, api = FakeRedis(), _api()
    redis.h[ws.ORDER_STATE_KEY] = {
        "done": ws._state(21, {"out": "2026-09-10"}, "active", True),
        "open": ws._state(22, {"count": 1}, "active", False),
    }
    report = ws.ExportReport()
    await ws.export_orders(_config(), _notion([]), redis, api, True, report)
    api.update_order.assert_called_once_with(22, {"status": "cancelled"})
    assert redis.h[ws.ORDER_STATE_KEY] == {}  # both forgotten; the done one stays in the CRM untouched


@pytest.mark.asyncio
async def test_mass_vanish_only_warns():
    redis, api = FakeRedis(), _api()
    redis.h[ws.ORDER_STATE_KEY] = {f"o{i}": ws._state(i, {"count": 1}, "active", False) for i in range(11)}
    report = ws.ExportReport()
    await ws.export_orders(_config(), _notion([]), redis, api, True, report)
    api.update_order.assert_not_called()
    assert report.warnings and "11" in report.warnings[0]


# ---------- files ----------

def _acc(**kw):
    base = dict(page_id="a1", title="ТВИКСИ сентябрь 2026", model_id="m1", status="work", of_files=10)
    base.update(kw)
    return NotionAccounting(**base)


@pytest.mark.asyncio
async def test_files_sent_only_on_change_and_zeroing_is_blocked():
    redis, api = FakeRedis(), _api()
    await ws.export_files(_config(), _notion([], [_acc()]), redis, api, True, ws.ExportReport())
    assert api.upsert_files.call_count == 1

    await ws.export_files(_config(), _notion([], [_acc()]), redis, api, True, ws.ExportReport())
    assert api.upsert_files.call_count == 1  # unchanged -> nothing sent

    report = ws.ExportReport()
    await ws.export_files(_config(), _notion([], [_acc(of_files=0)]), redis, api, True, report)
    assert api.upsert_files.call_count == 1 and "обнулились" in report.warnings[0]


@pytest.mark.asyncio
async def test_files_decrease_is_held_once_then_sent_if_unchanged():
    redis, api = FakeRedis(), _api()
    await ws.export_files(_config(), _notion([], [_acc(of_files=200)]), redis, api, True, ws.ExportReport())
    report = ws.ExportReport()
    await ws.export_files(_config(), _notion([], [_acc(of_files=20)]), redis, api, True, report)
    assert api.upsert_files.call_count == 1 and "уменьшилось of 200→20" in report.warnings[0]
    report = ws.ExportReport()
    await ws.export_files(_config(), _notion([], [_acc(of_files=20)]), redis, api, True, report)
    assert api.upsert_files.call_count == 2 and not report.warnings  # confirmed by staying the same


@pytest.mark.asyncio
async def test_files_spike_is_held():
    redis, api = FakeRedis(), _api()
    await ws.export_files(_config(), _notion([], [_acc(of_files=100)]), redis, api, True, ws.ExportReport())
    report = ws.ExportReport()
    await ws.export_files(_config(), _notion([], [_acc(of_files=1000)]), redis, api, True, report)
    assert api.upsert_files.call_count == 1 and "скачок" in report.warnings[0]


@pytest.mark.asyncio
async def test_files_new_empty_month_is_not_sent():
    redis, api = FakeRedis(), _api()
    report = ws.ExportReport()
    await ws.export_files(_config(), _notion([], [_acc(of_files=0)]), redis, api, True, report)
    api.upsert_files.assert_not_called()
    assert report.empty()


@pytest.mark.asyncio
async def test_files_of_model_with_two_live_records_are_not_sent():
    redis, api = FakeRedis(), _api()
    report = ws.ExportReport()
    records = [_acc(), _acc(page_id="a2", title="", of_files=50)]
    await ws.export_files(_config(), _notion([], records), redis, api, True, report)
    api.upsert_files.assert_not_called()
    assert "две живые записи" in report.warnings[0]


@pytest.mark.asyncio
async def test_unknown_profile_is_reported_once():
    redis, api = FakeRedis(), _api()
    api.upsert_files.side_effect = WmlApiError("WML API POST /content-request-files: HTTP 422: Profile not found")
    first, second = ws.ExportReport(), ws.ExportReport()
    await ws.export_files(_config(), _notion([], [_acc()]), redis, api, True, first)
    await ws.export_files(_config(), _notion([], [_acc()]), redis, api, True, second)
    assert "нет такого профиля" in first.warnings[0] and not first.errors
    assert second.empty()
    assert api.upsert_files.call_count == 2  # still retried


@pytest.mark.asyncio
async def test_identical_orders_are_all_created():
    # several identical orders on one day are normal (entered one by one)
    redis, api = FakeRedis(), _api()
    orders = [_order("a", title="ТВИКСИ | custom"), _order("b", title="ТВИКСИ | custom")]
    report = ws.ExportReport()
    await ws.export_orders(_config(), _notion(orders), redis, api, True, report)
    assert api.create_order.call_count == 2 and not report.warnings


@pytest.mark.asyncio
async def test_orders_sharing_one_crm_id_are_not_sent():
    redis, api = FakeRedis(), _api()
    orders = [_order("a", wml_id=7, count=2), _order("b", wml_id=7, count=3)]
    report = ws.ExportReport()
    await ws.export_orders(_config(), _notion(orders), redis, api, True, report)
    api.update_order.assert_not_called()
    assert "CRM id 7" in report.warnings[0]


# ---------- entry point ----------

@pytest.mark.asyncio
async def test_skipped_during_month_close_and_silent_when_nothing_happens(monkeypatch):
    bot = SimpleNamespace(send_message=AsyncMock())
    redis = FakeRedis()
    redis.kv[CLOSE_IN_PROGRESS_KEY] = "1"
    notion = _notion([_order("new")])
    await ws.run_wml_export(bot, _config(), notion, redis)
    notion.query_all_orders.assert_not_awaited()

    redis.kv.clear()
    monkeypatch.setattr(ws, "WmlApi", lambda *a: _api())
    await ws.run_wml_export(bot, _config(apply=False), _notion([]), redis)
    bot.send_message.assert_not_awaited()  # nothing to do -> no message
