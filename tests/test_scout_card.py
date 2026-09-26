import asyncio
from types import SimpleNamespace

from app.filters.topic_access import TopicAccessMessageFilter
from app.services import scout_card


def test_topic_access_private_only_editor_allowed():
    filt = TopicAccessMessageFilter()
    config = SimpleNamespace(
        allowed_editors={1},
        scouts_chat_id=-1001,
        crm_topic_thread_id=123,
    )
    msg_editor = SimpleNamespace(
        chat=SimpleNamespace(type="private", id=10),
        from_user=SimpleNamespace(id=1),
        message_thread_id=None,
    )
    msg_viewer = SimpleNamespace(
        chat=SimpleNamespace(type="private", id=10),
        from_user=SimpleNamespace(id=2),
        message_thread_id=None,
    )
    assert asyncio.run(filt(msg_editor, config)) is True
    assert asyncio.run(filt(msg_viewer, config)) is False


def test_topic_access_scouts_chat_only_editor_allowed():
    filt = TopicAccessMessageFilter()
    config = SimpleNamespace(
        allowed_editors={1},
        scouts_chat_id=-1001,
        crm_topic_thread_id=123,
    )
    msg_editor = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup", id=-1001),
        from_user=SimpleNamespace(id=1),
        message_thread_id=None,
    )
    msg_stranger = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup", id=-1001),
        from_user=SimpleNamespace(id=2),
        message_thread_id=None,
    )
    assert asyncio.run(filt(msg_editor, config)) is True
    assert asyncio.run(filt(msg_stranger, config)) is False



class _FakeArchiveNotion:
    def __init__(self, orders_db="archive-orders-db", accounting_db="archive-acc-db"):
        self.orders_db = orders_db
        self.accounting_db = accounting_db
        self.lookups: list[tuple[str, str, str]] = []

    async def find_archive_orders_db(self, archive_page_id, month_name_en):
        self.lookups.append(("orders", archive_page_id, month_name_en))
        return self.orders_db

    async def find_archive_accounting_db(self, archive_page_id, month_name_en):
        self.lookups.append(("content", archive_page_id, month_name_en))
        return self.accounting_db


def _fake_today(monkeypatch, y, m, d):
    from datetime import date as real_date

    monkeypatch.setattr(scout_card, "_today", lambda: real_date(y, m, d))


def _order(item_id, out, order_type, status="Done", in_date=None, count=None):
    props = {
        "Title": {"title": [{"plain_text": f"order {item_id}"}]},
        "out": {"date": {"start": out} if out else None},
        "in": {"date": {"start": in_date} if in_date else None},
        "type": {"select": {"name": order_type}},
        "status": {"select": {"name": status}},
    }
    if count is not None:
        props["count"] = {"type": "number", "number": count}
    return {"id": item_id, "properties": props}


def _counts(by_month):
    return {m: b["counts"] for m, b in by_month.items()}


