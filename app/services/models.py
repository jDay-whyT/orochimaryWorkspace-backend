"""Models service"""
import logging
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionModel

LOGGER = logging.getLogger(__name__)


class ModelsService:
    """Service for working with models database"""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def search_models(self, query: str) -> list[dict[str, Any]]:
        """Search models by name"""
        models = await self.notion.query_models(
            self.config.db_models,
            query,
        )
        return [
            {
                "id": m.page_id,
                "name": m.title,
                "project": m.project,
                "status": m.status,
                "winrate": m.winrate,
            }
            for m in models
        ]

    async def get_model_by_id(self, model_id: str) -> dict[str, Any] | None:
        """Get model by ID"""
        try:
            model = await self.notion.get_model(model_id)
            if not model:
                return None
            return {
                "id": model.page_id,
                "name": model.title,
                "project": model.project,
                "status": model.status,
                "winrate": model.winrate,
            }
        except Exception as e:
            LOGGER.exception(f"Failed to get model {model_id}")
            return None

    async def close(self):
        """Close connections"""
        await self.notion.close()
