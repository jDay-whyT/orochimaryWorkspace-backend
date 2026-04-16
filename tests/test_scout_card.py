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


def test_format_scout_card_winrate_and_rent():
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
            "acc_content": "reddit, twitter",
            "needs_rent": "TRUE",
            "total_files": "0",
            "files_target": "200",
            "files_pct": "0",
            "last_shoot_date": "2026-04-14",
            "orders_total": "9",
            "orders_done": "6",
            "orders_open": "3",
        },
    )
    assert "💥 Буст: plug | talking" in text
    assert "🏠 Аренда: нужна" in text
    assert "📅 Последняя съёмка: 14 апр" in text
    assert "• Winrate: 66.7%" in text
