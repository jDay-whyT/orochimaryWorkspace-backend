import asyncio
from types import SimpleNamespace

from app.filters.topic_access import TopicAccessMessageFilter
from app.services.scout_card import _format_scout_card


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


def test_format_scout_card_files_and_orders():
    text = _format_scout_card(
        "Курага",
        {
            "status": "work",
            "project": "GRAND",
            "scout": "@brm",
            "assist": "@cuterr12345",
            "language": "eng > b1, ru, ua",
            "anal": "plug,No",
            "calls": "talking, —",
            "needs_rent": "TRUE",
            "last_shoot_date": "2026-04-14",
        },
        {"optional": "reddit, twitter"},
        {"of_files": "30", "reddit_files": "15", "twitter_files": "11", "fansly_files": "0"},
        6,
        2,
    )
    assert "💥 Буст: plug | talking" in text
    assert "🔗 Трафик: reddit, twitter" in text
    assert "🏠 Аренда: нужна" in text
    assert "• OF: 30" in text
    assert "• Reddit: 15" in text
    assert "• Twitter: 11" in text
    assert "Fansly" not in text
    assert "📅 Последняя съёмка: 14 апр" in text
    assert "📈 Ордера (30д · custom/call):" in text
    assert "• Done: 6 | Open: 2" in text


def test_format_scout_card_empty_orders_and_files():
    text = _format_scout_card(
        "Курага",
        {"status": "work"},
        {},
        {"of_files": "0", "reddit_files": "0", "twitter_files": "0", "fansly_files": "0"},
        0,
        0,
    )
    assert "🔗 Трафик: —" in text
    assert "📦 Файлы месяца: —" in text
    assert "📈 Ордера: —" in text
