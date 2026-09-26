"""Scout report card helpers based on Notion data."""

from __future__ import annotations

import asyncio
import calendar as _calendar
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Config

LOGGER = logging.getLogger(__name__)

from app.utils.constants import DB_FORMS_DEFAULT
from app.utils.formatting import MONTHS_RU_LOWER
from app.services.notion import NotionClient


def _today() -> date:
    """Today in the bot's timezone (Cloud Run runs in UTC)."""
    return datetime.now(ZoneInfo(os.getenv("TIMEZONE", "Europe/Brussels") or "Europe/Brussels")).date()

_DB_MODELS_DEFAULT = "1fc32bee-e7a0-809f-8bbe-000be8182d4d"
_DB_ORDERS_DEFAULT = "20b32bee-e7a0-81ab-b72b-000b78a1e78a"
_DB_PLANNER_DEFAULT = "1fb32bee-e7a0-815f-ae1d-000ba6995a1a"
_DB_ACCOUNTING_DEFAULT = "1ff32bee-e7a0-8025-a26c-000bc7008ec8"

_MONTHS_EN = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

# Card window: current month + this many previous months.
_HISTORY_MONTHS = 3
# How far ahead planned shoots are shown.
_SHOOTS_AHEAD_DAYS = 60


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
    if num is None and prop.get("type") == "formula":
        # Formula columns (e.g. Total) nest the value: {"formula": {"type": "number", "number": X}}
        num = (prop.get("formula") or {}).get("number")
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
    # Query results already carry full properties — no extra get_page round-trip.
    data = await notion.query_database(
        db_models,
        {"page_size": 25, "filter": {"property": "model", "title": {"contains": model_name}}},
    )
    target = _normalize(model_name)
    page = next(
        (
            item for item in data.get("results", [])
            if _normalize(_extract_title(item.get("properties", {}).get("model"))) == target
        ),
        None,
    )
    if not page:
        return None

    props = page.get("properties", {})
    return {
        "page_id": page["id"],
        "status": _extract_select_name(props.get("status")),
        "project": _extract_select_name(props.get("project")),
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


def _accounting_label(yyyy_mm: str) -> str:
    """Accounting rows are titled like "апрель 2026"."""
    year, month = yyyy_mm.split("-")
    return f"{MONTHS_RU_LOWER[int(month) - 1]} {year}"


def _accounting_row(props: dict[str, Any]) -> dict[str, int]:
    # Every "<platform>_files" number column is picked up, so new columns
    # added in Notion (tango_files, ...) show up without a code change.
    row = {"total": _extract_number(props.get("Total"))}
    for name, prop in props.items():
        if name.endswith("_files") and (prop or {}).get("type") in {"number", "formula", None}:
            row[name] = _extract_number(prop)
    return row


def _accounting_payload(model_page_id: str, labels: list[str]) -> dict[str, Any]:
    title_filters = [{"property": "Title", "title": {"contains": label}} for label in labels]
    return {
        "page_size": 100,
        "filter": {
            "and": [
                {"property": "model", "relation": {"contains": model_page_id}},
                title_filters[0] if len(title_filters) == 1 else {"or": title_filters},
            ]
        },
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
    }


def _bucket_accounting(items: list[dict[str, Any]], months: list[str]) -> dict[str, dict[str, int]]:
    # Title match, not last_edited_time: rows get edited after their month ends.
    result: dict[str, dict[str, int]] = {}
    for item in items:  # newest edit first -> first hit per month wins
        props = item.get("properties", {})
        title = _normalize(_extract_title(props.get("Title")))
        for month in months:
            if month not in result and _accounting_label(month) in title:
                result[month] = _accounting_row(props)
                break
    return result


async def _fetch_accounting_months(
    notion: NotionClient,
    db_accounting: str,
    model_page_id: str,
    months: list[str],
) -> dict[str, dict[str, int]]:
    """Accounting rows for several YYYY-MM months in one query; past months fall back to ARCHIVE."""
    items = await _query_all_pages(
        notion,
        db_accounting,
        _accounting_payload(model_page_id, [_accounting_label(m) for m in months]),
    )
    result = _bucket_accounting(items, months)

    today = _today()
    cur_yyyy_mm = f"{today.year:04d}-{today.month:02d}"
    archive_page_id = os.getenv("ARCHIVE_PAGE_ID", "").strip()
    missing_past = [m for m in months if m not in result and m < cur_yyyy_mm]
    if archive_page_id and missing_past:

        async def _from_archive(month: str) -> None:
            archive_db_id = await notion.find_archive_accounting_db(
                archive_page_id, _MONTHS_EN[int(month[5:7]) - 1]
            )
            if not archive_db_id:
                return
            archived = await _query_all_pages(
                notion, archive_db_id, _accounting_payload(model_page_id, [_accounting_label(month)])
            )
            result.update(_bucket_accounting(archived, [month]))

        await asyncio.gather(*[_from_archive(m) for m in missing_past])

    LOGGER.debug("scout accounting: model=%s months=%s found=%s", model_page_id, months, list(result))
    return result


async def _fetch_shoots(
    notion: NotionClient,
    db_planner: str,
    model_page_id: str,
) -> list[dict[str, Any]]:
    """Shoots from the start of the month _HISTORY_MONTHS ago up to _SHOOTS_AHEAD_DAYS ahead."""
    today = _today()
    start = today.replace(day=1)
    for _ in range(_HISTORY_MONTHS):
        start = (start - timedelta(days=1)).replace(day=1)
    date_from = start.isoformat()
    date_to = (today + timedelta(days=_SHOOTS_AHEAD_DAYS)).isoformat()

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

    result: list[dict[str, Any]] = []
    for item in items:
        props = item.get("properties", {})
        shoot_date_raw = _extract_date(props.get("date"))
        if not _parse_iso_date(shoot_date_raw):
            continue
        result.append({
            "id": item.get("id") or "",
            "date": shoot_date_raw[:10],
            # Planner dates may carry a time: "2026-09-24T14:00:00.000+03:00".
            "time": shoot_date_raw[11:16] if len(shoot_date_raw) > 10 else "",
            "location": _extract_select_name(props.get("location")) or "",
            "types": _extract_multi_select(props.get("content")),
            "status": _normalize(_extract_select_name(props.get("status"))),
        })

    return result


def _month_bounds(yyyy_mm: str) -> tuple[str, str]:
    year, month = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    last = _calendar.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last).isoformat()


