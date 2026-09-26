"""Month close: final CRM push, then rename + zero the working Accounting records.

Replaces the manual "rename, then zero by hand" routine (the Notion archive copy
is still made by hand beforehand — the API cannot duplicate a database).
Only `work` records are touched; Tango records are left alone (their Content
"Tango" tag marks them, and they are not part of the CRM export).

Each record is updated with ONE request (new title + zeroed counts + empty
Content), so no record is ever zeroed while still carrying the old month's name.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.config import Config
from app.services.notion import NotionAccounting, NotionClient
from app.utils.accounting import rename_month_in_title
from app.utils.constants import ACCOUNTING_STATUS_WORK
from app.utils.formatting import MONTHS_RU_LOWER

LOGGER = logging.getLogger(__name__)

# Number columns that hold a month's file counts (social_files was removed)
FILE_COUNT_FIELDS = ("of_files", "reddit_files", "twitter_files", "fansly_files", "request_files", "tango_files")

CLOSE_IN_PROGRESS_KEY = "month_close:in_progress"  # exporters must skip while set
_NOTION_INTERVAL_SECONDS = 0.35  # Notion allows ~3 requests/s


def month_label(yyyy_mm: str) -> str:
    year, month = yyyy_mm.split("-")
    return f"{MONTHS_RU_LOWER[int(month) - 1]} {year}"


def _is_tango(record: NotionAccounting, model) -> bool:
    return "Tango" in (record.content or []) or (
        model is not None and (model.project or "").strip().upper() == "TANGO"
    )


@dataclass
class CloseItem:
    record: NotionAccounting
    new_title: str | None  # None = keep the current title


@dataclass
class ClosePlan:
    new_month: str
    items: list[CloseItem] = field(default_factory=list)
    tango_skipped: int = 0
    titles_to_fix: list[str] = field(default_factory=list)  # odd titles left as they are


async def plan_close(config: Config, notion: NotionClient, new_month: str) -> ClosePlan:
    """Which `work` records get renamed/zeroed, and what their titles become."""
    records = await notion.query_accounting_by_status(config.db_accounting, ACCOUNTING_STATUS_WORK)
    models = {m.page_id.replace("-", ""): m for m in await notion.query_all_models(config.db_models)}

    plan = ClosePlan(new_month=new_month)
    for record in records:
        model = models.get((record.model_id or "").replace("-", ""))
        if _is_tango(record, model):
            plan.tango_skipped += 1
            continue
        title = (record.title or "").strip()
        if not title or title == "(no title)":
            # Untitled pages (made by hand) get a proper name on the way.
            new_title = f"{model.title} {month_label(new_month)}" if model else None
        else:
            new_title = rename_month_in_title(title, new_month)
            if new_title is None:
                plan.titles_to_fix.append(title)
            elif new_title == title:
                new_title = None
        plan.items.append(CloseItem(record=record, new_title=new_title))
    return plan


def close_payload(item: CloseItem) -> dict[str, Any]:
    props: dict[str, Any] = {name: {"number": 0} for name in FILE_COUNT_FIELDS}
    props["Content"] = {"multi_select": []}
    if item.new_title:
        props["Title"] = {"title": [{"text": {"content": item.new_title}}]}
    return {"properties": props}


async def apply_close(notion: NotionClient, plan: ClosePlan, redis=None) -> tuple[int, list[str]]:
    """Rename + zero every planned record. Returns (done, errors)."""
    if redis is not None:
        await redis.set(CLOSE_IN_PROGRESS_KEY, datetime.utcnow().isoformat(), ex=1800)
    done = 0
    errors: list[str] = []
    try:
        for item in plan.items:
            try:
                await notion.update_page_properties(item.record.page_id, close_payload(item)["properties"])
                done += 1
            except Exception as e:
                LOGGER.exception("Month close failed for %s", item.record.page_id)
                errors.append(f"{item.record.title}: {e}")
            await asyncio.sleep(_NOTION_INTERVAL_SECONDS)
    finally:
        if redis is not None:
            await redis.delete(CLOSE_IN_PROGRESS_KEY)
    return done, errors
