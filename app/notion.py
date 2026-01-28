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
        self._session: aiohttp.ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._session and not self._session.closed:
            if self._session_loop and self._session_loop is loop and not loop.is_closed():
                return self._session
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )
        self._session_loop = loop
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._session_loop = None

    async def _request(self, method: str, url: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        session = await self._get_session()
        return await safe_request(session, method, url, json=json)

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


async def safe_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    json: dict[str, Any] | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    for attempt in range(retries + 1):
        try:
            async with session.request(method, url, json=json) as response:
                if response.status < 400:
                    return await response.json()
                payload = (await response.text()).strip()
                short_payload = payload[:200] if payload else "<empty>"
                if response.status in {429, 500, 502, 503, 504} and attempt < retries:
                    LOGGER.warning("Notion API retry %s %s: %s", response.status, url, short_payload)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                LOGGER.error("Notion API error %s %s: %s", response.status, url, short_payload)
                raise RuntimeError(f"Notion API error {response.status}")
        except aiohttp.ClientError:
            LOGGER.exception("Notion API request failed %s %s", method, url)
            raise
        except asyncio.TimeoutError:
            LOGGER.exception("Notion API timeout %s %s", method, url)
            raise
    raise RuntimeError("Notion API retry limit exceeded")
