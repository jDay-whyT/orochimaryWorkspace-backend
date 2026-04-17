"""Scout report card helpers based on Google Sheets models tab."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import date, datetime, timedelta
from typing import Any

from app.services.analytics import ANALYTICS_SPREADSHEET_ID_DEFAULT

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


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_date_human(value: Any) -> str:
    if not value:
        return "—"
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return f"{dt.day} {_MONTHS_RU[dt.month]}"
        except ValueError:
            continue
    return "—"


def _split_values(raw: Any) -> list[str]:
    if raw is None:
        return []
    return [chunk.strip() for chunk in str(raw).split(",") if chunk.strip()]


def _format_boost(anal: Any, calls: Any) -> str:
    items: list[str] = []
    for value in [*_split_values(anal), *_split_values(calls)]:
        if value in {"No", "—"}:
            continue
        items.append(value)
    return " | ".join(items) if items else "—"


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _format_monthly_files(accounting_row: dict[str, Any] | None) -> str:
    if not accounting_row:
        return "📦 Файлы месяца: —"
    categories = [
        ("OF", accounting_row.get("of_files")),
        ("Reddit", accounting_row.get("reddit_files")),
        ("Twitter", accounting_row.get("twitter_files")),
        ("Fansly", accounting_row.get("fansly_files")),
    ]
    lines: list[str] = []
    for label, raw in categories:
        value = int(_to_float(raw) or 0)
        if value > 0:
            lines.append(f"   • {label}: {value}")
    if not lines:
        return "📦 Файлы месяца: —"
    return "📦 Файлы месяца:\n" + "\n".join(lines)


def _format_scout_card(
    model_name: str,
    model_row: dict[str, Any],
    forms_row: dict[str, Any] | None,
    accounting_row: dict[str, Any] | None,
    orders_done: int,
    orders_open: int,
) -> str:
    status = model_row.get("status") or "—"
    project = model_row.get("project") or "—"
    scout = model_row.get("scout") or "—"
    assist = model_row.get("assist") or "—"
    language = model_row.get("language") or "—"
    boost = _format_boost(model_row.get("anal"), model_row.get("calls"))
    optional = forms_row.get("optional") if forms_row else ""
    traffic = optional or "—"
    rent_bool = _to_bool(model_row.get("needs_rent"))
    rent = "нужна" if rent_bool else "не нужна"
    last_shoot = _parse_date_human(model_row.get("last_shoot_date"))
    files_block = _format_monthly_files(accounting_row)
    orders_block = (
        "📈 Ордера: —"
        if (orders_done + orders_open) == 0
        else (
            "📈 Ордера (30д · custom/call):\n"
            f"   • Done: {orders_done} | Open: {orders_open}"
        )
    )

    return (
        f"📊 {model_name.upper()}\n"
        f"├ Статус: {status} · {project}\n"
        f"├ Скаут: {scout}\n"
        f"├ Ассист: {assist}\n"
        f"│\n"
        f"🌐 Язык: {language}\n"
        f"💥 Буст: {boost}\n"
        f"🔗 Трафик: {traffic}\n"
        f"🏠 Аренда: {rent}\n"
        f"│\n"
        f"{files_block}\n"
        f"📅 Последняя съёмка: {last_shoot}\n"
        f"│\n"
        f"{orders_block}"
    )


def _parse_order_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _load_scout_card_data_sync(
    model_name: str,
    service_account_json: str,
    spreadsheet_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, int, int]:
    import gspread
    from google.oauth2.service_account import Credentials

    if not service_account_json or not spreadsheet_id:
        return None, None, None, 0, 0

    try:
        sa_info = json.loads(service_account_json)
    except (json.JSONDecodeError, ValueError):
        sa_info = json.loads(base64.b64decode(service_account_json + "==").decode("utf-8"))
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(spreadsheet_id)
    models_records = spreadsheet.worksheet("models").get_all_records(expected_headers=None)
    forms_records = spreadsheet.worksheet("forms").get_all_records(expected_headers=None)
    accounting_records = spreadsheet.worksheet("accounting").get_all_records(expected_headers=None)
    orders_records = spreadsheet.worksheet("orders").get_all_records(expected_headers=None)

    target = model_name.strip().lower()
    model_row = next(
        (row for row in models_records if _normalize(row.get("model")) == target),
        None,
    )
    forms_row = next(
        (row for row in forms_records if _normalize(row.get("model_name")) == target),
        None,
    )

    current_month = date.today().strftime("%Y-%m")
    accounting_row = next(
        (
            row for row in accounting_records
            if _normalize(row.get("model")) == target
            and str(row.get("edited_at", "")).strip().startswith(current_month)
        ),
        None,
    )

    done_count = 0
    open_count = 0
    cutoff = date.today() - timedelta(days=30)
    for row in orders_records:
        if _normalize(row.get("model")) != target:
            continue
        if _normalize(row.get("type")) not in {"custom", "call"}:
            continue
        in_date = _parse_order_date(row.get("date_in"))
        if not in_date or in_date < cutoff:
            continue
        status = _normalize(row.get("status"))
        if status == "done":
            done_count += 1
        elif status == "open":
            open_count += 1

    return model_row, forms_row, accounting_row, done_count, open_count


async def build_scout_report_card(model_name: str) -> str | None:
    """Build scout card from Google Sheets models row, no caching."""
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    spreadsheet_id = os.getenv(
        "ANALYTICS_SPREADSHEET_ID",
        ANALYTICS_SPREADSHEET_ID_DEFAULT,
    ).strip()
    model_row, forms_row, accounting_row, orders_done, orders_open = await asyncio.to_thread(
        _load_scout_card_data_sync,
        model_name,
        service_account_json,
        spreadsheet_id,
    )
    if not model_row:
        return None
    return _format_scout_card(
        model_name,
        model_row,
        forms_row,
        accounting_row,
        orders_done,
        orders_open,
    )
