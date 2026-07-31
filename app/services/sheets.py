import asyncio
import logging

import aiohttp
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.service_account import Credentials

from app.services.tango_schedule import TangoRawRow

LOGGER = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GRID_FIELDS = "sheets.data.rowData.values(formattedValue,userEnteredFormat.backgroundColor,textFormatRuns,hyperlink)"


class SheetsClient:
    """
    Async Google Sheets API client with singleton pattern per service account.
    Mirrors NotionClient's session-lifecycle handling.
    """
    _instances: dict[str, "SheetsClient"] = {}

    def __new__(cls, service_account_info: dict) -> "SheetsClient":
        key = service_account_info.get("client_email", "") or repr(sorted(service_account_info.items()))
        if key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, service_account_info: dict) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        self._session: aiohttp.ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._session and not self._session.closed:
            if self._session_loop and self._session_loop is loop and not loop.is_closed():
                return self._session
            LOGGER.info("Closing stale Sheets session from different event loop")
            try:
                await self._session.close()
            except Exception as e:
                LOGGER.warning("Error closing stale Sheets session: %s", e)

        self._session = aiohttp.ClientSession()
        self._session_loop = loop
        return self._session

    async def _access_token(self) -> str:
        if not self._credentials.valid:
            await asyncio.to_thread(self._credentials.refresh, GoogleAuthRequest())
        return self._credentials.token

    async def get_tab_rows(self, spreadsheet_id: str, tab_name: str) -> list[TangoRawRow]:
        """Fetch column A (name) + B (current week) + C (url) with formatting for a tab."""
        token = await self._access_token()
        session = await self._get_session()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        params = {
            "ranges": "'{}'!A:C".format(tab_name.replace("'", "''")),
            "fields": GRID_FIELDS,
        }
        headers = {"Authorization": f"Bearer {token}"}
        async with session.get(url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()

        sheets = data.get("sheets") or []
        if not sheets:
            return []
        sheet_data = sheets[0].get("data") or [{}]
        row_data = sheet_data[0].get("rowData") or []

        rows: list[TangoRawRow] = []
        for row in row_data[1:]:  # row_data[0] is the header row ("name", "current week", "url", ...)
            values = row.get("values") or []
            name_cell = values[0] if len(values) > 0 else {}
            week_cell = values[1] if len(values) > 1 else {}
            url_cell = values[2] if len(values) > 2 else {}
            name = (name_cell.get("formattedValue") or "").strip()
            if not name:
                continue
            rows.append(TangoRawRow(
                name=name,
                name_background=(name_cell.get("userEnteredFormat") or {}).get("backgroundColor"),
                week_text=week_cell.get("formattedValue") or "",
                week_text_format_runs=week_cell.get("textFormatRuns"),
                url=url_cell.get("hyperlink") or url_cell.get("formattedValue") or "",
            ))
        return rows

    async def get_sheet_tabs(self, spreadsheet_id: str) -> dict[str, int]:
        """Return {tab_title: sheetId} for every tab in the spreadsheet."""
        token = await self._access_token()
        session = await self._get_session()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        params = {"fields": "sheets.properties"}
        headers = {"Authorization": f"Bearer {token}"}
        async with session.get(url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return {
            s["properties"]["title"]: s["properties"]["sheetId"]
            for s in data.get("sheets", [])
        }

    async def add_sheet_tab(self, spreadsheet_id: str, title: str) -> int:
        """Create a new tab and return its sheetId."""
        token = await self._access_token()
        session = await self._get_session()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
        payload = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return data["replies"][0]["addSheet"]["properties"]["sheetId"]

    async def get_tab_grid(self, spreadsheet_id: str, tab_name: str, last_column: str = "L") -> list[list[str]]:
        """Return every row's formatted values (column A..last_column) for a tab."""
        token = await self._access_token()
        session = await self._get_session()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/'{tab_name}'!A:{last_column}"
        params = {"valueRenderOption": "FORMATTED_VALUE"}
        headers = {"Authorization": f"Bearer {token}"}
        async with session.get(url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return data.get("values", [])

    async def insert_rows(
        self, spreadsheet_id: str, sheet_id: int, start_index: int, end_index: int,
    ) -> None:
        """
        Insert `end_index - start_index` blank rows at 0-based `start_index`,
        shifting existing rows (and any formula ranges referencing them) down.
        `inheritFromBefore` copies formatting from the row above the insertion
        point rather than leaving the new rows unformatted.
        """
        token = await self._access_token()
        session = await self._get_session()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
        payload = {
            "requests": [{
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "inheritFromBefore": start_index > 0,
                },
            }],
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            await resp.json()

    async def update_values(self, spreadsheet_id: str, updates: list[tuple[str, list[list]]]) -> None:
        """
        Write values into specific ranges.

        `updates` is a list of (a1_range, rows) pairs, e.g.
        ("'ИЮЛЬ'!B5:F5", [[ "work", "twitter, reddit", 120, 3, 5 ]]).
        USER_ENTERED so formula strings (e.g. "=SUM(I3:K9)") are parsed as
        formulas rather than stored as literal text.
        """
        if not updates:
            return
        token = await self._access_token()
        session = await self._get_session()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate"
        payload = {
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": a1_range, "values": rows} for a1_range, rows in updates],
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            await resp.json()