def _orders_payload(
    model_page_id: str,
    first_day: str,
    last_day: str,
    include_open: bool = False,
) -> dict[str, Any]:
    by_model = {"property": "model", "relation": {"contains": model_page_id}}
    closed_in_range = {
        "and": [
            by_model,
            {"property": "out", "date": {"on_or_after": first_day}},
            {"property": "out", "date": {"on_or_before": last_day}},
        ]
    }
    if not include_open:
        return {"page_size": 100, "filter": closed_in_range}
    # "out" is the close date — open orders have it empty.
    still_open = {"and": [by_model, {"property": "out", "date": {"is_empty": True}}]}
    return {"page_size": 100, "filter": {"or": [closed_in_range, still_open]}}


def _order_item(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("properties", {})
    count = props.get("count")
    received = props.get("received")
    return {
        "id": item.get("id") or "",
        "title": _extract_title(props.get("Title")) or "",
        "type": _normalize(_extract_select_name(props.get("type"))),
        "status": _normalize(_extract_select_name(props.get("status"))),
        "in": (_extract_date(props.get("in")) or "")[:10],
        "out": (_extract_date(props.get("out")) or "")[:10],
        "count": _extract_number(count) if count and count.get("number") is not None else None,
        "received": _extract_number(received) if received and received.get("number") is not None else None,
    }


async def _fetch_orders_months(
    notion: NotionClient,
    db_orders: str,
    model_page_id: str,
    months: list[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    """
    Orders for each YYYY-MM month plus currently open orders.

    Main DB: one query over the whole range (+ open orders, which have no
    "out" date yet). Past months also live in ARCHIVE -> orders column ->
    "<month> robin" (one DB per month).

    Returns (by_month, open_items, months_whose_archive_failed), where
    by_month[m] = {"counts": {type: n}, "items": [...]}. Canceled orders are
    listed but not counted. A main DB failure raises so the card marks all
    order sections as failed.
    """
    first_day = _month_bounds(min(months))[0]
    last_day = _month_bounds(max(months))[1]

    today = _today()
    cur_yyyy_mm = f"{today.year:04d}-{today.month:02d}"
    archive_page_id = os.getenv("ARCHIVE_PAGE_ID", "").strip()
    past = [m for m in months if m < cur_yyyy_mm] if archive_page_id else []

    async def _archive(month: str) -> list[dict[str, Any]]:
        archive_db_id = await notion.find_archive_orders_db(archive_page_id, _MONTHS_EN[int(month[5:7]) - 1])
        if not archive_db_id:
            LOGGER.warning("scout orders: no archive db for %s", month)
            return []
        return await _query_all_pages(
            notion, archive_db_id, _orders_payload(model_page_id, *_month_bounds(month))
        )

    main_items, *archive_results = await asyncio.gather(
        _query_all_pages(
            notion, db_orders, _orders_payload(model_page_id, first_day, last_day, include_open=True)
        ),
        *[_archive(m) for m in past],
        return_exceptions=True,
    )
    if isinstance(main_items, BaseException):
        raise main_items

    failed: list[str] = []
    all_items = list(main_items)
    for month, archived in zip(past, archive_results):
        if isinstance(archived, BaseException):
            LOGGER.warning("scout orders: archive query failed for %s: %s", month, archived)
            failed.append(month)
            continue
        all_items.extend(archived)

    by_month: dict[str, dict[str, Any]] = {m: {"counts": {}, "items": []} for m in months}
    open_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in all_items:
        item_id = item.get("id")
        if item_id:
            if item_id in seen:
                continue
            seen.add(item_id)
        order = _order_item(item)
        if not order["out"]:
            if order["status"] == "open":
                open_items.append(order)
                continue
            # Closed/canceled without a close date: file it under the month it came in.
            month = order["in"][:7]
        else:
            month = order["out"][:7]
        bucket = by_month.get(month)
        if bucket is None:
            continue
        bucket["items"].append(order)
        if order["type"] and order["status"] != "canceled":
            bucket["counts"][order["type"]] = bucket["counts"].get(order["type"], 0) + 1

    for bucket in by_month.values():
        bucket["items"].sort(key=lambda o: o["out"] or o["in"], reverse=True)
    open_items.sort(key=lambda o: o["in"] or "9999")  # oldest first — most overdue on top

    return by_month, open_items, failed


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

    today = _today()
    cur_yyyy_mm = today.strftime("%Y-%m")

    def _month_ago(n: int) -> str:
        t = today
        for _ in range(n):
            t = t.replace(day=1) - timedelta(days=1)
        return t.strftime("%Y-%m")

    h_months = [_month_ago(n) for n in range(1, _HISTORY_MONTHS + 1)]
    failed: list[str] = []

    all_months = [cur_yyyy_mm, *h_months]

    async def _safe(sections: list[str], coro, default):
        try:
            return await coro
        except Exception:
            LOGGER.warning("scout card %s: %s failed", model_name, sections[0], exc_info=True)
            failed.extend(sec for sec in sections if sec not in failed)
            return default

    traffic, accounting, shoots, (orders, orders_open, orders_failed) = await asyncio.gather(
        _safe(["traffic"], _fetch_forms_traffic(notion, db_forms, model_page_id), "—"),
        _safe(
            ["content", *[f"content:{m}" for m in h_months]],
            _fetch_accounting_months(notion, db_accounting, model_page_id, all_months),
            {},
        ),
        _safe(["shoots"], _fetch_shoots(notion, db_planner, model_page_id), []),
        _safe(
            ["orders", *[f"orders:{m}" for m in h_months]],
            _fetch_orders_months(notion, db_orders, model_page_id, all_months),
            ({}, [], []),
        ),
    )
    failed.extend(f"orders:{m}" for m in orders_failed)

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
        "content_current": accounting.get(cur_yyyy_mm, {}),
        "content_history": [{"month": m, "data": accounting.get(m, {})} for m in h_months],
        "orders_open": orders_open,
        "orders_current": orders.get(cur_yyyy_mm, {}).get("counts", {}),
        "orders_current_items": orders.get(cur_yyyy_mm, {}).get("items", []),
        "orders_history": [
            {
                "month": m,
                "data": orders.get(m, {}).get("counts", {}),
                "items": orders.get(m, {}).get("items", []),
            }
            for m in h_months
        ],
        "current_month": cur_yyyy_mm,
        "history_months": h_months,
        "today": today.isoformat(),
        "shoots": shoots,
        "failed": failed,
    }
