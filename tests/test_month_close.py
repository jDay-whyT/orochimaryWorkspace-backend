"""Month close: which records are renamed/zeroed and how."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import month_close
from app.services.notion import NotionAccounting, NotionModel

CONFIG = SimpleNamespace(db_accounting="a", db_models="m")
MODELS = [
    NotionModel(page_id="m-1", title="ТРИКО", project="КИЕВ"),
    NotionModel(page_id="m-2", title="ГАРМОНИЯ"),
    NotionModel(page_id="m-3", title="Танго 8", project="TANGO"),
]


def _rec(page_id, title, model_id, content=None):
    return NotionAccounting(page_id=page_id, title=title, model_id=model_id, status="work", content=content)


def _notion(records):
    notion = AsyncMock()
    notion.query_accounting_by_status.return_value = records
    notion.query_all_models.return_value = MODELS
    return notion


@pytest.mark.asyncio
async def test_plan_renames_names_untitled_and_skips_tango():
    notion = _notion([
        _rec("r1", "ТРИКО сентябрь 2026", "m1"),
        _rec("r2", "", "m2"),                           # untitled -> gets a proper name
        _rec("r3", "Танго 8", "m3"),                    # Tango model -> untouched
        _rec("r4", "X", "m1", content=["Tango"]),       # Tango tag -> untouched
        _rec("r5", "ТРИКО октябрь 2026", "m1"),         # already the new month -> keep title
        _rec("r6", "Странное имя", "m1"),               # no month suffix -> keep, but report
    ])
    plan = await month_close.plan_close(CONFIG, notion, "2026-10")

    titles = {item.record.page_id: item.new_title for item in plan.items}
    assert titles == {
        "r1": "ТРИКО октябрь 2026",
        "r2": "ГАРМОНИЯ октябрь 2026",
        "r5": None,
        "r6": None,
    }
    assert plan.tango_skipped == 2
    assert plan.titles_to_fix == ["Странное имя"]


def test_close_payload_zeroes_counts_clears_content_and_renames_in_one_request():
    item = month_close.CloseItem(record=_rec("r1", "ТРИКО сентябрь 2026", "m1"), new_title="ТРИКО октябрь 2026")
    props = month_close.close_payload(item)["properties"]
    for name in ("of_files", "reddit_files", "twitter_files", "fansly_files", "request_files", "tango_files"):
        assert props[name] == {"number": 0}
    assert "social_files" not in props  # column was removed
    assert props["Content"] == {"multi_select": []}  # record has no tags
    assert props["Title"]["title"][0]["text"]["content"] == "ТРИКО октябрь 2026"

    keep = month_close.close_payload(month_close.CloseItem(record=item.record, new_title=None))["properties"]
    assert "Title" not in keep


class _Redis:
    def __init__(self):
        self.kv = {}
        self.seen_during = []

    async def set(self, k, v, ex=None):
        self.kv[k] = v

    async def delete(self, k):
        self.kv.pop(k, None)


@pytest.mark.asyncio
async def test_apply_continues_after_error_and_flags_close_in_progress(monkeypatch):
    monkeypatch.setattr(month_close, "_NOTION_INTERVAL_SECONDS", 0)
    redis = _Redis()
    notion = AsyncMock()

    async def update(page_id, props):
        redis.seen_during.append(month_close.CLOSE_IN_PROGRESS_KEY in redis.kv)
        if page_id == "bad":
            raise RuntimeError("Notion 502")

    notion.update_page_properties.side_effect = update
    plan = month_close.ClosePlan(new_month="2026-10", items=[
        month_close.CloseItem(record=_rec("ok1", "A сентябрь 2026", "m1"), new_title="A октябрь 2026"),
        month_close.CloseItem(record=_rec("bad", "B сентябрь 2026", "m1"), new_title="B октябрь 2026"),
        month_close.CloseItem(record=_rec("ok2", "C сентябрь 2026", "m1"), new_title=None),
    ])

    done, errors = await month_close.apply_close(notion, plan, redis)

    assert done == 2 and len(errors) == 1 and "Notion 502" in errors[0]
    assert all(redis.seen_during)                         # exporters see "close in progress"
    assert month_close.CLOSE_IN_PROGRESS_KEY not in redis.kv  # cleared afterwards


# ---------- notify managers after the close ----------

from unittest.mock import MagicMock  # noqa: E402

from app.handlers import accounting_rename  # noqa: E402

OWNER = 111


def _notify_query(user_id=OWNER, data="notify_month:2026-10"):
    query = MagicMock()
    query.data = data
    query.from_user = SimpleNamespace(id=user_id)
    query.bot.send_message = AsyncMock()
    query.message.edit_reply_markup = AsyncMock()
    query.answer = AsyncMock()
    return query


def _notify_config(chat_id=-100, thread=0):
    return SimpleNamespace(owner_telegram_id=OWNER, managers_chat_id=chat_id, managers_topic_thread_id=thread)


@pytest.mark.asyncio
async def test_notify_sends_to_managers_topic_and_removes_button():
    query = _notify_query()
    await accounting_rename.cb_notify_month(query, _notify_config(thread=7))

    kwargs = query.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == -100 and kwargs["message_thread_id"] == 7
    assert "октябр" in kwargs["text"].lower()
    query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_notify_without_topic_posts_to_chat_root():
    query = _notify_query()
    await accounting_rename.cb_notify_month(query, _notify_config(thread=0))
    assert query.bot.send_message.call_args.kwargs["message_thread_id"] is None


@pytest.mark.asyncio
async def test_notify_ignores_non_owner_and_bad_month():
    query = _notify_query(user_id=999)
    await accounting_rename.cb_notify_month(query, _notify_config())
    query.bot.send_message.assert_not_called()

    query = _notify_query(data="notify_month:oops")
    await accounting_rename.cb_notify_month(query, _notify_config())
    query.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_notify_failure_keeps_button_for_retry():
    query = _notify_query()
    query.bot.send_message.side_effect = RuntimeError("chat not found")
    await accounting_rename.cb_notify_month(query, _notify_config())
    query.message.edit_reply_markup.assert_not_called()


def test_orders_push_lines_report_counts_errors_and_busy_export():
    from app.services.wml_scheduled import ExportReport

    assert "другая выгрузка" in accounting_rename._orders_push_lines(None)[0]

    report = ExportReport(created=["a"], updated=["b", "c"], errors=["X: timeout"])
    lines = accounting_rename._orders_push_lines(report)
    assert "создано 1, обновлено 2, отменено 0" in lines[0]
    assert any("X: timeout" in line for line in lines)
    assert any("после повторной выгрузки" in line for line in lines)


def test_close_keeps_reddit_and_tango_tags_and_clears_the_rest():
    record = _rec("r1", "ТРИКО сентябрь 2026", "m1", content=["OF", "reddit", "Twitter", "Tango", "Fansly"])
    props = month_close.close_payload(month_close.CloseItem(record=record, new_title=None))["properties"]
    assert props["Content"] == {"multi_select": [{"name": "reddit"}, {"name": "Tango"}]}
    assert props["reddit_files"] == {"number": 0}  # the count is still reset

    upper = _rec("r2", "ГАРМОНИЯ сентябрь 2026", "m2", content=["Reddit"])
    props = month_close.close_payload(month_close.CloseItem(record=upper, new_title=None))["properties"]
    assert props["Content"] == {"multi_select": [{"name": "Reddit"}]}  # original spelling kept


# ---------- safety net: report must be written before the cleanup ----------


class _FlagRedis:
    def __init__(self, flags=()):
        self.flags = set(flags)

    async def get(self, key):
        return "1" if key in self.flags else None


async def _preview(monkeypatch, redis, arg="2026-10"):
    plan = month_close.ClosePlan(new_month=arg)
    monkeypatch.setattr(accounting_rename, "plan_close", AsyncMock(return_value=plan))
    message = MagicMock()
    message.chat.type = "private"
    message.from_user = SimpleNamespace(id=OWNER)
    message.answer = AsyncMock()
    await accounting_rename.cmd_rename_month(message, SimpleNamespace(args=arg), _notify_config(), MagicMock(), redis)
    text = message.answer.call_args.args[0]
    button = message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    return text, button


def test_previous_month_wraps_the_year():
    assert accounting_rename.previous_month("2026-10") == "2026-09"
    assert accounting_rename.previous_month("2027-01") == "2026-12"


@pytest.mark.asyncio
async def test_preview_warns_when_report_not_written(monkeypatch):
    text, button = await _preview(monkeypatch, _FlagRedis())
    assert "/reports 2026-09" in text
    assert button.text.startswith("⚠️ Всё равно закрыть")
    assert button.callback_data == "close_month:2026-10"


@pytest.mark.asyncio
async def test_preview_is_clean_when_report_written_or_redis_missing(monkeypatch):
    from app.services.salary_report import salary_reported_redis_key

    text, button = await _preview(monkeypatch, _FlagRedis({salary_reported_redis_key("2026-09")}))
    assert "/reports" not in text and button.text.startswith("✅ Закрыть месяц")

    text, button = await _preview(monkeypatch, None)
    assert "/reports" not in text and button.text.startswith("✅ Закрыть месяц")
