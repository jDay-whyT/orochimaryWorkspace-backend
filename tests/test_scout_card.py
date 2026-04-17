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
        accounting_row={"of_files": 30, "reddit_files": 15, "twitter_files": 11, "fansly_files": 0},
        orders_done=6,
        orders_open=2,
        last_shoot_line="📅 Последняя съёмка: 14 апр · reddit, main pack",
        next_shoot_line="📅 Следующая съёмка: 25 апр · twitter",
    )
    assert "💥 Буст: plug | talking" in text
    assert "🔗 Трафик: reddit, twitter" in text
    assert "🏠 Аренда: нужна" in text
    assert "• OF: 30" in text
    assert "• Reddit: 15" in text
    assert "• Twitter: 11" in text
    assert "Fansly" not in text
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
    assert "📦 Файлы месяца: —" in text
    assert "📈 Ордера: —" in text
    assert "📅 Следующая съёмка" not in text
