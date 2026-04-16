"""Scout report card helpers based on Google Sheets models tab."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
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


def _format_winrate(done: Any, opened: Any) -> str:
    done_f = _to_float(done) or 0.0
    open_f = _to_float(opened) or 0.0
    denom = done_f + open_f
    if denom <= 0:
        return "—"
    return f"{(done_f / denom) * 100:.1f}%"


def _format_scout_card(model_name: str, row: dict[str, Any]) -> str:
    status = row.get("status") or "—"
    project = row.get("project") or "—"
    scout = row.get("scout") or "—"
    assist = row.get("assist") or "—"
    language = row.get("language") or "—"
    boost = _format_boost(row.get("anal"), row.get("calls"))
    traffic = row.get("acc_content") or "—"
    rent_bool = _to_bool(row.get("needs_rent"))
    rent = "нужна" if rent_bool else "не нужна"
    files_total = int(_to_float(row.get("total_files")) or 0)
    files_target = int(_to_float(row.get("files_target")) or 0)
    files_pct = _to_float(row.get("files_pct"))
    files_pct_text = f"{files_pct:.0f}%" if files_pct is not None else "—"
    last_shoot = _parse_date_human(row.get("last_shoot_date"))
    orders_total = int(_to_float(row.get("orders_total")) or 0)
    orders_done = int(_to_float(row.get("orders_done")) or 0)
    orders_open = int(_to_float(row.get("orders_open")) or 0)
    winrate = _format_winrate(orders_done, orders_open)

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
        f"📦 Файлы месяца: {files_total} / {files_target} ({files_pct_text})\n"
        f"📅 Последняя съёмка: {last_shoot}\n"
        f"│\n"
        f"📈 Ордера:\n"
        f"   • Всего: {orders_total} | Done: {orders_done} | Open: {orders_open}\n"
        f"   • Winrate: {winrate}"
    )


def _load_model_from_sheet_sync(
    model_name: str,
    service_account_json: str,
    spreadsheet_id: str,
) -> dict[str, Any] | None:
    import gspread
    from google.oauth2.service_account import Credentials

    if not service_account_json or not spreadsheet_id:
        return None

    sa_info = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(spreadsheet_id).worksheet("models")
    records = sheet.get_all_records(expected_headers=None)
    target = model_name.strip().lower()
    for row in records:
        row_name = str(row.get("model", "")).strip().lower()
        if row_name == target:
            return row
    return None


async def build_scout_report_card(model_name: str) -> str | None:
    """Build scout card from Google Sheets models row, no caching."""
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    spreadsheet_id = os.getenv(
        "ANALYTICS_SPREADSHEET_ID",
        ANALYTICS_SPREADSHEET_ID_DEFAULT,
    ).strip()
    pythonrow = await asyncio.to_thread(
        _load_model_from_sheet_sync,
        model_name,
        service_account_json,
        spreadsheet_id,
    )
    if not pythonrow:
        return None
    return _format_scout_card(model_name, pythonrow)
