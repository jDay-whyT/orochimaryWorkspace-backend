"""Orders -> WML CRM export: payload building, batch picking, sending, API client."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import wml_export
from app.services.notion import NotionModel, NotionOrder
from app.services.wml_api import WmlApi, WmlApiError

MODEL = NotionModel(page_id="m-1", title="ТВИКСИ", project="КИЕВ")
TANGO = NotionModel(page_id="m-2", title="Танго 8", project="TANGO")


def _order(**kw):
    base = dict(page_id="o1", title="ТВИКСИ | custom 1/1", model_id="m1", order_type="custom",
                in_date="2026-09-18", status="Open", count=1)
    base.update(kw)
    return NotionOrder(**base)


# ---------- payload ----------

def test_payload_open_order_has_no_out():
    payload, reason = wml_export.order_payload(_order(), MODEL)
    assert reason is None
    assert payload == {"profile": "ТВИКСИ", "title": "ТВИКСИ | custom 1/1", "in": "2026-09-18", "type": 2, "count": 1}


def test_payload_closed_by_out_even_if_status_open():
    payload, _ = wml_export.order_payload(
        _order(order_type="short", count=3, out_date="2026-09-25", received=3, status="Open"), MODEL)
    assert payload["type"] == 3 and payload["out"] == "2026-09-25" and payload["received"] == 3


@pytest.mark.parametrize("order,model,reason", [
    (_order(), None, "нет модели"),
    (_order(), TANGO, "Tango"),
    (_order(status="Canceled"), MODEL, "отменён"),
    (_order(order_type="mystery"), MODEL, "тип «mystery»"),
    (_order(in_date=None), MODEL, "нет даты in"),
])
def test_payload_skips(order, model, reason):
    assert wml_export.order_payload(order, model) == (None, reason)


def test_all_order_types_mapped():
    for t, expected in [("ad request", 1), ("custom", 2), ("short", 3), ("call", 4), ("verif reddit", 5)]:
        assert wml_export.order_payload(_order(order_type=t), MODEL)[0]["type"] == expected


# ---------- picking ----------

@pytest.mark.asyncio
async def test_pick_latest_unsent_exportable_orders():
    notion = AsyncMock()
    notion.query_all_models.return_value = [MODEL, TANGO]
    notion.query_orders_in_month.return_value = [
        _order(page_id="old", in_date="2026-09-01"),
        _order(page_id="new", in_date="2026-09-25"),
        _order(page_id="mid", in_date="2026-09-10"),
        _order(page_id="sent", in_date="2026-09-26", wml_id=7),
        _order(page_id="tango", in_date="2026-09-26", model_id="m2"),
    ]
    batch = await wml_export.pick_month_orders(SimpleNamespace(db_orders="o", db_models="m"), notion, "2026-09", 2)
    assert [o.page_id for o, _ in batch.items] == ["new", "mid"]   # latest first, limit 2
    assert batch.already_sent == 1
    assert batch.skipped == {"Tango": 1}


# ---------- sending ----------

@pytest.mark.asyncio
async def test_send_stores_crm_id_and_continues_after_error(monkeypatch):
    monkeypatch.setattr(wml_export, "_SEND_INTERVAL_SECONDS", 0)
    api = MagicMock()
    api.create_order.side_effect = [{"id": 11}, WmlApiError("profile not found"), {"id": 13}]
    notion = AsyncMock()
    items = [(_order(page_id=p), {"title": p}) for p in ("a", "b", "c")]

    sent, errors = await wml_export.send_orders(api, notion, items)

    assert sent == 2 and len(errors) == 1 and "profile not found" in errors[0]
    notion.set_order_wml_id.assert_any_await("a", 11)
    notion.set_order_wml_id.assert_any_await("c", 13)
    assert notion.set_order_wml_id.await_count == 2


# ---------- API client ----------

def _resp(status, data):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    return r


def test_api_logs_in_once_and_retries_on_401():
    session = MagicMock()
    session.post.side_effect = [_resp(200, {"success": True, "token": "t1"}),
                                _resp(200, {"success": True, "token": "t2"})]
    session.request.side_effect = [_resp(401, {"success": False}),
                                   _resp(200, {"success": True, "id": 5})]
    api = WmlApi("u", "p", session=session)

    assert api.create_order({"title": "x"})["id"] == 5
    assert session.post.call_count == 2  # initial login + re-login after 401
    assert session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer t2"


def test_api_raises_on_business_error():
    session = MagicMock()
    session.post.return_value = _resp(200, {"success": True, "token": "t"})
    session.request.return_value = _resp(422, {"success": False, "error": "bad type"})
    with pytest.raises(WmlApiError, match="bad type"):
        WmlApi("u", "p", session=session).upsert_files({"profile": "X"})
