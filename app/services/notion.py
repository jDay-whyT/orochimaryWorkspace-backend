import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import aiohttp

NOTION_VERSION = "2022-06-28"
LOGGER = logging.getLogger(__name__)


@dataclass
class NotionModel:
    """Model (database model) entity."""
    page_id: str
    title: str
    project: str | None = None
    status: str | None = None
    winrate: str | None = None


@dataclass
class NotionOrder:
    """Order entity."""
    page_id: str
    title: str
    model_id: str | None = None
    model_title: str | None = None
    order_type: str | None = None
    in_date: str | None = None
    out_date: str | None = None
    status: str | None = None
    count: int | None = None
    comments: str | None = None
    from_project: str | None = None


@dataclass
class NotionPlanner:
    """Planner (shoot) entity."""
    page_id: str
    title: str
    model_id: str | None = None
    model_title: str | None = None
    date: str | None = None
    status: str | None = None
    content: list[str] | None = None
    location: str | None = None
    comments: str | None = None


@dataclass
class NotionAccounting:
    """Accounting entity — one record per model per month."""
    page_id: str
    title: str
    model_id: str | None = None
    model_title: str | None = None
    files: int = 0
    comment: str | None = None
    status: str | None = None
    last_edited: str | None = None
    content: list[str] | None = None


