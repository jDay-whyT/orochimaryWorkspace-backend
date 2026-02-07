"""Accounting service — one record per model per month.

Title format: "{MODEL_NAME} · accounting {YYYY-MM}"
Fields used: Title, model (relation), Files (number), Comment (rich_text).
"""
import logging
from datetime import datetime
from typing import Any

from app.config import Config
from app.services.notion import NotionClient, NotionAccounting

LOGGER = logging.getLogger(__name__)


def _yyyy_mm(config: Config) -> str:
    """Return current month as YYYY-MM."""
    return datetime.now(config.timezone).strftime("%Y-%m")


class AccountingService:
    """Service for working with accounting database."""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def _get_model_name(self, model_id: str) -> str:
        model = await self.notion.get_model(model_id)
        return model.title if model and model.title else "Unknown"

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
        files_to_add: int,
        month: str | None = None,
    ) -> dict[str, Any]:
        """
        Add files to current-month record.  Creates if missing.

        Returns dict with keys: id, files, model_id, model_name.
        """
        yyyy_mm = month or _yyyy_mm(self.config)
        records = await self.notion.query_monthly_records(
            self.config.db_accounting, model_id, yyyy_mm,
        )

        record = records[0] if records else None
        if len(records) > 1 and record:
            LOGGER.warning(
                "Multiple accounting records for model %s in %s; using latest %s",
                model_id,
                yyyy_mm,
                record.page_id,
            )

        if record:
            new_files = record.files + files_to_add
            await self.notion.update_accounting_files(record.page_id, new_files)
            model_name = await self._get_model_name(model_id)
            return {
                "id": record.page_id,
                "files": new_files,
                "model_id": model_id,
                "model_name": model_name,
            }

        model_name = await self._get_model_name(model_id)
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
        }

    async def get_all_month_records(self) -> list[dict[str, Any]]:
        """Get all accounting records for current month."""
        yyyy_mm = _yyyy_mm(self.config)
        records = await self.notion.query_accounting_all_month(
            self.config.db_accounting, yyyy_mm,
        )
        fpm = self.config.files_per_month
        return [
            {
                "id": r.page_id,
                "model_id": r.model_id,
                "model_name": r.model_title or "Unknown",
                "files": r.files,
                "percent": min(100, round(r.files / fpm * 100)) if fpm > 0 else 0,
                "over": max(0, r.files - fpm),
            }
            for r in records
        ]

    async def update_comment(
        self,
        target_id: str | None,
        comment: str,
        month: str | None = None,
        *,
        page_id: str | None = None,
    ) -> None:
        """Update Comment for an accounting record."""
        if page_id:
            await self.notion.update_accounting_comment(page_id, comment)
            return

        if not target_id:
            LOGGER.warning("Missing model_id for accounting comment update")
            return

        yyyy_mm = month or _yyyy_mm(self.config)
        records = await self.notion.query_monthly_records(
            self.config.db_accounting, target_id, yyyy_mm,
        )
        record = records[0] if records else None
        if len(records) > 1 and record:
            LOGGER.warning(
                "Multiple accounting records for model %s in %s; using latest %s",
                target_id,
                yyyy_mm,
                record.page_id,
            )
        if not record:
            LOGGER.warning(
                "No accounting record found for model %s in %s",
                target_id,
                yyyy_mm,
            )
            return

        await self.notion.update_accounting_comment(record.page_id, comment)

    async def close(self):
        """Close connections."""
        await self.notion.close()
