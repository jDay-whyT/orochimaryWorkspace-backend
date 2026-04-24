"""Scout report card helpers based on Notion data."""

from __future__ import annotations

import asyncio
import html
import os
from datetime import date, datetime, timedelta
from typing import Any

from app.utils.constants import ARCHIVE_ORDERS_DBS, DB_FORMS_DEFAULT
from app.services.notion import NotionClient

_DB_MODELS_DEFAULT = "1fc32bee-e7a0-809f-8bbe-000be8182d4d"
_DB_ORDERS_DEFAULT = "20b32bee-e7a0-81ab-b72b-000b78a1e78a"
_DB_PLANNER_DEFAULT = "1fb32bee-e7a0-815f-ae1d-000ba6995a1a"
_DB_ACCOUNTING_DEFAULT = "1ff32bee-e7a0-8025-a26c-000bc7008ec8"

_MONTHS_RU = {
    1: "янв",
    2: "фев",
    3: "мар",
    4: "апр",
    5: "май",
    6: "июн",
    7: "июл",
    8: "авг",
    9: "сен",
    10: "окт",
    11: "ноя",
    12: "дек",
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


def _format_monthly_files(accounting_row: dict[str, int] | None) -> str:
    if not accounting_row:
        return "📁 Контент за мес: —"
    categories = [
        ("of_files", "OF"),
        ("reddit_files", "Reddit"),
        ("twitter_files", "Twitter"),
        ("fansly_files", "Fansly"),
        ("social_files", "Social"),
        ("request_files", "Request"),
    ]
    parts: list[str] = []
    for key, label in categories:
        value = accounting_row.get(key, 0)
        if value > 0:
            parts.append(f"<b>{label} {value}</b>")
    if not parts:
        return "📁 Контент за мес: —"
    return "📁 Контент за мес: " + " · ".join(parts)


def _format_shoot_line(prefix: str, dt: str | None, content: list[str] | None, empty_text: str) -> str:
    day = _format_ru_day(dt)
    if day == "—":
        return f"{prefix}: {empty_text}"
    content_text = ", ".join(content or [])
    return f"{prefix}: {day}" + (f" · {content_text}" if content_text else "")


def _format_scout_card(
    model_name: str,
    model_row: dict[str, Any],
    traffic: str,
    accounting_row: dict[str, int] | None,
    orders_done: int,
    orders_open: int,
    last_shoot_line: str,
    next_shoot_line: str | None,
) -> str:
    import re as _re

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

    # Header — model bold, project bold
    header = f"<b>{safe(model_name.upper())}</b>  {safe(status)}"
    if project:
        header += f" · <b>{safe(project)}</b>"

    lines = [header]

    # Scout → Assist
    if scout or assist:
        lines.append(f"  └ {safe(scout or '—')} → {safe(assist or '—')}")

    lines.append("")

    # Info block
    if language:
        lines.append(f"  | {safe(language)}")

    # Boost: replace Ru labels with En
    boost_en = boost.replace("Анал:", "anal:").replace("Колл:", "calls:")
    if boost_en:
        lines.append(f"  | {safe(boost_en)}")

    lines.append(f"  | traffic: {safe(traffic_text)}  |  rent: {rent}")

    lines.append("")

    # Content block — bold numbers
    files_block = _format_monthly_files(accounting_row)
    files_text = files_block.replace("📁 Контент за мес: ", "").replace("📁 Контент за мес:", "").strip()
    files_text_escaped = safe(files_text)
    files_text_bold = _re.sub(r'\b(\d+)\b', r'<b>\1</b>', files_text_escaped)
    lines.append(f"  ▸ content: {files_text_bold}")

    # Shoots — bold dates
    def _strip_prefix(line: str) -> str:
        for prefix in ["🎬 Снятый: ", "📅 Ближ. съёмка: ", "снятый: ", "след. съёмка: "]:
            if line.startswith(prefix):
                return line[len(prefix):]
        return line

    last_data = _strip_prefix(last_shoot_line)
    # Bold the date part (first token before ' · ')
    if " · " in last_data:
        date_part, rest = last_data.split(" · ", 1)
        lines.append(f"  ▸ last shoot: <b>{safe(date_part)}</b> · {safe(rest)}")
    else:
        lines.append(f"  ▸ last shoot: {safe(last_data)}")

    if next_shoot_line:
        next_data = _strip_prefix(next_shoot_line)
        if next_data and next_data not in {"не запланировано", "не было"}:
            if " · " in next_data:
                date_part, rest = next_data.split(" · ", 1)
                lines.append(f"  ▸ next shoot: <b>{safe(date_part)}</b> · {safe(rest)}")
            else:
                lines.append(f"  ▸ next shoot: <b>{safe(next_data)}</b>")

    lines.append("")

    # Orders — bold label and numbers
    lines.append(f"  <b>orders</b>")
    lines.append(f"  | done: <b>{orders_done}</b>  |  open: <b>{orders_open}</b>")

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
) -> dict[str, int] | None:
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = (next_month - timedelta(days=1)).isoformat()

    items = await _query_all_pages(
        notion,
        db_accounting,
        {
            "page_size": 50,
            "filter": {
                "and": [
                    {"property": "model", "relation": {"contains": model_page_id}},
                    {
                        "property": "edit day",
                        "last_edited_time": {
                            "on_or_after": month_start,
                            "on_or_before": month_end,
                        },
                    },
                ]
            },
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        },
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


async def _fetch_orders_stats(notion: NotionClient, db_orders: str, model_page_id: str) -> tuple[int, int]:
    cutoff = date.today() - timedelta(days=30)
    query_payload = {
        "page_size": 100,
        "filter": {
            "and": [
                {"property": "model", "relation": {"contains": model_page_id}},
                {"property": "in", "date": {"on_or_after": cutoff.isoformat()}},
            ]
        },
    }

    items_by_db: list[list[dict[str, Any]]]
    if ARCHIVE_ORDERS_DBS:
        previous_month_index = date.today().month - 1
        previous_month_archive_db = ARCHIVE_ORDERS_DBS[-1 if previous_month_index >= 1 else 0]
        items_by_db = await asyncio.gather(
            _query_all_pages(notion, db_orders, query_payload),
            _query_all_pages(notion, previous_month_archive_db, query_payload),
        )
    else:
        items_by_db = [await _query_all_pages(notion, db_orders, query_payload)]

    items = [item for batch in items_by_db for item in batch]

    done = 0
    open_count = 0
    for item in items:
        props = item.get("properties", {})
        order_type = _normalize(_extract_select_name(props.get("type")))
        count = _extract_number(props.get("count"))

        include = False
        if order_type in {"custom", "call"}:
            include = True
        elif order_type == "short" and count >= 10:
            include = True

        if not include:
            continue

        status = _normalize(_extract_select_name(props.get("status")))
        if status == "done":
            done += 1
        elif status == "open":
            open_count += 1

    return done, open_count


async def _fetch_shoots_lines(
    notion: NotionClient,
    db_planner: str,
    model_page_id: str,
) -> tuple[str, str | None]:
    items = await _query_all_pages(
        notion,
        db_planner,
        {
            "page_size": 100,
            "filter": {"property": "model", "relation": {"contains": model_page_id}},
            "sorts": [{"property": "date", "direction": "ascending"}],
        },
    )

    today = date.today()
    last_done: tuple[date, str | None, list[str]] | None = None
    next_planned: tuple[date, str | None, list[str]] | None = None

    for item in items:
        props = item.get("properties", {})
        shoot_date_raw = _extract_date(props.get("date"))
        shoot_date = _parse_iso_date(shoot_date_raw)
        if not shoot_date:
            continue

        status = _normalize(_extract_select_name(props.get("status")))
        content = _extract_multi_select(props.get("content"))

        if status == "done":
            if last_done is None or shoot_date > last_done[0]:
                last_done = (shoot_date, shoot_date_raw, content)

        if status in {"scheduled", "planned"} and shoot_date >= today:
            if next_planned is None or shoot_date < next_planned[0]:
                next_planned = (shoot_date, shoot_date_raw, content)

    last_line = _format_shoot_line(
        "🎬 Снятый",
        last_done[1] if last_done else None,
        last_done[2] if last_done else None,
        "не было",
    )
    next_line = _format_shoot_line(
        "📅 Ближ. съёмка",
        next_planned[1] if next_planned else None,
        next_planned[2] if next_planned else None,
        "не запланировано",
    )

    return last_line, next_line


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
    traffic, accounting_row, orders_stats, shoots_lines = await asyncio.gather(
        _fetch_forms_traffic(notion, db_forms, model_page_id),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id),
        _fetch_orders_stats(notion, db_orders, model_page_id),
        _fetch_shoots_lines(notion, db_planner, model_page_id),
    )

    return _format_scout_card(
        model_name=model_name,
        model_row=model_row,
        traffic=traffic,
        accounting_row=accounting_row,
        orders_done=orders_stats[0],
        orders_open=orders_stats[1],
        last_shoot_line=shoots_lines[0],
        next_shoot_line=shoots_lines[1],
    )
