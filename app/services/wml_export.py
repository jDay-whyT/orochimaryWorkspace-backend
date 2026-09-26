"""Push Notion orders to the WML CRM. Notion is the source; the CRM only receives.

Each sent order keeps its CRM id in the Notion `wml_id` field, so it is never
created twice. Tango models are not exported. An order counts as closed when it
has an `out` date (managers sometimes close by hand without setting Done).
"""

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.config import Config
from app.services.notion import NotionClient, NotionModel, NotionOrder
from app.services.wml_api import ORDER_TYPES, WmlApi

LOGGER = logging.getLogger(__name__)

# WML API allows ~10 requests/s; stay well below.
_SEND_INTERVAL_SECONDS = 0.2


def order_payload(order: NotionOrder, model: NotionModel | None) -> tuple[dict[str, Any] | None, str | None]:
    """CRM fields for an order, or (None, reason) when it must not be sent."""
    if model is None:
        return None, "нет модели"
    if (model.project or "").strip().upper() == "TANGO":
        return None, "Tango"
    if (order.status or "").strip().lower() == "canceled":
        return None, "отменён"
    order_type = (order.order_type or "").strip().lower()
    if order_type not in ORDER_TYPES:
        return None, f"тип «{order.order_type or '—'}»"
    if not order.in_date:
        return None, "нет даты in"

    payload: dict[str, Any] = {
        "profile": model.title,
        "title": order.title,
        "in": order.in_date[:10],
        "type": order_type,
    }
    if order.count is not None:
        payload["count"] = order.count
    if order.out_date:
        payload["out"] = order.out_date[:10]
    if order.received is not None:
        payload["received"] = order.received
    return payload, None


@dataclass
class OrderBatch:
    items: list[tuple[NotionOrder, dict[str, Any]]] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    already_sent: int = 0


async def pick_month_orders(config: Config, notion: NotionClient, yyyy_mm: str, limit: int) -> OrderBatch:
    """The `limit` latest (by `in`) not-yet-sent exportable orders of the month."""
    orders = await notion.query_orders_in_month(config.db_orders, yyyy_mm)
    models = {m.page_id.replace("-", ""): m for m in await notion.query_all_models(config.db_models)}

    batch = OrderBatch()
    for order in sorted(orders, key=lambda o: o.in_date or "", reverse=True):
        if order.wml_id is not None:
            batch.already_sent += 1
            continue
        payload, reason = order_payload(order, models.get((order.model_id or "").replace("-", "")))
        if payload is None:
            batch.skipped[reason] += 1
            continue
        if len(batch.items) < limit:
            batch.items.append((order, payload))
    return batch


async def send_orders(
    api: WmlApi, notion: NotionClient, items: list[tuple[NotionOrder, dict[str, Any]]],
) -> tuple[int, list[str]]:
    """Create each order in the CRM and remember its id in Notion. Returns (sent, errors)."""
    sent = 0
    errors: list[str] = []
    for order, payload in items:
        try:
            resp = await asyncio.to_thread(api.create_order, payload)
            await notion.set_order_wml_id(order.page_id, int(resp["id"]))
            sent += 1
        except Exception as e:
            LOGGER.exception("WML export failed for order %s", order.page_id)
            errors.append(f"{order.title}: {e}")
        await asyncio.sleep(_SEND_INTERVAL_SECONDS)
    return sent, errors


# ---------------------------------------------------------------------------
# Monthly file counts (Accounting) -> CRM "content request files"
# ---------------------------------------------------------------------------

def files_month(records: list, fallback: str) -> str:
    """The month the working Accounting records currently hold, as YYYY-MM.

    Records are renamed by hand at month close (/rename_month), so until the
    owner closes September its records still say "сентябрь 2026" even in early
    October. The most common "<month> <year>" among live titles wins.
    """
    from app.utils.formatting import MONTHS_RU_LOWER

    seen: Counter = Counter()
    for record in records:
        if (record.status or "").strip().lower() == "stop":
            continue
        # Whole words only: a model called "МАЙЯ" must not read as May.
        words = (record.title or "").lower().split()
        year = next((w for w in words if w.isdigit() and len(w) == 4), None)
        month = next((MONTHS_RU_LOWER.index(w) + 1 for w in words if w in MONTHS_RU_LOWER), None)
        if year and month:
            seen[f"{year}-{month:02d}"] += 1
    return seen.most_common(1)[0][0] if seen else fallback


def files_payload(record, model: NotionModel | None, yyyy_mm: str) -> tuple[dict[str, Any] | None, str | None]:
    """CRM fields for a model's monthly file counts, or (None, reason)."""
    if model is None:
        return None, "нет модели"
    if (model.project or "").strip().upper() == "TANGO" or "Tango" in (record.content or []):
        return None, "Tango"
    if (record.status or "").strip().lower() == "stop":
        return None, "stop"
    counts = {
        "of": record.of_files,
        "reddit": record.reddit_files,
        "twitter": record.twitter_files,
        "fansly": record.fansly_files,
        # social_files is being retired; its files are counted as requests
        "request": record.request_files + record.social_files,
    }
    total = int(record.total) if record.total is not None else sum(counts.values())
    return {"profile": model.title, "month": yyyy_mm, **counts, "total": total}, None


@dataclass
class FilesBatch:
    month: str = ""
    items: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)


async def pick_files(config: Config, notion: NotionClient, calendar_month: str) -> FilesBatch:
    """Each exportable model's current file counts, for the month the records hold."""
    from app.services.accounting import working_records

    records = await notion.query_all_accounting(config.db_accounting)
    month = files_month(records, calendar_month)
    working, _ = working_records(records, month)
    models = {m.page_id.replace("-", ""): m for m in await notion.query_all_models(config.db_models)}

    batch = FilesBatch(month=month)
    for model_key, record in working.items():
        payload, reason = files_payload(record, models.get(model_key), month)
        if payload is None:
            batch.skipped[reason] += 1
        else:
            batch.items.append((record, payload))
    batch.items.sort(key=lambda item: item[1]["profile"])
    return batch


async def send_files(api: WmlApi, items: list[tuple[Any, dict[str, Any]]]) -> tuple[int, list[str]]:
    """Upsert each model's monthly counts (the CRM matches by profile + month)."""
    sent = 0
    errors: list[str] = []
    for _, payload in items:
        try:
            await asyncio.to_thread(api.upsert_files, payload)
            sent += 1
        except Exception as e:
            LOGGER.exception("WML files export failed for %s", payload.get("profile"))
            errors.append(f"{payload.get('profile')}: {e}")
        await asyncio.sleep(_SEND_INTERVAL_SECONDS)
    return sent, errors
