"""Scout report card helpers based on Notion data."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta
from typing import Any

from app.services.analytics import DB_FORMS_DEFAULT
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
    items: list[str] = []
    for raw in (anal, calls):
        for chunk in str(raw or "").split(","):
            val = chunk.strip()
            if not val or val in {"No", "—"}:
                continue
            items.append(val)
    return " | ".join(items) if items else "—"


def _format_monthly_files(accounting_row: dict[str, int] | None) -> str:
    if not accounting_row:
        return "📦 Файлы месяца: —"
    categories = [
        ("OF", accounting_row.get("of_files", 0)),
        ("Reddit", accounting_row.get("reddit_files", 0)),
        ("Twitter", accounting_row.get("twitter_files", 0)),
        ("Fansly", accounting_row.get("fansly_files", 0)),
    ]
    lines = [f"   • {label}: {value}" for label, value in categories if value > 0]
    if not lines:
        return "📦 Файлы месяца: —"
    return "📦 Файлы месяца:\n" + "\n".join(lines)


def _format_shoot_line(prefix: str, dt: str | None, content: list[str] | None) -> str:
    day = _format_ru_day(dt)
    if day == "—":
        return f"{prefix}: —"
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
    status = model_row.get("status") or "—"
    project = model_row.get("project") or "—"
    scout = model_row.get("scout") or "—"
    assist = model_row.get("assist") or "—"
    language = model_row.get("language") or "—"
    boost = _format_boost(model_row.get("anal"), model_row.get("calls"))
    needs_rent = _normalize(model_row.get("needs_rent"))
    rent = "нужна" if needs_rent in {"true", "yes", "1", "нужна"} else "не нужна"
    files_block = _format_monthly_files(accounting_row)
    orders_block = (
        "📈 Ордера: —"
        if (orders_done + orders_open) == 0
        else f"📈 Ордера:\n   • Done: {orders_done} | Open: {orders_open}"
    )

    parts = [
        f"📊 {model_name.upper()}",
        f"├ Статус: {status} · {project}",
        f"├ Скаут: {scout}",
        f"├ Ассист: {assist}",
        "│",
        f"🌐 Язык: {language}",
        f"💥 Буст: {boost}",
        f"🔗 Трафик: {traffic}",
        f"🏠 Аренда: {rent}",
        "│",
        files_block,
        last_shoot_line,
    ]
    if next_shoot_line:
        parts.append(next_shoot_line)
    parts.extend(["│", orders_block])
    return "\n".join(parts)


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
    yyyy_mm: str,
) -> dict[str, int] | None:
    items = await _query_all_pages(
        notion,
        db_accounting,
        {
            "page_size": 50,
            "filter": {
                "and": [
                    {"property": "model", "relation": {"contains": model_page_id}},
                    {"property": "Title", "title": {"contains": yyyy_mm}},
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
    }


async def _fetch_orders_stats(notion: NotionClient, db_orders: str, model_page_id: str) -> tuple[int, int]:
    cutoff = date.today() - timedelta(days=30)
    items = await _query_all_pages(
        notion,
        db_orders,
        {
            "page_size": 100,
            "filter": {
                "and": [
                    {"property": "model", "relation": {"contains": model_page_id}},
                    {"property": "in", "date": {"on_or_after": cutoff.isoformat()}},
                ]
            },
        },
    )

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

    last_line = _format_shoot_line("📅 Последняя съёмка", last_done[1] if last_done else None, last_done[2] if last_done else None)
    next_line = None
    if next_planned:
        next_line = _format_shoot_line("📅 Следующая съёмка", next_planned[1], next_planned[2])

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
    yyyy_mm = date.today().strftime("%Y-%m")

    traffic, accounting_row, orders_stats, shoots_lines = await asyncio.gather(
        _fetch_forms_traffic(notion, db_forms, model_page_id),
        _fetch_monthly_accounting(notion, db_accounting, model_page_id, yyyy_mm),
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
