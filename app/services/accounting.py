"""Accounting service — one record per model per month.

Title format: "{MODEL_NAME} {месяц_ru_lower}" e.g. "КЛЕЩ февраль"
Fields used: Title, model (relation), Files (number), Comment (rich_text), Content (multi_select).
"""
import logging
from datetime import datetime
from typing import Any

from app.config import Config
from app.services.notion import NotionClient, NotionAccounting
from app.utils.accounting import calculate_accounting_progress

LOGGER = logging.getLogger(__name__)


def _yyyy_mm(config: Config) -> str:
    """Return current month as YYYY-MM."""
    return datetime.now(config.timezone).strftime("%Y-%m")


class AccountingService:
    """Service for working with accounting database."""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def get_monthly_record(self, model_id: str) -> NotionAccounting | None:
        """Get current-month record for a model (or None)."""
        try:
            return await self.notion.get_monthly_record(
                self.config.db_accounting, model_id, _yyyy_mm(self.config),
            )
        except Exception:
            LOGGER.exception("Failed to get monthly record for model %s", model_id)
            return None

    async def add_files(
        self,
        model_id: str,
        model_name: str,
        files_to_add: int,
    ) -> dict[str, Any]:
        """
        Add files to current-month record.  Creates if missing.

        Returns dict with keys: id, files, model_id, model_name.
        """
        yyyy_mm = _yyyy_mm(self.config)
        record = await self.notion.get_monthly_record(
            self.config.db_accounting, model_id, yyyy_mm,
        )

        if record:
            new_files = record.files + files_to_add
            await self.notion.update_accounting_files(record.page_id, new_files)
            return {
                "id": record.page_id,
                "files": new_files,
                "model_id": model_id,
                "model_name": model_name,
                "status": record.status,
            }
        else:
            page_id = await self.notion.create_accounting_record(
                database_id=self.config.db_accounting,
                model_page_id=model_id,
                model_name=model_name,
                files=files_to_add,
                yyyy_mm=yyyy_mm,
            )
            return {
                "id": page_id,
                "files": files_to_add,
                "model_id": model_id,
                "model_name": model_name,
                "status": None,
            }

    async def get_all_month_records(self) -> list[dict[str, Any]]:
        """Get all accounting records for current month."""
        yyyy_mm = _yyyy_mm(self.config)
        records = await self.notion.query_accounting_all_month(
            self.config.db_accounting, yyyy_mm,
        )
        results: list[dict[str, Any]] = []
        for record in records:
            target, pct, over = calculate_accounting_progress(record.files, record.status)
            results.append(
                {
                    "id": record.page_id,
                    "model_id": record.model_id,
                    "model_name": record.model_title or "Unknown",
                    "files": record.files,
                    "target": target,
                    "percent": pct,
                    "over": over,
                    "status": record.status,
                }
            )
        return results

    async def update_comment(self, record_id: str, comment: str) -> None:
        """Update Comment for an accounting record."""
        await self.notion.update_accounting_comment(record_id, comment)

    async def update_content(self, page_id: str, content_types: list[str]) -> None:
        """Update Content multi-select for an accounting record."""
        await self.notion.update_accounting_content(page_id, content_types)

    async def close(self):
        """Close connections."""
        await self.notion.close()
