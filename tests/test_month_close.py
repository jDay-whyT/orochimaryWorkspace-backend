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
    assert props["Content"] == {"multi_select": []}
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
