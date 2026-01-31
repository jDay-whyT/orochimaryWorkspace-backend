"""Accounting service - Phase 4"""
import logging
from datetime import datetime
from typing import Any
from app.config import Config
from app.services.notion import NotionClient, NotionAccounting

LOGGER = logging.getLogger(__name__)


class AccountingService:
    """Service for working with accounting database"""

    def __init__(self, config: Config):
        self.config = config
        self.notion = NotionClient(config.notion_token)

    async def get_current_month_records(self) -> list[dict[str, Any]]:
        """Get accounting records for current month"""
        now = datetime.now(self.config.timezone)
        month_str = now.strftime("%B")  # "January", "February", etc.

        records = await self.notion.query_accounting_by_month(
            self.config.db_accounting,
            month_str,
        )

        return [
            {
                "id": r.page_id,
                "model_id": r.model_id,
                "model_name": r.model_title or "Unknown",
                "amount": r.amount or 0,
                "percent": r.percent or 0.0,
                "content": r.content or [],
                "status": r.status,
                "comments": r.comments,
                "month": month_str,
            }
            for r in records
        ]

    async def get_record_by_model(self, model_id: str) -> dict[str, Any] | None:
        """Get current month record for specific model"""
        now = datetime.now(self.config.timezone)
        month_str = now.strftime("%B")

        try:
            record = await self.notion.get_accounting_record(
                self.config.db_accounting,
                model_id,
                month_str,
            )

            if not record:
                return None

            return {
                "id": record.page_id,
                "model_id": record.model_id,
                "model_name": record.model_title or "Unknown",
                "amount": record.amount or 0,
                "percent": record.percent or 0.0,
                "content": record.content or [],
                "status": record.status,
                "comments": record.comments,
                "month": month_str,
            }
        except Exception as e:
            LOGGER.exception(f"Failed to get accounting record for model {model_id}")
            return None

    async def add_files(
        self,
        model_id: str,
        model_name: str,
        files_to_add: int,
    ) -> dict[str, Any]:
        """Add files to current month record"""
        now = datetime.now(self.config.timezone)
        month_str = now.strftime("%B")

        # Get or create record
        record = await self.get_record_by_model(model_id)

        if record:
            # Update existing
            current_amount = record["amount"]
            new_amount = current_amount + files_to_add
            new_percent = round(new_amount / self.config.files_per_month, 2)

            await self.notion.update_accounting_files(
                record["id"],
                new_amount,
                new_percent,
            )

            return {
                "id": record["id"],
                "model_id": model_id,
                "model_name": model_name,
                "amount": new_amount,
                "percent": new_percent,
                "content": record["content"],
                "status": record["status"],
                "comments": record["comments"],
                "month": month_str,
            }
        else:
            # Create new record
            new_amount = files_to_add
            new_percent = round(new_amount / self.config.files_per_month, 2)

            page_id = await self.notion.create_accounting_record(
                database_id=self.config.db_accounting,
                model_page_id=model_id,
                amount=new_amount,
                month=month_str,
                files_per_month=self.config.files_per_month,
            )

            return {
                "id": page_id,
                "model_id": model_id,
                "model_name": model_name,
                "amount": new_amount,
                "percent": new_percent,
                "content": [],
                "status": "work",
                "comments": None,
                "month": month_str,
            }

    async def update_content(self, record_id: str, content: list[str]) -> None:
        """Update content for accounting record"""
        await self.notion.update_accounting_content(record_id, content)

    async def update_comment(self, record_id: str, comment: str) -> None:
        """Update comment for accounting record"""
        await self.notion.update_accounting_comment(record_id, comment)

    async def close(self):
        """Close connections"""
        await self.notion.close()
