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


def _notify_config(targets=None, topic=7, crm_chat=-100):
    return SimpleNamespace(owner_telegram_id=OWNER, managers_chat_id=-555, crm_chat_id=crm_chat, crm_topic_thread_id=topic,
                           manager_targets={"di": (456, None)} if targets is None else targets)


@pytest.mark.asyncio
async def test_notify_goes_to_robins_topic_and_other_managers_dm_then_removes_button():
    query = _notify_query()
    await accounting_rename.cb_notify_month(query, _notify_config())

    sent = [c.kwargs for c in query.bot.send_message.call_args_list]
    assert {(k["chat_id"], k["message_thread_id"]) for k in sent} == {(-100, 7), (456, None)}
    assert all("September report has been sent" in k["text"] and "start tracking October" in k["text"] for k in sent)
    query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_notify_robin_only_via_topic_and_one_message_per_destination():
    query = _notify_query()
    targets = {"robin": (999, None), "a": (456, None), "b": (456, None)}  # Robin's DM is ignored; a/b share a chat
    await accounting_rename.cb_notify_month(query, _notify_config(targets))
    sent = {(c.kwargs["chat_id"], c.kwargs["message_thread_id"]) for c in query.bot.send_message.call_args_list}
    assert sent == {(-100, 7), (456, None)} and query.bot.send_message.call_count == 2


@pytest.mark.asyncio
async def test_notify_ignores_non_owner_bad_month_and_no_targets():
    for query, config in (
        (_notify_query(user_id=999), _notify_config()),
        (_notify_query(data="notify_month:oops"), _notify_config()),
        (_notify_query(), _notify_config({}, topic=0)),
        (_notify_query(), _notify_config({}, crm_chat=0)),  # CRM group unknown: managers chat is NOT a stand-in
    ):
        await accounting_rename.cb_notify_month(query, config)
        query.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_notify_partial_failure_keeps_button_for_retry():
    query = _notify_query()
    query.bot.send_message.side_effect = [None, RuntimeError("chat not found")]
    await accounting_rename.cb_notify_month(query, _notify_config())
    assert query.bot.send_message.call_count == 2
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
    assert "⚠️" not in text and button.text.startswith("✅ Закрыть месяц")

    text, button = await _preview(monkeypatch, None)
    assert "⚠️" not in text and "/reports" not in text and button.text.startswith("✅ Закрыть месяц")


@pytest.mark.asyncio
async def test_close_button_notifies_managers_and_reaches_the_summary_message(monkeypatch):
    """The 'notify' button must actually be attached to the final close message."""
    plan = month_close.ClosePlan(new_month="2026-10")
    monkeypatch.setattr(accounting_rename, "plan_close", AsyncMock(return_value=plan))
    monkeypatch.setattr(accounting_rename, "apply_close", AsyncMock(return_value=(0, [])))
    sent = AsyncMock()
    monkeypatch.setattr(accounting_rename, "safe_edit_message", sent)
    monkeypatch.setattr(accounting_rename, "safe_query_answer", AsyncMock())
    monkeypatch.setattr(accounting_rename, "try_acquire_write_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(accounting_rename, "release_write_lock", AsyncMock())
    query = _notify_query(data="close_month:2026-10")
    config = SimpleNamespace(owner_telegram_id=OWNER, managers_chat_id=-555, crm_chat_id=-100, crm_topic_thread_id=7,
                             manager_targets={}, wml_username="", wml_password="", wml_export_apply=False)

    await accounting_rename.cb_close_month(query, config, MagicMock(), None)

    final = sent.call_args_list[-1]
    assert "Месяц закрыт" in final.args[1]
    assert final.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "notify_month:2026-10"

    config.crm_chat_id = 0  # nobody to notify -> no button
    sent.reset_mock()
    await accounting_rename.cb_close_month(query, config, MagicMock(), None)
    assert sent.call_args_list[-1].kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_preview_shows_when_report_was_written(monkeypatch):
    from app.services.salary_report import salary_reported_redis_key

    class _Stamped(_FlagRedis):
        async def get(self, key):
            return "2026-10-01T09:30:12" if key in self.flags else None

    text, _ = await _preview(monkeypatch, _Stamped({salary_reported_redis_key("2026-09")}))
    assert "2026-10-01 09:30" in text


def test_month_closed_text_is_plain_english_and_wraps_the_year():
    text = accounting_rename.month_closed_text("2026-10")
    assert "The September report has been sent." in text and "start tracking October now." in text
    assert "December report" in accounting_rename.month_closed_text("2027-01")


class _SetRedis:
    def __init__(self):
        self.sets = {}

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def expire(self, key, seconds):
        pass


@pytest.mark.asyncio
async def test_notify_retry_only_sends_to_those_who_missed_it():
    redis = _SetRedis()
    query = _notify_query()
    query.bot.send_message.side_effect = [RuntimeError("thread not found"), None]  # CRM topic (first) fails, DM ok
    await accounting_rename.cb_notify_month(query, _notify_config({"di": (456, None)}), redis)
    assert query.bot.send_message.call_count == 2
    query.message.edit_reply_markup.assert_not_called()

    query = _notify_query()  # second press, the topic works now
    await accounting_rename.cb_notify_month(query, _notify_config({"di": (456, None)}), redis)
    sent = [(c.kwargs["chat_id"], c.kwargs["message_thread_id"]) for c in query.bot.send_message.call_args_list]
    assert sent == [(-100, 7)]  # di already had it
    query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
