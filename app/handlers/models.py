"""Model search handlers for NLP routing."""

import logging
from typing import Any

from app.services import NotionClient
from app.services.notion import _extract_title, _extract_multi_select
from app.utils.exceptions import NotionAPIError


LOGGER = logging.getLogger(__name__)


async def search_model_by_name_or_alias(
    name: str, db_id: str, notion: NotionClient
) -> list[dict[str, Any]]:
    """
    Search models by name or alias (case-insensitive).

    Returns:
        List of models: [{"id": str, "name": str, "aliases": list[str]}, ...]
    """
    name_lower = name.lower()

    # Notion API query with filter (case-insensitive search)
    # Note: Notion API filters are case-insensitive by default for "contains"
    payload = {
        "filter": {
            "or": [
                {"property": "model", "title": {"contains": name}},
                {"property": "aliases", "multi_select": {"contains": name}},
            ]
        }
    }

    url = f"https://api.notion.com/v1/databases/{db_id}/query"

    try:
        response = await notion._request("POST", url, json=payload)
    except NotionAPIError as e:
        LOGGER.warning("Failed to search models: %s", e)
        return []
    except Exception as e:
        LOGGER.exception("Failed to search models: %s", e)
        return []

    models = []
    for item in response.get("results", []):
        title = _extract_title(item, "model")
        aliases = _extract_multi_select(item, "aliases")

        if not title:
            LOGGER.warning("Skipping model %s - no title found", item.get("id"))
            continue

        # Case-insensitive check (client-side filtering)
        title_match = name_lower in title.lower()
        alias_match = any(name_lower in alias.lower() for alias in aliases)

        if title_match or alias_match:
            models.append({"id": item["id"], "name": title, "aliases": aliases})

    LOGGER.info("Found %d models for query '%s'", len(models), name)
    return models
