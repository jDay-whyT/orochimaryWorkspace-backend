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
        orders_done=6,
        orders_open=2,
        last_shoot_line="📅 Последняя съёмка: 14 апр · reddit, main pack",
        next_shoot_line="📅 Следующая съёмка: 25 апр · twitter",
    )
    assert "💥 Буст: Анал: plug | Колл: talking" in text
    assert "🔗 Трафик: reddit, twitter" in text
    assert "🏠 Аренда: нужна" in text
    assert "📦 Файлы месяца: OF: 30 | Reddit: 10 | Twitter: 5 | Fansly: 2" in text
    assert "📅 Последняя съёмка: 14 апр · reddit, main pack" in text
    assert "📅 Следующая съёмка: 25 апр · twitter" in text
    assert "📈 Ордера:" in text
    assert "• Done: 6 | Open: 2" in text


def test_format_scout_card_empty_orders_and_files():
    text = _format_scout_card(
        model_name="Курага",
        model_row={"status": "work"},
        traffic="—",
        accounting_row={"of_files": 0, "reddit_files": 0, "twitter_files": 0, "fansly_files": 0},
        orders_done=0,
        orders_open=0,
        last_shoot_line="📅 Последняя съёмка: —",
        next_shoot_line=None,
    )
    assert "🔗 Трафик: —" in text
    assert "📦 Файлы месяца: OF: 0" in text
    assert "📈 Ордера: —" in text
    assert "📅 Следующая съёмка" not in text


def test_format_boost_always_shows_both_labels():
    assert _format_boost("No, —", "") == "Анал: No | Колл: No"
    assert _format_boost("plug", "sexual, No") == "Анал: plug | Колл: sexual"


def test_fetch_orders_stats_merges_main_and_archive(monkeypatch):
    async def fake_query(_notion, db_id, _payload):
        if db_id == "main-db":
            return [
                {
                    "properties": {
                        "type": {"select": {"name": "custom"}},
                        "status": {"select": {"name": "done"}},
                        "count": {"number": 1},
                    }
                }
            ]
        if db_id == "archive-db":
            return [
                {
                    "properties": {
                        "type": {"select": {"name": "short"}},
                        "status": {"select": {"name": "open"}},
                        "count": {"number": 10},
                    }
                }
            ]
        return []

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setattr(scout_card, "ARCHIVE_ORDERS_DBS", ["archive-db"])

    done, open_count = asyncio.run(scout_card._fetch_orders_stats(object(), "main-db", "model-id"))
    assert done == 1
    assert open_count == 1


def test_fetch_orders_stats_without_archives(monkeypatch):
    async def fake_query(_notion, db_id, _payload):
        assert db_id == "main-db"
        return [
            {
                "properties": {
                    "type": {"select": {"name": "call"}},
                    "status": {"select": {"name": "open"}},
                    "count": {"number": 3},
                }
            }
        ]

    monkeypatch.setattr(scout_card, "_query_all_pages", fake_query)
    monkeypatch.setattr(scout_card, "ARCHIVE_ORDERS_DBS", [])

    done, open_count = asyncio.run(scout_card._fetch_orders_stats(object(), "main-db", "model-id"))
    assert done == 0
    assert open_count == 1


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

    assert result == {"of_files": 12, "reddit_files": 4, "twitter_files": 3, "fansly_files": 2}
    assert captured_payload["filter"]["and"] == [
        {"property": "model", "relation": {"contains": "model-page-id"}},
        {
            "property": "edit day",
            "last_edited_time": {"on_or_after": "2026-04-01", "on_or_before": "2026-04-30"},
        },
    ]
