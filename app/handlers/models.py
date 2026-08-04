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

    # Notion filters are case-insensitive by default for "contains"
    combined_payload = {
        "filter": {
            "or": [
                {"property": "model", "title": {"contains": name}},
                {"property": "aliases", "multi_select": {"contains": name}},
            ]
        }
    }
    # multi_select "contains" only matches values that are already registered
    # options on the "aliases" property. A search term that isn't one of those
    # options makes Notion reject the *entire* request with 400 - which also
    # kills the (valid) title match in the same OR filter. Fall back to a
    # title-only query so an unregistered term still finds title matches.
    title_only_payload = {
        "filter": {"property": "model", "title": {"contains": name}}
    }

    url = f"https://api.notion.com/v1/databases/{db_id}/query"

    try:
        response = await notion._request("POST", url, json=combined_payload)
    except Exception:
        try:
            response = await notion._request("POST", url, json=title_only_payload)
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
