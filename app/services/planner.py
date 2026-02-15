"""Planner service - Phase 3"""
import logging
from datetime import date
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionPlanner

LOGGER = logging.getLogger(__name__)


class PlannerService:
    """Service for working with planner (shoots) database"""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def _resolve_model_name(self, model_id: str | None, fallback: str | None = None) -> str:
        if fallback:
            return fallback
        if not model_id:
            return "—"
        try:
            model = await self.notion.get_model(model_id)
            if model and model.title:
                return model.title
        except Exception:
            LOGGER.warning("Failed to resolve planner model title for %s", model_id)
        return "—"

    async def get_upcoming_shoots(self) -> list[dict[str, Any]]:
        """Get upcoming shoots (planned/scheduled/rescheduled)"""
        shoots = await self.notion.query_upcoming_shoots(self.config.db_planner)
        results: list[dict[str, Any]] = []
        for s in shoots:
            model_name = await self._resolve_model_name(s.model_id, s.model_title)
            results.append(
                {
                    "id": s.page_id,
                    "model_id": s.model_id,
                    "model_name": model_name,
                    "date": s.date,
                    "status": s.status,
                    "content": s.content or [],
                    "location": s.location,
                    "comments": s.comments,
                    "title": s.title,
                }
            )
        return results

    async def get_shoot_by_id(self, shoot_id: str) -> dict[str, Any] | None:
        """Get shoot by ID"""
        try:
            shoot = await self.notion.get_shoot(shoot_id)
            if not shoot:
                return None
            model_name = await self._resolve_model_name(shoot.model_id, shoot.model_title)
            return {
                "id": shoot.page_id,
                "model_id": shoot.model_id,
                "model_name": model_name,
                "date": shoot.date,
                "status": shoot.status,
                "content": shoot.content or [],
                "location": shoot.location,
                "comments": shoot.comments,
                "title": shoot.title,
            }
        except Exception as e:
            LOGGER.exception(f"Failed to get shoot {shoot_id}")
            return None

    async def create_shoot(
        self,
        model_id: str,
        shoot_date: str,
        content: list[str],
        location: str,
        comment: str | None = None,
    ) -> str:
        """Create new shoot"""
        shoot_date_obj = date.fromisoformat(shoot_date)
        title = f"Shoot · {shoot_date_obj.isoformat()}"
        return await self.notion.create_shoot(
            database_id=self.config.db_planner,
            model_page_id=model_id,
            shoot_date=shoot_date_obj,
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
