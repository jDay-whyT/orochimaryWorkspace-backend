"""Model search handlers for NLP routing."""

import logging
from typing import Any

from app.services import NotionClient
from app.services.notion import _extract_title, _extract_multi_select


LOGGER = logging.getLogger(__name__)


async def search_model_by_name_or_alias(
    name: str, db_id: str, notion: NotionClient
) -> list[dict[str, Any]]:
    """Search models by name or alias (case-insensitive); returns [{"id", "name", "aliases"}, ...]."""
    name_lower = name.lower()

    # multi_select "contains" only matches values that are already registered
    # options on the "aliases" property - an unregistered search term makes
    # Notion reject the whole request with 400. There's no way to filter by
    # alias server-side without risking that, so fetch every page (unfiltered,
    # paginated) and match both title and aliases client-side.
    url = f"https://api.notion.com/v1/databases/{db_id}/query"

    models = []
    cursor: str | None = None
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        try:
            response = await notion._request("POST", url, json=payload)
        except Exception as e:
            LOGGER.exception("Failed to search models: %s", e)
            return []

        for item in response.get("results", []):
            title = _extract_title(item, "model")
            aliases = _extract_multi_select(item, "aliases")

            if not title:
                LOGGER.warning("Skipping model %s - no title found", item.get("id"))
                continue

            title_match = name_lower in title.lower()
            alias_match = any(name_lower in alias.lower() for alias in aliases)

            if title_match or alias_match:
                models.append({"id": item["id"], "name": title, "aliases": aliases})

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    LOGGER.info("Found %d models for query '%s'", len(models), name)
    return models