def test_fetch_orders_months_single_main_query_buckets_by_month(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_query(_notion, db_id, payload):
        calls.append((db_id, payload))
        return [
            _order("a", "2026-09-03", "custom"),
            _order("b", "2026-09-20", "custom", count=3),
            _order("c", "2026-08-11", "short"),
            _order("d", "2026-06-01", "call"),
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.delenv("ARCHIVE_PAGE_ID", raising=False)
    _fake_today(monkeypatch, 2026, 9, 24)

    by_month, open_items, failed = asyncio.run(
        scout_card._fetch_orders_months(
            _FakeArchiveNotion(), "main-db", "model-id",
            ["2026-09", "2026-08", "2026-07", "2026-06"],
        )
    )

    assert failed == [] and open_items == []
    assert _counts(by_month) == {
        "2026-09": {"custom": 2},
        "2026-08": {"short": 1},
        "2026-07": {},
        "2026-06": {"call": 1},
    }
    # Newest close date first; count carried through.
    assert [o["id"] for o in by_month["2026-09"]["items"]] == ["b", "a"]
    assert by_month["2026-09"]["items"][0]["count"] == 3
    assert by_month["2026-09"]["items"][1]["count"] is None
    assert len(calls) == 1
    closed, still_open = calls[0][1]["filter"]["or"]
    assert {"property": "out", "date": {"on_or_after": "2026-06-01"}} in closed["and"]
    assert {"property": "out", "date": {"on_or_before": "2026-09-30"}} in closed["and"]
    assert {"property": "out", "date": {"is_empty": True}} in still_open["and"]


def test_fetch_orders_months_open_and_canceled(monkeypatch):
    async def fake_query(_notion, _db_id, _payload):
        return [
            _order("o2", None, "custom", status="Open", in_date="2026-09-10"),
            _order("o1", None, "short", status="Open", in_date="2026-08-28"),
            _order("x", "2026-09-05", "call", status="Canceled"),
            _order("y", None, "custom", status="Canceled", in_date="2026-09-02"),
            _order("z", "2026-09-06", "call"),
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.delenv("ARCHIVE_PAGE_ID", raising=False)
    _fake_today(monkeypatch, 2026, 9, 24)

    by_month, open_items, _ = asyncio.run(
        scout_card._fetch_orders_months(_FakeArchiveNotion(), "main-db", "model-id", ["2026-09"])
    )

    assert [o["id"] for o in open_items] == ["o1", "o2"]  # oldest first
    assert open_items[0]["status"] == "open"
    # Canceled orders are listed but not counted.
    assert by_month["2026-09"]["counts"] == {"call": 1}
    assert sorted(o["id"] for o in by_month["2026-09"]["items"]) == ["x", "y", "z"]


def test_fetch_orders_months_queries_archive_for_past_months_only(monkeypatch):
    queried: list[str] = []

    async def fake_query(_notion, db_id, payload):
        queried.append(db_id)
        if db_id == "archive-orders-db":
            # Archive queries never include the open-orders branch.
            assert "or" not in payload["filter"]
            first_day = payload["filter"]["and"][1]["date"]["on_or_after"]
            return [_order(f"arch-{first_day}", first_day, "verif reddit")]
        return []

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setenv("ARCHIVE_PAGE_ID", "archive-page")
    _fake_today(monkeypatch, 2026, 9, 24)
    notion = _FakeArchiveNotion()

    by_month, _, failed = asyncio.run(
        scout_card._fetch_orders_months(
            notion, "main-db", "model-id", ["2026-09", "2026-08", "2026-07", "2026-06"]
        )
    )

    assert failed == []
    assert [m for kind, _, m in notion.lookups if kind == "orders"] == ["august", "july", "june"]
    assert queried.count("main-db") == 1
    assert queried.count("archive-orders-db") == 3
    assert by_month["2026-09"]["counts"] == {}
    assert by_month["2026-07"]["counts"] == {"verif reddit": 1}


def test_fetch_orders_months_dedupes_across_main_and_archive(monkeypatch):
    async def fake_query(_notion, _db_id, _payload):
        return [_order("same", "2026-08-05", "call")]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setenv("ARCHIVE_PAGE_ID", "archive-page")
    _fake_today(monkeypatch, 2026, 9, 24)

    by_month, _, _ = asyncio.run(
        scout_card._fetch_orders_months(_FakeArchiveNotion(), "main-db", "model-id", ["2026-09", "2026-08"])
    )
    assert by_month["2026-08"]["counts"] == {"call": 1}
    assert len(by_month["2026-08"]["items"]) == 1


def test_fetch_orders_months_archive_failure_marks_month(monkeypatch):
    async def fake_query(_notion, db_id, _payload):
        if db_id == "archive-orders-db":
            raise RuntimeError("Notion API retry limit exceeded")
        return [_order("a", "2026-09-02", "short")]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setenv("ARCHIVE_PAGE_ID", "archive-page")
    _fake_today(monkeypatch, 2026, 9, 24)

    by_month, _, failed = asyncio.run(
        scout_card._fetch_orders_months(_FakeArchiveNotion(), "main-db", "model-id", ["2026-09", "2026-08"])
    )
    assert failed == ["2026-08"]
    assert by_month["2026-09"]["counts"] == {"short": 1}


def test_fetch_orders_months_main_failure_raises(monkeypatch):
    async def fake_query(_notion, _db_id, _payload):
        raise RuntimeError("Notion API retry limit exceeded")

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.delenv("ARCHIVE_PAGE_ID", raising=False)
    _fake_today(monkeypatch, 2026, 9, 24)

    import pytest
    with pytest.raises(RuntimeError):
        asyncio.run(
            scout_card._fetch_orders_months(_FakeArchiveNotion(), "main-db", "model-id", ["2026-09"])
        )


def test_fetch_shoots_covers_three_past_months_and_future(monkeypatch):
    async def fake_query(_notion, _db_id, payload):
        captured["filter"] = payload["filter"]
        return [
            {
                "id": "s1",
                "properties": {
                    "date": {"date": {"start": "2026-06-14"}},
                    "status": {"select": {"name": "done"}},
                    "content": {"multi_select": [{"name": "reddit"}, {"name": "main pack"}]},
                },
            },
            {
                "id": "s2",
                "properties": {
                    "date": {"date": {"start": "2026-10-14T14:30:00.000+03:00"}},
                    "location": {"select": {"name": "rent"}},
                    "status": {"select": {"name": "Planned"}},
                    "content": {"multi_select": [{"name": "twitter"}]},
                },
            },
            {"id": "s3", "properties": {"date": {"date": None}}},
        ]

    captured = {}
    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    _fake_today(monkeypatch, 2026, 9, 24)

    result = asyncio.run(scout_card._fetch_shoots(object(), "planner-db", "model-id"))

    assert result == [
        {"id": "s1", "date": "2026-06-14", "time": "", "location": "",
         "types": ["reddit", "main pack"], "status": "done"},
        {"id": "s2", "date": "2026-10-14", "time": "14:30", "location": "rent",
         "types": ["twitter"], "status": "planned"},
    ]
    date_filters = captured["filter"]["and"]
    # Start of June (3 months back from September), today + 60 days.
    assert {"property": "date", "date": {"on_or_after": "2026-06-01"}} in date_filters
    assert {"property": "date", "date": {"on_or_before": "2026-11-23"}} in date_filters


def _acc_row(title, of_files):
    return {"properties": {"Title": {"title": [{"plain_text": title}]}, "of_files": {"number": of_files}}}


def test_fetch_accounting_months_one_or_query(monkeypatch):
    calls: list[dict] = []

    async def fake_query(_notion, _db_id, payload):
        calls.append(payload)
        return [
            _acc_row("Mia сентябрь 2026", 12),
            _acc_row("Mia август 2026", 7),
            _acc_row("Mia август 2026 old", 1),  # older edit of the same month loses
            _acc_row("Mia июль 2026", 5),
            _acc_row("Mia июнь 2026", 3),
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setenv("ARCHIVE_PAGE_ID", "archive-page")
    _fake_today(monkeypatch, 2026, 9, 24)
    notion = _FakeArchiveNotion()

    result = asyncio.run(
        scout_card._fetch_accounting_months(
            notion, "accounting-db", "model-page-id", ["2026-09", "2026-08", "2026-07", "2026-06"]
        )
    )

    assert {m: r["of_files"] for m, r in result.items()} == {
        "2026-09": 12, "2026-08": 7, "2026-07": 5, "2026-06": 3,
    }
    assert result["2026-09"]["total"] == 0
    assert len(calls) == 1
    and_filter = calls[0]["filter"]["and"]
    assert and_filter[0] == {"property": "model", "relation": {"contains": "model-page-id"}}
    assert and_filter[1] == {"or": [
        {"property": "Title", "title": {"contains": "сентябрь 2026"}},
        {"property": "Title", "title": {"contains": "август 2026"}},
        {"property": "Title", "title": {"contains": "июль 2026"}},
        {"property": "Title", "title": {"contains": "июнь 2026"}},
    ]}
    assert notion.lookups == []  # everything found in main DB


def test_fetch_accounting_months_archive_only_for_missing_past(monkeypatch):
    queried: list[str] = []

    async def fake_query(_notion, db_id, _payload):
        queried.append(db_id)
        if db_id == "archive-acc-db":
            return [_acc_row("Mia июнь 2026", 9)]
        return [_acc_row("Mia август 2026", 7)]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setenv("ARCHIVE_PAGE_ID", "archive-page")
    _fake_today(monkeypatch, 2026, 9, 24)
    notion = _FakeArchiveNotion()

    result = asyncio.run(
        scout_card._fetch_accounting_months(
            notion, "accounting-db", "model-page-id", ["2026-09", "2026-08", "2026-07", "2026-06"]
        )
    )

    # Current month is never looked up in the archive; found months are skipped.
    assert sorted(m for _, _, m in notion.lookups) == ["july", "june"]
    assert result["2026-06"]["of_files"] == 9
    assert "2026-07" not in result and "2026-09" not in result
    assert queried.count("accounting-db") == 1


def test_build_card_partial_failure_keeps_other_sections(monkeypatch):
    async def fake_model_row(_notion, _db, name):
        return {"page_id": "pid", "status": "work", "project": "p", "scout": "@s",
                "assist": "", "language": "", "anal": "", "calls": "", "needs_rent": ""}

    async def ok_traffic(*_a):
        return "reddit"

    async def ok_accounting(*_a):
        return {"2026-09": {"of_files": 1}}

    async def ok_shoots(*_a):
        return []

    async def broken_orders(*_a):
        raise RuntimeError("Notion API retry limit exceeded")

    monkeypatch.setattr(scout_card, "_fetch_model_row", fake_model_row)
    monkeypatch.setattr(scout_card, "_fetch_forms_traffic", ok_traffic)
    monkeypatch.setattr(scout_card, "_fetch_accounting_months", ok_accounting)
    monkeypatch.setattr(scout_card, "_fetch_shoots", ok_shoots)
    monkeypatch.setattr(scout_card, "_fetch_orders_months", broken_orders)
    _fake_today(monkeypatch, 2026, 9, 24)

    config = SimpleNamespace(db_models="m", db_accounting="a", db_orders="o", db_planner="p")
    card = asyncio.run(scout_card.build_scout_report_card_json("Mia", object(), config))

    assert card["content_current"] == {"of_files": 1}
    assert card["traffic"] == ["reddit"]
    assert card["history_months"] == ["2026-08", "2026-07", "2026-06"]
    assert card["today"] == "2026-09-24"
    assert card["failed"] == ["orders", "orders:2026-08", "orders:2026-07", "orders:2026-06"]
    assert card["orders_current"] == {}
    assert card["orders_open"] == []
    assert card["orders_current_items"] == []


def test_accounting_row_reads_new_files_columns_and_formula_total():
    row = scout_card._accounting_row({
        "Total": {"type": "formula", "formula": {"type": "number", "number": 42}},
        "of_files": {"type": "number", "number": 10},
        "tango_files": {"type": "number", "number": 6},
        "comments": {"type": "rich_text", "rich_text": []},
    })
    assert row == {"total": 42, "of_files": 10, "tango_files": 6}
