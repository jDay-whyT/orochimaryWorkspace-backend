"""Regression tests: salary month guard, WML HTML escaping, comment truncation, DD.MM year, /shoots access."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers import notifications, reports
from app.router import dispatcher
from app.services import salary_report, wml_sync
from app.services.notion import NotionAccounting, NotionPlanner
from app.utils.formatting import MAX_COMMENT_LENGTH, format_appended_comment


# ---- bug 2: /reports must not overwrite a closed month ----

@pytest.mark.asyncio
async def test_reports_refuses_closed_month_and_writes_nothing(monkeypatch):
    rec = NotionAccounting(page_id="a", title="КАЗАШКА ноябрь 2026", model_id="m", status="work")
    notion = AsyncMock()
    notion.query_all_accounting.return_value = [rec]
    config = SimpleNamespace(owner_telegram_id=1, salary_sheet_id="s", timezone="UTC", db_accounting="d")
    message = MagicMock()
    message.chat.type = "private"
    message.from_user.id = 1
    message.answer = AsyncMock()
    write = AsyncMock()
    monkeypatch.setattr(reports, "write_salary_report", write)
    await reports.cmd_reports(message, SimpleNamespace(args="2026-10"), config, notion, MagicMock())
    write.assert_not_awaited()
    assert "2026-11" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_load_salary_accounting_same_month_ok():
    rec = NotionAccounting(page_id="a", title="КАЗАШКА ноябрь 2026", model_id="m", status="work")
    notion = AsyncMock()
    notion.query_all_accounting.return_value = [rec]
    config = SimpleNamespace(db_accounting="d")
    assert await salary_report.load_salary_accounting(notion, config, "2026-11", check_month=True)


# ---- bug 3: scraped text escaped ----

@pytest.mark.asyncio
async def test_new_profile_message_is_escaped():
    profile = SimpleNamespace(name="A<b>&", register_date="x", office="O<", scout="S&", fansly_date=None,
                              profile_url=None, wml_id=None, tango_date=None)
    bot = AsyncMock()
    await wml_sync._notify_new_profile(bot, SimpleNamespace(owner_telegram_id=1), None, profile, None)
    text = bot.send_message.await_args.kwargs["text"]
    assert "A&lt;b&gt;&amp;" in text and "O&lt;" in text and "S&amp;" in text


# ---- bug 4: newest comment kept ----

def test_appended_comment_keeps_new_text():
    out = format_appended_comment("a" * MAX_COMMENT_LENGTH, "NEW COMMENT")
    assert len(out) <= MAX_COMMENT_LENGTH and out.endswith("NEW COMMENT")
    assert format_appended_comment("a", "b" * 3000) == "b" * MAX_COMMENT_LENGTH
    assert format_appended_comment("a", "b") == "a\n---\nb"


# ---- bug 6: DD.MM year closest to today ----

async def _typed(monkeypatch, today, text):
    monkeypatch.setattr(dispatcher, "today_in_tz", lambda tz: today)
    monkeypatch.setattr(dispatcher, "_clear_previous_screen_keyboard", AsyncMock())
    monkeypatch.setattr(dispatcher, "_cleanup_prompt_message", AsyncMock())
    message = MagicMock()
    message.from_user.id = 1
    message.chat.id = 100
    message.answer = AsyncMock(return_value=MagicMock(message_id=9))
    memory = MagicMock()
    state = {"flow": "nlp_shoot", "step": "awaiting_custom_date", "new_shoot": True, "model_id": "m",
             "model_name": "M", "content_types": []}
    config = SimpleNamespace(timezone="UTC", allowed_editors={1})
    await dispatcher._handle_custom_date_input(message, text, state, config, AsyncMock(), memory)
    return next(c.kwargs["shoot_date"] for c in memory.update.call_args_list if "shoot_date" in c.kwargs)


@pytest.mark.asyncio
async def test_dd_mm_goes_back_to_previous_year(monkeypatch):
    assert await _typed(monkeypatch, date(2027, 1, 5), "28.12") == "2026-12-28"


@pytest.mark.asyncio
async def test_dd_mm_goes_forward_and_stays(monkeypatch):
    assert await _typed(monkeypatch, date(2026, 12, 20), "05.01") == "2027-01-05"
    assert await _typed(monkeypatch, date(2026, 11, 13), "15.10") == "2026-10-15"


@pytest.mark.asyncio
async def test_dd_mm_leap_day_skips_invalid_year(monkeypatch):
    assert await _typed(monkeypatch, date(2027, 3, 1), "29.02") == "2028-02-29"


# ---- bug 8: /shoots editors only ----

@pytest.mark.asyncio
async def test_shoots_ignored_for_non_editor(monkeypatch):
    fetch = AsyncMock(return_value=([], date(2026, 11, 13)))
    board = AsyncMock()
    monkeypatch.setattr(notifications, "_fetch_shoots", fetch)
    monkeypatch.setattr(notifications, "update_board", board)
    message = MagicMock()
    message.from_user.id = 99
    message.answer = AsyncMock()
    config = SimpleNamespace(allowed_editors={1})
    for chat_type in ("private", "group"):
        message.chat.type = chat_type
        await notifications.cmd_upcoming_shoots(message, config, AsyncMock())
    fetch.assert_not_awaited()
    board.assert_not_awaited()
    message.answer.assert_not_awaited()


def test_format_board_escapes():
    shoot = NotionPlanner(page_id="p", title="t", model_title="A<i>", date="2026-11-14", location="L&")
    out = notifications._format_board([shoot])
    assert "A&lt;i&gt;" in out and "L&amp;" in out
