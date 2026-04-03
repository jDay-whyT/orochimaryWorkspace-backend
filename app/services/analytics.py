"""
app/services/analytics.py

Синхронизация Notion → Google Sheets + обратная запись winrate в Notion.
Запускается через /sync_analytics.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

LOGGER = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

DB_FORMS_DEFAULT = "22932beee7a0802492b2fd8b16ece74b"
ANALYTICS_SPREADSHEET_ID_DEFAULT = "1UjOVnivgJmZfmZGib2nkaorCSOR1LgLiFy2VXN4NAQo"

ANALYTICS_ASSISTANTS = os.getenv(
    "ANALYTICS_ASSISTANTS",
    "@cuterr12345,@gggqqq33"
).split(",")

FILES_TARGET_WORK = 200
FILES_TARGET_NEW  = 150

ACTIVE_STATUSES = {"work", "new", "inactive"}

# score → stars  (descending threshold order)
_STAR_MAP = [
    (86, "★★★★★"),
    (71, "★★★★☆"),
    (56, "★★★☆☆"),
    (41, "★★☆☆☆"),
    (21, "★☆☆☆☆"),
    ( 0, "☆☆☆☆☆"),
]

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Sheet tab names (must match actual spreadsheet tabs)
_TAB_MODELS     = "models"
_TAB_ORDERS     = "orders"
_TAB_SHOOTS     = "shoots"
_TAB_ACCOUNTING = "accounting"
_TAB_FORMS      = "forms"


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class AnalyticsSyncResult:
    n_models:     int = 0
    n_orders:     int = 0
    n_shoots:     int = 0
    n_accounting: int = 0
    n_forms:      int = 0
    n_winrate:    int = 0
    elapsed_sec:  float = 0.0
    errors:       list[str] = field(default_factory=list)


# ── Notion import helpers ──────────────────────────────────────────────────────
# Import private helpers from notion.py (module-level functions, not private methods)

from app.services.notion import (  # noqa: E402
    NotionClient,
    _extract_select,
    _extract_status,
    _extract_multi_select,
    _extract_number,
    _extract_relation_id,
    _extract_date,
    _extract_any_title,
)


def _extract_person_or_select(page: dict[str, Any], prop_name: str) -> str | None:
    """Extract people property (→ names), or fall back to select / rich_text."""
    prop = page.get("properties", {}).get(prop_name)
    if not prop:
        return None
    ptype = prop.get("type")
    if ptype == "people":
        names = [p.get("name", "") for p in prop.get("people", []) if p.get("name")]
        return ", ".join(names) if names else None
    if ptype == "select":
        val = prop.get("select")
        return val.get("name") if val else None
    if ptype == "rich_text":
        frags = prop.get("rich_text", [])
        text = "".join(f.get("plain_text", "") for f in frags).strip()
        return text or None
    return None


# ── Pagination helper ──────────────────────────────────────────────────────────

async def _fetch_all_pages(
    notion: NotionClient,
    url: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Paginate through a Notion database query, returning all results."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body = {**payload, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = await notion._request("POST", url, json=body)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


# ── Fetch functions ────────────────────────────────────────────────────────────

async def _fetch_all_models(
    notion: NotionClient,
    db_id: str,
) -> list[dict[str, Any]]:
    """Fetch all models with all analytics-relevant fields."""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    assist_filters = [
        {"property": "assist", "select": {"equals": a.strip()}}
        for a in ANALYTICS_ASSISTANTS
    ]
    payload = {
        "filter": {
            "and": [
                {
                    "or": [
                        {"property": "status", "status": {"equals": "work"}},
                        {"property": "status", "status": {"equals": "inactive"}},
                    ]
                },
                {"or": assist_filters},
            ]
        }
    }
    items = await _fetch_all_pages(notion, url, payload)
    models = []
    for item in items:
        title = await notion._extract_model_title(item)
        if not title:
            LOGGER.debug("Skipping model %s — no title", item.get("id"))
            continue
        models.append({
            "page_id":  item["id"].replace("-", ""),
            "model":    title,
            "status":   _extract_status(item, "status"),
            "project":  _extract_select(item, "project"),
            "assist":   _extract_person_or_select(item, "assist"),
            "scout":    _extract_person_or_select(item, "scout"),
            "winrate":  _extract_select(item, "winrate"),
            "language": ", ".join(_extract_multi_select(item, "language")),
            "anal":     ", ".join(_extract_multi_select(item, "anal")),
            "calls":    ", ".join(_extract_multi_select(item, "calls")),
        })
    return models


async def _fetch_all_orders(
    notion: NotionClient,
    db_id: str,
    since: date,
) -> list[dict[str, Any]]:
    """Fetch all non-archived orders where date_in >= since."""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    payload = {
        "filter": {
            "property": "in",
            "date": {"on_or_after": since.isoformat()},
        },
        "sorts": [{"property": "in", "direction": "ascending"}],
    }
    items = await _fetch_all_pages(notion, url, payload)
    today = date.today()
    orders = []
    for item in items:
        in_date  = _extract_date(item, "in")
        out_date = _extract_date(item, "out")
        status   = _extract_select(item, "status")
        days_raw = _extract_number(item, "days")
        cnt_raw  = _extract_number(item, "count")

        days_open: int | None = None
        if status == "Open" and in_date:
            try:
                days_open = (today - date.fromisoformat(in_date)).days
            except ValueError:
                pass

        raw_mid = _extract_relation_id(item, "model")
        orders.append({
            "page_id":  item["id"],
            "model_id": raw_mid.replace("-", "") if raw_mid else None,
            "type":     _extract_select(item, "type"),
            "status":   status,
            "date_in":  in_date,
            "date_out": out_date,
            "days":     int(days_raw) if days_raw is not None else None,
            "days_open": days_open,
            "count":    int(cnt_raw) if cnt_raw is not None else None,
        })
    return orders


async def _fetch_all_planner(
    notion: NotionClient,
    db_id: str,
) -> list[dict[str, Any]]:
    """Fetch all planner entries (all statuses; formula uses done/cancelled/stuck)."""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    payload = {"sorts": [{"property": "date", "direction": "descending"}]}
    items = await _fetch_all_pages(notion, url, payload)
    rows = []
    for item in items:
        raw_mid = _extract_relation_id(item, "model")
        rows.append({
            "page_id":  item["id"],
            "model_id": raw_mid.replace("-", "") if raw_mid else None,
            "date":     _extract_date(item, "date"),
            "status":   _extract_select(item, "status"),
            "location": _extract_select(item, "location"),
            "content":  _extract_multi_select(item, "content"),
        })
    return rows


async def _fetch_accounting_for_month(
    notion: NotionClient,
    db_id: str,
    yyyy_mm: str,
) -> list[dict[str, Any]]:
    """Fetch all accounting records for a given month (three-format search, deduped)."""
    from app.utils.formatting import MONTHS_RU_LOWER

    year, month_str = yyyy_mm.split("-")
    month_label    = MONTHS_RU_LOWER[int(month_str) - 1]
    primary_label  = f"{month_label} {year}"

    url  = f"https://api.notion.com/v1/databases/{db_id}/query"
    seen: set[str] = set()
    all_items: list[dict[str, Any]] = []

    for term in (primary_label, month_label, yyyy_mm):
        payload = {
            "filter": {"property": "Title", "title": {"contains": term}},
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        }
        for item in await _fetch_all_pages(notion, url, payload):
            if item["id"] not in seen:
                seen.add(item["id"])
                all_items.append(item)

    records = []
    for item in all_items:
        files_raw   = _extract_number(item, "Files")
        last_edited = item.get("last_edited_time", "")

        # Explicitly extract relation ID to avoid URL-vs-ID mismatch
        rel = item.get("properties", {}).get("model", {}).get("relation", [])
        if rel:
            raw_id   = rel[0].get("id", "")
            model_id = raw_id.replace("-", "") if raw_id else None
        else:
            model_id = None

        records.append({
            "page_id":   item["id"],
            "model_id":  model_id,
            "title":     _extract_any_title(item) or "",
            "status":    _extract_status(item, "status"),
            "content":   _extract_multi_select(item, "Content"),
            "files":     int(files_raw) if files_raw is not None else 0,
            "edited_at": last_edited[:10] if last_edited else "",
        })
    return records


async def _fetch_all_forms(
    notion: NotionClient,
    db_id: str,
) -> list[dict[str, Any]]:
    """Fetch all Forms entries (reference data, rewritten each sync)."""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    items = await _fetch_all_pages(notion, url, {})
    rows = []
    for item in items:
        raw_mid = _extract_relation_id(item, "model")
        rows.append({
            "page_id":  item["id"],
            "model_id": raw_mid.replace("-", "") if raw_mid else None,
            "model":    _extract_any_title(item) or "",
            "status":   (
                _extract_select(item, "status")
                or _extract_status(item, "status")
            ),
            "lang":     _extract_select(item, "lang"),
            "anal":     _extract_select(item, "anal"),
            "calls":    _extract_select(item, "calls"),
            "optional": _extract_multi_select(item, "optional"),
        })
    return rows


# ── Date helpers ───────────────────────────────────────────────────────────────

def _first_day_of_last_month() -> date:
    today = date.today()
    first_this = today.replace(day=1)
    last_prev  = first_this - timedelta(days=1)
    return last_prev.replace(day=1)


# ── Score / stars ──────────────────────────────────────────────────────────────

def _score_to_stars(score: float) -> str:
    for threshold, stars in _STAR_MAP:
        if score >= threshold:
            return stars
    return "☆☆☆☆☆"


# ── Model metrics calculation ──────────────────────────────────────────────────

def _build_model_rows(
    models: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    planner: list[dict[str, Any]],
    acc_cur: dict[str, dict[str, Any]],
    acc_prev_ids: set[str],
) -> tuple[list[list], list[tuple[str, str]]]:
    """
    Compute per-model metrics and assemble models-sheet rows.

    Returns:
        rows            — list of value lists for the models sheet
        winrate_updates — list of (page_id, stars) for Notion PATCH
    """
    # Index by model_id for O(1) lookup
    orders_by_model: dict[str, list] = {}
    for o in orders:
        mid = o.get("model_id")
        if mid:
            orders_by_model.setdefault(mid, []).append(o)

    planner_by_model: dict[str, list] = {}
    for s in planner:
        mid = s.get("model_id")
        if mid:
            planner_by_model.setdefault(mid, []).append(s)

    rows: list[list] = []
    winrate_updates: list[tuple[str, str]] = []

    for m in models:
        pid    = m["page_id"].replace("-", "")
        mstatus = m["status"] or ""

        # ── Orders metrics (all fetched orders are already date-filtered) ──────
        model_orders    = orders_by_model.get(pid, [])
        orders_total    = len(model_orders)
        orders_open     = sum(1 for o in model_orders if o["status"] == "Open")
        orders_done     = sum(1 for o in model_orders if o["status"] == "Done")
        orders_canceled = sum(
            1 for o in model_orders if o["status"] in {"Canceled", "Cancelled"}
        )

        # Penalty: each Open order with days_open > 5 adds 5 pts
        penalties = 0
        for o in model_orders:
            if o["status"] == "Open" and (o.get("days_open") or 0) > 5:
                penalties += 5

        closed = orders_done + orders_canceled
        orders_winrate = orders_done / closed if closed > 0 else 0.0

        # ── Shoots metrics ────────────────────────────────────────────────────
        model_shoots     = planner_by_model.get(pid, [])
        shoots_done      = sum(1 for s in model_shoots if s["status"] == "done")
        shoots_cancelled = sum(1 for s in model_shoots if s["status"] == "cancelled")
        shoots_stuck     = sum(1 for s in model_shoots if s["status"] == "stuck")
        shoots_planned   = sum(
            1 for s in model_shoots
            if s["status"] in {"planned", "scheduled", "rescheduled"}
        )

        dcs = shoots_done + shoots_cancelled + shoots_stuck
        has_shoots = dcs > 0
        shoots_rel = shoots_done / dcs if dcs > 0 else 0.0

        # Last shoot date among done/cancelled/stuck
        closed_dates = [
            s["date"] for s in model_shoots
            if s["date"] and s["status"] in {"done", "cancelled", "stuck"}
        ]
        last_shoot_date = max(closed_dates) if closed_dates else ""

        # Unique content types across all shoots for this model
        content_types: set[str] = set()
        for s in model_shoots:
            content_types.update(s.get("content") or [])
        content_types_str = ", ".join(sorted(content_types))

        needs_rent = any(
            (s.get("location") or "").lower() == "rent" for s in model_shoots
        )

        # ── Accounting metrics ────────────────────────────────────────────────
        acc_rec     = acc_cur.get(pid)
        total_files = acc_rec["files"] if acc_rec else 0
        files_target = FILES_TARGET_WORK if mstatus == "work" else FILES_TARGET_NEW
        files_pct    = total_files / files_target if files_target > 0 else 0.0
        acc_content  = (
            ", ".join(acc_rec["content"])
            if acc_rec and acc_rec.get("content") else ""
        )
        has_files = bool(acc_rec) or (pid in acc_prev_ids)

        # ── Performance score ─────────────────────────────────────────────────
        if has_shoots and has_files:
            score = orders_winrate * 50 + shoots_rel * 25 + files_pct * 25
        elif not has_shoots and has_files:
            score = orders_winrate * 67 + files_pct * 33
        elif has_shoots and not has_files:
            score = orders_winrate * 67 + shoots_rel * 33
        else:
            score = orders_winrate * 100

        score = max(0.0, min(100.0, score - penalties))
        stars = _score_to_stars(score)

        # ── Assemble row ──────────────────────────────────────────────────────
        rows.append([
            m["model"],
            m.get("project") or "",
            m.get("assist") or "",
            m.get("scout") or "",
            mstatus,
            m.get("winrate") or "",           # winrate_notion (current)
            round(orders_winrate * 100, 1),   # winrate_calc
            round(score, 1),                  # performance_score
            stars,                            # winrate_stars
            orders_total,
            orders_open,
            orders_done,
            orders_canceled,
            penalties,                        # days_open_penalties
            shoots_done,
            shoots_planned,
            shoots_cancelled,
            last_shoot_date,
            content_types_str,
            total_files,
            files_target,
            round(files_pct * 100, 1),        # files_pct (%)
            m.get("language") or "",
            m.get("anal") or "",
            m.get("calls") or "",
            True if needs_rent else False,
            acc_content,
        ])

        # Queue winrate update for active models
        if mstatus in ACTIVE_STATUSES:
            winrate_updates.append((pid, stars))

    return rows, winrate_updates


# ── Google Sheets (sync, runs in thread) ───────────────────────────────────────

def _write_sheets_sync(
    service_account_json: str,
    spreadsheet_id: str,
    sheets_data: dict[str, list[list]],
) -> None:
    """Clear and rewrite each tab. Must be called inside asyncio.to_thread()."""
    import base64

    import gspread
    from google.oauth2.service_account import Credentials

    raw = service_account_json
    if not raw:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is empty")

    try:
        sa_info = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        try:
            sa_info = json.loads(base64.b64decode(raw + "==").decode("utf-8"))
        except Exception as e:
            raise ValueError(
                f"Не могу распарсить GOOGLE_SERVICE_ACCOUNT_JSON: {e}. "
                f"Первые 50 символов: {raw[:50]!r}"
            )

    LOGGER.info(
        "Sheets JSON parsed OK, client_email=%s",
        sa_info.get("client_email"),
    )
    creds   = Credentials.from_service_account_info(sa_info, scopes=GOOGLE_SCOPES)
    gc      = gspread.authorize(creds)
    sh      = gc.open_by_key(spreadsheet_id)

    for tab_name, rows in sheets_data.items():
        try:
            ws = sh.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(
                title=tab_name,
                rows=max(len(rows) + 20, 100),
                cols=30,
            )
        ws.clear()
        if rows:
            headers = [h for h in rows[0] if h is not None]
            n = len(headers)
            clean = [headers] + [
                [
                    str(r[i]) if i < len(r) and r[i] is not None else ""
                    for i in range(n)
                ]
                for r in rows[1:]
            ]
            ws.update("A1", clean, value_input_option="RAW")


# ── Notion winrate write-back ──────────────────────────────────────────────────

async def _update_notion_winrates(
    notion: NotionClient,
    updates: list[tuple[str, str]],
) -> int:
    """Patch winrate select on each active model page. Returns count of successes."""
    if not updates:
        return 0

    async def _patch(page_id: str, stars: str) -> bool:
        try:
            await notion._request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{page_id}",
                json={"properties": {"winrate": {"select": {"name": stars}}}},
            )
            return True
        except Exception as exc:
            LOGGER.warning("Failed to update winrate page=%s: %s", page_id, exc)
            return False

    # Send in small batches to stay well below Notion rate limit (~3 req/s)
    BATCH_SIZE = 5
    success = 0
    for i in range(0, len(updates), BATCH_SIZE):
        batch   = updates[i : i + BATCH_SIZE]
        results = await asyncio.gather(*[_patch(pid, s) for pid, s in batch])
        success += sum(results)
        if i + BATCH_SIZE < len(updates):
            await asyncio.sleep(0.5)

    return success


# ── Sheet headers ──────────────────────────────────────────────────────────────

_MODELS_HEADER = [
    "model", "project", "assist", "scout", "status",
    "winrate_notion", "winrate_calc", "performance_score", "winrate_stars",
    "orders_total", "orders_open", "orders_done", "orders_canceled",
    "days_open_penalties",
    "shoots_done", "shoots_planned", "shoots_cancelled",
    "last_shoot_date", "content_types_shoots",
    "total_files", "files_target", "files_pct",
    "language", "anal", "calls",
    "needs_rent", "acc_content",
]

_ORDERS_HEADER     = ["model", "type", "status", "date_in", "date_out", "days", "days_open", "count"]
_SHOOTS_HEADER     = ["model", "date", "status", "location", "content_types"]
_ACCOUNTING_HEADER = ["model", "title", "status", "content", "files", "edited_at"]
_FORMS_HEADER      = ["model", "status", "lang", "anal", "calls", "optional"]


# ── Main entry point ───────────────────────────────────────────────────────────

async def run_analytics_sync(
    notion: NotionClient,
    db_models: str,
    db_orders: str,
    db_planner: str,
    db_accounting: str,
) -> AnalyticsSyncResult:
    """
    Full analytics sync pipeline:
      1. Parallel fetch from Notion (models, orders, planner, accounting ×2, forms)
      2. Calculate per-model performance metrics
      3. Write 5 tabs to Google Sheets (via asyncio.to_thread)
      4. Patch winrate select back into Notion

    Reads from env:
      GOOGLE_SERVICE_ACCOUNT_JSON  — service account JSON string (required)
      ANALYTICS_SPREADSHEET_ID     — target spreadsheet (falls back to hard-coded default)
      DB_FORMS                     — Forms database ID (falls back to default)
    """
    t0     = time.monotonic()
    result = AnalyticsSyncResult()

    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    spreadsheet_id       = os.getenv(
        "ANALYTICS_SPREADSHEET_ID", ANALYTICS_SPREADSHEET_ID_DEFAULT
    ).strip()
    db_forms = os.getenv("DB_FORMS", DB_FORMS_DEFAULT).strip()

    if not service_account_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")

    today        = date.today()
    cur_yyyy_mm  = today.strftime("%Y-%m")
    prev_yyyy_mm = _first_day_of_last_month().strftime("%Y-%m")
    orders_since = _first_day_of_last_month()

    # ── 1. Parallel Notion fetch ───────────────────────────────────────────────
    LOGGER.info("Analytics: starting parallel Notion fetch")
    gathered = await asyncio.gather(
        _fetch_all_models(notion, db_models),
        _fetch_all_orders(notion, db_orders, orders_since),
        _fetch_all_planner(notion, db_planner),
        _fetch_accounting_for_month(notion, db_accounting, cur_yyyy_mm),
        _fetch_accounting_for_month(notion, db_accounting, prev_yyyy_mm),
        _fetch_all_forms(notion, db_forms),
        return_exceptions=True,
    )

    labels = ("models", "orders", "planner", "accounting_cur", "accounting_prev", "forms")

    def _unwrap(label: str, val: Any) -> list:
        if isinstance(val, BaseException):
            LOGGER.error("Analytics: fetch failed [%s]: %s", label, val)
            if label == "forms":
                result.errors.append("⚠️ forms: недоступна")
            else:
                result.errors.append(f"{label}: {val}")
            return []
        return val  # type: ignore[return-value]

    (
        models_raw,
        orders_raw,
        planner_raw,
        acc_cur_raw,
        acc_prev_raw,
        forms_raw,
    ) = [_unwrap(lbl, val) for lbl, val in zip(labels, gathered)]

    result.n_models     = len(models_raw)
    result.n_orders     = len(orders_raw)
    result.n_shoots     = len(planner_raw)
    result.n_accounting = len(acc_cur_raw)
    result.n_forms      = len(forms_raw)

    LOGGER.info(
        "Analytics: fetched — models=%d orders=%d shoots=%d acc_cur=%d acc_prev=%d forms=%d",
        result.n_models, result.n_orders, result.n_shoots,
        result.n_accounting, len(acc_prev_raw), result.n_forms,
    )

    # Debug: dump accounting model_ids and a few model page_ids to diagnose join issues
    for acc in acc_cur_raw + acc_prev_raw:
        LOGGER.info(
            "ACC: model_id=%s title=%s files=%s",
            acc.get("model_id"), acc.get("title"), acc.get("files"),
        )
    for m in models_raw[:3]:
        LOGGER.info(
            "MODEL: page_id=%s name=%s",
            m.get("page_id"), m.get("model"),
        )

    # ── 2. Index accounting ────────────────────────────────────────────────────
    # Keep only first record per model (most recently edited, because of sort)
    acc_cur: dict[str, dict[str, Any]] = {}
    for rec in acc_cur_raw:
        mid = rec.get("model_id")
        if mid and mid not in acc_cur:
            acc_cur[mid] = rec

    acc_prev_ids: set[str] = {
        rec["model_id"] for rec in acc_prev_raw if rec.get("model_id")
    }

    # ── 3. Calculate model metrics ────────────────────────────────────────────
    model_rows, winrate_updates = _build_model_rows(
        models_raw, orders_raw, planner_raw, acc_cur, acc_prev_ids
    )

    # ── 4. Build denormalized rows for other tabs ─────────────────────────────
    # page_ids are already stored without dashes (normalized in _fetch_all_models)
    name_by_id: dict[str, str] = {m["page_id"]: m["model"] for m in models_raw}

    # All orders (Open + Done + Canceled) — same dataset used for metrics
    LOGGER.info(
        "Analytics: orders for Sheets — total=%d open=%d done=%d canceled=%d",
        len(orders_raw),
        sum(1 for o in orders_raw if o.get("status") == "Open"),
        sum(1 for o in orders_raw if o.get("status") == "Done"),
        sum(1 for o in orders_raw if o.get("status") in {"Canceled", "Cancelled"}),
    )
    orders_rows = [
        [
            name_by_id.get(o.get("model_id", ""), ""),
            o["type"]     or "",
            o["status"]   or "",
            o["date_in"]  or "",
            o["date_out"] or "",
            o["days"]     if o["days"]      is not None else "",
            o["days_open"] if o["days_open"] is not None else "",
            o["count"]    if o["count"]     is not None else "",
        ]
        for o in orders_raw
    ]

    shoots_rows = [
        [
            name_by_id.get(s.get("model_id") or "", ""),
            s.get("date")     or "",
            s.get("status")   or "",
            s.get("location") or "",
            ", ".join(s.get("content") or []),
        ]
        for s in planner_raw
    ]

    accounting_rows = [
        [
            name_by_id.get(a.get("model_id", ""), ""),
            a["title"],
            a["status"]    or "",
            ", ".join(a.get("content") or []),
            a["files"],
            a["edited_at"] or "",
        ]
        for a in acc_cur_raw
    ]

    forms_rows = [
        [
            name_by_id.get(f.get("model_id", ""), f["model"]),
            f["status"]   or "",
            f["lang"]     or "",
            f["anal"]     or "",
            f["calls"]    or "",
            ", ".join(f.get("optional") or []),
        ]
        for f in forms_raw
    ]

    sheets_data = {
        _TAB_MODELS:     [_MODELS_HEADER]     + model_rows,
        _TAB_ORDERS:     [_ORDERS_HEADER]     + orders_rows,
        _TAB_SHOOTS:     [_SHOOTS_HEADER]     + shoots_rows,
        _TAB_ACCOUNTING: [_ACCOUNTING_HEADER] + accounting_rows,
        _TAB_FORMS:      [_FORMS_HEADER]      + forms_rows,
    }

    # ── 5. Write to Google Sheets (sync → thread) ─────────────────────────────
    LOGGER.info("Analytics: writing to Sheets id=%s", spreadsheet_id)
    try:
        await asyncio.to_thread(
            _write_sheets_sync,
            service_account_json,
            spreadsheet_id,
            sheets_data,
        )
    except Exception as e:
        import traceback
        LOGGER.error(f"Analytics: Sheets write failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        raise

    # ── 6. Write winrates back to Notion ──────────────────────────────────────
    LOGGER.info("Analytics: patching %d Notion winrates", len(winrate_updates))
    try:
        result.n_winrate = await _update_notion_winrates(notion, winrate_updates)
    except Exception as exc:
        LOGGER.error("Analytics: Notion winrate update failed: %s", exc)
        result.errors.append(f"Winrate: {exc}")

    result.elapsed_sec = time.monotonic() - t0
    LOGGER.info(
        "Analytics sync complete in %.1fs — models=%d orders=%d shoots=%d "
        "acc=%d forms=%d winrate=%d errors=%d",
        result.elapsed_sec,
        result.n_models, result.n_orders, result.n_shoots,
        result.n_accounting, result.n_forms, result.n_winrate,
        len(result.errors),
    )
    return result
