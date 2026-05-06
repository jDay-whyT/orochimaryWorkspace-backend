import asyncio
from types import SimpleNamespace

from app.filters.topic_access import TopicAccessMessageFilter
from app.services import scout_card
from app.services.scout_card import _format_boost, _format_scout_card


def test_topic_access_private_only_editor_allowed():
    filt = TopicAccessMessageFilter()
    config = SimpleNamespace(
        allowed_editors={1},
        report_viewers={2},
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


def test_topic_access_scouts_chat_allows_report_viewer():
    filt = TopicAccessMessageFilter()
    config = SimpleNamespace(
        allowed_editors={1},
        report_viewers={2},
        scouts_chat_id=-1001,
        crm_topic_thread_id=123,
    )
    msg = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup", id=-1001),
        from_user=SimpleNamespace(id=2),
        message_thread_id=None,
    )
    assert asyncio.run(filt(msg, config)) is True


def test_format_scout_card_files_orders_and_shoots():
    text = _format_scout_card(
        model_name="Курага",
        model_row={
            "status": "work",
            "project": "GRAND",
            "scout": "@brm",
            "assist": "@cuterr12345",
            "language": "eng > b1, ru, ua",
            "anal": "plug,No",
            "calls": "talking, —",
            "needs_rent": "TRUE",
        },
        traffic="reddit, twitter",
        accounting_row={
            "of_files": 30,
            "reddit_files": 10,
            "twitter_files": 5,
            "fansly_files": 2,
        },
        accounting_prev_row={
            "of_files": 12,
            "reddit_files": 8,
        },
        shoots=[
            ("2026-04-14", ["reddit", "main pack"], "done"),
            ("2026-05-25", ["twitter"], "planned"),
        ],
        orders_current={"custom": 2, "short": 1},
        orders_prev={"custom": 5, "verif reddit": 2},
    )
    assert "<i>" in text
    assert "anal:" in text
    assert "calls:" in text
    assert "traffic:" in text
    assert "rent:" in text
    assert "Content" in text
    assert "OF: <b>30</b>" in text
    assert "Reddit: <b>10</b>" in text
    assert "OF: <b>12</b>" in text
    assert "Shoots" in text
    assert "<b>14 apr</b>" in text
    assert "reddit, main pack · done" in text
    assert "<b>25 may</b>" in text
    assert "twitter · planned" in text
    assert "Orders" in text
    assert "custom: <b>2</b>" in text
    assert "short: <b>1</b>" in text
    assert "verif: <b>2</b>" in text


def test_format_scout_card_empty_orders_and_files():
    text = _format_scout_card(
        model_name="Курага",
        model_row={"status": "work"},
        traffic="—",
        accounting_row={"of_files": 0, "reddit_files": 0, "twitter_files": 0, "fansly_files": 0},
        accounting_prev_row=None,
        shoots=[],
        orders_current={},
        orders_prev={},
    )
    assert "traffic:" in text
    assert "Content: —" in text
    assert "Shoots: —" in text
    assert "Orders: no orders" in text


def test_format_boost_always_shows_both_labels():
    assert _format_boost("No, —", "") == "Анал: No | Колл: No"
    assert _format_boost("plug", "sexual, No") == "Анал: plug | Колл: sexual"


def test_fetch_orders_by_type_counts_per_type(monkeypatch):
    async def fake_query(_notion, _db_id, _payload):
        return [
            {"properties": {"type": {"select": {"name": "custom"}}, "count": {"number": 1}}},
            {"properties": {"type": {"select": {"name": "custom"}}, "count": {"number": 1}}},
            {"properties": {"type": {"select": {"name": "short"}}, "count": {"number": 1}}},
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    result = asyncio.run(
        scout_card._fetch_orders_by_type(object(), "main-db", "model-id", "2026-04")
    )
    assert result == {"custom": 2, "short": 1}


def test_fetch_orders_by_type_empty(monkeypatch):
    async def fake_query(_notion, _db_id, _payload):
        return []

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    result = asyncio.run(
        scout_card._fetch_orders_by_type(object(), "main-db", "model-id", "2026-05")
    )
    assert result == {}


def test_fetch_shoots_lines_returns_tuples_in_range(monkeypatch):
    async def fake_query(_notion, _db_id, payload):
        captured["filter"] = payload["filter"]
        return [
            {
                "properties": {
                    "date": {"date": {"start": "2026-04-14"}},
                    "status": {"select": {"name": "done"}},
                    "content": {"multi_select": [{"name": "reddit"}, {"name": "main pack"}]},
                }
            },
            {
                "properties": {
                    "date": {"date": {"start": "2026-05-14"}},
                    "status": {"select": {"name": "planned"}},
                    "content": {"multi_select": [{"name": "twitter"}]},
                }
            },
        ]

    captured = {}
    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    class FakeDate:
        @staticmethod
        def today():
            from datetime import date
            return date(2026, 5, 6)

    monkeypatch.setattr(scout_card, "date", FakeDate)

    result = asyncio.run(
        scout_card._fetch_shoots_lines(object(), "planner-db", "model-id")
    )

    assert len(result) == 2
    assert result[0] == ("2026-04-14", ["reddit", "main pack"], "done")
    assert result[1] == ("2026-05-14", ["twitter"], "planned")

    # Verify date range filter: -60 days = 2026-03-07, +14 days = 2026-05-20
    date_filters = captured["filter"]["and"]
    assert {"property": "date", "date": {"on_or_after": "2026-03-07"}} in date_filters
    assert {"property": "date", "date": {"on_or_before": "2026-05-20"}} in date_filters


def test_fetch_monthly_accounting_filters_by_model_and_edit_day(monkeypatch):
    captured_payload = {}

    async def fake_query(_notion, _db_id, payload):
        nonlocal captured_payload
        captured_payload = payload
        return [
            {
                "properties": {
                    "of_files": {"number": 12},
                    "reddit_files": {"number": 4},
                    "twitter_files": {"number": 3},
                    "fansly_files": {"number": 2},
                }
            }
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    class FakeDate:
        @staticmethod
        def today():
            from datetime import date
            return date(2026, 4, 17)

    monkeypatch.setattr(scout_card, "date", FakeDate)

    result = asyncio.run(
        scout_card._fetch_monthly_accounting(
            notion=object(),
            db_accounting="accounting-db",
            model_page_id="model-page-id",
        )
    )

    assert result == {
        "of_files": 12,
        "reddit_files": 4,
        "twitter_files": 3,
        "fansly_files": 2,
        "social_files": 0,
        "request_files": 0,
    }
    assert captured_payload["filter"]["and"] == [
        {"property": "model", "relation": {"contains": "model-page-id"}},
        {
            "property": "edit day",
            "last_edited_time": {"on_or_after": "2026-04-01", "on_or_before": "2026-04-30"},
        },
    ]


def test_fetch_monthly_accounting_prev_month(monkeypatch):
    captured_payload = {}

    async def fake_query(_notion, _db_id, payload):
        nonlocal captured_payload
        captured_payload = payload
        return []

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    class FakeDate:
        @staticmethod
        def today():
            from datetime import date
            return date(2026, 5, 10)

    monkeypatch.setattr(scout_card, "date", FakeDate)

    result = asyncio.run(
        scout_card._fetch_monthly_accounting(
            notion=object(),
            db_accounting="accounting-db",
            model_page_id="model-page-id",
            month_offset=-1,
        )
    )

    assert result is None
    date_filter = captured_payload["filter"]["and"][1]["last_edited_time"]
    assert date_filter["on_or_after"] == "2026-04-01"
    assert date_filter["on_or_before"] == "2026-04-30"
