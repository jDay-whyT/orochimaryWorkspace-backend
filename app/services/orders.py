"""Orders service - Phase 2"""
import logging
import time
from datetime import date
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionOrder

LOGGER = logging.getLogger(__name__)

CACHE_TTL = 60.0
_cache: dict[str, tuple[Any, float]] = {}


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry:
        data, ts = entry
        if time.monotonic() - ts < CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: Any) -> None:
    _cache[key] = (data, time.monotonic())


async def get_cached_orders(
    notion: NotionClient,
    config: Config,
    model_id: str,
) -> list[NotionOrder]:
    """Get open orders with in-memory TTL cache."""
    key = model_id
    cached = _get_cached(key)
    if cached is not None:
        return cached

    orders = await notion.query_open_orders(
        config.db_orders,
        model_page_id=model_id,
    )
    _set_cached(key, orders)
    return orders


class OrdersService:
    """Service for working with orders database"""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def get_open_orders(self, model_id: str) -> list[dict[str, Any]]:
        """Get open orders for model"""
        orders = await self.notion.query_open_orders(
            self.config.db_orders,
            model_id,
        )

        return [
            {
                "id": o.page_id,
                "type": o.order_type,
                "in_date": o.in_date,
                "count": o.count,
                "comments": o.comments,
                "status": o.status,
            }
            for o in orders
        ]

    async def create_order(
        self,
        model_id: str,
        order_type: str,
        in_date: str,
        count: int,
        comment: str | None = None,
    ) -> str:
        """Create new order"""
        # Generate title
        title = f"{order_type} — {in_date}"

        return await self.notion.create_order(
            database_id=self.config.db_orders,
            model_page_id=model_id,
            order_type=order_type,
            in_date=date.fromisoformat(in_date),
            count=count,
            title=title,
            comments=comment,
        )

    async def close_order(self, order_id: str, out_date: str) -> None:
        """Close order"""
        await self.notion.close_order(
            order_id,
            date.fromisoformat(out_date),
        )

    async def update_comment(self, order_id: str, comment: str) -> None:
        """Update order comment"""
        await self.notion.update_order(
            order_id,
            {"comments": {"rich_text": [{"text": {"content": comment}}]}},
        )

    async def close(self):
        """Close connections"""
        await self.notion.close()
