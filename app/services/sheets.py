import asyncio
import logging

import aiohttp
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.service_account import Credentials

from app.services.tango_schedule import TangoRawRow

LOGGER = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
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
            "ranges": f"{tab_name}!A:C",
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
