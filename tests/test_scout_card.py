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



def test_fetch_orders_by_type_counts_per_type(monkeypatch):
    async def fake_query(_notion, _db_id, _payload):
        return [
            {"properties": {"type": {"select": {"name": "custom"}}, "count": {"number": 1}}},
            {"properties": {"type": {"select": {"name": "custom"}}, "count": {"number": 1}}},
            {"properties": {"type": {"select": {"name": "short"}}, "count": {"number": 1}}},
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    # Use current month so archive DB is not queried (no double-counting).
    result = asyncio.run(
        scout_card._fetch_orders_by_type(object(), "main-db", "model-id", "2026-05")
    )
    assert result == {"custom": 2, "short": 1}


def test_fetch_orders_by_type_queries_archive_for_prev_month(monkeypatch):
    queried_dbs: list[str] = []

    async def fake_query(_notion, db_id, _payload):
        queried_dbs.append(db_id)
        return []

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    # April 2026 is a previous month and has an archive entry (month key 4).
    asyncio.run(
        scout_card._fetch_orders_by_type(object(), "main-db", "model-id", "2026-04")
    )
    from app.utils.constants import ARCHIVE_ORDERS_DBS
    assert "main-db" in queried_dbs
    assert ARCHIVE_ORDERS_DBS[4] in queried_dbs  # April = month 4


def test_fetch_orders_by_type_no_archive_for_current_month(monkeypatch):
    queried_dbs: list[str] = []

    async def fake_query(_notion, db_id, _payload):
        queried_dbs.append(db_id)
        return []

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)

    asyncio.run(
        scout_card._fetch_orders_by_type(object(), "main-db", "model-id", "2026-05")
    )
    assert queried_dbs == ["main-db"]


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

    # Verify date range filter: -30 days = 2026-04-06, +14 days = 2026-05-20
    date_filters = captured["filter"]["and"]
    assert {"property": "date", "date": {"on_or_after": "2026-04-06"}} in date_filters
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
        "total": 0,
        "of_files": 12,
        "reddit_files": 4,
        "twitter_files": 3,
        "fansly_files": 2,
        "social_files": 0,
        "request_files": 0,
    }
    assert captured_payload["filter"]["and"] == [
        {"property": "model", "relation": {"contains": "model-page-id"}},
        {"property": "Title", "title": {"contains": "апрель 2026"}},
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
    assert captured_payload["filter"]["and"] == [
        {"property": "model", "relation": {"contains": "model-page-id"}},
        {"property": "Title", "title": {"contains": "апрель 2026"}},
    ]
