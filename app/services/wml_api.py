"""JSON API client for the WML CRM (wml.pp.ua/api) — orders and monthly file counts.

Separate from `wml_client` (HTML scraper): this one writes. Same account
(WML_USERNAME / WML_PASSWORD). The token is fetched on first use and again on
a 401. Synchronous (requests) — call through asyncio.to_thread.

Orders are "content requests"; monthly file counts are "content request files"
(create is an upsert by profile + month on the CRM side).
"""
import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

API_URL = "https://wml.pp.ua/api"
_TIMEOUT = 20

# Notion order `type` -> WML content-request type id
ORDER_TYPE_IDS = {
    "ad request": 1,
    "custom": 2,
    "short": 3,
    "call": 4,
    "verif reddit": 5,
}


class WmlApiError(RuntimeError):
    pass


class WmlApi:
    def __init__(self, username: str, password: str, session: requests.Session | None = None) -> None:
        self._username = username
        self._password = password
        self._session = session or requests.Session()
        self._token: str | None = None

    def _login(self) -> None:
        resp = self._session.post(
            f"{API_URL}/login",
            json={"username": self._username, "password": self._password},
            timeout=_TIMEOUT,
        )
        data = self._json(resp)
        if not data.get("success") or not data.get("token"):
            raise WmlApiError(f"WML login failed (HTTP {resp.status_code})")
        self._token = data["token"]

    @staticmethod
    def _json(resp: requests.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError:
            raise WmlApiError(f"WML API: non-JSON response (HTTP {resp.status_code})")

    def _call(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._token is None:
            self._login()
        for attempt in (1, 2):
            resp = self._session.request(
                method,
                f"{API_URL}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 401 and attempt == 1:
                self._login()  # token expired — once
                continue
            data = self._json(resp)
            if resp.status_code >= 400 or not data.get("success"):
                raise WmlApiError(f"WML API {method} {path}: HTTP {resp.status_code}: {str(data)[:200]}")
            return data
        raise WmlApiError(f"WML API {method} {path}: unauthorized after re-login")

    def create_order(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a content request. Required: profile, title, in, type; optional: out, count, received.
        The returned `id` is needed for later updates."""
        return self._call("POST", "/content-request", fields)

    def update_order(self, request_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        """Update out / count / received of an existing content request."""
        return self._call("POST", f"/content-request/{request_id}", fields)

    def upsert_files(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create or update a model's monthly file counts (profile + month identify the row)."""
        return self._call("POST", "/content-request-files", fields)
