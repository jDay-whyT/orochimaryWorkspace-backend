"""Scout report card helpers based on Notion data."""

from __future__ import annotations

import asyncio
import calendar as _calendar
import html
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

LOGGER = logging.getLogger(__name__)

from app.utils.constants import ARCHIVE_ORDERS_DBS, DB_FORMS_DEFAULT
from app.utils.formatting import MONTHS_RU_LOWER
from app.services.notion import NotionClient

_DB_MODELS_DEFAULT = "1fc32bee-e7a0-809f-8bbe-000be8182d4d"
_DB_ORDERS_DEFAULT = "20b32bee-e7a0-81ab-b72b-000b78a1e78a"
_DB_PLANNER_DEFAULT = "1fb32bee-e7a0-815f-ae1d-000ba6995a1a"
_DB_ACCOUNTING_DEFAULT = "1ff32bee-e7a0-8025-a26c-000bc7008ec8"

_MONTHS_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}

_MONTHS_EN = {
    1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
    7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec",
}

_ORDER_TYPE_SHORT = {
    "custom": "custom",
    "short": "short",
    "verif reddit": "verif",
    "call": "call",
    "ad request": "ad req",
}


def _parse_iso_date(raw: str | None) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    value = value[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _format_ru_day(raw: str | None) -> str:
    dt = _parse_iso_date(raw)
    if not dt:
        return "—"
    return f"{dt.day} {_MONTHS_RU[dt.month]}"


def _format_en_day(raw: str | None) -> str:
    dt = _parse_iso_date(raw)
    if not dt:
        return "—"
    return f"{dt.day} {_MONTHS_EN[dt.month]}"


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


def _format_boost(anal: str | None, calls: str | None) -> str:
    def _format_label(raw: str | None) -> str:
        values: list[str] = []
        for chunk in str(raw or "").split(","):
            val = chunk.strip()
            if not val or val in {"No", "—"}:
                continue
            values.append(val)
        return ", ".join(values) if values else "No"

    anal_text = _format_label(anal)
    calls_text = _format_label(calls)
    return f"Анал: {anal_text} | Колл: {calls_text}"


def _format_content_month(label: str, accounting_row: dict[str, int] | None) -> str | None:
    """Returns 'may: OF: <b>3</b> · Reddit: <b>1</b>' or None if all zeros."""
    if not accounting_row:
        return None
    categories = [
        ("of_files", "OF"),
        ("reddit_files", "Reddit"),
        ("twitter_files", "Twitter"),
        ("fansly_files", "Fansly"),
        ("social_files", "Social"),
        ("request_files", "Request"),
    ]
    parts: list[str] = []
    for key, name in categories:
        val = accounting_row.get(key, 0)
        if val > 0:
            parts.append(f"{name}: <b>{val}</b>")
    if not parts:
        return None
    return f"{label}: " + " · ".join(parts)


def _format_orders_month(label: str, orders: dict[str, int]) -> str | None:
    """Returns 'may: custom: <b>2</b> · short: <b>1</b>' or None if all zeros."""
    parts: list[str] = []
    for order_type, count in orders.items():
        if count > 0:
            display = _ORDER_TYPE_SHORT.get(order_type, order_type)
            parts.append(f"{display}: <b>{count}</b>")
    if not parts:
        return None
    return f"{label}: " + " · ".join(parts)


def _format_scout_card(
    model_name: str,
    model_row: dict[str, Any],
    traffic: str,
    accounting_row: dict[str, int] | None,
    accounting_prev_row: dict[str, int] | None,
    shoots: list[tuple[str, list[str], str]],
    orders_current: dict[str, int],
    orders_prev: dict[str, int],
) -> str:
    today = date.today()
    cur_label = _MONTHS_EN[today.month]
    prev_month_date = today.replace(day=1) - timedelta(days=1)
    prev_label = _MONTHS_EN[prev_month_date.month]

    status = str(model_row.get("status") or "—").strip()
    project = str(model_row.get("project") or "").strip()
    scout = str(model_row.get("scout") or "").strip()
    assist = str(model_row.get("assist") or "").strip()
    language = str(model_row.get("language") or "").strip()
    boost = _format_boost(model_row.get("anal"), model_row.get("calls"))
    needs_rent = _normalize(model_row.get("needs_rent"))
    rent = "yes" if needs_rent in {"true", "yes", "1", "нужна"} else "no"
    traffic_text = str(traffic or "").strip() or "—"

    safe = html.escape

    header = f"<b>{safe(model_name.upper())}</b> · {safe(status)}"
    if project:
        header += f" · <b>{safe(project)}</b>"

    lines = [header]

    if scout or assist:
        lines.append(f"  └ {safe(scout or '—')} → {safe(assist or '—')}")

    lines.append("")

    # Info block — italic, no pipe prefix
    if language:
        lines.append(f"  <i>{safe(language)}</i>")

    boost_en = boost.replace("Анал:", "anal:").replace("Колл:", "calls:")
    if boost_en:
        lines.append(f"  <i>{safe(boost_en)}</i>")

    traffic_parts = [f"<b>{safe(t.strip())}</b>" for t in traffic_text.split(",") if t.strip()]
    traffic_bold = ", ".join(traffic_parts) if traffic_parts else "—"
    lines.append(f"  <i>traffic: {traffic_bold}</i>")
    lines.append(f"  <i>rent: {rent}</i>")

    lines.append("")

    # Content section — two months
    cur_content = _format_content_month(cur_label, accounting_row)
    prev_content = _format_content_month(prev_label, accounting_prev_row)
    if cur_content or prev_content:
        lines.append("Content")
        if cur_content:
            lines.append(cur_content)
        if prev_content:
            lines.append(prev_content)
    else:
        lines.append("Content: —")

    lines.append("")

    # Shoots section — date range
    if shoots:
        lines.append("Shoots")
        for date_str, content_types, shoot_status in shoots:
            day = _format_en_day(date_str)
            content_text = ", ".join(content_types) if content_types else "—"
            lines.append(f"<b>{safe(day)}</b> · {safe(content_text)} · {safe(shoot_status)}")
    else:
        lines.append("Shoots: —")

    lines.append("")

    # Orders section — two months
    cur_orders = _format_orders_month(cur_label, orders_current)
    prev_orders = _format_orders_month(prev_label, orders_prev)
    if cur_orders or prev_orders:
        lines.append("Orders")
        if cur_orders:
            lines.append(cur_orders)
        if prev_orders:
            lines.append(prev_orders)
    else:
        lines.append("Orders: no orders")

    return "\n".join(lines)


async def _query_all_pages(
    notion: NotionClient,
    database_id: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        query_payload = dict(payload)
        if cursor:
            query_payload["start_cursor"] = cursor
        data = await notion._request("POST", url, json=query_payload)
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

    page = await notion._request("GET", f"https://api.notion.com/v1/pages/{model.page_id}")
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

    if LOGGER.isEnabledFor(logging.DEBUG):
        all_records = await _query_all_pages(
            notion,
            db_accounting,
            {
                "page_size": 100,
                "filter": {"property": "model", "relation": {"contains": model_page_id}},
                "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            },
        )
        titles = [
            _extract_title(r.get("properties", {}).get("Title"))
            for r in all_records
        ]
        LOGGER.debug(
            "scout accounting all titles for model=%s: %s",
            model_page_id, titles,
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

    if not items:
        return None
    props = items[0].get("properties", {})
    return {
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
                {"property": "in", "date": {"on_or_after": first_day}},
                {"property": "in", "date": {"on_or_before": last_day}},
            ]
        },
    }

    items = await _query_all_pages(notion, db_orders, query_payload)

    result: dict[str, int] = {}
    for item in items:
        props = item.get("properties", {})
        order_type = _normalize(_extract_select_name(props.get("type")))
        if order_type:
            result[order_type] = result.get(order_type, 0) + 1

    return result


async def build_scout_report_card(model_name: str, notion: NotionClient) -> str | None:
    """Build scout card from Notion databases."""
    db_models = os.getenv("DB_MODELS", _DB_MODELS_DEFAULT).strip()
    db_forms = os.getenv("DB_FORMS", DB_FORMS_DEFAULT).strip()
    db_accounting = os.getenv("DB_ACCOUNTING", _DB_ACCOUNTING_DEFAULT).strip()
    db_orders = os.getenv("DB_ORDERS", _DB_ORDERS_DEFAULT).strip()
    db_planner = os.getenv("DB_PLANNER", _DB_PLANNER_DEFAULT).strip()

    model_row = await _fetch_model_row(notion, db_models, model_name)
    if not model_row:
        return None

    model_page_id = model_row["page_id"]

    today = date.today()
    cur_yyyy_mm = today.strftime("%Y-%m")
    prev_month_date = today.replace(day=1) - timedelta(days=1)
    prev_yyyy_mm = prev_month_date.strftime("%Y-%m")

    (
        traffic,
        accounting_row,
        accounting_prev_row,
        shoots,
        orders_current,
        orders_prev,
    ) = await asyncio.gather(
        _fetch_forms_traffic(notion, db_forms, model_page_id),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, month_offset=0),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, month_offset=-1),
        _fetch_shoots_lines(notion, db_planner, model_page_id),
        _fetch_orders_by_type(notion, db_orders, model_page_id, cur_yyyy_mm),
        _fetch_orders_by_type(notion, db_orders, model_page_id, prev_yyyy_mm),
    )

    return _format_scout_card(
        model_name=model_name,
        model_row=model_row,
        traffic=traffic,
        accounting_row=accounting_row,
        accounting_prev_row=accounting_prev_row,
        shoots=shoots,
        orders_current=orders_current,
        orders_prev=orders_prev,
    )
