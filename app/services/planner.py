"""Planner service - Phase 3"""
import logging
import time
from datetime import date
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionPlanner

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


async def get_cached_shoots(
    notion: NotionClient,
    config: Config,
    model_id: str,
) -> list[NotionPlanner]:
    """Get upcoming shoots with in-memory TTL cache."""
    key = model_id
    cached = _get_cached(key)
    if cached is not None:
        return cached

    shoots = await notion.query_upcoming_shoots(
        config.db_planner,
        model_page_id=model_id,
    )
    _set_cached(key, shoots)
    return shoots


class PlannerService:
    """Service for working with planner (shoots) database"""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def get_upcoming_shoots(self) -> list[dict[str, Any]]:
        """Get upcoming shoots (planned/scheduled/rescheduled)"""
        shoots = await self.notion.query_upcoming_shoots(self.config.db_planner)
        return [
            {
                "id": s.page_id,
                "model_id": s.model_id,
                "model_name": s.model_title or "Unknown",
                "date": s.date,
                "status": s.status,
                "content": s.content or [],
                "location": s.location,
                "comments": s.comments,
            }
            for s in shoots
        ]

    async def get_shoot_by_id(self, shoot_id: str) -> dict[str, Any] | None:
        """Get shoot by ID"""
        try:
            shoot = await self.notion.get_shoot(shoot_id)
            if not shoot:
                return None
            return {
                "id": shoot.page_id,
                "model_id": shoot.model_id,
                "model_name": shoot.model_title or "Unknown",
                "date": shoot.date,
                "status": shoot.status,
                "content": shoot.content or [],
                "location": shoot.location,
                "comments": shoot.comments,
            }
        except Exception as e:
            LOGGER.exception(f"Failed to get shoot {shoot_id}")
            return None

    async def create_shoot(
        self,
        model_id: str,
        shoot_date: date,
        content: list[str],
        location: str,
        title: str,
        comment: str | None = None,
    ) -> str:
        """Create new shoot"""
        return await self.notion.create_shoot(
            database_id=self.config.db_planner,
            model_page_id=model_id,
            shoot_date=shoot_date,
            content=content,
            location=location,
            title=title,
            comments=comment,
        )

    async def mark_done(self, shoot_id: str) -> None:
        """Mark shoot as done"""
        await self.notion.update_shoot_status(shoot_id, "done")

    async def cancel_shoot(self, shoot_id: str) -> None:
        """Cancel shoot"""
        await self.notion.update_shoot_status(shoot_id, "cancelled")

    async def reschedule_shoot(self, shoot_id: str, new_date: str) -> None:
        """Reschedule shoot to new date"""
        await self.notion.reschedule_shoot(shoot_id, new_date)

    async def update_comment(self, shoot_id: str, comment: str) -> None:
        """Update shoot comment"""
        await self.notion.update_shoot_comment(shoot_id, comment)

    async def close(self):
        """Close connections"""
        await self.notion.close()
