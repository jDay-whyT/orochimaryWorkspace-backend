"""Scout report card helpers based on Notion data."""

from __future__ import annotations

import asyncio
import calendar as _calendar
import logging
import os
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Config

LOGGER = logging.getLogger(__name__)

from app.utils.constants import ARCHIVE_ORDERS_DBS, DB_FORMS_DEFAULT
from app.utils.formatting import MONTHS_RU_LOWER
from app.services.notion import NotionClient

_DB_MODELS_DEFAULT = "1fc32bee-e7a0-809f-8bbe-000be8182d4d"
_DB_ORDERS_DEFAULT = "20b32bee-e7a0-81ab-b72b-000b78a1e78a"
_DB_PLANNER_DEFAULT = "1fb32bee-e7a0-815f-ae1d-000ba6995a1a"
_DB_ACCOUNTING_DEFAULT = "1ff32bee-e7a0-8025-a26c-000bc7008ec8"


def _parse_iso_date(raw: str | None) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    value = value[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None



def _extract_title(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    fragments = prop.get("title", [])
    text = "".join(part.get("plain_text", "") for part in fragments).strip()
    return text or None


def _extract_select_name(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    for key in ("select", "status"):
        obj = prop.get(key)
        if obj and obj.get("name"):
            return obj["name"]
    return None


def _extract_rich_text(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    fragments = prop.get("rich_text", [])
    text = "".join(part.get("plain_text", "") for part in fragments).strip()
    return text or None


def _extract_number(prop: dict[str, Any] | None) -> int:
    if not prop:
        return 0
    num = prop.get("number")
    if num is None:
        return 0
    try:
        return int(float(num))
    except (TypeError, ValueError):
        return 0


def _extract_multi_select(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    values = prop.get("multi_select", [])
    return [item.get("name", "").strip() for item in values if item.get("name", "").strip()]


def _extract_relation_ids(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    relation = prop.get("relation", [])
    return [item.get("id", "") for item in relation if item.get("id")]


def _extract_date(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    date_obj = prop.get("date")
    if not date_obj:
        return None
    return date_obj.get("start")


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()



async def _query_all_pages(
    notion: NotionClient,
    database_id: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        query_payload = dict(payload)
        if cursor:
            query_payload["start_cursor"] = cursor
        data = await notion.query_database(database_id, query_payload)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break

    return results


async def _fetch_model_row(notion: NotionClient, db_models: str, model_name: str) -> dict[str, Any] | None:
    models = await notion.query_models(db_models, model_name, limit=25)
    target = _normalize(model_name)
    model = next((item for item in models if _normalize(item.title) == target), None)
    if not model:
        return None

    page = await notion.get_page(model.page_id)
    props = page.get("properties", {})
    return {
        "page_id": model.page_id,
        "status": _extract_select_name(props.get("status")) or model.status,
        "project": _extract_select_name(props.get("project")) or model.project,
        "scout": _extract_select_name(props.get("scout")) or _extract_rich_text(props.get("scout")),
        "assist": _extract_rich_text(props.get("assist")) or _extract_select_name(props.get("assist")),
        "language": _extract_rich_text(props.get("language")) or ", ".join(_extract_multi_select(props.get("language"))),
        "anal": ", ".join(_extract_multi_select(props.get("anal"))),
        "calls": ", ".join(_extract_multi_select(props.get("calls"))),
        "needs_rent": _extract_select_name(props.get("needs_rent"))
        or _extract_rich_text(props.get("needs_rent")),
    }


async def _fetch_forms_traffic(notion: NotionClient, db_forms: str, model_page_id: str) -> str:
    items = await _query_all_pages(
        notion,
        db_forms,
        {
            "page_size": 100,
            "filter": {"property": "model", "relation": {"contains": model_page_id}},
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        },
    )
    if not items:
        return "—"
    optional = _extract_multi_select(items[0].get("properties", {}).get("optional"))
    return ", ".join(optional) if optional else "—"


async def _fetch_monthly_accounting(
    notion: NotionClient,
    db_accounting: str,
    model_page_id: str,
    month_offset: int = 0,
) -> dict[str, int] | None:
    today = date.today()
    # Navigate months using only replace/timedelta to stay compatible with
    # monkeypatched date.today() in tests (FakeDate doesn't support construction).
    target = today
    for _ in range(abs(month_offset)):
        if month_offset < 0:
            target = target.replace(day=1) - timedelta(days=1)
        else:
            target = (target.replace(day=28) + timedelta(days=4)).replace(day=1)

    # Title filter: "апрель 2026" — more reliable than last_edited_time,
    # which misses records last edited outside the target month.
    month_label = MONTHS_RU_LOWER[target.month - 1]
    title_contains = f"{month_label} {target.year}"

    LOGGER.debug(
        "scout accounting query: model=%s offset=%d title_contains=%r",
        model_page_id, month_offset, title_contains,
    )

    items = await _query_all_pages(
        notion,
        db_accounting,
        {
            "page_size": 50,
            "filter": {
                "and": [
                    {"property": "model", "relation": {"contains": model_page_id}},
                    {"property": "Title", "title": {"contains": title_contains}},
                ]
            },
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        },
    )

    LOGGER.debug(
        "scout accounting result: model=%s offset=%d title_contains=%r count=%d",
        model_page_id, month_offset, title_contains, len(items),
    )

    if not items and month_offset < 0:
        archive_page_id = os.getenv("ARCHIVE_PAGE_ID", "").strip()
        if archive_page_id:
            month_en_full = target.strftime("%B").lower()
            archive_db_id = await notion.find_archive_accounting_db(archive_page_id, month_en_full)
            if archive_db_id:
                LOGGER.debug(
                    "scout accounting fallback to archive db=%s for %s",
                    archive_db_id, title_contains,
                )
                items = await _query_all_pages(
                    notion,
                    archive_db_id,
                    {
                        "page_size": 50,
                        "filter": {
                            "and": [
                                {"property": "model", "relation": {"contains": model_page_id}},
                                {"property": "Title", "title": {"contains": title_contains}},
                            ]
                        },
                        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
                    },
                )
                LOGGER.debug(
                    "scout accounting archive result: model=%s title=%r count=%d",
                    model_page_id, title_contains, len(items),
                )

    if not items:
        return None
    props = items[0].get("properties", {})
    return {
        "total": _extract_number(props.get("Total")),
        "of_files": _extract_number(props.get("of_files")),
        "reddit_files": _extract_number(props.get("reddit_files")),
        "twitter_files": _extract_number(props.get("twitter_files")),
        "fansly_files": _extract_number(props.get("fansly_files")),
        "social_files": _extract_number(props.get("social_files")),
        "request_files": _extract_number(props.get("request_files")),
    }


async def _fetch_shoots_lines(
    notion: NotionClient,
    db_planner: str,
    model_page_id: str,
) -> list[tuple[str, list[str], str]]:
    today = date.today()
    date_from = (today - timedelta(days=30)).isoformat()
    date_to = (today + timedelta(days=14)).isoformat()

    items = await _query_all_pages(
        notion,
        db_planner,
        {
            "page_size": 100,
            "filter": {
                "and": [
                    {"property": "model", "relation": {"contains": model_page_id}},
                    {"property": "date", "date": {"on_or_after": date_from}},
                    {"property": "date", "date": {"on_or_before": date_to}},
                ]
            },
            "sorts": [{"property": "date", "direction": "ascending"}],
        },
    )

    result: list[tuple[str, list[str], str]] = []
    for item in items:
        props = item.get("properties", {})
        shoot_date_raw = _extract_date(props.get("date"))
        if not _parse_iso_date(shoot_date_raw):
            continue
        status = _normalize(_extract_select_name(props.get("status")))
        content = _extract_multi_select(props.get("content"))
        result.append((shoot_date_raw, content, status))

    return result


async def _fetch_orders_by_type(
    notion: NotionClient,
    db_orders: str,
    model_page_id: str,
    yyyy_mm: str,
) -> dict[str, int]:
    year, month_str = yyyy_mm.split("-")
    year_i, month_i = int(year), int(month_str)
    first_day = date(year_i, month_i, 1).isoformat()
    last_day = date(year_i, month_i, _calendar.monthrange(year_i, month_i)[1]).isoformat()

    query_payload = {
        "page_size": 100,
        "filter": {
            "and": [
                {"property": "model", "relation": {"contains": model_page_id}},
                {"property": "out", "date": {"on_or_after": first_day}},
                {"property": "out", "date": {"on_or_before": last_day}},
            ]
        },
    }

    dbs_to_query = [db_orders]

    today = date.today()
    is_prev_month = (year_i, month_i) < (today.year, today.month)
    if is_prev_month and month_i in ARCHIVE_ORDERS_DBS:
        dbs_to_query.append(ARCHIVE_ORDERS_DBS[month_i])

    all_items: list = []
    for db_id in dbs_to_query:
        try:
            all_items.extend(await _query_all_pages(notion, db_id, query_payload))
        except Exception:
            LOGGER.warning("_fetch_orders_by_type: failed to query db=%s", db_id)

    result: dict[str, int] = {}
    for item in all_items:
        props = item.get("properties", {})
        order_type = _normalize(_extract_select_name(props.get("type")))
        if order_type:
            result[order_type] = result.get(order_type, 0) + 1

    return result


async def build_scout_report_card_json(
    model_name: str,
    notion: NotionClient,
    config: "Config",
) -> dict | None:
    """Build scout card as structured JSON dict (for Mini App API)."""
    db_models = config.db_models
    db_forms = os.getenv("DB_FORMS", DB_FORMS_DEFAULT).strip()
    db_accounting = config.db_accounting
    db_orders = config.db_orders
    db_planner = config.db_planner

    model_row = await _fetch_model_row(notion, db_models, model_name)
    if not model_row:
        return None

    model_page_id = model_row["page_id"]

    today = date.today()
    cur_yyyy_mm = today.strftime("%Y-%m")

    def _month_ago(n: int) -> str:
        t = today
        for _ in range(n):
            t = t.replace(day=1) - timedelta(days=1)
        return t.strftime("%Y-%m")

    h_months = [_month_ago(1), _month_ago(2), _month_ago(3)]
    prev_yyyy_mm = h_months[0]

    (
        traffic,
        accounting_row,
        accounting_h1,
        accounting_h2,
        accounting_h3,
        shoots,
        orders_current,
        orders_h1,
        orders_h2,
        orders_h3,
    ) = await asyncio.gather(
        _fetch_forms_traffic(notion, db_forms, model_page_id),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, month_offset=0),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, month_offset=-1),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, month_offset=-2),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, month_offset=-3),
        _fetch_shoots_lines(notion, db_planner, model_page_id),
        _fetch_orders_by_type(notion, db_orders, model_page_id, cur_yyyy_mm),
        _fetch_orders_by_type(notion, db_orders, model_page_id, h_months[0]),
        _fetch_orders_by_type(notion, db_orders, model_page_id, h_months[1]),
        _fetch_orders_by_type(notion, db_orders, model_page_id, h_months[2]),
    )

    needs_rent = _normalize(model_row.get("needs_rent"))
    rent = needs_rent in {"true", "yes", "1", "нужна"}
    traffic_list = [
        t.strip() for t in (traffic or "").split(",")
        if t.strip() and t.strip() != "—"
    ]

    return {
        "model_name": model_name,
        "status": model_row.get("status") or "",
        "project": model_row.get("project") or "",
        "scout": model_row.get("scout") or "",
        "assist": model_row.get("assist") or "",
        "language": model_row.get("language") or "",
        "anal": model_row.get("anal") or "",
        "calls": model_row.get("calls") or "",
        "rent": rent,
        "traffic": traffic_list,
        "content_current": accounting_row or {},
        "content_history": [
            {"month": h_months[0], "data": accounting_h1 or {}},
            {"month": h_months[1], "data": accounting_h2 or {}},
            {"month": h_months[2], "data": accounting_h3 or {}},
        ],
        "orders_current": orders_current,
        "orders_history": [
            {"month": h_months[0], "data": orders_h1},
            {"month": h_months[1], "data": orders_h2},
            {"month": h_months[2], "data": orders_h3},
        ],
        "current_month": cur_yyyy_mm,
        "shoots": [
            {"date": date_str, "types": content_types, "status": shoot_status}
            for date_str, content_types, shoot_status in shoots
        ],
    }