class NotionClient:
    """
    Async Notion API client with singleton pattern per token.
    Properly manages aiohttp session lifecycle to prevent resource leaks.
    """
    _instances: dict[str, 'NotionClient'] = {}
    _lock = asyncio.Lock()
    
    def __new__(cls, token: str) -> 'NotionClient':
        """Ensure single instance per token."""
        if token not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[token] = instance
        return cls._instances[token]
    
    def __init__(self, token: str) -> None:
        # Prevent re-initialization
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._token = token
        self._session: aiohttp.ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._session and not self._session.closed:
            if self._session_loop and self._session_loop is loop and not loop.is_closed():
                return self._session
            # Close old session from different event loop to prevent resource leaks
            LOGGER.info("Closing stale session from different event loop")
            try:
                await self._session.close()
            except Exception as e:
                LOGGER.warning("Error closing stale session: %s", e)

        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        )
        self._session_loop = loop
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._session_loop = None
    
    @classmethod
    async def close_all(cls) -> None:
        """Close all singleton instances. Call on application shutdown."""
        for instance in cls._instances.values():
            await instance.close()
        cls._instances.clear()

    async def _request(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        session = await self._get_session()

        for attempt in range(retries + 1):
            try:
                async with session.request(method, url, json=json) as response:
                    if response.status < 400:
                        return await response.json()

                    payload = (await response.text()).strip()
                    short_payload = payload[:200] if payload else "<empty>"

                    if response.status in {429, 500, 502, 503, 504} and attempt < retries:
                        backoff = 2 ** attempt  # 1s, 2s, 4s
                        LOGGER.warning(
                            "Notion API retry %d/%d %s %s: %s (backoff=%.1fs)",
                            attempt + 1, retries, response.status, url, short_payload, backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    LOGGER.error("Notion API error %s %s: %s", response.status, url, short_payload)
                    raise RuntimeError(f"Notion API error {response.status}")

            except aiohttp.ClientError:
                if attempt < retries:
                    backoff = 2 ** attempt  # 1s, 2s, 4s
                    LOGGER.warning(
                        "Notion API client error retry %d/%d %s %s (backoff=%.1fs)",
                        attempt + 1, retries, method, url, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                LOGGER.exception("Notion API request failed %s %s", method, url)
                raise
            except asyncio.TimeoutError:
                if attempt < retries:
                    backoff = 2 ** attempt  # 1s, 2s, 4s
                    LOGGER.warning(
                        "Notion API timeout retry %d/%d %s %s (backoff=%.1fs)",
                        attempt + 1, retries, method, url, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                LOGGER.exception("Notion API timeout %s %s", method, url)
                raise

        raise RuntimeError("Notion API retry limit exceeded")

    # ==================== Models ====================

    async def query_models(
        self,
        database_id: str,
        name_query: str,
        limit: int = 10,
    ) -> list[NotionModel]:
        """Search models by name."""
        LOGGER.info("Querying models database %s with query: %s", database_id, name_query)

        # If query is empty, fetch all models without filter
        if not name_query or not name_query.strip():
            payload = {
                "page_size": limit,
            }
        else:
            # Search by 'model' title field
            payload = {
                "page_size": limit,
                "filter": {
                    "property": "model",
                    "title": {"contains": name_query},
                },
            }

        url = f"https://api.notion.com/v1/databases/{database_id}/query"

        try:
            data = await self._request("POST", url, json=payload)
        except RuntimeError as e:
            LOGGER.error("Failed to query models database %s: %s", database_id, e)
            # Log helpful debugging info
            if "404" in str(e):
                LOGGER.error(
                    "Database not found (404). Possible causes:\n"
                    "  1. DB_MODELS environment variable is not set correctly\n"
                    "  2. Database ID '%s' doesn't exist\n"
                    "  3. Notion token doesn't have access to this database\n"
                    "  4. Database was deleted or moved",
                    database_id
                )
            raise

        results: list[NotionModel] = []
        for item in data.get("results", []):
            title = await self._extract_model_title(item)
            if title:
                # Check if title matches query (for client-side filtering when title comes from relation)
                if not name_query or not name_query.strip() or \
                   name_query.lower() in title.lower():
                    results.append(NotionModel(
                        page_id=item["id"],
                        title=title,
                        project=_extract_select(item, "project"),
                        status=_extract_status(item, "status"),
                        winrate=_extract_select(item, "winrate"),
                    ))
            else:
                LOGGER.warning("Skipping model %s - no valid title found", item.get("id"))

        LOGGER.info("Found %d models for query '%s'", len(results), name_query)
        return results

    async def get_model(self, page_id: str) -> NotionModel | None:
        """Get a single model by page ID."""
        url = f"https://api.notion.com/v1/pages/{page_id}"
        try:
            data = await self._request("GET", url)
            title = await self._extract_model_title(data)
            if not title:
                LOGGER.warning("Model %s has no valid title", page_id)
                return None
            return NotionModel(
                page_id=data["id"],
                title=title,
                project=_extract_select(data, "project"),
                status=_extract_status(data, "status"),
                winrate=_extract_select(data, "winrate"),
            )
        except Exception:
            LOGGER.exception("Failed to get model %s", page_id)
            return None

    async def _extract_model_title(self, page: dict[str, Any]) -> str | None:
        """
        Extract model title with fallback logic:
        1. Try 'model' title field (standard title field)
        2. Try other common title fields (Name, name, title, Title)
        3. Return None if all fail
        """
        page_id = page.get("id", "unknown")

        # Try standard title field 'model'
        title = _extract_title(page, "model")
        if title:
            LOGGER.debug("Model %s: using 'model' title: %s", page_id, title)
            return title

        # Log available properties for debugging
        properties = page.get("properties", {})
        available_props = list(properties.keys())
        LOGGER.debug("Model %s: 'model' is empty, available properties: %s",
                    page_id, available_props)

        # Fallback: try other common title fields
        for field in ["Name", "name", "title", "Title"]:
            fallback_title = _extract_title(page, field)
            if fallback_title:
                LOGGER.info("Model %s: using fallback field '%s': %s",
                            page_id, field, fallback_title)
                return fallback_title

        LOGGER.warning(
            "Model %s: no valid title found. "
            "Available properties: %s. "
            "Consider adding a non-empty 'model' title field in Notion.",
            page_id, available_props
        )
        return None

    # ==================== Orders ====================

    async def query_open_orders(
        self, 
        database_id: str, 
        model_page_id: str | None = None,
        limit: int = 50,
    ) -> list[NotionOrder]:
        """Query open orders, optionally filtered by model."""
        filters = [
            {"property": "out", "date": {"is_empty": True}},
            {"property": "status", "select": {"equals": "Open"}},
        ]
        
        if model_page_id:
            filters.append({"property": "model", "relation": {"contains": model_page_id}})
        
        payload = {
            "page_size": limit,
            "filter": {"and": filters},
            "sorts": [{"property": "in", "direction": "ascending"}],
        }
        
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        data = await self._request("POST", url, json=payload)
        
        return [_parse_order(item) for item in data.get("results", [])]

    async def create_order(
        self,
        database_id: str,
        model_page_id: str,
        order_type: str,
        in_date: date,
        count: int,
        title: str,
        comments: str | None = None,
        from_project: str | None = None,
    ) -> str:
        """Create a new order. Returns page ID."""
        properties: dict[str, Any] = {
            "Title": {"title": [{"text": {"content": title}}]},
            "model": {"relation": [{"id": model_page_id}]},
            "type": {"select": {"name": order_type}},
            "in": {"date": {"start": in_date.isoformat()}},
            "status": {"select": {"name": "Open"}},
            "count": {"number": count},
        }

        if comments:
            properties["comments"] = {"rich_text": [{"text": {"content": comments}}]}

        if from_project:
            properties["from"] = {"select": {"name": from_project}}

        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }

        LOGGER.info(
            "Creating order: database_id=%s, title_key='Title', title_value='%s'",
            database_id, title
        )

        url = "https://api.notion.com/v1/pages"
        data = await self._request("POST", url, json=payload)
        return data["id"]

    async def close_order(self, page_id: str, out_date: date) -> None:
        """Close an order by setting out date and status to Done."""
        payload = {
            "properties": {
                "out": {"date": {"start": out_date.isoformat()}},
                "status": {"select": {"name": "Done"}},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def update_order_comment(self, page_id: str, comment: str) -> None:
        """Update order comment."""
        # Notion rich_text content limit is 2000 chars; truncate as safety net.
        if len(comment) > 2000:
            LOGGER.warning("Order comment truncated: page_id=%s len=%d", page_id, len(comment))
            comment = comment[:2000]
        payload = {
            "properties": {
                "comments": {"rich_text": [{"text": {"content": comment}}]},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    # ==================== Planner ====================

    async def query_upcoming_shoots(
        self,
        database_id: str,
        model_page_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 50,
    ) -> list[NotionPlanner]:
        """Query upcoming shoots (planned/scheduled/rescheduled)."""
        if statuses is None:
            statuses = ["planned", "scheduled", "rescheduled"]
        
        filters: list[dict[str, Any]] = []
        
        # Status filter (OR)
        status_filters = [
            {"property": "status", "select": {"equals": s}} 
            for s in statuses
        ]
        if len(status_filters) == 1:
            filters.append(status_filters[0])
        else:
            filters.append({"or": status_filters})
        
        if model_page_id:
            filters.append({"property": "model", "relation": {"contains": model_page_id}})
        
        payload = {
            "page_size": limit,
            "filter": {"and": filters} if len(filters) > 1 else filters[0],
            "sorts": [{"property": "date", "direction": "ascending"}],
        }
        
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        data = await self._request("POST", url, json=payload)
        
        return [_parse_planner(item) for item in data.get("results", [])]

    async def create_shoot(
        self,
        database_id: str,
        model_page_id: str,
        shoot_date: date,
        content: list[str],
        location: str,
        title: str,
        comments: str | None = None,
        status: str | None = None,
    ) -> str:
        """Create a new shoot. Returns page ID."""
        shoot_status = status or "planned"
        properties: dict[str, Any] = {
            "Title": {"title": [{"text": {"content": title}}]},
            "model": {"relation": [{"id": model_page_id}]},
            "date": {"date": {"start": shoot_date.isoformat()}},
            "status": {"select": {"name": shoot_status}},
            "location": {"select": {"name": location}},
            "content": {"multi_select": [{"name": c} for c in content]},
        }

        if comments:
            properties["comments"] = {"rich_text": [{"text": {"content": comments}}]}

        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }

        LOGGER.info(
            "Creating shoot: database_id=%s, title_key='Title', title_value='%s'",
            database_id, title
        )

        url = "https://api.notion.com/v1/pages"
        data = await self._request("POST", url, json=payload)
        return data["id"]

    async def update_shoot_status(self, page_id: str, status: str) -> None:
        """Update shoot status."""
        payload = {
            "properties": {
                "status": {"select": {"name": status}},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def reschedule_shoot(self, page_id: str, new_date: date) -> None:
        """Reschedule a shoot."""
        payload = {
            "properties": {
                "date": {"date": {"start": new_date.isoformat()}},
                "status": {"select": {"name": "rescheduled"}},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    # ==================== Accounting ====================

    async def query_monthly_records(
        self,
        database_id: str,
        model_page_id: str,
        yyyy_mm: str,
    ) -> list[NotionAccounting]:
        """
        Query accounting records for a model in a given month.

        Three-step search (stops at first hit):
          1. primary   — model relation + Title contains "{month_ru} {year}"
          2. fallback1 — model relation + Title contains "{month_ru}"  (old records w/o year)
          3. fallback2 — model relation + Title contains "{yyyy_mm}"   (very old records)
        Returns list sorted by last_edited_time descending.
        """
        from app.utils.formatting import MONTHS_RU_LOWER

        year, month_str = yyyy_mm.split("-")
        month_idx = int(month_str) - 1
        month_label = MONTHS_RU_LOWER[month_idx]

        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        model_filter = {"property": "model", "relation": {"contains": model_page_id}}
        sorts = [{"timestamp": "last_edited_time", "direction": "descending"}]

        # Step 1 — primary: "{month_ru} {year}" (e.g. "февраль 2026")
        primary_label = f"{month_label} {year}"
        payload = {
            "page_size": 10,
            "filter": {"and": [
                model_filter,
                {"property": "Title", "title": {"contains": primary_label}},
            ]},
            "sorts": sorts,
        }
        data = await self._request("POST", url, json=payload)
        results = [_parse_accounting(item) for item in data.get("results", [])]
        if results:
            LOGGER.debug("query_monthly_records: found via primary ('%s')", primary_label)
            return results

        # Step 2 — fallback1: "{month_ru}" only (e.g. "февраль")
        payload_fb1 = {
            "page_size": 10,
            "filter": {"and": [
                model_filter,
                {"property": "Title", "title": {"contains": month_label}},
            ]},
            "sorts": sorts,
        }
        data_fb1 = await self._request("POST", url, json=payload_fb1)
        results_fb1 = [_parse_accounting(item) for item in data_fb1.get("results", [])]
        if results_fb1:
            LOGGER.debug("query_monthly_records: found via fallback1 ('%s')", month_label)
            return results_fb1

        # Step 3 — fallback2: "{yyyy_mm}" (e.g. "2026-02")
        payload_fb2 = {
            "page_size": 10,
            "filter": {"and": [
                model_filter,
                {"property": "Title", "title": {"contains": yyyy_mm}},
            ]},
            "sorts": sorts,
        }
        data_fb2 = await self._request("POST", url, json=payload_fb2)
        results_fb2 = [_parse_accounting(item) for item in data_fb2.get("results", [])]
        if results_fb2:
            LOGGER.debug("query_monthly_records: found via fallback2 ('%s')", yyyy_mm)
        return results_fb2

    async def get_monthly_record(
        self,
        database_id: str,
        model_page_id: str,
        yyyy_mm: str,
    ) -> NotionAccounting | None:
        """
        Get the single monthly accounting record for a model.

        If >1 records found, returns the most recently edited one.
        """
        records = await self.query_monthly_records(
            database_id, model_page_id, yyyy_mm,
        )
        if not records:
            return None
        # Already sorted by last_edited_time desc
        return records[0]

    async def create_accounting_record(
        self,
        database_id: str,
        model_page_id: str,
        model_name: str,
        files: int,
        yyyy_mm: str,
    ) -> str:
        """
        Create new monthly accounting record.

        Title format: "{MODEL_NAME} {месяц_ru_lower} {year}" e.g. "КЛЕЩ февраль 2026"
        """
        from app.utils.formatting import MONTHS_RU_LOWER

        model = await self.get_model(model_page_id)
        status = (
            model.status
            if model and model.status in ["work", "new", "inactive"]
            else "work"
        )

        year, month_str = yyyy_mm.split("-")
        month_idx = int(month_str) - 1
        month_label = MONTHS_RU_LOWER[month_idx]
        title = f"{model_name} {month_label} {year}"

        properties: dict[str, Any] = {
            "Title": {"title": [{"text": {"content": title}}]},
            "model": {"relation": [{"id": model_page_id}]},
            "Files": {"number": files},
            "status": {"status": {"name": status}},
        }

        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }

        LOGGER.info(
            "Creating accounting record: database_id=%s, title='%s'",
            database_id, title,
        )

        url = "https://api.notion.com/v1/pages"
        response = await self._request("POST", url, json=payload)
        return response["id"]

    async def update_accounting_files(
        self,
        page_id: str,
        files: int,
    ) -> None:
        """Update accounting Files number."""
        payload = {
            "properties": {
                "Files": {"number": files},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def update_accounting_comment(self, page_id: str, comment: str) -> None:
        """Update accounting Comment."""
        # Notion rich_text content limit is 2000 chars; truncate as safety net.
        if len(comment) > 2000:
            LOGGER.warning("Accounting comment truncated: page_id=%s len=%d", page_id, len(comment))
            comment = comment[:2000]
        payload = {
            "properties": {
                "Comment": {"rich_text": [{"text": {"content": comment}}]},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def update_accounting_content(
        self,
        page_id: str,
        items: list[str],
    ) -> None:
        """Update accounting Content multi-select."""
        payload = {
            "properties": {
                "Content": {"multi_select": [{"name": item} for item in items]},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def query_accounting_all_month(
        self,
        database_id: str,
        yyyy_mm: str,
        limit: int = 100,
    ) -> list[NotionAccounting]:
        """Query ALL accounting records for a given month (across models).

        Searches three title formats and merges results (dedup by page id):
          1. "{month_ru} {year}" — new format
          2. "{month_ru}"        — old format without year
          3. "{yyyy_mm}"         — very old format
        """
        from app.utils.formatting import MONTHS_RU_LOWER

        year, month_str = yyyy_mm.split("-")
        month_idx = int(month_str) - 1
        month_label = MONTHS_RU_LOWER[month_idx]
        primary_label = f"{month_label} {year}"

        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        sorts = [{"timestamp": "last_edited_time", "direction": "descending"}]

        all_items: list[dict[str, Any]] = []
        for search_term in (primary_label, month_label, yyyy_mm):
            payload = {
                "page_size": limit,
                "filter": {"property": "Title", "title": {"contains": search_term}},
                "sorts": sorts,
            }
            data = await self._request("POST", url, json=payload)
            all_items.extend(data.get("results", []))

        seen_ids: set[str] = set()
        results = []
        for item in all_items:
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            accounting = _parse_accounting(item)
            if accounting.model_id:
                model = await self.get_model(accounting.model_id)
                accounting.model_title = model.title if model else None
            results.append(accounting)
        return results

    async def update_order(self, page_id: str, properties: dict[str, Any]) -> None:
        """Update order properties."""
        payload = {"properties": properties}
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def get_shoot(self, page_id: str) -> NotionPlanner | None:
        """Get shoot by page ID."""
        try:
            url = f"https://api.notion.com/v1/pages/{page_id}"
            data = await self._request("GET", url)

            model_id = _extract_relation_id(data, "model")
            model_title = None
            if model_id:
                model = await self.get_model(model_id)
                model_title = model.title if model else None

            shoot = _parse_planner(data)
            shoot.model_title = model_title
            return shoot
        except Exception:
            LOGGER.exception("Failed to get shoot %s", page_id)
            return None

    async def update_shoot_comment(self, page_id: str, comment: str) -> None:
        """Update shoot comment."""
        # Notion rich_text content limit is 2000 chars; truncate as safety net.
        if len(comment) > 2000:
            LOGGER.warning("Shoot comment truncated: page_id=%s len=%d", page_id, len(comment))
            comment = comment[:2000]
        payload = {
            "properties": {
                "comments": {"rich_text": [{"text": {"content": comment}}]}
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)

    async def query_shoots_in_date_range(
        self,
        database_id: str,
        date_from: date,
        date_to: date,
        statuses: list[str] | None = None,
    ) -> list[NotionPlanner]:
        """Query all shoots across all models within a date range, with model titles resolved."""
        filters: list[dict[str, Any]] = [
            {"property": "date", "date": {"on_or_after": date_from.isoformat()}},
            {"property": "date", "date": {"on_or_before": date_to.isoformat()}},
        ]

        if statuses is not None:
            status_filters = [
                {"property": "status", "select": {"equals": s}}
                for s in statuses
            ]
            filters.append(
                {"or": status_filters} if len(status_filters) > 1 else status_filters[0]
            )

        payload = {
            "page_size": 100,
            "filter": {"and": filters},
            "sorts": [{"property": "date", "direction": "ascending"}],
        }

        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        data = await self._request("POST", url, json=payload)

        shoots = [_parse_planner(item) for item in data.get("results", [])]
        for shoot in shoots:
            if shoot.model_id:
                model = await self.get_model(shoot.model_id)
                shoot.model_title = model.title if model else None

        return shoots

    async def update_shoot_content(self, page_id: str, items: list[str]) -> None:
        """Update shoot Content multi-select."""
        payload = {
            "properties": {
                "content": {"multi_select": [{"name": item} for item in items]},
            }
        }
        url = f"https://api.notion.com/v1/pages/{page_id}"
        await self._request("PATCH", url, json=payload)


# ==================== Helper functions ====================

def _extract_title(page: dict[str, Any], property_name: str) -> str | None:
    """Extract title property value."""
    prop = page.get("properties", {}).get(property_name)
    if not prop:
        return None

    # Support both 'title' and 'rich_text' types for flexibility
    prop_type = prop.get("type")
    if prop_type == "title":
        fragments = prop.get("title", [])
    elif prop_type == "rich_text":
        fragments = prop.get("rich_text", [])
    else:
        return None

    if not fragments:
        return None

    text = "".join(part.get("plain_text", "") for part in fragments).strip()
    return text if text else None


def _extract_any_title(page: dict[str, Any]) -> str | None:
    """
    Auto-detect and extract title from common title field names.
    Tries: Name, name, title, Title, open (legacy)
    """
    for field_name in ["Name", "name", "title", "Title", "open"]:
        title = _extract_title(page, field_name)
        if title:
            return title
    return None


def _extract_rich_text(page: dict[str, Any], property_name: str) -> str | None:
    """Extract rich_text property value."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "rich_text":
        return None
    fragments = prop.get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in fragments).strip() or None


def _extract_date(page: dict[str, Any], property_name: str) -> str | None:
    """Extract date property value (start date as ISO string)."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "date":
        return None
    value = prop.get("date")
    if not value:
        return None
    return value.get("start")


def _extract_select(page: dict[str, Any], property_name: str) -> str | None:
    """Extract select property value."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "select":
        return None
    value = prop.get("select")
    if not value:
        return None
    return value.get("name")


def _extract_status(page: dict[str, Any], property_name: str) -> str | None:
    """Extract status property value."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "status":
        return None
    value = prop.get("status")
    if not value:
        return None
    return value.get("name")


def _extract_multi_select(page: dict[str, Any], property_name: str) -> list[str]:
    """Extract multi_select property values."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "multi_select":
        return []
    values = prop.get("multi_select", [])
    return [v.get("name") for v in values if v.get("name")]


def _extract_number(page: dict[str, Any], property_name: str) -> float | None:
    """Extract number property value."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "number":
        return None
    return prop.get("number")


def _extract_relation_id(page: dict[str, Any], property_name: str) -> str | None:
    """Extract first relation ID."""
    prop = page.get("properties", {}).get(property_name)
    if not prop or prop.get("type") != "relation":
        return None
    relations = prop.get("relation", [])
    if not relations:
        return None
    return relations[0].get("id")


def _parse_order(item: dict[str, Any]) -> NotionOrder:
    """Parse order from Notion API response."""
    count = _extract_number(item, "count")
    return NotionOrder(
        page_id=item["id"],
        title=_extract_any_title(item) or "(no title)",
        model_id=_extract_relation_id(item, "model"),
        order_type=_extract_select(item, "type"),
        in_date=_extract_date(item, "in"),
        out_date=_extract_date(item, "out"),
        status=_extract_select(item, "status"),
        count=int(count) if count is not None else None,
        comments=_extract_rich_text(item, "comments"),
        from_project=_extract_select(item, "from"),
    )


def _parse_planner(item: dict[str, Any]) -> NotionPlanner:
    """Parse planner entry from Notion API response."""
    return NotionPlanner(
        page_id=item["id"],
        title=_extract_any_title(item) or "(no title)",
        model_id=_extract_relation_id(item, "model"),
        date=_extract_date(item, "date"),
        status=_extract_select(item, "status"),
        content=_extract_multi_select(item, "content"),
        location=_extract_select(item, "location"),
        comments=_extract_rich_text(item, "comments"),
    )


def _parse_accounting(item: dict[str, Any]) -> NotionAccounting:
    """Parse accounting entry from Notion API response."""
    files_val = _extract_number(item, "Files")
    last_edited = item.get("last_edited_time")
    return NotionAccounting(
        page_id=item["id"],
        title=_extract_any_title(item) or "(no title)",
        model_id=_extract_relation_id(item, "model"),
        files=int(files_val) if files_val is not None else 0,
        comment=_extract_rich_text(item, "Comment"),
        status=_extract_status(item, "status"),
        last_edited=last_edited,
        content=_extract_multi_select(item, "Content"),
    )
