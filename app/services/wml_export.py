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
