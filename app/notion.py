import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import aiohttp

NOTION_VERSION = "2022-06-28"
LOGGER = logging.getLogger(__name__)


@dataclass
class NotionOrder:
    page_id: str
    title: str
    in_date: str | None
    order_type: str | None


class NotionClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    async def close(self) -> None:
        await self._session.close()

    async def _request(self, method: str, url: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        retries = 2
        for attempt in range(retries + 1):
            async with self._session.request(method, url, json=json) as response:
                if response.status in {429, 500, 502, 503, 504} and attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if response.status >= 400:
                    payload = await response.text()
                    LOGGER.error("Notion API error %s %s: %s", response.status, url, payload)
                    raise RuntimeError(f"Notion API error {response.status}")
                return await response.json()
        raise RuntimeError("Notion API retry limit exceeded")

    async def query_models(self, database_id: str, name_query: str) -> list[tuple[str, str]]:
        payload = {
            "page_size": 5,
            "filter": {
                "property": "Name",
                "title": {"contains": name_query},
            },
        }
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        data = await self._request("POST", url, json=payload)
        results: list[tuple[str, str]] = []
        for item in data.get("results", []):
            title = _extract_title(item, "Name")
            if title:
                results.append((item["id"], title))
        return results

    async def create_order(
        self,
        database_id: str,
        model_page_id: str,
        order_type: str,
        in_date: date,
        count: int,
        title: str,
        comments: str | None,
    ) -> None:
        properties: dict[str, Any] = {
            "open": {"title": [{"text": {"content": title}}]},
            "model": {"relation": [{"id": model_page_id}]},
            "type": {"select": {"name": order_type}},
            "in": {"date": {"start": in_date.isoformat()}},
            "status": {"select": {"name": "Open"}},
            "count": {"number": count},
        }
        if comments:
            properties["comments"] = {"rich_text": [{"text": {"content": comments}}]}
        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        url = "https://api.notion.com/v1/pages"
        await self._request("POST", url, json=payload)

    async def query_open_orders(self, database_id: str, model_page_id: str) -> list[NotionOrder]:
        payload = {
            "page_size": 20,
            "filter": {
                "and": [
                    {"property": "model", "relation": {"contains": model_page_id}},
                    {"property": "out", "date": {"is_empty": True}},
                    {"property": "status", "select": {"equals": "Open"}},
                ]
            },
            "sorts": [{"property": "in", "direction": "ascending"}],
        }
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        data = await self._request("POST", url, json=payload)
        orders: list[NotionOrder] = []
        for item in data.get("results", []):
            title = _extract_title(item, "open")
            in_date = _extract_date(item, "in")
            order_type = _extract_select(item, "type")
            orders.append(
                NotionOrder(page_id=item["id"], title=title or "(no title)", in_date=in_date, order_type=order_type)
            )
        return orders

    async def close_order(self, order_page_id: str, out_date: date) -> None:
        payload = {
            "properties": {
                "out": {"date": {"start": out_date.isoformat()}},
                "status": {"select": {"name": "Done"}},
            }
        }
        url = f"https://api.notion.com/v1/pages/{order_page_id}"
        await self._request("PATCH", url, json=payload)


def _extract_title(page: dict[str, Any], property_name: str) -> str | None:
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "title":
        return None
    fragments = prop.get("title", [])
    return "".join(part.get("plain_text", "") for part in fragments).strip() or None


def _extract_date(page: dict[str, Any], property_name: str) -> str | None:
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "date":
        return None
    value = prop.get("date")
    if not value:
        return None
    return value.get("start")


def _extract_select(page: dict[str, Any], property_name: str) -> str | None:
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "select":
        return None
    value = prop.get("select")
    if not value:
        return None
    return value.get("name")
