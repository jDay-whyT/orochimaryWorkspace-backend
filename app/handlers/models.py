"""Model search handlers for NLP routing."""

import logging
from typing import Any

from app.services import NotionClient
from app.services.notion import _extract_title, _extract_multi_select


LOGGER = logging.getLogger(__name__)


async def search_model_by_name_or_alias(
    name: str, db_id: str, notion: NotionClient
) -> list[dict[str, Any]]:
    """All models as [{"id", "name", "aliases"}, ...]; the resolver scores them against `name`.

    multi_select "contains" only matches values that are already registered
    options on the "aliases" property - an unregistered search term makes
    Notion reject the whole request with 400. So every page is fetched
    (unfiltered, paginated) and matching - typos included - happens client-side.
    """
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

            models.append({"id": item["id"], "name": title, "aliases": aliases})

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    LOGGER.info("Loaded %d models for query '%s'", len(models), name)
    return models
